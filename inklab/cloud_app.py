"""Shared HTTPS deployment. Authentication and durable user isolation wrap both UI and MCP."""
import asyncio
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import anyio
from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.routing import Route, Mount

from . import store
from .cloud_auth import PRINCIPAL, ContextTokenVerifier, SupabaseIdentity
from .cloud_storage import CloudError, SupabaseWorkspace, fingerprint


def create_cloud_app(identity=None, repository=None):
    public = (os.environ.get("INKLAB_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL", "")).rstrip("/")
    supabase = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
    if not all([public,supabase,key]) or urlparse(public).scheme != "https" or urlparse(supabase).scheme != "https":
        raise RuntimeError("Set HTTPS INKLAB_PUBLIC_URL, SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY before cloud startup")
    os.environ["INKLAB_CLOUD"] = "1"
    os.environ["INKLAB_PUBLIC_URL"] = public
    from .app import app as editor
    from . import mcp_server as local
    identity = identity or SupabaseIdentity(supabase)
    repository = repository or SupabaseWorkspace(supabase,key)
    server = MCPServer("InkLab", instructions=(
        "Create engineering PDF notes using the current user's private handwriting workspace. "
        "First call open_workspace to let the user upload their PDF and handwriting samples. "
        "Only access the authenticated user's data. Read the page image before placing blocks. "
        "Inspect the rendered export image and report missing handwriting glyphs honestly. "
        "This app does not train a handwriting neural network or submit to a school LMS."),
        auth=AuthSettings(issuer_url=supabase+"/auth/v1",resource_server_url=public+"/mcp",
                          required_scopes=["openid"],validate_token_resource=False),
        token_verifier=ContextTokenVerifier())
    readers=["list_documents","inspect_pdf","get_page_image","get_export_page_image","list_handwriting_profiles","load_layout"]
    for name in readers+["register_glyph"]:
        server.add_tool(getattr(local,name),annotations=ToolAnnotations(
            read_only_hint=name in readers,destructive_hint=False,open_world_hint=False))

    @server.tool(annotations=ToolAnnotations(read_only_hint=True,open_world_hint=False))
    def open_workspace() -> dict:
        """Open your private web workspace to upload PDFs/handwriting images, manage samples and download results."""
        return {"workspace_url":public,"instructions":"같은 계정으로 로그인한 뒤 PDF와 필기 샘플을 올려주세요."}

    @server.tool(annotations=ToolAnnotations(read_only_hint=False,destructive_hint=False,open_world_hint=False))
    def render_pdf(layout: local.Layout) -> dict:
        """Render the current user's typed/LaTeX blocks into their PDF; return the authenticated download page."""
        result=local.render_pdf(layout)
        result.pop("local_download_url",None)
        result["download_page"]=public+"/download/"+result["id"]
        return result

    mcp_app=server.streamable_http_app(json_response=True,stateless_http=True,host="0.0.0.0",
        max_request_body_size=4*1024*1024,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=[urlparse(public).netloc,"localhost:*","127.0.0.1:*","testserver"],
            allowed_origins=[public]))

    async def config(request):
        return JSONResponse({"cloud":True,"supabase_url":supabase,"publishable_key":key,"mcp_url":public+"/mcp",
                             "github_login":os.environ.get("INKLAB_GITHUB_LOGIN")=="1"})

    async def auth_page(request):
        return FileResponse(store.ROOT/"static/cloud-auth.html")

    async def session(request):
        if request.headers.get("origin") != public:
            return JSONResponse({"detail":"Origin mismatch"},403)
        if request.method=="DELETE":
            response=JSONResponse({"ok":True});response.delete_cookie("inklab_session",path="/");return response
        if int(request.headers.get("content-length","0"))>20000:
            return JSONResponse({"detail":"Request too large"},413)
        try:
            token=(await request.json()).get("access_token","")
            principal=await anyio.to_thread.run_sync(identity.verify,token)
        except (ValueError,TypeError):
            principal=None
        if not principal:
            return JSONResponse({"detail":"로그인이 필요합니다."},401)
        response=JSONResponse({"ok":True})
        response.set_cookie("inklab_session",token,httponly=True,secure=True,samesite="lax",
                            max_age=max(1,principal.expires_at-int(time.time())),path="/")
        return response

    routes=[Route('/healthz',lambda r:JSONResponse({"status":"ok"})),
        Route('/auth/config',config),Route('/auth/session',session,methods=['POST','DELETE']),
        Route('/login',auth_page),Route('/oauth/consent',auth_page),Route('/download/{identifier}',auth_page)]
    # mcp_app owns its lifecycle and discovery; editor's catch-all static route remains last.
    mcp_app.router.routes[0:0]=routes
    mcp_app.router.routes.append(Mount('/',app=editor))
    return CloudGateway(mcp_app,identity,repository,public)


