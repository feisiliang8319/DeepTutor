"""Use the existing application account session for the education service.

Both services read the same host-local runtime home. Neither a selected profile
nor a Cloudflare/email header substitutes for the application's signed session.
"""
from dataclasses import dataclass

from fastapi import HTTPException


@dataclass(frozen=True)
class AccountIdentity:
    username: str
    user_id: str
    role: str


class NativeAccountAccess:
    def __init__(self, *, decode=None, lookup=None):
        if decode is None and lookup is None:
            from deeptutor.services import auth

            if not auth.AUTH_ENABLED:
                raise ValueError('Native education access requires application authentication')
            decode, lookup = auth.decode_token, auth.get_user_info
        if decode is None or lookup is None:
            raise ValueError('Both account validation functions are required')
        self.decode, self.lookup = decode, lookup

    def authenticate(self, request) -> AccountIdentity:
        authorization = request.headers.get('authorization', '')
        parts = authorization.split(None, 1)
        token = (parts[1].strip() if len(parts) == 2 and parts[0].lower() == 'bearer'
                 else request.cookies.get('dt_token'))
        if not token or len(token) > 16384:
            raise HTTPException(401, '请先登录 DeepTutor 账号')
        payload = self.decode(token)
        if payload is None:
            raise HTTPException(401, '登录已过期，请重新登录')
        record = self.lookup(payload.username)
        if (not record or record.get('disabled') or not record.get('id')
                or record['id'] != payload.user_id):
            raise HTTPException(403, '当前账号不可用')
        return AccountIdentity(payload.username, record['id'], record.get('role', 'user'))


def from_environment():
    import os

    from deeptutor.multi_user.teaching_identity import active
    mode = os.environ.get('EDU_AUTH_MODE', 'native' if active() else 'cloudflare')
    if active() and mode != 'native':
        raise ValueError('Teaching mode requires native education authentication')
    if mode == 'cloudflare':
        return None
    if mode != 'native':
        raise ValueError('EDU_AUTH_MODE must be native or cloudflare')
    return NativeAccountAccess()
