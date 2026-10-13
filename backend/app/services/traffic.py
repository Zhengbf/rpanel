from __future__ import annotations
import asyncio
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from app.db.session import AsyncSessionLocal
from app.db.models import TrafficHistory
from app.config import settings


class RingSeries:
    def __init__(self, maxlen: int = 28800):
        self.data: deque[tuple[float, float, float]] = deque(maxlen=maxlen)

    def push(self, ts: float, rx: float, tx: float) -> None:
        self.data.append((ts, rx, tx))

    def last(self) -> tuple[float, float, float] | None:
        return self.data[-1] if self.data else None

    def window(self, seconds: float) -> list[tuple[float, float, float]]:
        cutoff = time.time() - seconds
        return [d for d in self.data if d[0] >= cutoff]


class TrafficStore:
    def __init__(self):
        self._series: dict[str, RingSeries] = {}
        self._lock = asyncio.Lock()
        # 当前采样的是哪台设备。换设备时清空内存曲线，
        # 否则上一台路由器的接口/IP 会继续留在图上。
        self.device_id: int | None = None

    def bind_device(self, device_id: int | None) -> bool:
        """切到另一台路由器时丢弃内存里的历史曲线。返回是否发生了切换。"""
        if device_id == self.device_id:
            return False
        self._series.clear()
        self.device_id = device_id
        return True

    def series(self, dimension: str, key: str) -> RingSeries:
        k = f"{dimension}:{key}"
        if k not in self._series:
            self._series[k] = RingSeries()
        return self._series[k]

    def push_sample(self, dimension: str, key: str, rx_rate: float, tx_rate: float) -> None:
        self.series(dimension, key).push(time.time(), rx_rate, tx_rate)

    def history(self, dimension: str, key: str, window_seconds: float,
                max_points: int = 90) -> list[dict]:
        """按窗口取历史，并聚合到最多 max_points 个点。

        采样间隔是 1 秒，5 分钟就是 300 个点、24 小时更是 8 万多个点。
        直接把原始点丢给图表会糊成一片实心色块，看不出趋势，也会让
        前端传输量白白放大。这里按等长时间桶做平均，既保留走势又
        保证图上是点不是墙。
        """
        data = self.series(dimension, key).window(window_seconds)
        if not data:
            return []
        if len(data) <= max_points:
            return [{"ts": d[0], "rx": d[1], "tx": d[2]} for d in data]

        step = len(data) / max_points
        out: list[dict] = []
        for i in range(max_points):
            start = int(i * step)
            end = int((i + 1) * step)
            chunk = data[start:end] or [data[min(start, len(data) - 1)]]
            out.append({
                # 用桶内最后一个时间戳，图线末端才会贴住"现在"
                "ts": chunk[-1][0],
                "rx": sum(c[1] for c in chunk) / len(chunk),
                "tx": sum(c[2] for c in chunk) / len(chunk),
            })
        return out

    async def flush_minutely(self) -> None:
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0, tzinfo=None)
        rows = []
        for k, series in self._series.items():
            dimension, _, key = k.partition(":")
            win = series.window(60.0)
            if not win:
                continue
            rx = sum(w[1] for w in win) / len(win)
            tx = sum(w[2] for w in win) / len(win)
            rows.append(TrafficHistory(ts=now, dimension=dimension, key=key,
                                       device_id=self.device_id,
                                       rx_bytes=int(rx * 60), tx_bytes=int(tx * 60)))
        if not rows:
            return
        async with AsyncSessionLocal() as db:
            db.add_all(rows)
            await db.commit()

    async def cleanup(self) -> None:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=settings.history_retention_days)
        from sqlalchemy import delete
        async with AsyncSessionLocal() as db:
            await db.execute(delete(TrafficHistory).where(TrafficHistory.ts < cutoff))
            await db.commit()


store = TrafficStore()

