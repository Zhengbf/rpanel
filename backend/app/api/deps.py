from typing import Annotated
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal
from app.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    payload = decode_token(creds.credentials)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "凭证无效或已过期")
    return {"user_id": int(payload["sub"]), "username": payload["username"]}


async def require_writable(request: Request) -> None:
    if request.app.state.readonly:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "面板处于只读模式，禁止此操作")


_client_cache: dict = {}


async def get_current_device_id() -> int | None:
    """当前默认设备（正在被采样/管理的那台路由器）的 id；没绑定设备时为 None。"""
    from app.db.models import RouterDevice
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        dev = (await db.execute(
            select(RouterDevice).where(RouterDevice.is_default == True)  # noqa: E712
        )).scalar_one_or_none()
    return dev.id if dev else None


async def get_router_client():
    from app.db.models import RouterDevice
    from sqlalchemy import select
    from fastapi import HTTPException, status as http_status
    from app.adapters.ros.factory import create_client_for_device

    async def _resolve(db2):
        dev = (await db2.execute(
            select(RouterDevice).where(RouterDevice.is_default == True)  # noqa: E712
        )).scalar_one_or_none()
        if dev is None:
            raise HTTPException(http_status.HTTP_428_PRECONDITION_REQUIRED,
                                "尚未绑定路由器设备，请先完成向导")
        cached = _client_cache.get(dev.id)
        if cached is not None:
            return cached
        client = await create_client_for_device(dev)
        _client_cache[dev.id] = client
        return client

    async with AsyncSessionLocal() as db2:
        return await _resolve(db2)


