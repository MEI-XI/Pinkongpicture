import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from uuid import uuid4

from app.storage import Store

IDENTITY = ("name", "specification", "manufacturer")
PROFILE = (*IDENTITY, "address")


def normalized(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


class Products:
    def __init__(self, root):
        self.store = Store(root)

    def get(self, identifier):
        return self.store.get("product", identifier)

    def list(self):
        return self.store.list("product")

    def suggest_products(self, fields):
        candidates = []
        for product in self.list():
            current = product["versions"][-1]
            scores = [
                SequenceMatcher(None, normalized(fields[key]), normalized(current[key])).ratio()
                for key in IDENTITY
                if fields.get(key)
            ]
            score = sum(scores) / len(scores) if scores else 0
            if score >= 0.45:
                candidates.append(
                    {
                        "id": product["id"],
                        "code": product["code"],
                        "current": current,
                        "score": round(score, 3),
                        "differences": [
                            key
                            for key in PROFILE
                            if fields.get(key) and normalized(fields[key]) != normalized(current[key])
                        ],
                    }
                )
        return sorted(candidates, key=lambda item: item["score"], reverse=True)[:10]

    def link_product(self, fields, decision, connection=None):
        if connection is None:
            with self.store.transaction() as transaction:
                return self.link_product(fields, decision, transaction)
        values = {key: fields[key]["value"] for key in PROFILE}
        if decision["mode"] == "new":
            identifier = uuid4().hex
            product = {"id": identifier, "code": f"PK-{identifier[:10].upper()}", "versions": []}
        elif decision["mode"] == "link":
            product = self.store.get("product", decision["id"], connection)
            current = product["versions"][-1]
            if any(normalized(values[key]) != normalized(current[key]) for key in IDENTITY):
                raise ValueError("产品名称、规格或生产厂商不同，请新建产品档案")
            if normalized(values["address"]) != normalized(current["address"]):
                if not decision.get("accept_address_change"):
                    raise ValueError("生产地址发生变化，请核实并确认新增档案版本")
        else:
            raise ValueError("请选择新建档案或关联已有档案")
        if not product["versions"] or values != {key: product["versions"][-1][key] for key in PROFILE}:
            product["versions"].append(
                {
                    **values,
                    "version": len(product["versions"]) + 1,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        self.store.put("product", product["id"], product, connection)
        return {"id": product["id"], "code": product["code"], "version": product["versions"][-1]["version"]}
