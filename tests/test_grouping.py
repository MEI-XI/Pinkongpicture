from app.extraction import extract_candidates
from tests.test_extraction import block
from tests.test_records import make_image, verified_fields


def clues(image, lot):
    texts = ["产品名称：复配稳定剂", "规格：25kg", "生产厂商：青山公司"]
    if lot:
        texts.append(f"批号：{lot}")
    return extract_candidates([block(text, n, image=image) for n, text in enumerate(texts)])


def test_different_lots_are_split_and_unidentified_backs_remain_ungrouped():
    from app.grouping import propose_groups

    result = propose_groups(
        {
            "a": clues("a", "00123"),
            "b": clues("b", "00123"),
            "c": clues("c", "00999"),
            "back1": clues("back1", None),
            "back2": clues("back2", None),
        }
    )
    assert [group["image_ids"] for group in result["groups"]] == [["a", "b"], ["c"]]
    assert {item["image_id"] for item in result["ungrouped"]} == {"back1", "back2"}


def test_conflicting_batch_candidates_do_not_join_a_group():
    from app.grouping import propose_groups

    values = clues("a", "00123")
    values["lot"].extend(clues("a", "00999")["lot"])
    result = propose_groups({"a": values})
    assert result["groups"] == []
    assert result["ungrouped"][0]["image_id"] == "a"


def test_moving_photo_clears_stale_field_evidence_and_requires_recheck(tmp_path):
    from pytest import raises

    from app.domain import OcrBlock
    from app.images import ImageStore
    from app.records import Records

    records = Records(tmp_path)
    image = make_image(tmp_path)
    other_image = make_image(tmp_path)
    image_store = ImageStore(tmp_path)
    asset = image_store.get(image)
    asset.blocks = [
        OcrBlock(
            id=f"{image}:0",
            image_id=image,
            text="批号：00123",
            score=0.9,
            polygon=[(0, 0), (100, 0), (100, 30), (0, 30)],
        )
    ]
    image_store.save(asset)
    source = records.create_receipt([image, other_image])
    target = records.create_receipt([make_image(tmp_path)])
    fields = verified_fields()
    fields["lot"] = {"raw": "00123", "value": "00123", "source": "image", "refs": [f"{image}:0"]}
    records.confirm_receipt(
        source["id"], fields=fields, operator="王检验", expected_version=0, grouping_reviewed=True
    )
    records.move_image(
        image,
        target["id"],
        operator="王检验",
        reason="按同批送货单核对归属",
        expected_versions={source["id"]: 1, target["id"]: 0},
    )
    updated = records.get(source["id"])
    assert image not in updated["draft"]["image_ids"]
    assert "lot" not in updated["draft"]["fields"]
    assert updated["draft"]["grouping_reviewed"] is False
    assert updated["pending"] is True
    assert updated["confirmed"]["fields"]["lot"]["value"] == "00123"
    assert image in records.get(target["id"])["draft"]["image_ids"]
    with raises(ValueError):
        records.confirm_receipt(
            source["id"],
            fields=fields,
            operator="王检验",
            expected_version=2,
            grouping_reviewed=True,
            reason="复核",
        )
