import os
import uuid
from dataclasses import dataclass
from contextvars import ContextVar
from urllib.parse import urlparse

import jwt
from mcp.server.auth.provider import AccessToken


@dataclass(frozen=True)
class Principal:
    user_id: str
    token: str
    client_id: str | None
    expires_at: int


PRINCIPAL: ContextVar[Principal | None] = ContextVar("inklab_principal", default=None)


class SupabaseIdentity:
    def __init__(self, url):
        self.issuer = url.rstrip("/")+"/auth/v1"
        self.jwks = jwt.PyJWKClient(self.issuer+"/.well-known/jwks.json", cache_keys=True, lifespan=300)

    def verify(self, token, mcp=False):
        if not token or len(token)>16000:
            return None
        try:
            key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(token,key.key,algorithms=["ES256","RS256"],audience="authenticated",
                                issuer=self.issuer,options={"require":["exp","iss","aud","sub"]})
            user_id = str(uuid.UUID(claims["sub"]))
            if claims.get("role") != "authenticated":
                return None
            client_id = claims.get("client_id")
            if mcp and not client_id:
                return None
            allowed = os.environ.get("INKLAB_OAUTH_CLIENT_IDS", "").split(",")
            if mcp and allowed != [""] and client_id not in allowed:
                return None
            return Principal(user_id,token,client_id,int(claims["exp"]))
        except (jwt.PyJWTError, ValueError, KeyError):
            return None


class ContextTokenVerifier:
    async def verify_token(self, token):
        principal = PRINCIPAL.get()
        if not principal or principal.token != token or not principal.client_id:
            return None
        return AccessToken(token=token,client_id=principal.client_id,subject=principal.user_id,
                           expires_at=principal.expires_at,scopes=["openid"],
                           claims={"iss":os.environ["SUPABASE_URL"].rstrip("/")+"/auth/v1"})
