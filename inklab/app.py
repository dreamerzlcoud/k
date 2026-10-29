import json
import os
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import service, store
from .ai import create_draft
from .inference_server import detect_device, get_job
from .models import AIRequest, GenerateSentenceRequest, Layout, ProfileCreate, Sample

app = FastAPI(title="InkLab", version="0.1.0")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"] +
                   ([urlparse(os.environ["INKLAB_PUBLIC_URL"]).hostname] if os.environ.get("INKLAB_PUBLIC_URL") else []))


@app.middleware("http")
async def local_requests(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
        parsed = urlparse(origin)
        if parsed.netloc != request.headers.get("host") or parsed.scheme != request.url.scheme:
            return JSONResponse({"detail": "다른 웹사이트에서의 변경 요청은 허용되지 않습니다."}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    # Local editing tools should not run stale JavaScript against newer HTML.
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(ValueError)
async def bad_input(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


async def read_upload(file):
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > service.MAX_FILE:
            raise ValueError("최대 업로드 크기는 30MB입니다.")
    return bytes(data)


@app.get("/api/status")
def status():
    ai_conf = bool(
        (os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_MODEL"))
        or os.environ.get("GEMINI_API_KEY")
    )
    model_name = (
        os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        if os.environ.get("GEMINI_API_KEY")
        else (os.environ.get("OPENAI_MODEL") or "local-engineering-solver")
    )
    return {
        "ai_configured": ai_conf,
        "model": model_name,
        "handwriting_ai_ready": True,
        "device": detect_device(),
        "version": "2.0.0",
    }


@app.get("/auth/config")
def auth_config():
    return {"cloud": False}


@app.get("/api/documents")
def documents():
    return [service.inspect_document(p.stem) for p in store.folder("documents").glob("*.pdf")]


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...)):
    return service.import_pdf(await read_upload(file), file.filename or "assignment.pdf")


@app.post("/api/demo")
def demo():
    from .demo import create_demo
    return create_demo()


@app.get("/api/documents/{identifier}/pages/{page}.png")
def page_image(identifier: str, page: int):
    return Response(service.page_png(identifier, page), media_type="image/png")


@app.get("/api/profiles")
def profiles():
    return store.list_profiles()


@app.post("/api/profiles")
def create_profile(body: ProfileCreate):
    profile = {"id": store.new_id(), "name": body.name, "glyphs": {}}
    store.write_json(store.item_path("profiles", profile["id"], "json"), profile)
    return profile


@app.post("/api/profiles/{identifier}/samples")
def add_sample(identifier: str, body: Sample):
    return service.add_sample(identifier, body)


@app.get("/api/profiles/{identifier}/adaptive-prompts")
def adaptive_prompts(identifier: str):
    return service.get_profile_status(identifier)


@app.post("/api/handwriting/generate")
def generate_handwriting(body: GenerateSentenceRequest):
    return service.generate_sentence_preview(body)


@app.get("/api/documents/{identifier}/blank-spaces")
def blank_spaces(identifier: str, page: int = 0):
    return {"page": page, "regions": service.find_blank_spaces(identifier, page)}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    return get_job(job_id)


@app.delete("/api/profiles/{identifier}/glyphs/{codepoint}")
def delete_glyph(identifier: str, codepoint: int):
    with store.LOCK:
        profile = store.profile(identifier)
        ch = chr(codepoint)
        profile["glyphs"].pop(ch, None)
        profile.get("strokes", {}).pop(ch, None)
        store.write_json(store.item_path("profiles", identifier, "json"), profile)
    return profile


@app.post("/api/sample-sheets")
async def upload_samples(file: UploadFile = File(...)):
    return service.sample_pages(await read_upload(file), file.filename or "sample.png")


@app.get("/api/sample-sheets/{identifier}.png")
def sample_sheet(identifier: str):
    path = store.item_path("samples", identifier, "png")
    if not path.exists():
        raise HTTPException(404, "샘플 파일이 없습니다.")
    return FileResponse(path, media_type="image/png")


@app.put("/api/layouts")
def save_layout(body: Layout):
    return service.save_layout(body)


@app.get("/api/layouts/{identifier}")
def get_layout(identifier: str):
    return service.load_layout(identifier)


@app.post("/api/render")
def render(body: Layout):
    return service.render_layout(body)


@app.get("/api/exports/{identifier}.pdf")
def download(identifier: str):
    path = store.item_path("exports", identifier, "pdf")
    if not path.exists():
        raise HTTPException(404, "출력 파일이 없습니다.")
    return FileResponse(path, media_type="application/pdf", filename="inklab-annotated.pdf")


@app.get("/api/exports/{identifier}/pages/{page}.png")
def output_page(identifier: str, page: int):
    return Response(service.page_png(identifier, page, output=True), media_type="image/png")


@app.post("/api/draft")
def draft(body: AIRequest):
    try:
        return create_draft(body.document_id, body.instructions)
    except ValueError:
        raise
    except Exception as exc:
        from openai import APIError
        if isinstance(exc, APIError):
            raise HTTPException(502, "OpenAI 요청이 실패했습니다. API 키, 모델 접근 권한, 결제 상태와 네트워크를 확인하세요.") from exc
        raise


app.mount("/", StaticFiles(directory=store.ROOT / "static", html=True), name="static")
