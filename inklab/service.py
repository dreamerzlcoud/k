import base64
from functools import lru_cache
import io
import json
import math
import re
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageOps

from . import store
from .handwriting_ai import (
    compare_handwriting_style,
    extract_style_profile,
    get_adaptive_prompts,
    normalize_spen_strokes,
    render_spen_strokes_to_data_url,
    synthesize_korean_sentence,
)
from .models import Block, Draft, GenerateSentenceRequest, Layout, Sample
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


@lru_cache(maxsize=64)
def _cached_page_png(path_str: str, mtime_ns: int, size: int, page: int) -> bytes:
    with fitz.open(path_str) as doc:
        if not 0 <= page < len(doc):
            raise ValueError("존재하지 않는 페이지입니다.")
        scale = min(1.5, 1800 / max(doc[page].rect.width, doc[page].rect.height))
        return doc[page].get_pixmap(matrix=fitz.Matrix(scale, scale)).tobytes("png")


def page_png(identifier: str, page: int, output=False) -> bytes:
    path = store.item_path("exports", identifier, "pdf") if output else document_path(identifier)
    if not path.exists():
        raise ValueError("출력 파일이 없습니다.")
    stat = path.stat()
    return _cached_page_png(str(path), stat.st_mtime_ns, stat.st_size, page)


def _split_multi_char_sample(chars: list[str], image_url: str, strokes: list[dict]) -> list[tuple[str, str, list[dict]]]:
    """Split a multi-character canvas sample horizontally into per-character glyph+stroke pairs."""
    if len(chars) <= 1:
        return [(chars[0], image_url, strokes)]
    raw = base64.b64decode(image_url.split(",", 1)[1])
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    w, h = img.size
    step = w / len(chars)
    xs = [p["x"] for p in strokes] if strokes else []
    min_x = min(xs) if xs else 0.0
    max_x = max(xs) if xs else float(w)
    span_x = max(1.0, max_x - min_x)

    items = []
    for idx, ch in enumerate(chars):
        x0 = max(0, round(idx * step))
        x1 = min(w, round((idx + 1) * step))
        crop = img.crop((x0, 0, max(x0 + 4, x1), h))
        c_url = "data:image/png;base64," + base64.b64encode(png_bytes(crop)).decode()
        sx0 = min_x + (idx / len(chars)) * span_x - 2.0
        sx1 = min_x + ((idx + 1) / len(chars)) * span_x + 2.0
        c_strokes = [p for p in strokes if sx0 <= p["x"] <= sx1]
        items.append((ch, c_url, c_strokes))
    return items


def add_sample(profile_id: str, sample: Sample):
    chars = [c for c in sample.character if not c.isspace()]
    if not chars:
        raise ValueError("등록할 글자를 입력하세요.")
    cleaned_strokes = normalize_spen_strokes([p.model_dump() for p in sample.strokes]) if sample.strokes else []
    image_url = sample.image or (render_spen_strokes_to_data_url(cleaned_strokes) if cleaned_strokes else "")
    if not image_url:
        raise ValueError("PNG 이미지 또는 S펜 필기 획 데이터가 필요합니다.")

    pairs = _split_multi_char_sample(chars, image_url, cleaned_strokes)
    with store.LOCK:
        profile = store.profile(profile_id)
        strokes_map = profile.setdefault("strokes", {})
        for ch, ch_url, ch_strokes in pairs:
            encoded = normalize_sample(ch_url)
            variants = profile["glyphs"].setdefault(ch, [])
            if len(variants) >= 12 and len(chars) == 1:
                raise ValueError("한 글자에 최대 12개 샘플을 등록할 수 있습니다.")
            if len(variants) < 12:
                variants.append(encoded)
            if ch_strokes:
                s_vars = strokes_map.setdefault(ch, [])
                if len(s_vars) < 12:
                    s_vars.append(ch_strokes)
        style = extract_style_profile(profile)
        profile["style"] = {k: v for k, v in style.items() if not k.startswith("_")}
        store.write_json(store.item_path("profiles", profile_id, "json"), profile)
    return profile


def get_profile_status(profile_id: str = "default") -> dict:
    profile = store.profile(profile_id)
    adaptive = get_adaptive_prompts(profile)
    comparison = compare_handwriting_style(profile)
    return {
        **adaptive,
        "similarity_score": comparison["similarity_score"],
        "characters": {c: len(v) for c, v in profile.get("glyphs", {}).items()},
        "stroke_characters": {c: len(v) for c, v in profile.get("strokes", {}).items()},
    }


