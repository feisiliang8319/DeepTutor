"""Verify the existing Cloudflare Access identity before a parent judgment.

No shared-device profile, email header or unsigned JWT grants authority.
Configuration contains only the Access issuer/audience and an explicit
verified-email -> existing parent-profile map. No local-admin fallback.
"""
import json
import os
import re
import threading
import time

from fastapi import HTTPException


class CloudflareParentIdentity:
    def __init__(self, issuer, audience, parents, *, fetch_keys=None):
        if not re.fullmatch(r"https://[a-zA-Z0-9-]+\.cloudflareaccess\.com", issuer):
            raise ValueError("EDU_ACCESS_ISSUER must be a Cloudflare Access team HTTPS origin")
        if not audience or not isinstance(parents, dict) or not parents:
            raise ValueError("Access audience and parent mapping are required")
        if any(not isinstance(k, str) or not k.strip() or not isinstance(v, str)
               or not v.startswith("parent-") for k, v in parents.items()):
            raise ValueError("Every verified email must map to an existing parent profile")
        self.issuer, self.audience = issuer, audience
        self.parents = {k.strip().lower(): v for k, v in parents.items()}
        if len(self.parents) != len(parents):
            raise ValueError("Duplicate normalized parent email")
        self.fetch_keys = fetch_keys or self._fetch_keys
        self.keys, self.fetched_at = None, 0.0
        self.lock = threading.Lock()

    def _fetch_keys(self):
        import httpx
        try:
            response = httpx.get(self.issuer + "/cdn-cgi/access/certs", timeout=5,
                                 follow_redirects=False)
            response.raise_for_status()
            keys = response.json()
            if not isinstance(keys, dict) or not isinstance(keys.get("keys"), list) or not keys["keys"]:
                raise ValueError("missing signing keys")
            return keys
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, "家长身份验证服务暂时不可用") from exc

    def __call__(self, request):
        from jose import JWTError, jwt
        token = request.headers.get("Cf-Access-Jwt-Assertion")
        if not token or len(token) > 16384:
            raise HTTPException(401, "需要 Cloudflare Access 身份验证")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise JWTError("unsupported signing header")
        except JWTError as exc:
            raise HTTPException(401, "身份凭证无效") from exc
        with self.lock:
            now = time.monotonic()
            # Refresh on rotation, bounded to once per minute for unknown keys.
            unknown = self.keys and not any(k.get("kid") == header["kid"] for k in self.keys["keys"])
            if self.keys is None or now - self.fetched_at > 300 or (unknown and now - self.fetched_at > 60):
                self.keys = self.fetch_keys()
                self.fetched_at = now
            keys = self.keys
        try:
            claims = jwt.decode(token, keys, algorithms=["RS256"],
                                audience=self.audience, issuer=self.issuer,
                                options={"require_exp": True, "require_iat": True,
                                         "require_sub": True, "require_aud": True, "require_iss": True})
            email = claims.get("email")
            if not isinstance(email, str):
                raise JWTError("missing user email")
        except JWTError as exc:
            raise HTTPException(401, "身份凭证无效或已过期") from exc
        parent = self.parents.get(email.strip().lower())
        if parent is None:
            raise HTTPException(403, "当前登录身份没有家长复核权限")
        return parent


def from_environment():
    issuer = os.environ.get("EDU_ACCESS_ISSUER")
    audience = os.environ.get("EDU_ACCESS_AUDIENCE")
    parents = os.environ.get("EDU_PARENT_IDENTITIES")
    if not any((issuer, audience, parents)):
        return None
    if not all((issuer, audience, parents)):
        raise ValueError("All three EDU_ACCESS_ISSUER/AUDIENCE and EDU_PARENT_IDENTITIES settings are required")
    return CloudflareParentIdentity(issuer, audience, json.loads(parents))
