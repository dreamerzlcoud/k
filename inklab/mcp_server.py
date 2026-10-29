"""Local stdio MCP. Files are confined to InkLab's data directory."""
import json
from mcp.server import MCPServer
from mcp.server.mcpserver.utilities.types import Image

from . import service, store
from .ai import create_draft
from .inference_server import create_job, get_job
from .models import GenerateSentenceRequest, Layout, Sample, StrokePoint

mcp = MCPServer("InkLab", instructions=(
    "Engineering PDF handwriting & AI Hangul synthesis tool. Coordinates are PDF points from the top-left, pages zero-based. "
    "Use list_documents and inspect_pdf first. Use suggest_annotation_positions or analyze_and_solve_pdf to find blank spaces. "
    "Use start_handwriting_session and get_handwriting_profile_status to inspect jamo coverage and S-Pen style metrics. "
    "Use generate_handwriting_sentence or render_pdf and examine custom_glyphs_used vs ai_generated_glyphs."))


@mcp.tool()
def list_documents() -> list[dict]:
    """List PDFs uploaded in the local InkLab UI, including page dimensions and extracted text."""
    return [service.inspect_document(p.stem) for p in store.folder("documents").glob("*.pdf")]


@mcp.tool()
def import_pdf(filename: str) -> dict:
    """Import a PDF placed by the user in data/inbox. Pass a basename only, e.g. assignment.pdf."""
    from pathlib import Path
    if Path(filename).name != filename or not filename.lower().endswith(".pdf"):
        raise ValueError("data/inbox 안의 PDF 파일명만 허용됩니다.")
    root = store.folder("inbox").resolve()
    path = (root / filename).resolve()
    if path.parent != root or not path.is_file():
        raise ValueError("data/inbox에서 PDF를 찾을 수 없습니다.")
    if path.stat().st_size > service.MAX_FILE:
        raise ValueError("PDF는 30MB 이하여야 합니다.")
    return service.import_pdf(path.read_bytes(), filename)


@mcp.tool()
def inspect_pdf(document_id: str) -> dict:
    """Get original PDF page sizes and extracted text; scanned documents may have empty text."""
    return service.inspect_document(document_id)


@mcp.tool()
def get_page_image(document_id: str, page: int = 0) -> Image:
    """See the original page as an MCP image. Use this for scanned PDFs and blank-space placement."""
    return Image(data=service.page_png(document_id, page), format="png")


@mcp.tool()
def get_export_page_image(export_id: str, page: int = 0) -> Image:
    """Visually inspect a rendered result, including handwritten glyphs, before returning it."""
    return Image(data=service.page_png(export_id, page, output=True), format="png")


@mcp.tool()
def list_handwriting_profiles() -> list[dict]:
    """List the actual registered characters and number of variants, excluding image payloads."""
    return [{"id": p["id"], "name": p["name"], "characters": {c: len(v) for c, v in p["glyphs"].items()}}
            for p in store.list_profiles()]


@mcp.tool()
def register_glyph(
    profile_id: str,
    character: str,
    png_data_url: str = "",
    strokes: list[dict] | None = None,
) -> dict:
    """Register one labeled handwriting sample (PNG data URL and/or raw S-Pen stroke points)."""
    pts = [StrokePoint(**pt) for pt in (strokes or [])]
    p = service.add_sample(profile_id, Sample(character=character, image=png_data_url, strokes=pts))
    first_char = [c for c in character if not c.isspace()][0]
    return {
        "id": p["id"],
        "character": character,
        "variants": len(p["glyphs"].get(first_char, [])),
        "stroke_variants": len(p.get("strokes", {}).get(first_char, [])),
    }


@mcp.tool()
def start_handwriting_session(profile_id: str = "default", name: str = "") -> dict:
    """Start or resume an adaptive handwriting learning session; returns missing jamo/symbol prompts."""
    if name and profile_id != "default":
        path = store.item_path("profiles", profile_id, "json")
        if not path.exists():
            store.write_json(path, {"id": profile_id, "name": name[:60], "glyphs": {}, "strokes": {}})
    status = service.get_profile_status(profile_id)
    return {
        "session_active": True,
        "profile_id": status["profile_id"],
        "jamo_coverage_pct": status["jamo_coverage_pct"],
        "personalization_level": status["personalization_level"],
        "recommended_single_chars": status["recommended_single_chars"],
        "recommended_sentences": status["recommended_sentences"],
    }


