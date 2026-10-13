from app.domain import OcrBlock


def block(text, n=0, image="one", x=10, y=None):
    y = n * 30 if y is None else y
    return OcrBlock(
        id=f"{image}:{n}",
        image_id=image,
        text=text,
        score=0.92,
        polygon=[(x, y), (x + 400, y), (x + 400, y + 20), (x, y + 20)],
    )


def test_extracts_seven_labelled_fields_preserving_lot_and_original_date():
    from app.extraction import extract_candidates

    texts = [
        "产品名称：复配稳定剂",
        "规格：25kg/袋",
        "生产厂商：青山食品有限公司",
        "生产地址：浙江省杭州市测试路1号",
        "生产批号：00123",
        "生产日期：2026年10月1日",
        "保质期：12个月",
    ]
    result = extract_candidates([block(text, n) for n, text in enumerate(texts)])
    assert {key: values[0].value for key, values in result.items()} == {
        "name": "复配稳定剂",
        "specification": "25kg/袋",
        "manufacturer": "青山食品有限公司",
        "address": "浙江省杭州市测试路1号",
        "lot": "00123",
        "production_date": "2026-10-01",
        "shelf_life": "12个月",
    }
    assert result["production_date"][0].raw == "2026年10月1日"
    assert result["lot"][0].refs == ["one:4"]


def test_multiline_address_stops_before_other_label_and_keeps_all_evidence():
    from app.extraction import extract_candidates

    result = extract_candidates(
        [
            block("生产地址：浙江省杭州市", 0),
            block("临平区测试路1号", 1),
            block("生产日期：见封口", 2),
            block("保质期：12个月", 3),
        ]
    )
    assert result["address"][0].value == "浙江省杭州市临平区测试路1号"
    assert result["address"][0].refs == ["one:0", "one:1"]
    assert result["production_date"][0].needs_review is True


def test_multiple_specs_and_manufacturers_remain_candidates_not_guesses():
    from app.extraction import extract_candidates

    result = extract_candidates(
        [
            block("委托方：甲公司", 0),
            block("注册地址：甲市", 1),
            block("生产商：乙公司", 2),
            block("规格：25kg", 3),
            block("规格：20kg", 4),
        ]
    )
    assert [value.value for value in result["manufacturer"]] == ["乙公司"]
    assert result["address"] == []
    assert [value.value for value in result["specification"]] == ["25kg", "20kg"]
    assert all(value.needs_review for value in result["specification"])


def test_label_on_separate_line_uses_nearby_value_but_does_not_invent_dates():
    from app.extraction import extract_candidates

    result = extract_candidates(
        [
            block("产品名称", 0),
            block("复配稳定剂", 1),
            block("生产日期：03/04/26", 2),
            block("有效期至：2027年1月1日", 3),
        ]
    )
    assert result["name"][0].value == "复配稳定剂"
    assert result["production_date"][0].value == "03/04/26"
    assert result["production_date"][0].needs_review is True
    assert result["shelf_life"] == []


def test_impossible_calendar_date_remains_literal_and_requires_review():
    from app.extraction import extract_candidates

    result = extract_candidates([block("生产日期：2026-02-30")])
    assert result["production_date"][0].value == "2026-02-30"
    assert result["production_date"][0].needs_review is True
