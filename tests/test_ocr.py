from io import BytesIO

from PIL import Image

from app.images import ImageStore


def test_import_corrects_phone_orientation_and_preserves_source(tmp_path):
    """Wrong EXIF handling would put review and crop coordinates on different pixels."""
    source = Image.new("RGB", (60, 30), "white")
    source.paste("red", (0, 0, 30, 30))
    exif = Image.Exif()
    exif[274] = 6
    buffer = BytesIO()
    source.save(buffer, format="JPEG", exif=exif)
    original = buffer.getvalue()
    store = ImageStore(tmp_path)
    asset = store.import_image("手机照片.jpg", original)
    assert (asset.width, asset.height) == (30, 60)
    assert buffer.getvalue() == original
    reopened = ImageStore(tmp_path).get(asset.id)
    with Image.open(reopened.path) as displayed:
        assert displayed.getpixel((15, 10))[0] > 200
        assert displayed.getpixel((15, 10))[1] < 40
        assert displayed.getexif().get(274, 1) == 1
    assert store.import_image("手机照片.jpg", original).id != asset.id


def test_one_failed_ocr_does_not_discard_other_images(tmp_path):
    from app.domain import OcrBlock
    from app.ocr import OcrService

    buffer = BytesIO()
    Image.new("RGB", (60, 30), "white").save(buffer, format="PNG")
    images = ImageStore(tmp_path)
    bad = images.import_image("bad.png", buffer.getvalue())
    good = images.import_image("good.png", buffer.getvalue())

    class Engine:
        def recognize(self, asset):
            if asset.name == "bad.png":
                raise RuntimeError("识别失败")
            return [OcrBlock(id="b1", image_id=asset.id, text="批号:00123",
                             polygon=[(1, 2), (55, 2), (55, 20), (1, 20)], score=0.91)]

    service = OcrService(images, Engine())
    service.submit([bad.id, good.id])
    service.close()
    assert images.get(bad.id).status == "error"
    result = images.get(good.id)
    assert result.status == "done"
    assert result.blocks[0].text == "批号:00123"
    assert result.blocks[0].polygon[0] == (1, 2)
