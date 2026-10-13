from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db, get_current_user, require_writable
from app.db.models import RouterDevice, AuditLog, User
from app.security import encrypt_secret, verify_password, hash_password
from app.adapters.ros.rest_client import RestRouterOsClient
from app.adapters.ros.ssh_client import SshRouterOsClient
from app.adapters.ros.parser import normalize_host

router = APIRouter(prefix="/api/wizard", tags=["wizard"])


class TestConnectionRequest(BaseModel):
    host: str = Field(..., min_length=1, max_length=256)
    port: int = Field(443, ge=1, le=65535)
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=256)
    auth_method: str = Field("rest", pattern="^(rest|ssh)$")
    verify_tls: bool = False
    timeout: float = Field(10.0, gt=0, le=60)

    @field_validator("host")
    @classmethod
    def clean_host(cls, v: str) -> str:
        cleaned = normalize_host(v)
        if not cleaned:
            raise ValueError("主机地址不能为空")
        return cleaned


class BindDeviceRequest(TestConnectionRequest):
    name: str = Field(..., min_length=1, max_length=128)


class DeviceUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    host: str | None = Field(None, min_length=1, max_length=256)
    port: int | None = Field(None, ge=1, le=65535)
    username: str | None = Field(None, min_length=1, max_length=128)
    password: str | None = Field(None, min_length=1, max_length=256)
    auth_method: str | None = Field(None, pattern="^(rest|ssh)$")
    verify_tls: bool | None = None
    timeout: float | None = Field(None, gt=0, le=60)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6, max_length=128)


class DeviceOut(BaseModel):
    id: int
    name: str
    host: str
    port: int
    username: str
    auth_method: str
    verify_tls: bool
    timeout: float
    is_default: bool

    model_config = {"from_attributes": True}


PRIVATE_PREFIXES = ("10.", "192.168.", "172.16.", "172.17.", "172.18.",
                    "172.19.", "172.20.", "172.21.", "172.22.", "172.23.",
                    "172.24.", "172.25.", "172.26.", "172.27.", "172.28.",
                    "172.29.", "172.30.", "172.31.", "127.", "169.254.")


def validate_host(host: str) -> None:
    host = host.strip()
    if not any(host.startswith(p) for p in PRIVATE_PREFIXES):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "路由器地址必须是局域网私网 IP")


def _make_client(body):
    if body.auth_method == "ssh":
        return SshRouterOsClient(host=body.host, port=body.port, username=body.username,
                                 password=body.password, timeout=body.timeout)
    return RestRouterOsClient(host=body.host, port=body.port, username=body.username,
                              password=body.password, verify_tls=body.verify_tls,
                              timeout=body.timeout)


@router.post("/test-connection")
async def test_connection(body: TestConnectionRequest, user: dict = Depends(get_current_user)):
    validate_host(body.host)
    client = _make_client(body)
    try:
        result = await client.test_connection()
    finally:
        await client.close()
    return result.model_dump()


@router.post("/bind", response_model=DeviceOut)
async def bind_device(
    body: BindDeviceRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_writable),
):
    validate_host(body.host)
    client = _make_client(body)
    try:
        result = await client.test_connection()
    finally:
        await client.close()
    if not result.ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"绑定前测试连接失败：{result.message}")

    existing = (await db.execute(select(RouterDevice))).scalars().all()
    is_default = len(existing) == 0

    dev = RouterDevice(
        name=body.name, host=body.host.strip(), port=body.port,
        username=body.username, encrypted_password=encrypt_secret(body.password),
        auth_method=body.auth_method, verify_tls=body.verify_tls,
        timeout=body.timeout, is_default=is_default,
    )
    db.add(dev)
    db.add(AuditLog(user_id=user["user_id"], username=user["username"],
                    action="bind_device", target=body.host,
                    detail=f"设备名={body.name}, 方式={body.auth_method}"))
    await db.commit()
    await db.refresh(dev)

    # 关键：绑定后立即启动采样器，否则总览会一直空白
    from app.services.runtime import runtime
    from app.api.deps import _client_cache
    _client_cache.pop(dev.id, None)
    await runtime.restart()
    return dev


@router.get("/devices", response_model=list[DeviceOut])
async def list_devices(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    devices = (await db.execute(select(RouterDevice))).scalars().all()
    return devices


@router.put("/devices/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: int,
    body: DeviceUpdateRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_writable),
):
    dev = await db.get(RouterDevice, device_id)
    if dev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "设备不存在")

    if body.host is not None:
        cleaned = normalize_host(body.host)
        validate_host(cleaned)
        dev.host = cleaned
    if body.name is not None:
        dev.name = body.name
    if body.port is not None:
        dev.port = body.port
    if body.username is not None:
        dev.username = body.username
    if body.password is not None:
        dev.encrypted_password = encrypt_secret(body.password)
    if body.auth_method is not None:
        dev.auth_method = body.auth_method
    if body.verify_tls is not None:
        dev.verify_tls = body.verify_tls
    if body.timeout is not None:
        dev.timeout = body.timeout

    db.add(AuditLog(user_id=user["user_id"], username=user["username"],
                    action="update_device", target=dev.host, detail=dev.name))
    await db.commit()
    await db.refresh(dev)

    from app.services.runtime import runtime
    from app.api.deps import _client_cache
    _client_cache.pop(dev.id, None)
    if dev.is_default:
        await runtime.restart()
    return dev


@router.post("/devices/{device_id}/default")
async def set_default_device(
    device_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_writable),
):
    dev = await db.get(RouterDevice, device_id)
    if dev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "设备不存在")
    devices = (await db.execute(select(RouterDevice))).scalars().all()
    for d in devices:
        d.is_default = (d.id == device_id)
    await db.commit()

    from app.services.runtime import runtime
    from app.api.deps import _client_cache
    _client_cache.clear()
    await runtime.restart()
    return {"ok": True, "default_id": device_id}


@router.delete("/devices/{device_id}")
async def delete_device(
    device_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_writable),
):
    dev = await db.get(RouterDevice, device_id)
    if dev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "设备不存在")
    await db.delete(dev)
    db.add(AuditLog(user_id=user["user_id"], username=user["username"],
                    action="delete_device", target=dev.host))
    await db.commit()
    # 如果删了默认设备，把第一台设为默认
    remaining = (await db.execute(select(RouterDevice))).scalars().all()
    if remaining and not any(d.is_default for d in remaining):
        remaining[0].is_default = True
        await db.commit()

    from app.services.runtime import runtime
    from app.api.deps import _client_cache
    _client_cache.pop(device_id, None)
    await runtime.restart()
    return {"ok": True}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    db_user = await db.get(User, user["user_id"])
    if db_user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if not verify_password(body.old_password, db_user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "原密码错误")
    db_user.password_hash = hash_password(body.new_password)
    db.add(AuditLog(user_id=user["user_id"], username=user["username"],
                    action="change_password"))
    await db.commit()
    return {"ok": True}
