import pytest
from pydantic import ValidationError

from app.tools.example_tool import ExampleToolInput, EXAMPLE_TOOL_SPEC, slugify_text, validate_example_tool_spec


def test_example_tool_spec_is_valid():
    validate_example_tool_spec()

    assert EXAMPLE_TOOL_SPEC.name == "example.slugify_text"
    assert EXAMPLE_TOOL_SPEC.owner_module == "app.tools.example_tool"


def test_slugify_text_normalizes_input():
    result = slugify_text(ExampleToolInput(text=" FastAPI Lite: Example Tool "))

    assert result.slug == "fastapi-lite-example-tool"


def test_slugify_text_respects_max_length():
    result = slugify_text(ExampleToolInput(text="alpha beta gamma", max_length=10))

    assert result.slug == "alpha-beta"


def test_slugify_text_rejects_non_ascii_content():
    with pytest.raises(ValueError, match="ASCII letter or digit"):
        slugify_text(ExampleToolInput(text="!!!"))


def test_example_tool_input_schema_validates_bounds():
    with pytest.raises(ValidationError):
        ExampleToolInput(text="valid", max_length=0)
