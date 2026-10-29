"""Private per-user workspaces with durable, compare-and-swap snapshots.

Every database/storage operation uses the end user's JWT and RLS; no service-role key.
The free deployment runs one worker. CAS also prevents overwrites during rolling deploys.
"""
import hashlib
import io
import re
import zipfile
from pathlib import Path

import httpx

MAX_WORKSPACE = 45 * 1024 * 1024
ALLOWED_FILE = re.compile(r"(?:documents|profiles|layouts|samples|exports)/[a-zA-Z0-9_-]{1,64}\.(?:pdf|png|json)")


class CloudError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


def fingerprint(root):
    result = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result.update(path.relative_to(root).as_posix().encode())
            result.update(path.read_bytes())
    return result.digest()


def pack(root):
    files = [p for p in root.rglob("*") if p.is_file()]
    if len(files) > 1000 or sum(p.stat().st_size for p in files) > MAX_WORKSPACE:
        raise CloudError("개인 저장 공간 45MB를 초과했습니다. 기존 데이터를 정리하세요.", 413)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in files:
            name = path.relative_to(root).as_posix()
            if not ALLOWED_FILE.fullmatch(name) or path.is_symlink():
                raise CloudError("잘못된 작업 공간 파일입니다.", 400)
            archive.write(path, name)
    return stream.getvalue()


def unpack(data, root):
    if len(data) > MAX_WORKSPACE + 1_000_000:
        raise CloudError("저장 데이터 크기가 제한을 초과했습니다.", 413)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) > 1000 or sum(i.file_size for i in members) > MAX_WORKSPACE:
            raise CloudError("저장 데이터 크기가 제한을 초과했습니다.", 413)
        seen = set()
        for entry in members:
            if not ALLOWED_FILE.fullmatch(entry.filename) or entry.filename in seen:
                raise CloudError("잘못된 저장 파일 경로입니다.", 400)
            seen.add(entry.filename)
        for entry in members:
            target = root / entry.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(entry))


class SupabaseWorkspace:
    def __init__(self, url, publishable_key):
        self.url, self.key = url.rstrip("/"), publishable_key

    def client(self, token):
        return httpx.Client(base_url=self.url, timeout=60, headers={
            "apikey": self.key, "Authorization": "Bearer " + token,
        })

    def load(self, user_id, token, root):
        with self.client(token) as client:
            result = client.get("/rest/v1/inklab_workspaces", params={"select": "version,archive_path", "user_id": "eq."+user_id})
            if result.status_code != 200:
                raise CloudError("저장소에 연결하지 못했습니다.")
            rows = result.json()
            if not rows:
                return {"version": 0, "archive_path": None}
            row = rows[0]
            path = row["archive_path"]
            if not re.fullmatch(re.escape(user_id)+r"/[a-f0-9]{32}\.zip", path):
                raise CloudError("저장소 소유자 정보가 일치하지 않습니다.", 403)
            data = client.get("/storage/v1/object/authenticated/inklab-private/"+path)
            if data.status_code != 200:
                raise CloudError("작업 공간을 읽지 못했습니다.")
            unpack(data.content, root)
            return row

    def commit(self, user_id, token, root, previous):
        import uuid
        data = pack(root)
        key = user_id+"/"+uuid.uuid4().hex+".zip"
        with self.client(token) as client:
            uploaded = client.post("/storage/v1/object/inklab-private/"+key,
                                   content=data, headers={"Content-Type":"application/zip", "x-upsert":"false"})
            if uploaded.status_code not in (200,201):
                raise CloudError("작업 공간을 저장하지 못했습니다.")
            committed = client.post("/rest/v1/rpc/inklab_commit_workspace", json={
                "expected_version": previous["version"], "new_archive_path": key, "new_size": len(data),
            })
            if committed.status_code != 200:
                client.request("DELETE", "/storage/v1/object/inklab-private", json={"prefixes":[key]})
                raise CloudError("다른 창에서 내용이 변경됐거나 저장이 거부되었습니다. 새로고침 후 다시 시도하세요.",409)
            if previous["archive_path"]:
                # Old snapshot is no longer referenced. Failure here does not undo the commit.
                try:
                    client.request("DELETE", "/storage/v1/object/inklab-private", json={"prefixes":[previous["archive_path"]]})
                except httpx.HTTPError:
                    pass