def generate_sentence_preview(req: GenerateSentenceRequest) -> dict:
    profile = store.profile(req.profile_id)
    pixel_height = round(req.size * 2.2)
    synth = synthesize_korean_sentence(req.text, pixel_height, req.color, profile, seed=req.seed)
    comparison = compare_handwriting_style(profile, req.text)
    identifier = store.new_id()
    img_bytes = png_bytes(synth["image"])
    store.item_path("samples", f"gen_{identifier}", "png").write_bytes(img_bytes)
    return {
        "id": identifier,
        "text": req.text,
        "profile_id": req.profile_id,
        "preview_url": f"/api/sample-sheets/gen_{identifier}.png",
        "data_url": "data:image/png;base64," + base64.b64encode(img_bytes).decode(),
        "direct_glyphs": synth["direct_glyphs"],
        "ai_generated_glyphs": synth["ai_generated_glyphs"],
        "fallback_glyphs": synth["fallback_glyphs"],
        "style": synth["style"],
        "similarity_score": comparison["similarity_score"],
    }


def find_blank_spaces(identifier: str, page: int = 0) -> list[dict]:
    """Detect non-overlapping blank rectangular regions on a PDF page for placing solutions."""
    with fitz.open(document_path(identifier)) as doc:
        if not 0 <= page < len(doc):
            raise ValueError("존재하지 않는 페이지입니다.")
        p = doc[page]
        pw, ph = p.rect.width, p.rect.height
        occupied: list[fitz.Rect] = []
        for b in p.get_text("blocks"):
            occupied.append(fitz.Rect(b[0] - 6, b[1] - 4, b[2] + 6, b[3] + 4))
        for d in p.get_drawings():
            r = d.get("rect")
            if r and (r.width < pw * 0.9 or r.height < ph * 0.9):
                occupied.append(fitz.Rect(r.x0 - 4, r.y0 - 4, r.x1 + 4, r.y1 + 4))

        margin_x = max(36.0, pw * 0.07)
        usable_w = max(120.0, pw - 2 * margin_x)
        step_y = 18.0
        y = max(48.0, ph * 0.08)
        max_y = ph - max(36.0, ph * 0.05)

        regions = []
        band_start = None
        while y + step_y <= max_y:
            strip = fitz.Rect(margin_x, y, margin_x + usable_w, y + step_y)
            hit = any(strip.intersects(occ) for occ in occupied)
            if not hit:
                if band_start is None:
                    band_start = y
            else:
                if band_start is not None and (y - band_start) >= 54.0:
                    regions.append({
                        "page": page,
                        "x": round(margin_x, 1),
                        "y": round(band_start + 6, 1),
                        "width": round(usable_w, 1),
                        "height": round(min(220.0, y - band_start - 10), 1),
                    })
                band_start = None
            y += step_y

        if band_start is not None and (max_y - band_start) >= 54.0:
            regions.append({
                "page": page,
                "x": round(margin_x, 1),
                "y": round(band_start + 6, 1),
                "width": round(usable_w, 1),
                "height": round(min(220.0, max_y - band_start - 10), 1),
            })

        if not regions:
            regions.append({
                "page": page,
                "x": round(margin_x, 1),
                "y": round(ph * 0.65, 1),
                "width": round(usable_w, 1),
                "height": round(ph * 0.25, 1),
            })
        return regions


