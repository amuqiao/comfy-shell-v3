import re

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.api.operations import operation_registry
from app.core.config import get_settings
from app.core.error_registry import error_registry


def _schema_ref_names(schema: object, components: dict[str, object], seen: set[str] | None = None) -> set[str]:
    seen = seen or set()
    names: set[str] = set()
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            name = ref.rsplit("/", 1)[-1]
            names.add(name)
            if name not in seen:
                seen.add(name)
                names.update(_schema_ref_names(components.get(name, {}), components, seen))
        for value in schema.values():
            names.update(_schema_ref_names(value, components, seen))
    elif isinstance(schema, list):
        for item in schema:
            names.update(_schema_ref_names(item, components, seen))
    return names


def _expected_schema_tokens(schema_name: str | None) -> set[str]:
    if schema_name is None:
        return set()
    success_schema = schema_name.split("|", 1)[0]
    return {
        token
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", success_schema)
        if token not in {"dict", "list", "str", "int", "object"}
    }


def _has_schema_token(ref_names: set[str], token: str) -> bool:
    return any(name == token or name.startswith(f"{token}_") for name in ref_names)


def validate_operation_route_drift(app: FastAPI) -> None:
    settings = getattr(app.state, "settings", None) or get_settings()
    allowed_methods = {"GET", "POST", "PUT", "PATCH", "DELETE"}
    actual = {
        (method, route.path, route.operation_id, route.status_code or 200)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
        if method in allowed_methods
    }
    expected = {
        (spec.method, spec.full_path(settings.service.api_prefix), spec.operation_id, spec.success_status)
        for spec in operation_registry.all()
    }
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise RuntimeError(f"operation registry drift missing={missing} extra={extra}")

    routes_by_operation_id = {
        route.operation_id: route for route in app.routes if isinstance(route, APIRoute) and route.operation_id
    }
    openapi = app.openapi()
    components = openapi.get("components", {}).get("schemas", {})
    errors: list[str] = []
    for spec in operation_registry.all():
        route = routes_by_operation_id.get(spec.operation_id)
        if route is None:
            continue
        if route.response_model is None:
            errors.append(f"{spec.operation_id}: missing response_model")
        for code in spec.error_codes():
            error_registry.get(code)

        path_spec = openapi.get("paths", {}).get(spec.full_path(settings.service.api_prefix), {})
        operation_spec = path_spec.get(spec.method.lower(), {})
        if not operation_spec:
            errors.append(f"{spec.operation_id}: missing OpenAPI operation")
            continue

        if spec.request_schema is not None:
            request_body = operation_spec.get("requestBody", {})
            request_schema = (
                request_body.get("content", {}).get("application/json", {}).get("schema", {}).get("$ref", "")
            )
            if not request_schema.endswith(f"/{spec.request_schema}"):
                errors.append(f"{spec.operation_id}: request schema drift")

        responses = operation_spec.get("responses", {})
        success_response = responses.get(str(spec.success_status), {})
        success_schema = success_response.get("content", {}).get("application/json", {}).get("schema", {})
        success_refs = _schema_ref_names(success_schema, components)
        for token in _expected_schema_tokens(spec.response_schema):
            if not _has_schema_token(success_refs, token):
                errors.append(f"{spec.operation_id}: response schema drift missing {token}")

        for status in {str(error_registry.get(code).http_status) for code in spec.error_codes()}:
            if status not in responses:
                errors.append(f"{spec.operation_id}: missing OpenAPI error response {status}")
                continue
            error_schema = responses[status].get("content", {}).get("application/json", {}).get("schema", {})
            if "ErrorEnvelope" not in _schema_ref_names(error_schema, components):
                errors.append(f"{spec.operation_id}: error response {status} schema drift")

        security = operation_spec.get("security", [])
        if spec.auth_required and not security:
            errors.append(f"{spec.operation_id}: missing OpenAPI security")
        if not spec.auth_required and security:
            errors.append(f"{spec.operation_id}: unexpected OpenAPI security")

    if errors:
        raise RuntimeError(f"operation contract drift errors={errors}")
