from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from app.domain import ImageAsset
from app.storage import Store


class ImageStore:
    def __init__(self, root: Path):
        self.store = Store(root)
        self.directory = self.store.root / "images"
        self.directory.mkdir(exist_ok=True)

    def import_image(self, name: str, content: bytes) -> ImageAsset:
        if len(content) > 30 * 1024 * 1024:
            raise ValueError("单张图片不能超过 30 MB")
        identifier = uuid4().hex
        path = self.directory / f"{identifier}.png"
        try:
            with Image.open(BytesIO(content)) as original:
                if original.format not in {"JPEG", "PNG", "WEBP", "BMP"}:
                    raise ValueError("请使用 JPG、PNG、WebP 或 BMP 图片")
                if original.width * original.height > 40_000_000:
                    raise ValueError("图片超过 4000 万像素，请先缩小")
                canonical = ImageOps.exif_transpose(original).convert("RGB")
                canonical.save(path)
                width, height = canonical.size
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("图片损坏或格式不支持，请转换为 JPG 或 PNG") from exc
        asset = ImageAsset(id=identifier, name=Path(name).name, path=path, width=width, height=height)
        self.save(asset)
        return asset

    def save(self, asset: ImageAsset):
        self.store.put("image", asset.id, asset.model_dump(mode="json"))

    def get(self, identifier: str) -> ImageAsset:
        return ImageAsset.model_validate(self.store.get("image", identifier))

    def list(self) -> list[ImageAsset]:
        return [ImageAsset.model_validate(value) for value in self.store.list("image")]
