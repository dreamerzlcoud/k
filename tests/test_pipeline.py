import base64
import hashlib
import io
import random

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops, ImageDraw

from inklab import service, store
from inklab.app import app
from inklab.models import Block, Layout, Sample
from inklab.render import normalize_sample, png_bytes, render_math


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA", tmp_path)


def pdf_bytes(rotation=0):
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842)
        page.insert_text((40, 40), "Original assignment")
        page.set_rotation(rotation)
        return doc.tobytes()


def sample_url():
    image = Image.new("RGBA", (150, 150), "white")
    draw = ImageDraw.Draw(image)
    # Deliberately asymmetric X to detect loss, mirroring, or substitution.
    draw.line([(30,20),(100,120)], fill="black", width=9)
    draw.line([(115,25),(40,115)], fill="black", width=5)
    return "data:image/png;base64," + base64.b64encode(png_bytes(image)).decode()


@pytest.mark.parametrize("tex", [
    r"\int_0^1 x^2\,dx=\frac{1}{3}",
    r"\begin{bmatrix}1&2\\3&4\end{bmatrix}\begin{bmatrix}x\\y\end{bmatrix}",
    r"\begin{aligned}F&=ma\\a&=\frac{F}{m}\end{aligned}",
    r"\sum_{n=0}^{\infty}\frac{x^n}{n!}=e^x",
    r"\frac{\partial^2 u}{\partial t^2}=c^2\nabla^2u",
])
def test_engineering_math(tex):
    image, width, height, missing, count = render_math(tex, 18, {}, "#243d78", random.Random(1))
    assert image.getchannel("A").getbbox()
    assert width > 10 and height > 10
    assert count == 0 and missing


def test_actual_sample_replaces_math_glyph():
    sample = normalize_sample(sample_url())
    custom = render_math("x+x",18,{"x":[sample]},"#243d78",random.Random(1))
    original = render_math("x+x",18,{},"#243d78",random.Random(1))
    assert custom[4] == 2 and "x" not in custom[3]
    # Compare actual rendered pixels, not only replacement metadata.
    assert ImageChops.difference(custom[0],original[0]).convert("RGB").getbbox()


def test_blank_sample_rejected():
    data = "data:image/png;base64,"+base64.b64encode(png_bytes(Image.new("RGB",(50,50),"white"))).decode()
    with pytest.raises(ValueError): normalize_sample(data)


@pytest.mark.parametrize("rotation", [0,90,180,270])
def test_export_keeps_original_and_coordinates(rotation):
    original=pdf_bytes(rotation)
    info=service.import_pdf(original,"source.pdf")
    before=hashlib.sha256(service.document_path(info["id"]).read_bytes()).digest()
    result=service.render_layout(Layout(document_id=info["id"],blocks=[Block(content="x^2",x=100,y=170,width=200,height=80)]))
    assert before==hashlib.sha256(service.document_path(info["id"]).read_bytes()).digest()
    with fitz.open(store.item_path("exports",result["id"],"pdf")) as doc:
        assert "Original assignment" in doc[0].get_text()
        rect=doc[0].get_image_rects(doc[0].get_images()[0][0])[0]
        assert abs(rect.x0-100)<1 and abs(rect.y0-170)<1
        assert doc[0].rect.width == info["pages"][0]["width"]


def test_overflow_and_bad_page_fail_without_export():
    info=service.import_pdf(pdf_bytes(),"source.pdf")
    for block in [Block(content="x",x=590,width=100),Block(content="x",page=2),Block(content=r"\frac{x}{y}",height=1)]:
        with pytest.raises(ValueError): service.render_layout(Layout(document_id=info["id"],blocks=[block]))
    assert not list(store.folder("exports").glob("*.pdf"))


def test_korean_and_sample_pdf():
    info=service.import_pdf(pdf_bytes(),"source.pdf")
    sheets=service.sample_pages(pdf_bytes(),"notes.pdf")
    assert len(sheets["pages"]) == 1
    result=service.render_layout(Layout(document_id=info["id"],blocks=[Block(kind="text",content="공학수학 풀이입니다. 초기 조건을 대입합니다.",width=450,height=100)]))
    assert "공" in result["missing_glyphs"]
    assert service.page_png(result["id"],0,output=True).startswith(b"\x89PNG")


