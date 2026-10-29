import base64
import io
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from inklab import store
from inklab.cloud_app import create_cloud_app
from inklab.cloud_auth import Principal, SupabaseIdentity
from inklab.cloud_storage import CloudError, fingerprint, pack, unpack

A='11111111-1111-4111-8111-111111111111'
B='22222222-2222-4222-8222-222222222222'


class FakeIdentity:
    def verify(self,token,mcp=False):
        uid={'token-a':A,'token-b':B}.get(token)
        return Principal(uid,token,'test-client',int(time.time())+3600) if uid else None


class MemoryRepository:
    def __init__(self):self.rows={};self.fail=False
    def load(self,uid,token,root):
        record=self.rows.get(uid)
        if record:unpack(record[1],root)
        return {'version':record[0] if record else 0,'archive_path':None}
    def commit(self,uid,token,root,previous):
        if self.fail:raise CloudError('Persistence unavailable')
        assert previous['version']==self.rows.get(uid,(0,))[0]
        self.rows[uid]=(previous['version']+1,pack(root))


@pytest.fixture
def shared(monkeypatch):
    monkeypatch.setenv('INKLAB_PUBLIC_URL','https://testserver')
    monkeypatch.setenv('SUPABASE_URL','https://project.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY','sb_publishable_test')
    monkeypatch.setenv('INKLAB_CLOUD','1')
    repo=MemoryRepository()
    app=create_cloud_app(FakeIdentity(),repo)
    with TestClient(app,base_url='https://testserver') as client:
        yield client,repo


def headers(token='token-a'):
    return {'Authorization':'Bearer '+token,'Origin':'https://testserver'}


def test_unauthorized_and_oauth_discovery(shared):
    client,_=shared
    assert client.get('/healthz').status_code==200
    for path in ['/api/documents','/api/profiles','/mcp']:
        response=client.get(path)
        assert response.status_code==401
        assert 'resource_metadata' in response.headers['www-authenticate']
    metadata=client.get('/.well-known/oauth-protected-resource/mcp')
    assert metadata.status_code==200
    assert metadata.json()['authorization_servers']==['https://project.supabase.co/auth/v1']


def test_user_isolation_and_durable_restart(shared):
    client,repo=shared
    profile=client.post('/api/profiles',headers=headers(),json={'name':'Alice only'})
    assert profile.status_code==200,profile.text
    assert A in repo.rows and B not in repo.rows
    other=client.get('/api/profiles',headers=headers('token-b'))
    assert other.status_code==200
    assert all(p['name']!='Alice only' for p in other.json())
    own=client.get('/api/profiles',headers=headers())
    assert any(p['name']=='Alice only' for p in own.json())
    # Each request uses a fresh temporary directory: persistence is required to see the profile.
    assert store.WORKSPACE.get() is None


def test_private_download_and_paid_ai_disabled(shared):
    client,_=shared
    demo=client.post('/api/demo',headers=headers()).json()
    layout=client.get('/api/layouts/'+demo['id'],headers=headers()).json()
    result=client.post('/api/render',headers=headers(),json=layout)
    assert result.status_code==200,result.text
    url=result.json()['url']
    assert client.get(url,headers=headers()).content.startswith(b'%PDF')
    assert client.get(url,headers=headers('token-b')).status_code==404
    assert client.post('/api/draft',headers=headers(),json={}).status_code==403


def test_failed_persistence_not_reported_success(shared):
    client,repo=shared
    repo.fail=True
    response=client.post('/api/profiles',headers=headers(),json={'name':'Do not lose silently'})
    assert response.status_code==503
    assert not repo.rows


def test_cookie_login_and_csrf(shared):
    client,_=shared
    assert client.post('/auth/session',json={'access_token':'token-a'}).status_code==403
    response=client.post('/auth/session',headers={'Origin':'https://testserver'},json={'access_token':'token-a'})
    assert response.status_code==200
    assert 'HttpOnly' in response.headers['set-cookie'] and 'Secure' in response.headers['set-cookie']
    assert client.get('/api/profiles').status_code==200
    assert client.post('/api/demo',headers={'Origin':'https://evil.example'}).status_code==403
    # Cookies cannot act as a remote MCP authorization header.
    assert client.post('/mcp',json={}).status_code==401


def test_http_mcp_protocol_and_tools(shared):
    client,_=shared
    wire={**headers(),'Accept':'application/json, text/event-stream'}
    init=client.post('/mcp',headers=wire,json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{
        'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'test','version':'1'}}})
    assert init.status_code==200,init.text
    response=client.post('/mcp',headers=wire,json={'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
    names={tool['name'] for tool in response.json()['result']['tools']}
    assert {'open_workspace','render_pdf','get_page_image'} <= names
    assert 'import_pdf' not in names
    result=client.post('/mcp',headers=wire,json={'jsonrpc':'2.0','id':3,'method':'tools/call',
        'params':{'name':'list_handwriting_profiles','arguments':{}}})
    assert result.status_code==200,result.text
    assert not result.json()['result'].get('isError',False),result.text


def test_archive_rejects_path_traversal(tmp_path):
    for name in ['../outside.json','/outside.json','profiles/a.json/../../bad','profiles\\..\\outside.json']:
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as archive:archive.writestr(name,b'bad')
        with pytest.raises(CloudError):unpack(buf.getvalue(),tmp_path)
    assert not list(tmp_path.iterdir())


def test_signed_tokens_validate_issuer_audience_and_identity(monkeypatch):
    private=ec.generate_private_key(ec.SECP256R1())
    identity=SupabaseIdentity('https://project.supabase.co')
    monkeypatch.setattr(identity.jwks,'get_signing_key_from_jwt',lambda _:SimpleNamespace(key=private.public_key()))
    claims={'sub':A,'iss':'https://project.supabase.co/auth/v1','aud':'authenticated','exp':int(time.time())+60,'role':'authenticated','client_id':'chatgpt-client'}
    def token(payload):return jwt.encode(payload,private,algorithm='ES256')
    assert identity.verify(token(claims),mcp=True).user_id==A
    for changed in [{'aud':'other-service'},{'iss':'https://other-project.supabase.co/auth/v1'},{'exp':1},{'role':'anon'},{'sub':'../../another-user'}]:
        assert identity.verify(token({**claims,**changed}),mcp=True) is None
    browser={k:v for k,v in claims.items() if k!='client_id'}
    assert identity.verify(token(browser),mcp=True) is None
    assert identity.verify(token(browser),mcp=False).user_id==A
