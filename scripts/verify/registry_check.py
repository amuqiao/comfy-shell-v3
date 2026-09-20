from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from app.api.operations import operation_registry
from app.core.config.sections import ServiceSettings
from app.core.error_registry import error_registry
from app.core.lifecycle import build_health_registry
from app.core.registry_checks import validate_operation_route_drift
from app.main import build_lifecycle_provider_registry, create_app
from app.tools.example_tool import validate_example_tool_spec

REQUIRED_DOCS = (
    ROOT_DIR / "docs/current/implementation.md",
    ROOT_DIR / "docs/contracts/api-contract.md",
    ROOT_DIR / "docs/contracts/extension-contract.md",
    ROOT_DIR / "docs/plans/drift-checklist.md",
)
API_CONTRACT_DOC = ROOT_DIR / "docs/contracts/api-contract.md"


def _stable_doc_errors(spec) -> set[str]:
    errors = set(spec.errors)
    if spec.auth_required:
        errors.add("UNAUTHORIZED")
    if spec.request_schema is not None:
        errors.add("REQUEST_INVALID")
    return errors


def _extract_code_values(value: str) -> set[str]:
    if value.strip() == "none":
        return set()
    return set(re.findall(r"`([^`]+)`", value))


def _parse_routes_table(doc_path: Path) -> dict[str, dict[str, str]]:
    lines = doc_path.read_text(encoding="utf-8").splitlines()
    in_routes = False
    rows: dict[str, dict[str, str]] = {}
    for line in lines:
        if line.strip() == "## Routes":
            in_routes = True
            continue
        if in_routes and line.startswith("## "):
            break
        if not in_routes or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5 or cells[0] in {"Operation", "---"} or set(cells[0]) == {"-"}:
            continue
        operation_id = cells[0].strip("`")
        rows[operation_id] = {
            "method_path": cells[1].strip("`"),
            "auth": cells[2],
            "success": cells[3].strip("`"),
            "errors": cells[4],
        }
    return rows


def validate_api_contract_route_table(doc_path: Path = API_CONTRACT_DOC) -> None:
    service_settings = ServiceSettings()
    rows = _parse_routes_table(doc_path)
    errors: list[str] = []
    for spec in operation_registry.all():
        row = rows.get(spec.operation_id)
        if row is None:
            errors.append(f"{spec.operation_id}: missing docs route row")
            continue
        expected_method_path = f"{spec.method} {spec.full_path(service_settings.api_prefix)}"
        if row["method_path"] != expected_method_path:
            errors.append(f"{spec.operation_id}: docs method/path drift")
        expected_auth = "yes" if spec.auth_required else "no"
        if row["auth"] != expected_auth:
            errors.append(f"{spec.operation_id}: docs auth drift")
        if row["success"] != str(spec.success_status):
            errors.append(f"{spec.operation_id}: docs success status drift")
        actual_errors = _extract_code_values(row["errors"])
        expected_errors = _stable_doc_errors(spec)
        if actual_errors != expected_errors:
            errors.append(
                f"{spec.operation_id}: docs stable errors drift "
                f"expected={sorted(expected_errors)} actual={sorted(actual_errors)}"
            )
    extra = sorted(set(rows) - {spec.operation_id for spec in operation_registry.all()})
    if extra:
        errors.append(f"docs route table has unknown operations: {extra}")
    if errors:
        raise RuntimeError(f"api contract route table drift errors={errors}")


def main() -> int:
    error_registry.validate()
    operation_registry.validate()
    health_registry = build_health_registry()
    health_registry.validate()
    lifecycle_registry = build_lifecycle_provider_registry()
    lifecycle_registry.validate()
    validate_example_tool_spec()
    missing_docs = [str(path.relative_to(ROOT_DIR)) for path in REQUIRED_DOCS if not path.is_file()]
    if missing_docs:
        raise RuntimeError(f"required docs are missing: {missing_docs}")
    validate_operation_route_drift(create_app())
    validate_api_contract_route_table()
    print("OK registries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
