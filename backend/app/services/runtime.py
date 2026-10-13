"""
运行时管理：采样器与路由器连接的生命周期。

为什么需要它：
采样器原本只在后端启动时创建一次，用户在向导里「绑定设备」之后并没有被启动，
导致绑定完总览一片空白、右上角显示连接中断。现在把生命周期集中到这里，
绑定/切换/删除设备后调用 restart() 即可。
"""
from __future__ import annotations

import asyncio
import logging

from app.services.sampler import Sampler, detect_tunnel_interfaces, detect_wan_interfaces

logger = logging.getLogger(__name__)


class Runtime:
    def __init__(self) -> None:
        self.sampler: Sampler | None = None
        self._lock = asyncio.Lock()

    async def restart(self) -> bool:
        """按当前默认设备（重新）启动采样。返回是否成功启动。"""
        async with self._lock:
            await self._stop_locked()
            from sqlalchemy import select
            from app.db.models import RouterDevice
            from app.db.session import AsyncSessionLocal
            from app.adapters.ros.factory import create_client_for_device
            from app.services.traffic import store as traffic_store

            try:
                async with AsyncSessionLocal() as db:
                    dev = (await db.execute(
                        select(RouterDevice).where(RouterDevice.is_default == True)  # noqa: E712
                    )).scalar_one_or_none()
                if dev is None:
                    # 没有绑定设备时不该留着上一台的曲线
                    traffic_store.bind_device(None)
                    logger.info("未绑定默认设备，采样器不启动")
                    return False
                # 换设备（或首次启动）时清掉内存曲线，避免两台路由器的数据混在一张图上
                if traffic_store.bind_device(dev.id):
                    logger.info("切换采样目标为设备 #%s（内存曲线已重置）", dev.id)
                client = await create_client_for_device(dev)
                sampler = Sampler(client)
                await sampler.start()
                self.sampler = sampler
                logger.info("采样器已启动：设备 %s (%s)", dev.name, dev.host)
                return True
            except Exception:
                logger.warning("启动采样器失败（面板其余功能仍可用）", exc_info=True)
                return False

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        if self.sampler is None:
            return
        try:
            await self.sampler.stop()
            await self.sampler.client.close()
        except Exception:
            logger.debug("停止采样器时出错", exc_info=True)
        self.sampler = None

    @property
    def running(self) -> bool:
        return self.sampler is not None and self.sampler.running

    def status(self) -> dict:
        s = self.sampler
        return {
            "sampler_running": self.running,
            "router_connected": bool(s.connected) if s else False,
            "last_sample_ts": s.last_sample_ts if s else 0.0,
            "wan_interfaces": s.wan_ifaces if s else [],
            "total_interfaces": s.total_ifaces if s else [],
        }


runtime = Runtime()
