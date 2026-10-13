"""网络管理接口（DHCP）。新功能按同样结构扩展：一个 router 文件 + 一个 service。"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.api.deps import get_current_user, get_db, get_router_client, require_writable
from app.db.session import AsyncSessionLocal
from app.services.network import NetworkService

logger = logging.getLogger(__name__)


def _router_error(e: Exception, context: str = "DHCP 操作") -> str:
    """把适配器异常翻译成用户能看懂的原因。

    RouterOS 在 4xx 响应体里会给出具体原因（如 unknown parameter / invalid value），
    之前一律压成「HTTPStatusError」，导致界面上完全看不出问题在哪。
    """
    resp = getattr(e, "response", None)
    if resp is not None:
        detail = ""
        try:
            body = resp.json()
            detail = body.get("detail") or body.get("message") or ""
        except Exception:
            detail = (resp.text or "").strip()
        code = getattr(resp, "status_code", "?")
        text = f"路由器返回 {code}" + (f"：{detail}" if detail else "")
    else:
        text = f"{type(e).__name__}: {e}"
    return f"{context}失败：{text[:240]}"

router = APIRouter(prefix="/api/network", tags=["network"])


class MakeStaticRequest(BaseModel):
    lease_id: str = Field(..., min_length=1, max_length=64)


class DhcpServerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    interface: str = Field(..., min_length=1, max_length=64)
    address_pool: str = Field("", max_length=64)
    lease_time: str = Field("1d", max_length=32)


class DhcpServerUpdate(BaseModel):
    name: str | None = Field(None, max_length=64)
    interface: str | None = Field(None, max_length=64)
    address_pool: str | None = Field(None, max_length=64)
    lease_time: str | None = Field(None, max_length=32)
    disabled: bool | None = None


class DhcpProvisionRequest(BaseModel):
    """一站式创建：用户只填这一组，后端按 RouterOS 依赖顺序创建 pool → network → server。"""
    network_cidr: str = Field(..., min_length=7, max_length=64, description="如 192.168.8.0/24")
    gateway: str = Field(..., min_length=7, max_length=64)
    pool_name: str = Field(..., min_length=1, max_length=64)
    pool_ranges: str = Field(..., min_length=7, max_length=128, description="如 192.168.8.100-192.168.8.200")
    server_name: str = Field(..., min_length=1, max_length=64)
    interface: str = Field(..., min_length=1, max_length=64)
    dns_server: str = Field("", max_length=128)
    lease_time: str = Field("1d", max_length=32)
    comment: str = Field("", max_length=128)


class IpPoolCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    ranges: str = Field(..., min_length=3, max_length=128)
    comment: str = Field("", max_length=128)


class IpPoolUpdate(BaseModel):
    name: str | None = Field(None, max_length=64)
    ranges: str | None = Field(None, max_length=128)
    comment: str | None = Field(None, max_length=128)


class DhcpNetworkCreate(BaseModel):
    address: str = Field(..., min_length=7, max_length=64)
    gateway: str = Field("", max_length=64)
    netmask: str = Field("", max_length=64)
    dns_server: str = Field("", max_length=128)
    domain: str = Field("", max_length=64)
    comment: str = Field("", max_length=128)


class DhcpNetworkUpdate(BaseModel):
    address: str | None = Field(None, max_length=64)
    gateway: str | None = Field(None, max_length=64)
    netmask: str | None = Field(None, max_length=64)
    dns_server: str | None = Field(None, max_length=128)
    domain: str | None = Field(None, max_length=64)
    comment: str | None = Field(None, max_length=128)


class AddStaticRequest(BaseModel):
    address: str = Field(..., min_length=7, max_length=64)
    mac: str = Field(..., min_length=11, max_length=32)
    server: str = Field("", max_length=64)
    comment: str = Field("", max_length=128)

    @field_validator("mac")
    @classmethod
    def normalize_mac(cls, v: str) -> str:
        mac = v.strip().upper().replace("-", ":")
        if len(mac.split(":")) != 6:
            raise ValueError("MAC 格式应为 AA:BB:CC:DD:EE:FF")
        return mac


@router.get("/dhcp")
async def dhcp_overview(user: dict = Depends(get_current_user),
                        client=Depends(get_router_client)):
    return await NetworkService(client).dhcp_overview()


@router.get("/dhcp/leases")
async def dhcp_leases(user: dict = Depends(get_current_user),
                      client=Depends(get_router_client)):
    return await NetworkService(client).leases()


@router.post("/dhcp/provision")
async def provision_dhcp(body: DhcpProvisionRequest,
                         user: dict = Depends(get_current_user),
                         _: None = Depends(require_writable),
                         client=Depends(get_router_client)):
    """一站式创建 DHCP 服务（地址池 → 网段 → 服务器），已存在的对象会被复用。"""
    svc = NetworkService(client)
    async with AsyncSessionLocal() as db:
        try:
            return await svc.provision_dhcp(
                db, network_cidr=body.network_cidr, gateway=body.gateway,
                pool_name=body.pool_name, pool_ranges=body.pool_ranges,
                server_name=body.server_name, interface=body.interface,
                dns_server=body.dns_server, lease_time=body.lease_time,
                comment=body.comment,
                operator_id=user.get("user_id"), operator_name=user["username"])
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
        except Exception as e:
            logger.exception("新建 DHCP 服务失败")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e, "新建 DHCP 服务"))


@router.get("/dhcp/pools")
async def list_ip_pools(user: dict = Depends(get_current_user),
                        client=Depends(get_router_client)):
    return await NetworkService(client).pools()


@router.post("/dhcp/pools")
async def add_ip_pool(body: IpPoolCreate,
                      user: dict = Depends(get_current_user),
                      _: None = Depends(require_writable),
                      client=Depends(get_router_client)):
    svc = NetworkService(client)
    async with AsyncSessionLocal() as db:
        try:
            return await svc.add_pool(db, body.name, body.ranges, body.comment,
                                      user.get("user_id"), user["username"])
        except Exception as e:
            logger.exception("地址池操作失败")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e, "地址池操作"))


@router.patch("/dhcp/pools/{pool_id}")
async def update_ip_pool(pool_id: str, body: IpPoolUpdate,
                         user: dict = Depends(get_current_user),
                         _: None = Depends(require_writable),
                         client=Depends(get_router_client)):
    svc = NetworkService(client)
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "没有需要更新的字段")
    async with AsyncSessionLocal() as db:
        try:
            return await svc.set_pool(db, pool_id, fields, user.get("user_id"), user["username"])
        except Exception as e:
            logger.exception("地址池操作失败")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e, "地址池操作"))


@router.delete("/dhcp/pools/{pool_id}")
async def delete_ip_pool(pool_id: str,
                         user: dict = Depends(get_current_user),
                         _: None = Depends(require_writable),
                         client=Depends(get_router_client)):
    svc = NetworkService(client)
    async with AsyncSessionLocal() as db:
        try:
            return await svc.remove_pool(db, pool_id, user.get("user_id"), user["username"])
        except Exception as e:
            logger.exception("地址池操作失败")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e, "地址池操作"))


@router.post("/dhcp/servers")
async def add_dhcp_server(body: DhcpServerCreate,
                          user: dict = Depends(get_current_user),
                          _: None = Depends(require_writable),
                          client=Depends(get_router_client)):
    svc = NetworkService(client)
    async with AsyncSessionLocal() as db:
        try:
            return await svc.add_server(db, body.name, body.interface, body.address_pool,
                                        body.lease_time, user.get("user_id"), user["username"])
        except Exception as e:
            logger.exception("DHCP 服务器操作失败")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e, "DHCP 服务器操作"))


@router.patch("/dhcp/servers/{server_id}")
async def update_dhcp_server(server_id: str, body: DhcpServerUpdate,
                             user: dict = Depends(get_current_user),
                             _: None = Depends(require_writable),
                             client=Depends(get_router_client)):
    svc = NetworkService(client)
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "没有需要更新的字段")
    async with AsyncSessionLocal() as db:
        try:
            return await svc.set_server(db, server_id, fields, user.get("user_id"), user["username"])
        except Exception as e:
            logger.exception("DHCP 服务器操作失败")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e, "DHCP 服务器操作"))


@router.delete("/dhcp/servers/{server_id}")
async def delete_dhcp_server(server_id: str,
                             user: dict = Depends(get_current_user),
                             _: None = Depends(require_writable),
                             client=Depends(get_router_client)):
    svc = NetworkService(client)
    async with AsyncSessionLocal() as db:
        try:
            return await svc.remove_server(db, server_id, user.get("user_id"), user["username"])
        except Exception as e:
            logger.exception("DHCP 服务器操作失败")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e, "DHCP 服务器操作"))


@router.post("/dhcp/networks")
async def add_dhcp_network(body: DhcpNetworkCreate,
                           user: dict = Depends(get_current_user),
                           _: None = Depends(require_writable),
                           client=Depends(get_router_client)):
    svc = NetworkService(client)
    async with AsyncSessionLocal() as db:
        try:
            return await svc.add_network(db, body.address, body.gateway, body.netmask,
                                         body.dns_server, body.domain, body.comment,
                                         user.get("user_id"), user["username"])
        except Exception as e:
            logger.exception("DHCP 网段操作失败")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e, "DHCP 网段操作"))


@router.patch("/dhcp/networks/{network_id}")
async def update_dhcp_network(network_id: str, body: DhcpNetworkUpdate,
                              user: dict = Depends(get_current_user),
                              _: None = Depends(require_writable),
                              client=Depends(get_router_client)):
    svc = NetworkService(client)
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "没有需要更新的字段")
    async with AsyncSessionLocal() as db:
        try:
            return await svc.set_network(db, network_id, fields, user.get("user_id"), user["username"])
        except Exception as e:
            logger.exception("DHCP 网段操作失败")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e, "DHCP 网段操作"))


@router.delete("/dhcp/networks/{network_id}")
async def delete_dhcp_network(network_id: str,
                              user: dict = Depends(get_current_user),
                              _: None = Depends(require_writable),
                              client=Depends(get_router_client)):
    svc = NetworkService(client)
    async with AsyncSessionLocal() as db:
        try:
            return await svc.remove_network(db, network_id, user.get("user_id"), user["username"])
        except Exception as e:
            logger.exception("DHCP 网段操作失败")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e, "DHCP 网段操作"))


@router.post("/dhcp/leases/make-static")
async def make_static(body: MakeStaticRequest,
                      user: dict = Depends(get_current_user),
                      _: None = Depends(require_writable),
                      client=Depends(get_router_client)):
    svc = NetworkService(client)
    async with AsyncSessionLocal() as db:
        try:
            return await svc.make_static(db, body.lease_id, user.get("user_id"), user["username"])
        except Exception as e:
            logger.exception("绑定静态租约失败")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e, "绑定静态租约"))


@router.post("/dhcp/leases")
async def add_static(body: AddStaticRequest,
                     user: dict = Depends(get_current_user),
                     _: None = Depends(require_writable),
                     client=Depends(get_router_client)):
    svc = NetworkService(client)
    async with AsyncSessionLocal() as db:
        try:
            return await svc.add_static(db, body.address, body.mac, body.server,
                                        body.comment, user.get("user_id"), user["username"])
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
        except Exception as e:
            logger.exception("新增静态绑定失败")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e, "新增静态绑定"))


@router.delete("/dhcp/leases/{lease_id}")
async def remove_lease(lease_id: str,
                       user: dict = Depends(get_current_user),
                       _: None = Depends(require_writable),
                       client=Depends(get_router_client)):
    svc = NetworkService(client)
    async with AsyncSessionLocal() as db:
        try:
            return await svc.remove_lease(db, lease_id, user.get("user_id"), user["username"])
        except Exception as e:
            logger.exception("删除租约失败")
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e, "删除租约"))
