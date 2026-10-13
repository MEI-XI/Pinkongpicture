from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from app.domain import FIELDS, FieldValue
from app.extraction import normalize_date
from app.images import ImageStore
from app.products import Products
from app.storage import Store

BEIJING = timezone(timedelta(hours=8))


class Records:
    def __init__(self, root: Path, clock=None):
        self.store = Store(root)
        self.images = ImageStore(root)
        self.products = Products(root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def create_receipt(self, image_ids):
        if not image_ids:
            raise ValueError("请先选择至少一张图片")
        for identifier in image_ids:
            self.images.get(identifier)
        receipt = {
            "id": uuid4().hex,
            "version": 0,
            "entered_at": None,
            "draft": {
                "image_ids": list(dict.fromkeys(image_ids)),
                "fields": {},
                "grouping_reviewed": False,
                "region_labels": {},
                "product_decision": {"mode": "new"},
            },
            "confirmed": None,
            "history": [],
            "changes": [],
            "pending": True,
        }
        with self.store.transaction() as connection:
            assigned = {
                image for row in self.store.list("receipt", connection) for image in row["draft"]["image_ids"]
            }
            if assigned.intersection(image_ids):
                raise ValueError("部分照片已归组，请使用移动照片调整归属")
            self.store.put("receipt", receipt["id"], receipt, connection)
        return receipt

    def get(self, identifier):
        return self.store.get("receipt", identifier)

    def list(self):
        return self.store.list("receipt")

    def list_confirmed(self):
        return [record["confirmed"] for record in self.list() if record["confirmed"]]

    def move_image(self, image_id, target_id, *, operator, reason, expected_versions):
        if not operator.strip() or not reason.strip():
            raise ValueError("请填写操作人和可核实的归组依据")
        self.images.get(image_id)
        with self.store.transaction() as connection:
            receipts = self.store.list("receipt", connection)
            source = next((row for row in receipts if image_id in row["draft"]["image_ids"]), None)
            target = next((row for row in receipts if row["id"] == target_id), None)
            if target_id is not None and target is None:
                raise ValueError("目标图片组不存在")
            if source is target:
                return
            for receipt in [row for row in (source, target) if row is not None]:
                if expected_versions.get(receipt["id"]) != receipt["version"]:
                    raise ValueError("图片组已发生变化，请刷新后重试")
                before = deepcopy(receipt["draft"])
                if receipt is source:
                    receipt["draft"]["image_ids"].remove(image_id)
                else:
                    receipt["draft"]["image_ids"].append(image_id)
                available = {
                    block["id"]
                    for identifier in receipt["draft"]["image_ids"]
                    for block in self.store.get("image", identifier, connection)["blocks"]
                }
                receipt["draft"]["fields"] = {
                    key: value
                    for key, value in receipt["draft"]["fields"].items()
                    if value["source"] != "image" or set(value["refs"]).issubset(available)
                }
                receipt["draft"]["grouping_reviewed"] = False
                receipt["draft"]["region_labels"] = {
                    ref: label
                    for ref, label in receipt["draft"].get("region_labels", {}).items()
                    if ref in available
                }
                receipt.update(pending=True, version=receipt["version"] + 1)
                receipt["changes"].append(
                    {
                        "operator": operator,
                        "reason": reason,
                        "at": self.clock().astimezone(BEIJING).isoformat(timespec="seconds"),
                        "before": before,
                        "after": deepcopy(receipt["draft"]),
                    }
                )
                self.store.put("receipt", receipt["id"], receipt, connection)

    def edit_receipt(
        self,
        identifier,
        *,
        fields,
        operator,
        reason,
        expected_version,
        grouping_reviewed=False,
        region_labels=None,
        product_decision=None,
    ):
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
            receipt["draft"]["grouping_reviewed"] = grouping_reviewed
            if region_labels is not None:
                receipt["draft"]["region_labels"] = region_labels
            if product_decision is not None:
                receipt["draft"]["product_decision"] = product_decision
            receipt["changes"].append(
                {
                    "operator": operator,
                    "reason": reason,
                    "at": self.clock().astimezone(BEIJING).isoformat(timespec="seconds"),
                    "before": before,
                    "after": deepcopy(receipt["draft"]),
                }
            )
            receipt.update(pending=True, version=receipt["version"] + 1)
            self.store.put("receipt", identifier, receipt, connection)
        return receipt

    def confirm_receipt(
        self,
        identifier,
        *,
        fields,
        operator,
        expected_version,
        grouping_reviewed,
        reason="",
        product_decision=None,
        region_labels=None,
    ):
        if not operator.strip() or not grouping_reviewed:
            raise ValueError("请填写操作人，并确认图片属于同一产品、同一批号")
        with self.store.transaction() as connection:
            receipt = self.store.get("receipt", identifier, connection)
            if receipt["version"] != expected_version:
                raise ValueError("记录已发生变化，请刷新后重新核对")
            if receipt["confirmed"] and not reason.strip():
                raise ValueError("重新确认需要填写修改原因和资料来源")
            if not receipt["draft"]["image_ids"]:
                raise ValueError("当前组没有图片，请补充后再确认")
            timestamp = self.clock().astimezone(BEIJING).isoformat(timespec="seconds")
            entered = receipt["entered_at"] or timestamp
            values = {key: FieldValue.model_validate(value).model_dump() for key, value in fields.items()}
            if set(values) != set(FIELDS):
                raise ValueError("请核对全部七个字段")
            available_refs = {
                block["id"]
                for image_id in receipt["draft"]["image_ids"]
                for block in self.store.get("image", image_id, connection)["blocks"]
            }
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
            date_field = values["production_date"]
            if date_field["source"] != "missing":
                if any(
                    word in date_field["value"]
                    for word in ("见封口", "见瓶", "见袋", "见包装", "见喷码", "见标签")
                ):
                    raise ValueError("生产日期仍是位置指示，请补拍对应部位或依据核实资料填写")
                if normalize_date(date_field["raw"]) != normalize_date(date_field["value"]):
                    # The packaging transcription follows a correction; the original OCR
                    # remains in immutable image blocks, not in an exportable wrong date.
                    date_field["raw"] = date_field["value"]
                date_field["value"] = normalize_date(date_field["value"])
            if product_decision is None:
                previous = receipt["confirmed"]
                product_decision = (
                    {"mode": "link", "id": previous["product"]["id"]} if previous else {"mode": "new"}
                )
            product = self.products.link_product(values, product_decision, connection)
            snapshot = {
                "id": identifier,
                "version": len(receipt["history"]) + 1,
                "fields": values,
                "image_ids": receipt["draft"]["image_ids"],
                "operator": operator,
                "entered_at": entered,
                "confirmed_at": timestamp,
                "reason": reason,
                "product": product,
                "region_labels": region_labels or {},
            }
            receipt["confirmed"] = snapshot
            receipt["history"].append(deepcopy(snapshot))
            receipt["draft"].update(
                fields=deepcopy(values),
                grouping_reviewed=True,
                region_labels=region_labels or {},
                product_decision={"mode": "link", "id": product["id"]},
            )
            receipt.update(entered_at=entered, pending=False, version=receipt["version"] + 1)
            for sample in self.store.list("sample", connection):
                if sample["receipt_id"] == identifier and sample["status"] == "active":
                    sample["status"] = "superseded"
                    self.store.put("sample", sample["id"], sample, connection)
            self.store.put("receipt", identifier, receipt, connection)
        return snapshot
