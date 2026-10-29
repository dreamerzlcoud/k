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
