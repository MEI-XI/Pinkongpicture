from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.images import ImageStore
from app.ocr import OcrService, PaddleEngine
from app.records import Records
from app.settings import data_root
from app.views import router


def create_app(root=None, engine=None):
    root = Path(root or data_root())
    images = ImageStore(root)
    for asset in images.list():
        if asset.status in {"queued", "running"}:
            asset.status, asset.error = "error", "上次识别被中断，可点击重试"
            images.save(asset)
    ocr = OcrService(images, engine or PaddleEngine())

    @asynccontextmanager
    async def lifespan(application):
        yield
        ocr.close()

    application = FastAPI(title="品控图片工作台", lifespan=lifespan)
    application.state.root = root
    application.state.images = images
    application.state.records = Records(root)
    application.state.ocr = ocr
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @application.middleware("http")
    async def local_writes(request: Request, call_next):
        origin = request.headers.get("origin")
        expected_origin = f"{request.url.scheme}://{request.url.netloc}"
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin != expected_origin:
            return JSONResponse({"detail": "请从本机工作台页面操作"}, status_code=403)
        return await call_next(request)

    @application.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @application.exception_handler(KeyError)
    async def missing(request: Request, exc: KeyError):
        return JSONResponse({"detail": "记录或资源不存在，请刷新后重试"}, status_code=404)

    application.include_router(router)
    static = Path(__file__).parent / "static"
    static.mkdir(exist_ok=True)
    application.mount("/static", StaticFiles(directory=static), name="static")
    return application