def test_http_flow_and_origin_guard():
    with TestClient(app) as client:
        assert client.get("/").status_code==200
        result=client.post("/api/documents",files={"file":("source.pdf",pdf_bytes(),"application/pdf")})
        assert result.status_code==200
        identifier=result.json()["id"]
        profile=client.post("/api/profiles/default/samples",json={"character":"x","image":sample_url()})
        assert profile.status_code==200
        body=Layout(document_id=identifier,blocks=[Block(content="x^2")]).model_dump()
        assert client.put("/api/layouts",json=body).status_code==200
        assert client.get("/api/layouts/"+identifier).json()["blocks"][0]["content"]=="x^2"
        response=client.post("/api/render",json=body)
        assert response.status_code==200
        assert response.json()["custom_glyphs_used"]==1
        assert client.get(response.json()["url"]).content.startswith(b"%PDF")
        assert client.post("/api/demo",headers={"Origin":"https://other.example"}).status_code==403
        assert client.post("/api/documents",files={"file":("invalid.pdf",b"bad","application/pdf")}).status_code==400
        assert client.post("/api/sample-sheets",files={"file":("invalid.pdf",b"bad","application/pdf")}).status_code==400
        image=base64.b64decode(sample_url().split(",")[1])
        sample_response=client.post("/api/sample-sheets",files={"file":("sample.png",image,"image/png")})
        assert sample_response.status_code==200
        assert client.get('/api/sample-sheets/'+sample_response.json()['pages'][0]+'.png').status_code==200


def test_mcp_tools_and_render():
    import asyncio
    from mcp import Client
    from inklab.mcp_server import mcp
    async def exercise():
        async with Client(mcp) as client:
            result=await client.list_tools()
            names={tool.name for tool in result.tools}
            assert {"render_pdf","get_page_image","register_glyph"} <= names
            result=await client.call_tool("list_documents",{})
            assert not result.is_error
            info=service.import_pdf(pdf_bytes(),"mcp-source.pdf")
            image=await client.call_tool("get_page_image",{"document_id":info["id"]})
            assert not image.is_error
            assert any(item.type=="image" for item in image.content)
            result=await client.call_tool("render_pdf",{"layout":Layout(document_id=info["id"],blocks=[Block(content="x^2")]).model_dump()})
            assert not result.is_error
            assert service.load_layout(info["id"])["blocks"][0]["content"]=="x^2"
    asyncio.run(exercise())


def test_external_stdio_mcp(tmp_path):
    import asyncio
    import os
    import sys
    from mcp import Client, StdioServerParameters
    async def exercise():
        parameters=StdioServerParameters(command=sys.executable,args=[str(store.ROOT/'scripts/run_mcp.py')],
            env={**os.environ,"INKLAB_DATA_DIR":str(tmp_path),"PYTHONUTF8":"1"})
        async with Client(parameters) as client:
            result=await client.call_tool("list_handwriting_profiles",{})
            assert not result.is_error
            tools=await client.list_tools()
            assert "get_export_page_image" in {tool.name for tool in tools.tools}
    asyncio.run(exercise())


