from hashlib import sha256
from math import dist
from pathlib import Path

from PIL import Image

from app.images import ImageStore
from app.storage import Store


class Samples:
    def __init__(self, root):
        self.store = Store(root)
        self.images = ImageStore(root)
        self.directory = Path(root) / "samples"
        self.directory.mkdir(parents=True, exist_ok=True)

    def list(self):
        return self.store.list("sample")

    def collect_samples(self, revision, region_labels):
        receipt = self.store.get("receipt", revision["id"])
        if receipt["confirmed"]["version"] != revision["version"]:
            raise ValueError("只能为当前确认版本积累样本")
        refs = {
            ref
            for value in revision["fields"].values()
            if value["source"] == "image"
            for ref in value["refs"]
        }
        blocks = {
            block.id: (asset, block)
            for image_id in revision["image_ids"]
            for asset in [self.images.get(image_id)]
            for block in asset.blocks
        }
        created = []
        with self.store.transaction() as connection:
            for previous in self.store.list("sample", connection):
                if (
                    previous["receipt_id"] == revision["id"]
                    and previous["receipt_version"] != revision["version"]
                ):
                    previous["status"] = "superseded"
                    self.store.put("sample", previous["id"], previous, connection)
        for ref, label in region_labels.items():
            if ref not in refs or ref not in blocks or not label.strip():
                continue
            asset, block = blocks[ref]
            identifier = sha256(f"{revision['id']}:{revision['version']}:{ref}".encode()).hexdigest()
            path = self.directory / f"{identifier}.png"
            corners = block.polygon
            width = round(max(dist(corners[0], corners[1]), dist(corners[2], corners[3])))
            height = round(max(dist(corners[0], corners[3]), dist(corners[1], corners[2])))
            if width < 1 or height < 1:
                raise ValueError("文字区域无效，无法生成样本")
            with Image.open(asset.path) as image:
                quad = tuple(
                    number for point in [corners[0], corners[3], corners[2], corners[1]] for number in point
                )
                image.transform(
                    (width, height), Image.Transform.QUAD, quad, resample=Image.Resampling.BICUBIC
                ).save(path)
            sample = {
                "id": identifier,
                "receipt_id": revision["id"],
                "receipt_version": revision["version"],
                "image_id": asset.id,
                "block_id": ref,
                "corrected_text": label.strip(),
                "ocr_text": block.text,
                "crop_path": str(path),
                "status": "active",
                "operator": revision["operator"],
                "confirmed_at": revision["confirmed_at"],
            }
            self.store.put("sample", identifier, sample)
            created.append(sample)
        return created
