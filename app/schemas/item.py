from typing import Literal

from pydantic import Field

from app.schemas.common import StrictBaseModel

ItemStatus = Literal["draft", "active", "archived"]


class ItemCreateRequest(StrictBaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    status: ItemStatus = "active"


class ItemUpdateRequest(StrictBaseModel):
    expected_version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    status: ItemStatus | None = None


class ItemDeleteRequest(StrictBaseModel):
    expected_version: int = Field(ge=1)


class ItemResponse(StrictBaseModel):
    id: str
    owner_id: str
    name: str
    description: str | None
    status: ItemStatus
    version: int
    created_at: str
    updated_at: str


class ItemListResponse(StrictBaseModel):
    items: list[ItemResponse]
    next_cursor: str | None
    limit: int