class CloudGateway:
    def __init__(self, app, identity, repository, public):
        self.app,self.identity,self.repository,self.public=app,identity,repository,public
        # PyMuPDF and the small free instance are deliberately single-job.
        self.lock=asyncio.Lock()

    async def __call__(self,scope,receive,send):
        if scope["type"]!="http":
            return await self.app(scope,receive,send)
        request=Request(scope,receive)
        path=request.url.path
        protected=path.startswith('/api/') or path.rstrip('/')=='/mcp'
        if not protected:
            return await self.app(scope,receive,send)
        is_mcp=path.rstrip('/')=='/mcp'
        token=request.headers.get('authorization','').removeprefix('Bearer ')
        if not token and not is_mcp:
            token=request.cookies.get('inklab_session','')
        principal=await anyio.to_thread.run_sync(lambda:self.identity.verify(token,mcp=is_mcp))
        if not principal:
            response=JSONResponse({"detail":"로그인이 필요합니다."},401,headers={
                'WWW-Authenticate':f'Bearer resource_metadata="{self.public}/.well-known/oauth-protected-resource/mcp"',
                'Cache-Control':'no-store'})
            return await response(scope,receive,send)
        if not is_mcp and request.method not in ('GET','HEAD') and request.headers.get('origin')!=self.public:
            return await JSONResponse({'detail':'Origin mismatch'},403)(scope,receive,send)
        if path=='/api/draft':
            return await JSONResponse({'detail':'공용 앱은 연결된 ChatGPT에서 풀이를 작성합니다.'},403)(scope,receive,send)
        if int(request.headers.get('content-length','0'))>32*1024*1024:
            return await JSONResponse({'detail':'파일이 너무 큽니다.'},413)(scope,receive,send)
        try:
            async with self.lock:
                with tempfile.TemporaryDirectory(prefix='inklab-user-') as directory:
                    root=Path(directory)
                    row=await anyio.to_thread.run_sync(self.repository.load,principal.user_id,token,root)
                    before=await anyio.to_thread.run_sync(fingerprint,root)
                    workspace=store.WORKSPACE.set(root);auth=PRINCIPAL.set(principal)
                    messages=[]
                    async def buffer(message):
                        messages.append(message)
                    try:
                        # Disable sendfile offload so the temporary workspace survives until all bytes are buffered.
                        scope={**scope,'extensions':{k:v for k,v in scope.get('extensions',{}).items() if k!='http.response.pathsend'}}
                        await self.app(scope,receive,buffer)
                        status=next((m['status'] for m in messages if m['type']=='http.response.start'),500)
                        after=await anyio.to_thread.run_sync(fingerprint,root)
                        if status<400 and before!=after:
                            await anyio.to_thread.run_sync(self.repository.commit,principal.user_id,token,root,row)
                        for message in messages:
                            if message['type']=='http.response.start':
                                message['headers']=[(k,v) for k,v in message['headers'] if k.lower()!=b'cache-control']+[(b'cache-control',b'no-store')]
                            await send(message)
                    finally:
                        store.WORKSPACE.reset(workspace);PRINCIPAL.reset(auth)
        except CloudError as exc:
            await JSONResponse({'detail':str(exc)},exc.status)(scope,receive,send)

