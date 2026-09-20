from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypeAlias

from pydantic import Field

from app.schemas.common import StrictBaseModel

SchemaType: TypeAlias = type[StrictBaseModel]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    owner_module: str
    callable_name: str
    input_schema: SchemaType
    output_schema: SchemaType


class ExampleToolInput(StrictBaseModel):
    text: str = Field(min_length=1, max_length=200)
    max_length: int = Field(default=64, ge=1, le=128)


class ExampleToolOutput(StrictBaseModel):
    slug: str


def slugify_text(data: ExampleToolInput) -> ExampleToolOutput:
    normalized = data.text.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    normalized = normalized.strip("-")
    if not normalized:
        raise ValueError("tool input must contain at least one ASCII letter or digit")
    return ExampleToolOutput(slug=normalized[: data.max_length].rstrip("-"))


EXAMPLE_TOOL_SPEC = ToolSpec(
    name="example.slugify_text",
    owner_module="app.tools.example_tool",
    callable_name="slugify_text",
    input_schema=ExampleToolInput,
    output_schema=ExampleToolOutput,
)


def validate_example_tool_spec() -> None:
    if not EXAMPLE_TOOL_SPEC.name:
        raise RuntimeError("tool spec name is required")
    if EXAMPLE_TOOL_SPEC.owner_module != __name__:
        raise RuntimeError("tool spec owner_module must match module name")
    if EXAMPLE_TOOL_SPEC.callable_name != slugify_text.__name__:
        raise RuntimeError("tool spec callable_name must match callable")