def _eval_simple_expr(expr: str, var_vals: dict[str, float]) -> float | None:
    s = expr.strip()
    s = re.sub(r"\\left|\\right|\\,|\\;|\\quad|\\qquad", "", s)
    while m := re.search(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", s):
        s = s[: m.start()] + f"(({m.group(1)})/({m.group(2)}))" + s[m.end() :]
    s = s.replace("^", "**").replace("{", "(").replace("}", ")")
    s = re.sub(r"(\d)([a-zA-Z(])", r"\1*\2", s)
    s = s.replace("\\pi", str(math.pi)).replace("\\infty", "20.0")
    s = re.sub(r"\\exp\b", "exp", s)
    s = re.sub(r"\\sin\b", "sin", s)
    s = re.sub(r"\\cos\b", "cos", s)
    if re.search(r"[^0-9a-zA-Z_+*/().\-\s]", s):
        return None
    env = {"exp": math.exp, "sin": math.sin, "cos": math.cos, "e": math.e, **var_vals}
    try:
        return float(eval(s, {"__builtins__": {}}, env))
    except Exception:
        return None


def verify_math_expression(tex: str) -> dict:
    """Verify LaTeX syntax and check numerical/symbolic consistency of engineering equations."""
    clean = tex.strip()
    if clean.count("{") != clean.count("}"):
        return {"valid": False, "checked": True, "message": "LaTeX 중괄호 {} 짝이 맞지 않습니다."}

    # Check definite integral equality: \int_a^b f(x)\,dx = rhs
    m_int = re.search(
        r"\\int_\{?([0-9.\-]+)\}?\^\{?\s*([0-9.\-]+|\\infty)\s*\}?\s*(.+?)\\,?d([a-zA-Z])\s*=\s*(.+)$",
        clean,
    )
    if m_int:
        a_str, b_str, integrand, var, rhs_Part = m_int.groups()
        rhs_final = rhs_Part.split("=")[-1].strip()
        try:
            a = float(a_str)
            b = 18.0 if "infty" in b_str else float(b_str)
            n = 100
            h = (b - a) / n
            vals = []
            for k in range(n + 1):
                xv = a + k * h
                v = _eval_simple_expr(integrand, {var: xv})
                if v is None:
                    break
                w = 1 if k in (0, n) else (4 if k % 2 == 1 else 2)
                vals.append(w * v)
            rhs_val = _eval_simple_expr(rhs_final, {var: 1.0})
            if len(vals) == n + 1 and rhs_val is not None:
                approx = (h / 3.0) * sum(vals)
                if abs(approx - rhs_val) > max(0.02, abs(rhs_val) * 0.05):
                    return {
                        "valid": False,
                        "checked": True,
                        "message": f"적분 검산 경고: 좌변 수치적분 값({approx:.4g})과 우변({rhs_val:.4g})이 다릅니다.",
                    }
                return {"valid": True, "checked": True, "message": f"정적분 검산 통과 ({approx:.4g} ≈ {rhs_val:.4g})"}
        except Exception:
            pass

    # Check simple algebraic/numeric equality LHS = RHS
    if "=" in clean and "\\begin" not in clean and "\\int" not in clean and "\\sum" not in clean:
        parts = [p.strip() for p in clean.split("=") if p.strip()]
        if len(parts) >= 2:
            test_vars = {"x": 1.7, "y": 2.3, "t": 0.5, "a": 2.0, "b": 3.0, "c": 4.0, "m": 2.0, "F": 6.0}
            lhs_v = _eval_simple_expr(parts[0], test_vars)
            rhs_v = _eval_simple_expr(parts[-1], test_vars)
            if lhs_v is not None and rhs_v is not None:
                if abs(lhs_v - rhs_v) > max(1e-3, abs(rhs_v) * 1e-2):
                    return {
                        "valid": False,
                        "checked": True,
                        "message": f"수식 등호 검산 주의: 대입 검산 결과 좌변({lhs_v:.4g}) ≠ 우변({rhs_v:.4g})",
                    }
                return {"valid": True, "checked": True, "message": "등식 수치 검산 통과"}

    return {"valid": True, "checked": False, "message": "LaTeX 구조 정상"}


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
    warnings, missing, ai_generated = [], set(), set()
    used, ai_used = 0, 0
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
            if block.kind == "math":
                v_res = verify_math_expression(block.content)
                if not v_res["valid"]:
                    warnings.append(f"블록 {i+1}: {v_res['message']}")
            image, w, h, absent, count, ai_chars, ai_count = render_block(
                block,
                profile,
                layout.color,
                layout.seed + i,
                use_ai=layout.use_ai,
                return_ai_stats=True,
            )
            if w > block.width + .5 or h > block.height + .5:
                raise ValueError(f"블록 {i+1}: 내용 크기 {w:.0f}×{h:.0f}pt가 영역 "
                                 f"{block.width:.0f}×{block.height:.0f}pt를 넘습니다. 영역을 늘리거나 글자 크기를 줄이세요.")
            actual = fitz.Rect(block.x, block.y, block.x+w, block.y+h)
            for previous in occupied.get(block.page, []):
                if actual.intersects(previous):
                    warnings.append(f"블록 {i+1}: 다른 필기 블록과 겹칩니다.")
            occupied.setdefault(block.page, []).append(actual)
            missing.update(absent)
            ai_generated.update(ai_chars)
            used += count
            ai_used += ai_count
            prepared.append((block.page, actual, png_bytes(image)))
        for page, rect, image in prepared:
            doc[page].insert_image(rect, stream=image, overlay=True)
        identifier = store.new_id()
        target = store.item_path("exports", identifier, "pdf")
        doc.save(target, garbage=4, deflate=True)
    result = {
        "id": identifier,
        "url": f"/api/exports/{identifier}.pdf",
        "missing_glyphs": sorted(missing),
        "custom_glyphs_used": used,
        "ai_generated_glyphs": sorted(ai_generated),
        "ai_glyphs_used": ai_used,
        "warnings": warnings,
    }
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