def test_spen_strokes_adaptive_ai_handwriting_and_math_verification():
    from inklab.inference_server import inference_app
    with TestClient(app) as client, TestClient(inference_app) as inf_client:
        # 1. Tablet S-Pen stroke save & restore (coordinates, time, pressure, tilt, stroke_id, pen_lift)
        spen_points = [
            {"x": 20.0, "y": 15.0, "t": 10.0, "pressure": 0.78, "tilt_x": 18.0, "tilt_y": 8.0, "stroke_id": 0, "pen_lift": False},
            {"x": 28.0, "y": 65.0, "t": 35.0, "pressure": 0.88, "tilt_x": 20.0, "tilt_y": 9.0, "stroke_id": 0, "pen_lift": True},
            {"x": 25.0, "y": 40.0, "t": 55.0, "pressure": 0.72, "tilt_x": 16.0, "tilt_y": 7.0, "stroke_id": 1, "pen_lift": False},
            {"x": 55.0, "y": 40.0, "t": 80.0, "pressure": 0.84, "tilt_x": 19.0, "tilt_y": 8.0, "stroke_id": 1, "pen_lift": True},
        ]
        res = client.post("/api/profiles/default/samples", json={
            "character": "가",
            "image": sample_url(),
            "strokes": spen_points,
        })
        assert res.status_code == 200
        saved_profile = res.json()
        assert "가" in saved_profile["strokes"]
        assert saved_profile["strokes"]["가"][0][1]["pressure"] == 0.88
        assert saved_profile["strokes"]["가"][0][1]["pen_lift"] is True
        assert saved_profile["style"]["personalized"] is True

        # 2. Adaptive prompt endpoint & jamo coverage
        adaptive = client.get("/api/profiles/default/adaptive-prompts")
        assert adaptive.status_code == 200
        adaptive_data = adaptive.json()
        assert adaptive_data["jamo_coverage_pct"] > 0
        assert adaptive_data["stroke_glyph_count"] == 1
        assert len(adaptive_data["recommended_sentences"]) >= 1

        # 3. Unseen Korean sentence synthesis & style similarity comparison
        gen_res = client.post("/api/handwriting/generate", json={
            "profile_id": "default",
            "text": "가나다 미분해",
            "size": 24,
        })
        assert gen_res.status_code == 200
        gen_data = gen_res.json()
        assert "가" in gen_data["direct_glyphs"]
        assert set(gen_data["ai_generated_glyphs"]) >= {"나", "다", "미", "분", "해"}
        assert 0.5 <= gen_data["similarity_score"] <= 1.0
        assert client.get(gen_data["preview_url"]).status_code == 200

        # 4. Standalone AI inference service & job status
        assert inf_client.get("/health").json()["status"] == "ok"
        job_resp = inf_client.post("/jobs/generate", json={"text": "초기 조건"})
        assert job_resp.status_code == 200
        job_id = job_resp.json()["job_id"]
        assert inf_client.get(f"/jobs/{job_id}").json()["status"] == "completed"

        # 5. PDF blank space detection, math verification warning, and AI vs direct glyph distinction
        doc_info = service.import_pdf(pdf_bytes(), "test.pdf")
        blanks = client.get(f"/api/documents/{doc_info['id']}/blank-spaces?page=0")
        assert blanks.status_code == 200
        assert len(blanks.json()["regions"]) >= 1

        # Local AI draft without API key
        draft_res = client.post("/api/draft", json={"document_id": doc_info["id"], "instructions": "정적분 풀이"})
        assert draft_res.status_code == 200
        assert len(draft_res.json()["blocks"]) >= 1

        # Math verification: wrong integral value triggers warning, while unseen Korean uses AI handwriting
        render_res = service.render_layout(Layout(
            document_id=doc_info["id"],
            blocks=[
                Block(kind="text", content="가나다", x=60, y=150, width=250, height=70),
                Block(kind="math", content=r"\int_0^1 x^2\,dx=\frac{1}{2}", x=60, y=240, width=300, height=90),
            ],
        ))
        assert render_res["custom_glyphs_used"] == 1
        assert render_res["ai_glyphs_used"] == 2
        assert render_res["ai_generated_glyphs"] == ["나", "다"]
        assert any("적분 검산" in w for w in render_res["warnings"])


def test_extended_mcp_tools():
    import asyncio
    from mcp import Client
    from inklab.mcp_server import mcp

    async def exercise():
        async with Client(mcp) as client:
            tools_res = await client.list_tools()
            names = {t.name for t in tools_res.tools}
            assert {
                "start_handwriting_session",
                "get_handwriting_profile_status",
                "generate_handwriting_sentence",
                "suggest_annotation_positions",
                "analyze_and_solve_pdf",
                "get_job_status",
                "get_export_preview",
            } <= names

            sess = await client.call_tool("start_handwriting_session", {"profile_id": "default"})
            assert not sess.is_error
            status = await client.call_tool("get_handwriting_profile_status", {"profile_id": "default"})
            assert not status.is_error

            gen = await client.call_tool("generate_handwriting_sentence", {"text": "일반해", "profile_id": "default"})
            assert not gen.is_error
            gen_payload = json.loads(gen.content[0].text)
            job = await client.call_tool("get_job_status", {"job_id": gen_payload["job_id"]})
            assert not job.is_error

            doc_info = service.import_pdf(pdf_bytes(), "mcp-ext.pdf")
            pos = await client.call_tool("suggest_annotation_positions", {"document_id": doc_info["id"], "page": 0})
            assert not pos.is_error
            solved = await client.call_tool("analyze_and_solve_pdf", {"document_id": doc_info["id"]})
            assert not solved.is_error
            rendered = await client.call_tool(
                "render_pdf",
                {"layout": Layout(document_id=doc_info["id"], blocks=[Block(content="x^2=1")]).model_dump()},
            )
            export_id = json.loads(rendered.content[0].text)["id"]
            preview = await client.call_tool("get_export_preview", {"export_id": export_id, "page": 0})
            assert not preview.is_error

    import json
    asyncio.run(exercise())
