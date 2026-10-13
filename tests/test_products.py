import pytest

from tests.test_records import make_image, verified_fields


def test_product_address_versions_do_not_change_old_receipt_and_memory_excludes_batch(tmp_path):
    from app.products import Products
    from app.records import Records

    records = Records(tmp_path)
    products = Products(tmp_path)
    one = records.create_receipt([make_image(tmp_path)])
    old = records.confirm_receipt(
        one["id"],
        fields=verified_fields(),
        operator="王检验",
        expected_version=0,
        grouping_reviewed=True,
        product_decision={"mode": "new"},
    )
    assert old["product"]["version"] == 1
    suggestions = products.suggest_products(
        {"name": "复配稳定剂", "specification": "25kg/袋", "manufacturer": "青山食品有限公司"}
    )
    assert suggestions[0]["id"] == old["product"]["id"]
    assert "lot" not in suggestions[0]["current"]
    second = records.create_receipt([make_image(tmp_path)])
    changed = verified_fields(address="浙江省杭州市新址2号")
    decision = {"mode": "link", "id": old["product"]["id"], "accept_address_change": True}
    new = records.confirm_receipt(
        second["id"],
        fields=changed,
        operator="王检验",
        expected_version=0,
        grouping_reviewed=True,
        product_decision=decision,
    )
    assert new["product"]["version"] == 2
    assert records.get(one["id"])["confirmed"]["fields"]["address"]["value"] == "浙江省杭州市测试路1号"
    assert len(products.get(old["product"]["id"])["versions"]) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"specification": "20kg/袋"},
        {"manufacturer": "乙公司"},
        {"name": "复配着色剂"},
        {"address": "另一个地址"},
    ],
)
def test_link_conflicts_require_new_profile_or_explicit_address_approval(tmp_path, changes):
    from app.products import Products
    from app.records import Records

    records = Records(tmp_path)
    first = records.create_receipt([make_image(tmp_path)])
    old = records.confirm_receipt(
        first["id"], fields=verified_fields(), operator="王检验", expected_version=0, grouping_reviewed=True
    )
    other = records.create_receipt([make_image(tmp_path)])
    with pytest.raises(ValueError):
        records.confirm_receipt(
            other["id"],
            fields=verified_fields(**changes),
            operator="王检验",
            expected_version=0,
            grouping_reviewed=True,
            product_decision={"mode": "link", "id": old["product"]["id"]},
        )
    assert records.get(other["id"])["confirmed"] is None
    assert len(Products(tmp_path).get(old["product"]["id"])["versions"]) == 1
    new = records.confirm_receipt(
        other["id"],
        fields=verified_fields(**changes),
        operator="王检验",
        expected_version=0,
        grouping_reviewed=True,
        product_decision={"mode": "new"},
    )
    assert new["product"]["id"] != old["product"]["id"]
