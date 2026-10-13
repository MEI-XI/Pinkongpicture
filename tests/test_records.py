from datetime import datetime, timezone, timedelta
from io import BytesIO

import pytest
from PIL import Image

from app.images import ImageStore


def make_image(root):
    buffer = BytesIO()
    Image.new("RGB", (200, 80), "white").save(buffer, format="PNG")
    return ImageStore(root).import_image("label.png", buffer.getvalue()).id


def verified_fields(**changes):
    values = dict(name="复配稳定剂", specification="25kg/袋", manufacturer="青山食品有限公司",
                  address="浙江省杭州市测试路1号", lot="00123", production_date="2026年10月1日",
                  shelf_life="12个月")
    values.update(changes)
    return {key: {"raw": value, "value": value, "source": "external", "note": "送货单A经核实"}
            for key, value in values.items()}


def test_confirmed_receipt_survives_reopen_with_fixed_beijing_entry_time(tmp_path):
    from app.records import Records

    now = datetime(2026, 10, 13, 2, 30, tzinfo=timezone.utc)
    records = Records(tmp_path, clock=lambda: now)
    draft = records.create_receipt([make_image(tmp_path)])
    confirmed = records.confirm_receipt(draft["id"], fields=verified_fields(), operator="王检验",
                                        expected_version=0, grouping_reviewed=True)
    assert confirmed["entered_at"] == "2026-10-13T10:30:00+08:00"
    assert confirmed["fields"]["lot"]["value"] == "00123"
    reopened = Records(tmp_path).get(draft["id"])
    assert reopened["confirmed"]["operator"] == "王检验"
    assert reopened["confirmed"]["version"] == 1
    assert len(Records(tmp_path).list_confirmed()) == 1


@pytest.mark.parametrize("bad_field", [
    {"raw": "", "value": "", "source": "external", "note": "送货单"},
    {"raw": "", "value": "未标注", "source": "missing", "note": ""},
    {"raw": "00123", "value": "00123", "source": "external", "note": ""},
    {"raw": "00123", "value": "00123", "source": "image", "refs": ["other:1"]},
])
def test_confirmation_requires_evidence_or_an_explicit_missing_reason(tmp_path, bad_field):
    from app.records import Records

    records = Records(tmp_path)
    receipt = records.create_receipt([make_image(tmp_path)])
    fields = verified_fields()
    fields["lot"] = bad_field
    with pytest.raises(ValueError):
        records.confirm_receipt(receipt["id"], fields=fields, operator="王检验", expected_version=0,
                                grouping_reviewed=True)
    assert records.list_confirmed() == []


def test_edit_keeps_last_confirmed_snapshot_until_reconfirmation(tmp_path):
    from app.records import Records

    instant = [datetime(2026, 10, 13, 2, 30, tzinfo=timezone.utc)]
    records = Records(tmp_path, clock=lambda: instant[0])
    receipt = records.create_receipt([make_image(tmp_path)])
    records.confirm_receipt(receipt["id"], fields=verified_fields(), operator="王检验",
                            expected_version=0, grouping_reviewed=True)
    instant[0] += timedelta(days=1)
    draft = records.edit_receipt(receipt["id"], fields=verified_fields(lot="00124"),
                                 operator="李检验", reason="复核送货单更正", expected_version=1)
    assert records.list_confirmed()[0]["fields"]["lot"]["value"] == "00123"
    assert draft["pending"] is True
    revision = records.confirm_receipt(receipt["id"], fields=draft["draft"]["fields"],
                                       operator="李检验", expected_version=draft["version"],
                                       grouping_reviewed=True, reason="复核送货单更正")
    assert revision["fields"]["lot"]["value"] == "00124"
    assert revision["entered_at"] == "2026-10-13T10:30:00+08:00"
    history = records.get(receipt["id"])
    assert [r["fields"]["lot"]["value"] for r in history["history"]] == ["00123", "00124"]
    assert history["changes"][-1]["operator"] == "李检验"
    assert history["changes"][-1]["before"]["fields"]["lot"]["value"] == "00123"
    assert history["changes"][-1]["after"]["fields"]["lot"]["value"] == "00124"


@pytest.mark.parametrize("operator,reviewed", [("", True), ("王检验", False)])
def test_confirmation_requires_named_operator_and_group_check(tmp_path, operator, reviewed):
    from app.records import Records
    records = Records(tmp_path)
    receipt = records.create_receipt([make_image(tmp_path)])
    with pytest.raises(ValueError):
        records.confirm_receipt(receipt["id"], fields=verified_fields(), operator=operator,
                                expected_version=0, grouping_reviewed=reviewed)


def test_editing_confirmed_record_requires_reason_and_stale_writes_are_rejected(tmp_path):
    from app.records import Records
    records = Records(tmp_path)
    receipt = records.create_receipt([make_image(tmp_path)])
    records.confirm_receipt(receipt["id"], fields=verified_fields(), operator="王检验",
                            expected_version=0, grouping_reviewed=True)
    with pytest.raises(ValueError):
        records.edit_receipt(receipt["id"], fields=verified_fields(lot="00002"), operator="王检验",
                             expected_version=1, reason="")
    with pytest.raises(ValueError):
        records.confirm_receipt(receipt["id"], fields=verified_fields(lot="00002"), operator="王检验",
                                expected_version=0, grouping_reviewed=True, reason="修改")


def test_explicit_missing_is_allowed_and_new_arrivals_are_never_deduplicated(tmp_path):
    from app.records import Records
    records = Records(tmp_path)
    fields = verified_fields()
    fields["shelf_life"] = {"source": "missing", "note": "已核对包装全部信息面，未标注"}
    for _ in range(2):
        receipt = records.create_receipt([make_image(tmp_path)])
        records.confirm_receipt(receipt["id"], fields=fields, operator="王检验",
                                expected_version=0, grouping_reviewed=True)
    assert len(records.list_confirmed()) == 2
    assert records.list_confirmed()[0]["fields"]["shelf_life"]["value"] == "未标注"
