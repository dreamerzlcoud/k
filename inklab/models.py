from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    page: int = Field(default=0, ge=0, le=199)
    kind: Literal["text", "math"] = "math"
    content: str = Field(min_length=1, max_length=8000)
    x: float = Field(default=60, ge=0, le=14400)
    y: float = Field(default=150, ge=0, le=14400)
    width: float = Field(default=450, gt=0, le=14400)
    height: float = Field(default=100, gt=0, le=14400)
    size: float = Field(default=18, ge=6, le=64)


class Layout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str
    profile_id: str = "default"
    color: str = Field(default="#243d78", pattern=r"^#[0-9a-fA-F]{6}$")
    seed: int = Field(default=7, ge=0, le=2147483647)
    blocks: list[Block] = Field(default_factory=list, max_length=120)


class Draft(BaseModel):
    blocks: list[Block] = Field(max_length=120)
    notes: str


class Sample(BaseModel):
    character: str = Field(min_length=1, max_length=1)
    image: str = Field(max_length=3_000_000)


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class AIRequest(BaseModel):
    document_id: str
    instructions: str = Field(min_length=1, max_length=20000)
