"""Credential configuration and fixed-sample Jev connectivity test only."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from deeptutor.api.routers.auth import require_admin
from deeptutor.services import material_intelligence as service

class SafeValidationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                # Pydantic errors can include the rejected secret as raw input.
                raise HTTPException(422, {"code": "invalid_request"}) from None
        return safe_handler


router = APIRouter(dependencies=[Depends(require_admin)], route_class=SafeValidationRoute)


class KeyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr | None = Field(default=None, max_length=4096)


class ConnectionTest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def failed(exc):
    # No raw provider errors, bearer tokens or submitted keys in API responses.
    return HTTPException(503, {"code": exc.code})


@router.get("/settings")
def get_settings():
    return service.settings()


@router.put("/settings")
def put_settings(body: KeyUpdate):
    try:
        return service.save_key(body.api_key.get_secret_value() if body.api_key is not None else None)
    except service.IntelligenceError as exc:
        raise failed(exc) from None


@router.post("/test")
async def test_connection(body: ConnectionTest):
    try:
        return await service.connection_test()
    except service.IntelligenceError as exc:
        raise failed(exc) from None
