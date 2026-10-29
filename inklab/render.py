"""Keep MathJax layout; replace individual glyph shapes with actual user samples."""
import base64
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

import pymupdf as fitz
from fontTools.pens.boundsPen import BoundsPen
from fontTools.svgLib.path import parse_path
from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps

from .store import ROOT

SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG)
ET.register_namespace("xlink", XLINK)
Image.MAX_IMAGE_PIXELS = 20_000_000


def png_bytes(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def normalize_sample(data_url: str) -> str:
    if not data_url.startswith("data:image/png;base64,"):
        raise ValueError("PNG 이미지가 필요합니다.")
    try:
        image = Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1], validate=True))).convert("RGBA")
        image.thumbnail((1024, 1024))
        white = Image.new("RGBA", image.size, "white")
        white.alpha_composite(image)
        # Remove paper and preserve antialiased dark/colored ink.
        alpha = ImageOps.grayscale(white.convert("RGB")).point(lambda p: max(0, min(255, (240 - p) * 2)))
        bbox = alpha.getbbox()
        if not bbox or (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) < 4:
            raise ValueError("필기 획이 없습니다. 글자를 쓰거나 영역을 다시 선택하세요.")
        ink = Image.new("RGBA", image.size, "black")
        ink.putalpha(alpha)
        ink = ink.crop(bbox)
        ink.thumbnail((384, 384))
        return base64.b64encode(png_bytes(ink)).decode()
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("이미지를 읽을 수 없거나 너무 큽니다.") from exc


def tint_sample(encoded: str, color: str) -> Image.Image:
    image = Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGBA")
    tinted = Image.new("RGBA", image.size, ImageColor.getrgb(color))
    tinted.putalpha(image.getchannel("A"))
    return tinted


def node_binary() -> str:
    # The wheel's Scripts/node.exe is a Python launcher; prefer its native binary.
    import importlib.util
    spec = importlib.util.find_spec("nodejs_wheel")
    if spec and spec.origin:
        native = Path(spec.origin).parent / ("node.exe" if os.name == "nt" else "bin/node")
        if native.is_file():
            return str(native)
    candidate = Path(sys.executable).parent / ("node.exe" if os.name == "nt" else "node")
    if candidate.exists():
        return str(candidate)
    candidate = shutil.which("node")
    if candidate:
        return candidate
    raise ValueError("Node.js가 없습니다. setup.ps1을 실행하세요.")


@lru_cache(maxsize=128)
def math_svg(tex: str) -> str:
    tex = tex.strip()
    if tex.startswith("$$") and tex.endswith("$$"):
        tex = tex[2:-2]
    elif tex.startswith("$") and tex.endswith("$"):
        tex = tex[1:-1]
    result = subprocess.run([node_binary(), str(ROOT / "scripts/math.cjs")],
                            input=json.dumps({"tex": tex}), text=True, encoding="utf-8",
                            capture_output=True, cwd=ROOT, timeout=20,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise ValueError("수식을 렌더링할 수 없습니다. " + result.stderr[:300])
    return result.stdout


def render_math(content: str, size: float, glyphs: dict, color: str, rng: random.Random):
    root = ET.fromstring(math_svg(content))
    _, _, vw, vh = map(float, root.attrib["viewBox"].split())
    # MathJax's em is 1000 SVG units. Preserve the baseline and all structural spacing.
    width, height = vw * size / 1000, vh * size / 1000
    if width > 20000 or height > 20000:
        raise ValueError("수식이 너무 큽니다. 여러 블록으로 나누세요.")
    root.set("width", f"{width}pt")
    root.set("height", f"{height}pt")
    missing, used = set(), 0
    for parent in list(root.iter()):
        for index, child in enumerate(list(parent)):
            if child.tag != f"{{{SVG}}}path" or "data-c" not in child.attrib:
                continue
            try:
                char = unicodedata.normalize("NFKC", chr(int(child.attrib["data-c"], 16)))
            except ValueError:
                continue
            variants = glyphs.get(char) or (glyphs.get("-") if char == "−" else None)
            if not variants:
                missing.add(char)
                continue
            pen = BoundsPen(None)
            parse_path(child.attrib["d"], pen)
            if not pen.bounds:
                continue
            xmin, ymin, xmax, ymax = pen.bounds
            sample = tint_sample(rng.choice(variants), color)
            group = ET.Element(f"{{{SVG}}}g")
            if "transform" in child.attrib:
                group.set("transform", child.attrib["transform"])
            ET.SubElement(group, f"{{{SVG}}}image", {
                "x": str(xmin), "y": str(-ymax), "width": str(xmax-xmin),
                "height": str(ymax-ymin), "transform": "scale(1,-1)",
                "preserveAspectRatio": "none",
                f"{{{XLINK}}}href": "data:image/png;base64," + base64.b64encode(png_bytes(sample)).decode(),
            })
            parent.remove(child)
            parent.insert(index, group)
            used += 1
    for element in root.iter():
        for attribute in ("fill", "stroke"):
            if element.get(attribute) == "currentColor":
                element.set(attribute, color)
    with fitz.open(stream=ET.tostring(root), filetype="svg") as svg:
        with fitz.open(stream=svg.convert_to_pdf(), filetype="pdf") as pdf:
            scale = min(3, 5000 / max(width, height))
            pix = pdf[0].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=True)
            image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGBA")
    return image, width, height, missing, used


@lru_cache(maxsize=12)
def text_font(size: int):
    candidates = [os.environ.get("INKLAB_FONT", ""), "C:/Windows/Fonts/malgun.ttf",
                  "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default(size=size)


def render_text(content: str, size: float, width: float, glyphs: dict, color: str, rng: random.Random):
    scale = 3
    pixel_size = round(size * scale)
    font = text_font(pixel_size)
    line_height = round(pixel_size * 1.65)
    max_width = round(width * scale)
    x, y = 0, 0
    pieces = []
    missing, used = set(), 0
    for char in content:
        if char == "\n":
            x, y = 0, y + line_height
            continue
        if char in glyphs and glyphs[char]:
            sample = tint_sample(rng.choice(glyphs[char]), color)
            h = pixel_size
            w = max(2, round(h * sample.width / sample.height))
            sample = sample.resize((w, h), Image.Resampling.LANCZOS)
            advance = w + pixel_size * .10
            used += 1
        else:
            sample = None
            advance = font.getlength(char)
            if not char.isspace():
                missing.add(char)
        if advance > max_width:
            raise ValueError("문자 하나가 블록 너비보다 큽니다. 너비를 늘리세요.")
        if x + advance > max_width and x:
            x, y = 0, y + line_height
        pieces.append((char, sample, round(x), y))
        x += advance
    height = y + line_height
    if height * max_width > 30_000_000:
        raise ValueError("텍스트 블록이 너무 큽니다. 나누어 입력하세요.")
    image = Image.new("RGBA", (max_width, height))
    draw = ImageDraw.Draw(image)
    for char, sample, x, y in pieces:
        if sample is not None:
            # Keep descenders visually below the same baseline.
            offset = round(pixel_size * .18) if char in "gjpqy" else 0
            image.alpha_composite(sample, (x, y + round(pixel_size * .12) + offset))
        else:
            draw.text((x, y), char, font=font, fill=color)
    return image, width, height / scale, missing, used


def render_block(block, profile, color, seed):
    rng = random.Random(seed)
    glyphs = profile.get("glyphs", {})
    if block.kind == "math":
        return render_math(block.content, block.size, glyphs, color, rng)
    return render_text(block.content, block.size, block.width, glyphs, color, rng)
