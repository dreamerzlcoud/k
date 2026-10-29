"""Local stdio MCP. Files are confined to InkLab's data directory."""
from mcp.server import MCPServer
from mcp.server.mcpserver.utilities.types import Image

from . import service, store
from .models import Layout, Sample

mcp = MCPServer("InkLab", instructions=(
    "Engineering PDF handwriting tool. Coordinates are PDF points from the top-left, pages zero-based. "
    "Use list_documents and inspect_pdf first. Generate LaTeX math and separate Korean text blocks. "
    "Use render_pdf and examine warnings and missing_glyphs. Never claim missing glyphs are learned. "
    "Saved exports can be downloaded from the local web UI; this tool does not submit to an LMS."))


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
def register_glyph(profile_id: str, character: str, png_data_url: str) -> dict:
    """Register one labeled handwriting crop, PNG data URL. Use actual user handwriting."""
    p = service.add_sample(profile_id, Sample(character=character, image=png_data_url))
    return {"id": p["id"], "character": character, "variants": len(p["glyphs"][character])}


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
