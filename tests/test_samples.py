import pytest
from PIL import Image

from app.domain import OcrBlock
from app.images import ImageStore
from app.records import Records
from tests.test_records import make_image, verified_fields


def test_confirmed_region_correction_saves_actual_crop_and_replaces_older_label(tmp_path):
    from app.samples import Samples

    image_store = ImageStore(tmp_path)
    asset = image_store.get(make_image(tmp_path))
    asset.blocks = [
        OcrBlock(
            id=f"{asset.id}:0",
            image_id=asset.id,
            text="00128",
            score=0.81,
            polygon=[(10, 10), (110, 10), (110, 40), (10, 40)],
        )
    ]
    image_store.save(asset)
    records = Records(tmp_path)
    receipt = records.create_receipt([asset.id])
    fields = verified_fields()
    fields["lot"] = {"raw": "00128", "value": "00123", "source": "image", "refs": [f"{asset.id}:0"]}
    revision = records.confirm_receipt(
        receipt["id"], fields=fields, operator="王检验", expected_version=0, grouping_reviewed=True
    )
    samples = Samples(tmp_path)
    generated = samples.collect_samples(revision, {f"{asset.id}:0": "00123"})
    assert generated[0]["corrected_text"] == "00123"
    assert generated[0]["ocr_text"] == "00128"
    with Image.open(generated[0]["crop_path"]) as crop:
        assert crop.size == (100, 30)
    revised = records.confirm_receipt(
        receipt["id"],
        fields=verified_fields(lot="00124"),
        operator="李检验",
        expected_version=1,
        grouping_reviewed=True,
        reason="送货单补充核实",
    )
    assert samples.collect_samples(revised, {f"{asset.id}:0": "00124"}) == []
    assert samples.list()[0]["status"] == "superseded"


def test_field_level_cross_line_edit_does_not_become_a_single_ocr_label(tmp_path):
    from app.samples import Samples

    records = Records(tmp_path)
    receipt = records.create_receipt([make_image(tmp_path)])
    revision = records.confirm_receipt(
        receipt["id"], fields=verified_fields(), operator="王检验", expected_version=0, grouping_reviewed=True
    )
    assert Samples(tmp_path).collect_samples(revision, {}) == []


def test_reconfirmation_retires_old_samples_even_before_sample_writer_runs(tmp_path):
    from app.samples import Samples

    image_store = ImageStore(tmp_path)
    asset = image_store.get(make_image(tmp_path))
    asset.blocks = [
        OcrBlock(
            id=f"{asset.id}:0",
            image_id=asset.id,
            text="00128",
            score=0.8,
            polygon=[(10, 10), (110, 10), (110, 40), (10, 40)],
        )
    ]
    image_store.save(asset)
    records = Records(tmp_path)
    receipt = records.create_receipt([asset.id])
    fields = verified_fields()
    fields["lot"] = {"raw": "00128", "value": "00123", "source": "image", "refs": [f"{asset.id}:0"]}
    old = records.confirm_receipt(
        receipt["id"], fields=fields, operator="王检验", expected_version=0, grouping_reviewed=True
    )
    samples = Samples(tmp_path)
    samples.collect_samples(old, {f"{asset.id}:0": "00123"})
    records.confirm_receipt(
        receipt["id"],
        fields=verified_fields(),
        operator="王检验",
        expected_version=1,
        grouping_reviewed=True,
        reason="根据送货单更正",
    )
    assert samples.list()[0]["status"] == "superseded"


@pytest.mark.parametrize("reviewed", [False, True])
def test_changed_field_does_not_revalidate_old_label_without_explicit_region_review(tmp_path, reviewed):
    from app.samples import Samples

    images = ImageStore(tmp_path)
    asset = images.get(make_image(tmp_path))
    ref = f"{asset.id}:0"
    asset.blocks = [
        OcrBlock(
            id=ref,
            image_id=asset.id,
            text="00123",
            score=0.8,
            polygon=[(10, 10), (110, 10), (110, 40), (10, 40)],
        )
    ]
    images.save(asset)
    records = Records(tmp_path)
    receipt = records.create_receipt([asset.id])
    fields = verified_fields()
    fields["lot"] = {"raw": "00123", "value": "00123", "source": "image", "refs": [ref]}
    first = records.confirm_receipt(
        receipt["id"],
        fields=fields,
        operator="王检验",
        expected_version=0,
        grouping_reviewed=True,
        region_labels={ref: "00123"},
    )
    samples = Samples(tmp_path)
    samples.collect_samples(first, first["region_labels"])
    fields["lot"]["value"] = "00124"
    options = {"reviewed_region_refs": [ref]} if reviewed else {}
    changed = records.confirm_receipt(
        receipt["id"],
        fields=fields,
        operator="李检验",
        expected_version=1,
        grouping_reviewed=True,
        reason="复核批号",
        region_labels={ref: "00124" if reviewed else "00123"},
        **options,
    )
    generated = samples.collect_samples(changed, changed["region_labels"])
    assert [sample["corrected_text"] for sample in generated] == (["00124"] if reviewed else [])
    assert not any(
        sample["status"] == "active" and sample["corrected_text"] == "00123" for sample in samples.list()
    )
