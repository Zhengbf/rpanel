import logging
import ipaddress
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from app.api.deps import get_current_user, get_router_client, require_writable

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/port-forward", tags=["port-forward"])


def _router_error(e: Exception) -> str:
    resp = getattr(e, "response", None)
    if resp is not None:
        detail = ""
        try:
            body = resp.json()
            detail = body.get("detail") or body.get("message") or ""
        except Exception:
            detail = (resp.text or "").strip()
        code = getattr(resp, "status_code", "?")
        return f"路由器返回 {code}" + (f"：{detail[:200]}" if detail else "")
    return f"{type(e).__name__}: {e}"[:240]


class PortForwardRequest(BaseModel):
    name: str = Field("", max_length=128)
    protocol: str = Field("tcp", pattern="^(tcp|udp)$")
    wan_port: str = Field(..., min_length=1, max_length=32, pattern=r"^[0-9,\-]+$")
    target_ip: str = Field(..., min_length=7, max_length=64)
    target_port: str = Field("", max_length=32, pattern=r"^[0-9,\-]*$")
    in_interface: str = Field("", max_length=64)
    comment: str = Field("", max_length=128)

    @field_validator("target_ip")
    @classmethod
    def validate_target_ip(cls, v: str) -> str:
        try:
            ip = ipaddress.ip_address(v.strip())
        except ValueError:
            raise ValueError("内网 IP 格式不正确")
        if not ip.is_private:
            raise ValueError("只允许转发到私网地址")
        return v.strip()


class PortForwardUpdate(BaseModel):
    name: str | None = Field(None, max_length=128)
    protocol: str | None = Field(None, pattern="^(tcp|udp)$")
    wan_port: str | None = Field(None, max_length=32, pattern=r"^[0-9,\-]+$")
    target_ip: str | None = Field(None, min_length=7, max_length=64)
    target_port: str | None = Field(None, max_length=32, pattern=r"^[0-9,\-]*$")
    in_interface: str | None = Field(None, max_length=64)
    comment: str | None = Field(None, max_length=128)
    disabled: bool | None = None

    @field_validator("target_ip")
    @classmethod
    def validate_target_ip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            ip = ipaddress.ip_address(v.strip())
        except ValueError:
            raise ValueError("内网 IP 格式不正确")
        if not ip.is_private:
            raise ValueError("只允许转发到私网地址")
        return v.strip()


@router.get("")
async def list_port_forwards(user: dict = Depends(get_current_user),
                             client=Depends(get_router_client)):
    try:
        rules = await client.list_port_forwards()
    except Exception as e:
        logger.exception("读取端口转发失败")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e))
    return [{"id": r.id, "name": r.comment, "protocol": r.protocol,
             "wan_port": r.dst_port, "target_ip": r.to_addresses,
             "target_port": r.to_ports, "in_interface": r.in_interface,
             "disabled": r.disabled} for r in rules]


@router.post("")
async def add_port_forward(body: PortForwardRequest,
                           user: dict = Depends(get_current_user),
                           _: None = Depends(require_writable),
                           client=Depends(get_router_client)):
    try:
        await client.add_port_forward(
            protocol=body.protocol, dst_port=body.wan_port,
            to_addresses=body.target_ip, to_ports=body.target_port,
            in_interface=body.in_interface,
            comment=body.comment or body.name)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except Exception as e:
        logger.exception("新增端口转发失败")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e))
    return {"ok": True}


@router.patch("/{rule_id}")
async def update_port_forward(rule_id: str, body: PortForwardUpdate,
                              user: dict = Depends(get_current_user),
                              _: None = Depends(require_writable),
                              client=Depends(get_router_client)):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "没有需要更新的字段")
    if "target_ip" in fields:
        fields["to_addresses"] = fields.pop("target_ip")
    if "target_port" in fields:
        fields["to_ports"] = fields.pop("target_port")
    try:
        await client.set_port_forward(rule_id, fields)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    except Exception as e:
        logger.exception("编辑端口转发失败")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e))
    return {"ok": True}


@router.delete("/{rule_id}")
async def delete_port_forward(rule_id: str,
                              user: dict = Depends(get_current_user),
                              _: None = Depends(require_writable),
                              client=Depends(get_router_client)):
    try:
        await client.remove_port_forward(rule_id)
    except Exception as e:
        logger.exception("删除端口转发失败")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _router_error(e))
    return {"ok": True}
