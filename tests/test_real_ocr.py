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
