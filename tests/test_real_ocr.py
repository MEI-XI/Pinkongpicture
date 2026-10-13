import os
from io import BytesIO

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.images import ImageStore


@pytest.mark.real_ocr
@pytest.mark.skipif(os.environ.get("RUN_REAL_OCR") != "1", reason="set RUN_REAL_OCR=1 to load CPU models")
def test_real_cpu_reads_printed_lot_and_returns_display_coordinates(tmp_path):
    from app.ocr import PaddleEngine

    picture = Image.new("RGB", (1000, 240), "white")
    draw = ImageDraw.Draw(picture)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 56)
    draw.text((40, 60), "LOT: 00123", font=font, fill="black")
    buffer = BytesIO()
    picture.save(buffer, format="PNG")
    asset = ImageStore(tmp_path).import_image("synthetic-lot.png", buffer.getvalue())
    blocks = PaddleEngine().recognize(asset)
    assert any("00123" in block.text for block in blocks)
    assert all(0 <= x <= 1000 and 0 <= y <= 240 for block in blocks for x, y in block.polygon)


@pytest.mark.real_ocr
@pytest.mark.skipif(os.environ.get("RUN_REAL_OCR") != "1", reason="set RUN_REAL_OCR=1 to load CPU models")
@pytest.mark.parametrize("profile", ["mobile", "server"])
def test_real_chinese_label_pipeline(profile, tmp_path):
    """Printed synthetic label smoke test, not an accuracy claim for real packaging."""
    from time import perf_counter

    from app.extraction import extract_candidates
    from app.ocr import PaddleEngine

    picture = Image.new("RGB", (1300, 650), "white")
    draw = ImageDraw.Draw(picture)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 42)
    for line, text in enumerate(
        [
            "产品名称：复配稳定剂",
            "规格：25kg/袋",
            "生产厂商：青山食品有限公司",
            "生产地址：浙江省杭州市测试路1号",
            "生产批号：00123",
            "生产日期：2026年10月1日",
            "保质期：12个月",
        ]
    ):
        draw.text((40, 30 + 80 * line), text, font=font, fill="black")
    buffer = BytesIO()
    picture.save(buffer, format="PNG")
    asset = ImageStore(tmp_path).import_image("synthetic-chinese.png", buffer.getvalue())
    engine = PaddleEngine(profile=profile)
    start = perf_counter()
    first = engine.recognize(asset)
    first_seconds = perf_counter() - start
    start = perf_counter()
    second = engine.recognize(asset)
    warm_seconds = perf_counter() - start
    result = extract_candidates(second)
    assert result["name"][0].value == "复配稳定剂"
    assert result["lot"][0].value == "00123"
    assert result["production_date"][0].value == "2026-10-01"
    assert all(result[key] for key in result)
    print(f"{profile}: first={first_seconds:.3f}s warm={warm_seconds:.3f}s blocks={len(first)}")
