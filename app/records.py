from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.domain import FIELDS, FieldValue
from app.images import ImageStore
from app.storage import Store


BEIJING = timezone(timedelta(hours=8))


class Records:
    def __init__(self, root: Path, clock=None):
        self.store = Store(root)
        self.images = ImageStore(root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def create_receipt(self, image_ids):
        if not image_ids:
            raise ValueError("请先选择至少一张图片")
        for identifier in image_ids:
            self.images.get(identifier)
        receipt = {"id": uuid4().hex, "version": 0, "entered_at": None,
                   "draft": {"image_ids": list(dict.fromkeys(image_ids)), "fields": {},
                             "grouping_reviewed": False},
                   "confirmed": None, "history": [], "changes": [], "pending": True}
        self.store.put("receipt", receipt["id"], receipt)
        return receipt

    def get(self, identifier):
        return self.store.get("receipt", identifier)

    def list(self):
        return self.store.list("receipt")

    def list_confirmed(self):
        return [record["confirmed"] for record in self.list() if record["confirmed"]]

    def edit_receipt(self, identifier, *, fields, operator, reason, expected_version):
        with self.store.transaction() as connection:
            receipt = self.store.get("receipt", identifier, connection)
            if receipt["version"] != expected_version:
                raise ValueError("记录已发生变化，请刷新后重新核对")
            if not operator.strip() or (receipt["confirmed"] and not reason.strip()):
                raise ValueError("请填写操作人和修改原因")
            before = deepcopy(receipt["draft"])
            receipt["draft"]["fields"] = {
                key: FieldValue.model_validate(value).model_dump() for key, value in fields.items()
            }
            receipt["changes"].append({"operator": operator, "reason": reason,
                                       "at": self.clock().astimezone(BEIJING).isoformat(timespec="seconds"),
                                       "before": before, "after": deepcopy(receipt["draft"])})
            receipt.update(pending=True, version=receipt["version"] + 1)
            self.store.put("receipt", identifier, receipt, connection)
        return receipt

    def confirm_receipt(self, identifier, *, fields, operator, expected_version, grouping_reviewed,
                        reason="", **options):
        if not operator.strip() or not grouping_reviewed:
            raise ValueError("请填写操作人，并确认图片属于同一产品、同一批号")
        with self.store.transaction() as connection:
            receipt = self.store.get("receipt", identifier, connection)
            if receipt["version"] != expected_version:
                raise ValueError("记录已发生变化，请刷新后重新核对")
            if receipt["confirmed"] and not reason.strip():
                raise ValueError("重新确认需要填写修改原因和资料来源")
            timestamp = self.clock().astimezone(BEIJING).isoformat(timespec="seconds")
            entered = receipt["entered_at"] or timestamp
            values = {key: FieldValue.model_validate(value).model_dump() for key, value in fields.items()}
            if set(values) != set(FIELDS):
                raise ValueError("请核对全部七个字段")
            available_refs = {block["id"] for image_id in receipt["draft"]["image_ids"]
                              for block in self.store.get("image", image_id, connection)["blocks"]}
            for key, field in values.items():
                if field["source"] == "missing":
                    if not field["note"].strip():
                        raise ValueError(f"{FIELDS[key]}：请说明未标注的依据")
                    field["value"] = "未标注"
                elif not field["value"].strip():
                    raise ValueError(f"{FIELDS[key]}：请填写或明确标记未标注")
                elif field["source"] == "external" and not field["note"].strip():
                    raise ValueError(f"{FIELDS[key]}：请填写核实资料来源")
                elif field["source"] == "image" and (
                    not field["refs"] or not set(field["refs"]).issubset(available_refs)
                ):
                    raise ValueError(f"{FIELDS[key]}：请选择当前图片中的文字依据")
            snapshot = {"id": identifier, "version": len(receipt["history"]) + 1,
                        "fields": values, "image_ids": receipt["draft"]["image_ids"],
                        "operator": operator, "entered_at": entered,
                        "confirmed_at": timestamp, "reason": reason, "product": None}
            receipt["confirmed"] = snapshot
            receipt["history"].append(deepcopy(snapshot))
            receipt["draft"].update(fields=deepcopy(values), grouping_reviewed=True)
            receipt.update(entered_at=entered, pending=False, version=receipt["version"] + 1)
            self.store.put("receipt", identifier, receipt, connection)
        return snapshot
