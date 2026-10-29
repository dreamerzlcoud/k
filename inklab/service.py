import base64
import io
import json
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageOps

from . import store
from .models import Layout, Sample
from .render import normalize_sample, png_bytes, render_block

MAX_FILE = 30 * 1024 * 1024


def import_pdf(data: bytes, name: str) -> dict:
    if len(data) > MAX_FILE:
        raise ValueError("PDF는 30MB 이하로 올려주세요.")
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.needs_pass:
                raise ValueError("암호를 해제한 PDF를 올려주세요.")
            if not 1 <= len(doc) <= 200:
                raise ValueError("PDF는 1~200페이지까지 지원합니다.")
            for page in doc:
                if max(page.rect.width, page.rect.height) > 2500:
                    raise ValueError("페이지 크기는 한 변 2500pt 이하로 제한됩니다.")
    except (fitz.FileDataError, fitz.EmptyFileError) as exc:
        raise ValueError("유효한 PDF 파일이 아닙니다.") from exc
    identifier = store.new_id()
    store.item_path("documents", identifier, "pdf").write_bytes(data)
    store.write_json(store.item_path("documents", identifier, "json"), {"name": name[:200]})
    return inspect_document(identifier)


def document_path(identifier):
    path = store.item_path("documents", identifier, "pdf")
    if not path.exists():
        raise ValueError("PDF를 찾을 수 없습니다.")
    return path


def inspect_document(identifier) -> dict:
    with fitz.open(document_path(identifier)) as doc:
        meta = json.loads(store.item_path("documents", identifier, "json").read_text(encoding="utf-8"))
        return {"id": identifier, "name": meta["name"], "pages": [
            {"page": i, "width": p.rect.width, "height": p.rect.height,
             "text": p.get_text()[:16000]} for i, p in enumerate(doc)]}


def page_png(identifier: str, page: int, output=False) -> bytes:
    path = store.item_path("exports", identifier, "pdf") if output else document_path(identifier)
    if not path.exists():
        raise ValueError("출력 파일이 없습니다.")
    with fitz.open(path) as doc:
        if not 0 <= page < len(doc):
            raise ValueError("존재하지 않는 페이지입니다.")
        scale = min(1.5, 1800 / max(doc[page].rect.width, doc[page].rect.height))
        return doc[page].get_pixmap(matrix=fitz.Matrix(scale, scale)).tobytes("png")


def add_sample(profile_id: str, sample: Sample):
    encoded = normalize_sample(sample.image)
    with store.LOCK:
        profile = store.profile(profile_id)
        variants = profile["glyphs"].setdefault(sample.character, [])
        if len(variants) >= 12:
            raise ValueError("한 글자에 최대 12개 샘플을 등록할 수 있습니다.")
        variants.append(encoded)
        store.write_json(store.item_path("profiles", profile_id, "json"), profile)
    return profile


def sample_pages(data: bytes, filename: str) -> dict:
    """Rasterize sample sheets without pretending to recognize their characters."""
    if len(data) > MAX_FILE:
        raise ValueError("샘플 파일은 30MB 이하로 올려주세요.")
    identifier = store.new_id()
    pages = []
    if filename.lower().endswith(".pdf") or data.startswith(b"%PDF"):
        try:
            source = fitz.open(stream=data, filetype="pdf")
        except (fitz.FileDataError, fitz.EmptyFileError) as exc:
            raise ValueError("유효한 샘플 PDF가 아닙니다.") from exc
        with source as doc:
            if doc.needs_pass or not 1 <= len(doc) <= 30:
                raise ValueError("암호 없는 1~30페이지 샘플 PDF를 사용하세요.")
            for i, page in enumerate(doc):
                scale = min(2, 2400 / max(page.rect.width, page.rect.height))
                path = store.item_path("samples", f"{identifier}_{i}", "png")
                path.write_bytes(page.get_pixmap(matrix=fitz.Matrix(scale, scale)).tobytes("png"))
                pages.append(f"{identifier}_{i}")
    else:
        try:
            image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGBA")
            image.thumbnail((2400, 2400))
            path = store.item_path("samples", f"{identifier}_0", "png")
            path.write_bytes(png_bytes(image))
            pages.append(f"{identifier}_0")
        except (OSError, Image.DecompressionBombError) as exc:
            raise ValueError("PNG, JPG, WEBP 또는 PDF 샘플을 올려주세요.") from exc
    return {"pages": pages}


def render_layout(layout: Layout) -> dict:
    profile = store.profile(layout.profile_id)
    warnings, missing = [], set()
    used = 0
    prepared = []
    # Validate and render every block before writing anything to an output PDF.
    with fitz.open(document_path(layout.document_id)) as doc:
        for page in doc:
            page.remove_rotation()
        occupied = {}
        for i, block in enumerate(layout.blocks):
            if block.page >= len(doc):
                raise ValueError(f"블록 {i+1}: 페이지가 존재하지 않습니다.")
            rect = fitz.Rect(block.x, block.y, block.x+block.width, block.y+block.height)
            if not doc[block.page].rect.contains(rect):
                raise ValueError(f"블록 {i+1}: 지정 영역이 페이지 밖으로 벗어납니다.")
            image, w, h, absent, count = render_block(block, profile, layout.color, layout.seed+i)
            if w > block.width + .5 or h > block.height + .5:
                raise ValueError(f"블록 {i+1}: 내용 크기 {w:.0f}×{h:.0f}pt가 영역 "
                                 f"{block.width:.0f}×{block.height:.0f}pt를 넘습니다. 영역을 늘리거나 글자 크기를 줄이세요.")
            actual = fitz.Rect(block.x, block.y, block.x+w, block.y+h)
            for previous in occupied.get(block.page, []):
                if actual.intersects(previous):
                    warnings.append(f"블록 {i+1}: 다른 필기 블록과 겹칩니다.")
            occupied.setdefault(block.page, []).append(actual)
            missing.update(absent)
            used += count
            prepared.append((block.page, actual, png_bytes(image)))
        for page, rect, image in prepared:
            doc[page].insert_image(rect, stream=image, overlay=True)
        identifier = store.new_id()
        target = store.item_path("exports", identifier, "pdf")
        doc.save(target, garbage=4, deflate=True)
    result = {"id": identifier, "url": f"/api/exports/{identifier}.pdf",
              "missing_glyphs": sorted(missing), "custom_glyphs_used": used, "warnings": warnings}
    store.write_json(store.item_path("exports", identifier, "json"),
                     {"layout": layout.model_dump(), "report": result})
    return result


def save_layout(layout: Layout):
    document_path(layout.document_id)
    store.profile(layout.profile_id)
    store.write_json(store.item_path("layouts", layout.document_id, "json"), layout.model_dump())
    return {"saved": True}


def load_layout(identifier):
    path = store.item_path("layouts", identifier, "json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
