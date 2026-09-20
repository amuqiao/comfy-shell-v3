from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorSpec:
    code: str
    http_status: int
    message: str
    retryable: bool
    visibility: frozenset[str]


class ErrorRegistry:
    def __init__(self) -> None:
        self._items: dict[str, ErrorSpec] = {}
        self._frozen = False

    def register(self, spec: ErrorSpec) -> None:
        if self._frozen:
            raise RuntimeError("error registry is frozen")
        if spec.code in self._items:
            raise RuntimeError(f"duplicate error code: {spec.code}")
        self._items[spec.code] = spec

    def get(self, code: str) -> ErrorSpec:
        try:
            return self._items[code]
        except KeyError as exc:
            raise RuntimeError(f"unknown error code: {code}") from exc

    def all(self) -> tuple[ErrorSpec, ...]:
        return tuple(self._items.values())

    def freeze(self) -> None:
        self._frozen = True

    def validate(self) -> None:
        if "INTERNAL_ERROR" not in self._items:
            raise RuntimeError("INTERNAL_ERROR must be registered")


error_registry = ErrorRegistry()


def _register_defaults() -> None:
    specs = [
        ErrorSpec("REQUEST_INVALID", 422, "Request is invalid.", False, frozenset({"public", "internal"})),
        ErrorSpec("UNAUTHORIZED", 401, "Authentication is required.", False, frozenset({"public", "internal"})),
        ErrorSpec("FORBIDDEN", 403, "Permission denied.", False, frozenset({"public", "internal"})),
        ErrorSpec("RESOURCE_NOT_FOUND", 404, "Resource not found.", False, frozenset({"public", "internal"})),
        ErrorSpec("RESOURCE_CONFLICT", 409, "Resource conflict.", False, frozenset({"public", "internal"})),
        ErrorSpec("DEPENDENCY_UNAVAILABLE", 503, "Dependency is unavailable.", True, frozenset({"public", "internal"})),
        ErrorSpec("INTERNAL_ERROR", 500, "Internal server error.", True, frozenset({"public", "internal"})),
        ErrorSpec("ITEM_NOT_FOUND", 404, "Item not found.", False, frozenset({"public"})),
        ErrorSpec("ITEM_NAME_CONFLICT", 409, "Item name already exists.", False, frozenset({"public"})),
        ErrorSpec("ITEM_VERSION_CONFLICT", 409, "Item version conflict.", False, frozenset({"public"})),
    ]
    for spec in specs:
        error_registry.register(spec)
    error_registry.validate()
    error_registry.freeze()


_register_defaults()
