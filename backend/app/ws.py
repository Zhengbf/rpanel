from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.security import decode_token
import asyncio

router = APIRouter()

# 连上之后等第一帧认证消息的时限（秒）
AUTH_TIMEOUT = 5.0
# 认证失败/超时的关闭码：前端看到它就不再重连
CLOSE_UNAUTHORIZED = 4401


class WsHub:
    def __init__(self):
        self._clients: dict[WebSocket, set[str]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, ws: WebSocket, topics: set[str]) -> None:
        async with self._lock:
            self._clients[ws] = topics

    async def unsubscribe(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.pop(ws, None)

    async def publish(self, topic: str, data: dict) -> None:
        msg = {"topic": topic, "data": data}
        dead = []
        async with self._lock:
            for ws, topics in self._clients.items():
                if topic in topics or "*" in topics:
                    try:
                        await ws.send_json(msg)
                    except Exception:
                        dead.append(ws)
            for ws in dead:
                self._clients.pop(ws, None)


hub = WsHub()


async def _close(ws: WebSocket, code: int) -> None:
    try:
        await ws.close(code=code)
    except Exception:
        pass


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    """先握手，再用第一帧消息认证。

    令牌不走查询串：URL 会被 uvicorn 的日志记下来，等于把可用令牌写进磁盘。
    未登录的页面连上来会在 AUTH_TIMEOUT 后被 4401 关掉，不产生 403。
    """
    await ws.accept()

    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=AUTH_TIMEOUT)
    except Exception:
        await _close(ws, CLOSE_UNAUTHORIZED)
        return

    token = first.get("token") if isinstance(first, dict) else None
    payload = decode_token(token) if isinstance(token, str) else None
    if payload is None or payload.get("type") != "access":
        await _close(ws, CLOSE_UNAUTHORIZED)
        return

    topics = set(first.get("topics") or [])
    await hub.subscribe(ws, topics)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await hub.unsubscribe(ws)
