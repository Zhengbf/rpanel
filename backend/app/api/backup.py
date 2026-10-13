"""配置备份：把 RouterOS 的 /export 结果直接交给浏览器下载。

为什么走 SSH 而不是 REST：
    RouterOS 的 REST 接口不会把 /export 的命令输出放进响应体
    （POST /rest/export 恒返回空数组），也没有下载文件内容的接口
    （GET /rest/file/<name> 只回元数据）。所以「不落文件、直接拿文本」
    这条路只能在 SSH 下走：/export 会打到标准输出，我们原样收下。

设计取舍：
- 用 RSC（文本）而不是二进制 .backup：文本可读、可 diff、跨机型版本更稳。
- 路由器上不落文件，全程只在内存里过一手。
- 默认导出打码后的配置；勾选敏感模式才会带上密码等字段（需要
  RouterOS 用户具备 sensitive 策略）。
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select

from app.api.deps import get_current_user
from app.adapters.ros.ssh_client import SshRouterOsClient
from app.db.models import RouterDevice
from app.db.session import AsyncSessionLocal
from app.security import decrypt_secret

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/backup", tags=["backup"])


async def _default_device() -> RouterDevice:
    async with AsyncSessionLocal() as db:
        dev = (await db.execute(
            select(RouterDevice).where(RouterDevice.is_default == True)  # noqa: E712
        )).scalar_one_or_none()
    if dev is None:
        raise HTTPException(status.HTTP_428_PRECONDITION_REQUIRED,
                            "尚未绑定路由器设备，请先完成向导")
    return dev


@router.get("/export")
async def export_config(
    ssh_port: int = Query(22, ge=1, le=65535, description="路由器 SSH 端口"),
    sensitive: bool = Query(False, description="是否包含密码等敏感字段"),
    user: dict = Depends(get_current_user),
):
    dev = await _default_device()

    # 复用面板里已保存的凭据，用户不需要重新输入
    client = SshRouterOsClient(
        host=dev.host,
        port=ssh_port,
        username=dev.username,
        password=decrypt_secret(dev.encrypted_password),
        timeout=dev.timeout,
    )
    try:
        text = await client.export_config(sensitive=sensitive)
    except Exception as e:
        logger.exception("导出配置失败")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, _explain(e, ssh_port))
    finally:
        try:
            await client.close()
        except Exception:
            pass

    if not text or not text.strip():
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "路由器返回了空配置")

    filename = f"ros_{datetime.now().strftime('%Y%m%d_%H%M%S')}.rsc"
    return Response(
        content=text.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # 配置里有网络拓扑等信息，别让浏览器或中间层缓存
            "Cache-Control": "no-store",
        },
    )


def _explain(e: Exception, ssh_port: int) -> str:
    """把 SSH 侧的异常翻译成能照着做的提示。"""
    name = type(e).__name__
    text = str(e)
    if "PermissionDenied" in name or "auth" in text.lower():
        return (f"SSH 认证失败：请确认路由器已启用 SSH，且面板用户在 "
                f"RouterOS 里有 ssh 策略（/user group set <组> policy=...,ssh）")
    if "TimeoutError" in name or "TimedOut" in name:
        return f"连接路由器 {ssh_port} 端口超时：请确认已启用 /ip service enable ssh"
    if "Disconnect" in name or "OSError" in name:
        return f"无法通过 SSH 连接路由器（端口 {ssh_port}）：请在路由器执行 /ip service enable ssh"
    if "not enough permissions" in text:
        return "路由器拒绝了导出：面板用户缺少所需策略（导出需要 ssh，敏感模式还需要 sensitive）"
    return f"导出失败：{name}: {text}"[:240]
