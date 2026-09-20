from dataclasses import dataclass

from app.core.error_registry import error_registry
from app.schemas.envelope import ErrorEnvelope

COMMON_ERROR_CODES = frozenset({"REQUEST_INVALID", "INTERNAL_ERROR"})


@dataclass(frozen=True)
class OperationSpec:
    operation_id: str
    method: str
    path: str
    success_status: int
    # Route-specific business errors. Cross-cutting errors such as auth,
    # validation, and internal failures are defined by the common HTTP contract.
    errors: frozenset[str]
    request_schema: str | None = None
    response_schema: str | None = None
    auth_required: bool = True
    prefixed: bool = True

    def full_path(self, api_prefix: str) -> str:
        if not self.prefixed:
            return self.path
        if api_prefix == "/":
            return self.path
        return f"{api_prefix}{self.path}"

    def error_codes(self) -> frozenset[str]:
        codes = set(COMMON_ERROR_CODES)
        codes.update(self.errors)
        if self.auth_required:
            codes.add("UNAUTHORIZED")
        return frozenset(codes)


class OperationRegistry:
    def __init__(self) -> None:
        self._items: dict[str, OperationSpec] = {}
        self._frozen = False

    def register(self, spec: OperationSpec) -> None:
        if self._frozen:
            raise RuntimeError("operation registry is frozen")
        if spec.operation_id in self._items:
            raise RuntimeError(f"duplicate operation id: {spec.operation_id}")
        self._items[spec.operation_id] = spec

    def all(self) -> tuple[OperationSpec, ...]:
        return tuple(self._items.values())

    def get(self, operation_id: str) -> OperationSpec:
        try:
            return self._items[operation_id]
        except KeyError as exc:
            raise RuntimeError(f"unknown operation id: {operation_id}") from exc

    def freeze(self) -> None:
        self._frozen = True

    def validate(self) -> None:
        if not self._items:
            raise RuntimeError("operation registry must not be empty")


operation_registry = OperationRegistry()
operation_registry.register(
    OperationSpec(
        "health",
        "GET",
        "/health",
        200,
        frozenset(),
        response_schema="SuccessEnvelope",
        auth_required=False,
        prefixed=False,
    )
)
operation_registry.register(
    OperationSpec(
        "ready",
        "GET",
        "/ready",
        200,
        frozenset({"DEPENDENCY_UNAVAILABLE"}),
        response_schema="SuccessEnvelope",
        auth_required=False,
        prefixed=False,
    )
)
operation_registry.register(
    OperationSpec(
        "create_item",
        "POST",
        "/items",
        201,
        frozenset({"ITEM_NAME_CONFLICT"}),
        request_schema="ItemCreateRequest",
        response_schema="SuccessEnvelope[ItemResponse]",
    )
)
operation_registry.register(
    OperationSpec(
        "get_item",
        "GET",
        "/items/{item_id}",
        200,
        frozenset({"ITEM_NOT_FOUND"}),
        response_schema="SuccessEnvelope[ItemResponse]",
    )
)
operation_registry.register(
    OperationSpec(
        "list_items",
        "GET",
        "/items",
        200,
        frozenset({"REQUEST_INVALID"}),
        response_schema="SuccessEnvelope[ItemListResponse]",
    )
)
operation_registry.register(
    OperationSpec(
        "update_item",
        "PATCH",
        "/items/{item_id}",
        200,
        frozenset({"ITEM_NOT_FOUND", "ITEM_NAME_CONFLICT", "ITEM_VERSION_CONFLICT"}),
        request_schema="ItemUpdateRequest",
        response_schema="SuccessEnvelope[ItemResponse]",
    )
)
operation_registry.register(
    OperationSpec(
        "delete_item",
        "DELETE",
        "/items/{item_id}",
        200,
        frozenset({"ITEM_NOT_FOUND", "ITEM_VERSION_CONFLICT"}),
        request_schema="ItemDeleteRequest",
        response_schema="SuccessEnvelope[ItemResponse]",
    )
)
operation_registry.validate()
operation_registry.freeze()


def operation_responses(operation_id: str) -> dict[int, dict[str, object]]:
    grouped: dict[int, list[str]] = {}
    for code in sorted(operation_registry.get(operation_id).error_codes()):
        status = error_registry.get(code).http_status
        grouped.setdefault(status, []).append(code)
    return {
        status: {
            "model": ErrorEnvelope,
            "description": ", ".join(codes),
        }
        for status, codes in grouped.items()
    }
