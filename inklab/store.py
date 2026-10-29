import json
import os
import re
import threading
import uuid
from pathlib import Path
from contextvars import ContextVar

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("INKLAB_DATA_DIR", ROOT / "data")).resolve()
LOCK = threading.RLock()
WORKSPACE: ContextVar[Path | None] = ContextVar("inklab_workspace", default=None)


def folder(name: str) -> Path:
    root = WORKSPACE.get()
    if os.environ.get("INKLAB_CLOUD") == "1" and root is None:
        raise RuntimeError("Authenticated workspace is required in cloud mode")
    path = (root if root is not None else DATA) / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def item_path(kind: str, identifier: str, extension: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", identifier):
        raise ValueError("잘못된 파일 ID입니다.")
    return folder(kind) / f"{identifier}.{extension}"


def new_id() -> str:
    return uuid.uuid4().hex


def write_json(path: Path, value: dict):
    temporary = path.with_name(path.name + "." + new_id() + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def profile(identifier="default") -> dict:
    with LOCK:
        path = item_path("profiles", identifier, "json")
        if identifier == "default" and not path.exists():
            write_json(path, {"id": "default", "name": "나의 필기", "glyphs": {}})
        if not path.exists():
            raise ValueError("필기 프로필을 찾을 수 없습니다.")
        return json.loads(path.read_text(encoding="utf-8"))


def list_profiles() -> list[dict]:
    profile()
    return [json.loads(p.read_text(encoding="utf-8")) for p in folder("profiles").glob("*.json")]
