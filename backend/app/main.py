from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.db.session import init_db, AsyncSessionLocal
from app.api import (auth, wizard, devices, dashboard, sessions, firewall, alerts,
                     network, port_forward, backup)
from app import ws as ws_api
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.api.auth import limiter
from app.api.deps import get_current_user, require_writable

import logging
import logging.handlers
import sys
from pathlib import Path


def _setup_logging() -> None:
    """日志同时进 stdout（docker logs 可见）和滚动文件（/data/logs 持久化）。

    只留对排查有用的信息：面板自身的启动/绑定/采样/失败事件。
    httpx 每个成功的 REST 请求、uvicorn 逐条访问日志都属于噪音，关掉。
    """
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    chatter_filter = _DropWebSocketChatter()
    rename_filter = _RenameUvicornLogger()

    handlers: list[logging.Handler] = []

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    stream.addFilter(rename_filter)
    stream.addFilter(chatter_filter)
    handlers.append(stream)

    try:
        log_path = Path(settings.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        file_handler.setFormatter(fmt)
        file_handler.addFilter(rename_filter)
        file_handler.addFilter(chatter_filter)
        handlers.append(file_handler)
    except Exception:
        # 文件写不了也必须能启动：stdout 仍然可用
        pass

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in handlers:
        root.addHandler(handler)

    # uvicorn 自己的 logger 走同一套 handler，避免它另开一路写到别处
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        for existing in list(lg.handlers):
            lg.removeHandler(existing)
        for handler in handlers:
            lg.addHandler(handler)
        lg.propagate = False

    # 降噪：第三方库只在出错时说话
    for name in ("httpx", "httpcore", "urllib3", "asyncio", "websockets", "watchfiles"):
        logging.getLogger(name).setLevel(logging.WARNING)
    # 逐条访问日志（前端 1~5 秒轮询一次，量很大）不写
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class _DropWebSocketChatter(logging.Filter):
    """uvicorn 每接一个 WebSocket 都会补一行 "connection open/closed"。

    它和前面带 IP 的 "[accepted]" 行完全重复，只保留后者。
    """

    _noise = {"connection open", "connection closed"}

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if record.name in ("uvicorn", "uvicorn.error") and record.getMessage() in self._noise:
            return False
        return True


class _RenameUvicornLogger(logging.Filter):
    """uvicorn 把它的通用 logger 命名为 "uvicorn.error"。

    结果正常启动的那几行 INFO 也顶着 "error" 字样，看着像出错。这里只改显示名，
    不动级别也不动内容；真正的异常该是 ERROR 还是 ERROR。
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if record.name == "uvicorn.error":
            record.name = "uvicorn"
        return True


_setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    app.state.readonly = settings.readonly_mode

    # 采样器生命周全交给 runtime：绑定/切换设备后由向导接口触发重启
    from app.services.runtime import runtime
    from app.services.firewall import FirewallService
    from app.services.sampler import detect_wan_interfaces

    started = await runtime.restart()
    if started and runtime.sampler is not None:
        try:
            wan = await detect_wan_interfaces(runtime.sampler.client) or runtime.sampler.wan_ifaces
            async with AsyncSessionLocal() as db:
                await FirewallService(runtime.sampler.client, wan).reconcile(db)
        except Exception:
            pass

    yield
    await runtime.stop()


app = FastAPI(title="RouterPanel", version="0.2.0", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

for r in (auth.router, wizard.router, devices.router, dashboard.router,
          sessions.router, firewall.router, alerts.router, network.router,
          port_forward.router, backup.router, ws_api.router):
    app.include_router(r)


@app.get("/api/system/status")
async def system_status(user: dict = Depends(get_current_user)):
    """给前端顶栏用：采样器/路由器连接状态，避免只能靠 WebSocket 猜测。"""
    from app.services.runtime import runtime
    from sqlalchemy import select
    from app.db.models import RouterDevice

    async with AsyncSessionLocal() as db:
        dev = (await db.execute(
            select(RouterDevice).where(RouterDevice.is_default == True)  # noqa: E712
        )).scalar_one_or_none()

    st = runtime.status()
    bound = dev is not None
    if not bound:
        state = "unbound"          # 尚未绑定设备
    elif not st["sampler_running"]:
        state = "stopped"          # 绑定了但采样器没起来
    elif not st["router_connected"]:
        state = "disconnected"     # 采样器在跑但路由器不可达
    else:
        state = "ok"

    return {
        "state": state,
        "router_bound": bound,
        "device_name": dev.name if dev else None,
        "device_host": dev.host if dev else None,
        **st,
    }


@app.get("/api/health")
async def health():
    return {"status": "ok", "readonly": app.state.readonly}


# ---- 前端静态文件 + SPA fallback ----
from pathlib import Path
STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    if full_path.startswith(("api/", "ws")):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    file = STATIC_DIR / full_path
    if file.is_file():
        return FileResponse(file)
    # 带扩展名的资源缺失时返回 404，不要回 index.html
    # （否则前端引用的图片/字体缺失会被静默当成 HTML，很难排查）
    if "." in full_path.rsplit("/", 1)[-1]:
        return JSONResponse(status_code=404, content={"detail": "Asset not found"})
    return FileResponse(STATIC_DIR / "index.html")