@mcp.tool()
def get_handwriting_profile_status(profile_id: str = "default") -> dict:
    """Get detailed handwriting profile status: registered glyphs, S-Pen strokes, jamo coverage, and style metrics."""
    return service.get_profile_status(profile_id)


@mcp.tool()
def generate_handwriting_sentence(
    text: str,
    profile_id: str = "default",
    size: float = 24.0,
    color: str = "#243d78",
    seed: int = 7,
) -> dict:
    """Synthesize a new Korean sentence using the user's personalized AI handwriting profile (avoids large Base64 payloads)."""
    def _work():
        res = service.generate_sentence_preview(
            GenerateSentenceRequest(profile_id=profile_id, text=text, size=size, color=color, seed=seed)
        )
        res.pop("data_url", None)
        res["local_preview_url"] = "http://127.0.0.1:8765" + res["preview_url"]
        return res

    job = create_job("generate_handwriting_sentence", _work, sync_if_fast=True)
    return {"job_id": job["job_id"], "status": job["status"], **(job["result"] or {})}


@mcp.tool()
def suggest_annotation_positions(document_id: str, page: int = 0) -> dict:
    """Suggest non-overlapping blank-space rectangles on a PDF page for placing handwritten solutions."""
    return {"document_id": document_id, "page": page, "blank_spaces": service.find_blank_spaces(document_id, page)}


@mcp.tool()
def analyze_and_solve_pdf(
    document_id: str,
    instructions: str = "문제를 분석하고 빈 공간에 단계별 풀이와 수식을 배치해줘.",
    profile_id: str = "default",
) -> dict:
    """Analyze a PDF, generate step-by-step Korean/LaTeX solution blocks in blank spaces, and save the editable layout."""
    def _work():
        draft = create_draft(document_id, instructions)
        layout = Layout(document_id=document_id, profile_id=profile_id, blocks=draft.blocks)
        service.save_layout(layout)
        return {
            "document_id": document_id,
            "profile_id": profile_id,
            "blocks_count": len(draft.blocks),
            "blocks": [b.model_dump() for b in draft.blocks],
            "notes": draft.notes,
        }

    job = create_job("analyze_and_solve_pdf", _work, sync_if_fast=True)
    return {"job_id": job["job_id"], "status": job["status"], **(job["result"] or {})}


@mcp.tool()
def get_job_status(job_id: str) -> dict:
    """Check the status and result of a handwriting generation or PDF analysis job by Job ID."""
    return get_job(job_id)


@mcp.tool()
def get_export_preview(export_id: str, page: int = 0) -> dict:
    """Get export metadata, glyph usage breakdown, warnings, and download/preview URLs without large Base64 payloads."""
    meta_path = store.item_path("exports", export_id, "json")
    pdf_path = store.item_path("exports", export_id, "pdf")
    if not pdf_path.exists():
        raise ValueError("출력 파일이 없습니다.")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    report = meta.get("report", {})
    return {
        "export_id": export_id,
        "page": page,
        "download_url": f"/api/exports/{export_id}.pdf",
        "local_download_url": f"http://127.0.0.1:8765/api/exports/{export_id}.pdf",
        "page_preview_url": f"/api/exports/{export_id}/pages/{page}.png",
        "custom_glyphs_used": report.get("custom_glyphs_used", 0),
        "ai_glyphs_used": report.get("ai_glyphs_used", 0),
        "ai_generated_glyphs": report.get("ai_generated_glyphs", []),
        "missing_glyphs": report.get("missing_glyphs", []),
        "warnings": report.get("warnings", []),
    }


@mcp.tool()
def render_pdf(layout: Layout) -> dict:
    """Overlay text/math blocks on an uploaded PDF. Returns export URL, warnings, missing glyphs.

    Math content uses LaTeX, including aligned, bmatrix, integrals, fractions, Greek letters.
    Text blocks support Korean. Fails instead of clipping content beyond its rectangle.
    Saves the editable layout so the user can reopen it in the UI.
    """
    result = service.render_layout(layout)
    service.save_layout(layout)
    result["local_download_url"] = "http://127.0.0.1:8765" + result["url"]
    return result


@mcp.tool()
def load_layout(document_id: str) -> dict:
    """Load the most recently saved editable layout."""
    return service.load_layout(document_id) or {"document_id": document_id, "blocks": []}


if __name__ == "__main__":
    mcp.run(transport="stdio")
