from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

T = TypeVar("T")
MutationStatus = Literal["updated", "not_found", "version_conflict"]


@dataclass(frozen=True)
class MutationResult(Generic[T]):
    status: MutationStatus
    item: T | None = None
    current_version: int | None = None

    @classmethod
    def updated(cls, item: T) -> "MutationResult[T]":
        return cls(status="updated", item=item)

    @classmethod
    def not_found(cls) -> "MutationResult[T]":
        return cls(status="not_found")

    @classmethod
    def version_conflict(cls, current_version: int) -> "MutationResult[T]":
        return cls(status="version_conflict", current_version=current_version)

