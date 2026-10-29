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
    use_ai: bool = True
    blocks: list[Block] = Field(default_factory=list, max_length=120)


class Draft(BaseModel):
    blocks: list[Block] = Field(max_length=120)
    notes: str


class StrokePoint(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    x: float = Field(ge=-10000, le=10000)
    y: float = Field(ge=-10000, le=10000)
    t: float = Field(default=0.0, ge=0, le=86400000)
    pressure: float = Field(default=0.5, ge=0.0, le=1.0)
    tilt_x: float = Field(default=0.0, ge=-90.0, le=90.0)
    tilt_y: float = Field(default=0.0, ge=-90.0, le=90.0)
    stroke_id: int = Field(default=0, ge=0, le=1000)
    pen_lift: bool = False


class Sample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character: str = Field(min_length=1, max_length=40)
    image: str = Field(default="", max_length=3_000_000)
    strokes: list[StrokePoint] = Field(default_factory=list, max_length=4000)


class GenerateSentenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: str = "default"
    text: str = Field(min_length=1, max_length=500)
    size: float = Field(default=24, ge=8, le=64)
    color: str = Field(default="#243d78", pattern=r"^#[0-9a-fA-F]{6}$")
    seed: int = Field(default=7, ge=0, le=2147483647)


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class AIRequest(BaseModel):
    document_id: str
    instructions: str = Field(min_length=1, max_length=20000)
