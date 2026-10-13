import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter

from app.domain import OcrBlock
from app.images import ImageStore


class PaddleEngine:
    def __init__(self, profile="mobile", model_root: Path | None = None):
        if profile not in {"mobile", "server"}:
            raise ValueError("OCR profile must be mobile or server")
        self.profile = profile
        self.model_root = model_root or Path(__file__).resolve().parent.parent / "models"
        self.model = None

    def recognize(self, asset):
        if self.model is None:
            os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(self.model_root / "paddlex"))
            os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "bos")
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            from paddleocr import PaddleOCR

            self.model = PaddleOCR(
                device="cpu",
                text_detection_model_name=f"PP-OCRv5_{self.profile}_det",
                text_recognition_model_name=f"PP-OCRv5_{self.profile}_rec",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                cpu_threads=4,
                # Paddle 3.3.0 on Windows raises a PIR attribute error with oneDNN.
                enable_mkldnn=False,
            )
        result = self.model.predict(input=str(asset.path))[0].json["res"]
        return [
            OcrBlock(
                id=f"{asset.id}:{index}",
                image_id=asset.id,
                text=text,
                score=score,
                polygon=polygon,
            )
            for index, (text, score, polygon) in enumerate(
                zip(result["rec_texts"], result["rec_scores"], result["rec_polys"], strict=True)
            )
        ]


class OcrService:
    def __init__(self, images: ImageStore, engine):
        self.images = images
        self.engine = engine
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="packaging-ocr")
        self.lock = threading.Lock()

    def submit(self, identifiers: list[str]):
        with self.lock:
            for identifier in dict.fromkeys(identifiers):
                asset = self.images.get(identifier)
                if asset.status in {"queued", "running", "done"}:
                    continue
                asset.status, asset.error = "queued", ""
                self.images.save(asset)
                self.executor.submit(self.recognize_image, identifier)

    def recognize_image(self, identifier: str):
        asset = self.images.get(identifier)
        asset.status = "running"
        self.images.save(asset)
        start = perf_counter()
        try:
            asset.blocks = self.engine.recognize(asset)
            asset.status = "done"
            asset.error = ""
        except Exception as exc:
            asset.status = "error"
            asset.error = str(exc)
        asset.seconds = round(perf_counter() - start, 3)
        self.images.save(asset)
        return asset

    def close(self):
        self.executor.shutdown(wait=True)
