from datetime import datetime, timezone

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from tests.test_records import make_image, verified_fields


def template(root):
    path = root / "provided-template.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.title = "来料"
    sheet["A1"] = "产品名称"
    sheet["E2"].number_format = "@"
    sheet["A2"].font = Font(name="微软雅黑", bold=True)
    sheet["A2"].fill = PatternFill("solid", fgColor="DDEEFF")
    sheet["J2"] = "=ROW()-1"
    book.save(path)
    return path


def mapping():
    return {
        "sheet": "来料",
        "start_row": 2,
        "end_row": 20,
        "columns": dict(
            zip(
                [
                    "name",
                    "specification",
                    "manufacturer",
                    "address",
                    "lot",
                    "production_date",
                    "shelf_life",
                    "entered_at",
                    "operator",
                ],
                "ABCDEFGHI",
            )
        ),
        "date_mode": "raw",
        "missing_mode": "with_reason",
    }


def test_exports_only_confirmed_snapshot_and_preserves_template_and_leading_zeros(tmp_path):
    from app.excel import ExcelExporter
    from app.records import Records

    records = Records(tmp_path / "data")
    receipt = records.create_receipt([make_image(tmp_path / "data")])
    records.confirm_receipt(
        receipt["id"], fields=verified_fields(), operator="王检验", expected_version=0, grouping_reviewed=True
    )
    records.create_receipt([make_image(tmp_path / "data")])
    records.edit_receipt(
        receipt["id"],
        fields=verified_fields(lot="00555"),
        operator="王检验",
        expected_version=1,
        reason="更正中",
    )
    source = template(tmp_path)
    original = source.read_bytes()
    exporter = ExcelExporter(tmp_path / "data")
    output = exporter.export_confirmed(source, mapping())
    sheet = load_workbook(output["path"]).active
    assert output["count"] == 1
    assert output["pending_count"] == 1
    assert sheet["E2"].value == "00123"
    assert sheet["E2"].data_type == "s"
    assert sheet["A2"].font.bold is True
    assert sheet["A2"].fill.fgColor.rgb == "00DDEEFF"
    assert sheet["A3"].value is None
    assert sheet["J2"].value == "=ROW()-1"
    assert source.read_bytes() == original
    saved = output["path"].read_bytes()
    second = exporter.export_confirmed(source, mapping())
    assert second["path"] != output["path"]
    assert output["path"].read_bytes() == saved


def test_export_filter_uses_original_entry_date_and_writes_untrusted_text_as_text(tmp_path):
    from app.excel import ExcelExporter
    from app.records import Records

    now = [datetime(2026, 10, 13, 1, tzinfo=timezone.utc)]
    records = Records(tmp_path / "data", clock=lambda: now[0])
    fields = verified_fields(name="=DANGEROUS()")
    fields["shelf_life"] = {"source": "missing", "note": "包装未列保质期"}
    first = records.create_receipt([make_image(tmp_path / "data")])
    records.confirm_receipt(
        first["id"], fields=fields, operator="王检验", expected_version=0, grouping_reviewed=True
    )
    now[0] = datetime(2026, 10, 14, 1, tzinfo=timezone.utc)
    second = records.create_receipt([make_image(tmp_path / "data")])
    records.confirm_receipt(
        second["id"],
        fields=verified_fields(lot="00009"),
        operator="王检验",
        expected_version=0,
        grouping_reviewed=True,
    )
    export = ExcelExporter(tmp_path / "data").export_confirmed(
        template(tmp_path), mapping(), {"date_from": "2026-10-13", "date_to": "2026-10-13", "lot": "00123"}
    )
    sheet = load_workbook(export["path"]).active
    assert export["count"] == 1
    assert sheet["A2"].value == "=DANGEROUS()"
    assert sheet["A2"].data_type == "s"
    assert sheet["G2"].value == "未标注（包装未列保质期）"
    assert sheet["F2"].value == "2026年10月1日"


def test_template_mapping_rejects_collisions_and_does_not_overwrite_existing_cells(tmp_path):
    from app.excel import ExcelExporter

    source = template(tmp_path)
    exporter = ExcelExporter(tmp_path / "data")
    config = mapping()
    config["columns"]["operator"] = "A"
    with pytest.raises(ValueError):
        exporter.export_confirmed(source, config)
    book = load_workbook(source)
    book.active["E2"] = "模板示例，必须先清空"
    book.save(source)
    with pytest.raises(ValueError):
        exporter.export_confirmed(source, mapping())
