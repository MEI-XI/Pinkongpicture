import re
from datetime import date

from app.domain import FIELDS, FieldCandidate, OcrBlock

LABELS = {
    "name": ["产品名称", "品名", "名称"],
    "specification": ["规格型号", "规格", "净含量"],
    "manufacturer": ["生产厂商", "生产厂家", "生产企业", "生产商", "生产单位", "制造商"],
    "address": ["生产地址", "生产地", "厂址", "地址"],
    "lot": ["生产批号", "产品批号", "批号", "批次", "LOT"],
    "production_date": ["生产日期", "制造日期"],
    "shelf_life": ["保质期"],
}
LABEL_TO_FIELD = {label: key for key, labels in LABELS.items() for label in labels}
LABEL_PATTERN = re.compile(
    r"(?:^|[\s;；])(" + "|".join(sorted(LABEL_TO_FIELD, key=len, reverse=True)) + r")\s*[:：]?\s*",
    re.IGNORECASE,
)


def normalize_date(raw: str) -> str:
    text = raw.strip()
    match = re.fullmatch(r"(\d{4})[年./-](\d{1,2})[月./-](\d{1,2})日?", text)
    if match is None:
        match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text)
    if match:
        try:
            return date(*(int(value) for value in match.groups())).isoformat()
        except ValueError:
            pass
    return text


def extract_candidates(blocks: list[OcrBlock]) -> dict[str, list[FieldCandidate]]:
    result = {key: [] for key in FIELDS}
    ordered = sorted(
        blocks, key=lambda b: (b.image_id, min(y for _, y in b.polygon), min(x for x, _ in b.polygon))
    )
    for position, block in enumerate(ordered):
        matches = list(LABEL_PATTERN.finditer(block.text))
        for index, match in enumerate(matches):
            label = match.group(1)
            key = LABEL_TO_FIELD.get(label, "lot")
            end = matches[index + 1].start() if index + 1 < len(matches) else len(block.text)
            raw = block.text[match.end() : end].strip(" :：;；")
            refs = [block.id]
            if (not raw or key == "address") and index == len(matches) - 1:
                previous = block
                for following in ordered[position + 1 : position + 4]:
                    height = max(y for _, y in previous.polygon) - min(y for _, y in previous.polygon)
                    gap = min(y for _, y in following.polygon) - max(y for _, y in previous.polygon)
                    left = abs(min(x for x, _ in block.polygon) - min(x for x, _ in following.polygon))
                    if (
                        following.image_id != block.image_id
                        or not 0 <= gap <= height * 1.2
                        or left > height * 2
                        or LABEL_PATTERN.search(following.text)
                        or re.search(r"[:：]|委托|注册|储存|贮存|执行标准|注意|电话|许可证", following.text)
                    ):
                        break
                    raw += following.text.strip()
                    refs.append(following.id)
                    previous = following
                    if key != "address":
                        break
            if not raw:
                continue
            normalized = normalize_date(raw) if key == "production_date" else raw
            unclear_date = False
            if key == "production_date":
                try:
                    date.fromisoformat(normalized)
                except ValueError:
                    unclear_date = True
            result[key].append(
                FieldCandidate(
                    raw=raw,
                    value=normalized,
                    refs=refs,
                    reason=f"标签“{label}”" + ("，合并相邻文字" if len(refs) > 1 else ""),
                    needs_review=unclear_date or len(refs) > 1,
                )
            )
    for candidates in result.values():
        if len({candidate.value for candidate in candidates}) > 1:
            for candidate in candidates:
                candidate.needs_review = True
    return result
