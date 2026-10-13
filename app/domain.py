from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

FIELDS = {
    "name": "产品名称",
    "specification": "规格",
    "manufacturer": "生产厂商",
    "address": "生产地址",
    "lot": "批号",
    "production_date": "生产日期",
    "shelf_life": "保质期",
}


class FieldValue(BaseModel):
    raw: str = ""
    value: str = ""
    source: Literal["image", "external", "missing"] = "image"
    note: str = ""
    refs: list[str] = Field(default_factory=list)


class FieldCandidate(FieldValue):
    reason: str
    needs_review: bool = False


class OcrBlock(BaseModel):
    id: str
    image_id: str
    text: str
    polygon: list[tuple[float, float]]
    score: float


class ImageAsset(BaseModel):
    id: str
    name: str
    path: Path
    width: int
    height: int
    import_batch: str = ""
    status: Literal["imported", "queued", "running", "done", "error"] = "imported"
    blocks: list[OcrBlock] = Field(default_factory=list)
    seconds: float = 0
    error: str = ""
