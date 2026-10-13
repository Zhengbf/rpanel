"""
配置：力求"用户只需要填数据目录和端口"。

- DATA_DIR：数据目录（Docker 里是 /data 卷）。数据库、密钥都放这里。
- SECRET_KEY：优先取环境变量；没有时自动生成并保存到 DATA_DIR/secret.key。
  必须持久化：它同时用于数据库凭据加密和 JWT 签名，丢失后已保存的路由器密码无法解密。
- DATABASE_URL：默认落在 DATA_DIR 下；用绝对路径四斜杠写法保证与工作目录无关。
- ADMIN_PASSWORD：留空时首次启动自动生成随机密码，只写进 DATA_DIR/logs 的日志（不再落任何密码文件）。
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from pydantic_settings import BaseSettings


def _resolve_data_dir() -> Path:
    raw = os.environ.get("DATA_DIR", "").strip()
    path = Path(raw) if raw else Path("./data")
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


DATA_DIR = _resolve_data_dir()
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _resolve_secret_key() -> str:
    """环境变量优先；否则读取/生成 DATA_DIR/secret.key（600 权限）。"""
    env_key = os.environ.get("SECRET_KEY", "").strip()
    # 只有空值和 "change-me" 视为"未设置"。
    # 注意：不要把用户显式填写的其它值（含 .env.example 里的示例串）当作未设置，
    # 否则会自动换新密钥，导致已存的路由器凭据无法解密。
    if env_key and env_key != "change-me":
        return env_key

    key_file = DATA_DIR / "secret.key"
    if key_file.exists():
        saved = key_file.read_text(encoding="utf-8").strip()
        if saved:
            return saved

    generated = secrets.token_urlsafe(48)
    key_file.write_text(generated, encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass  # Windows 上忽略
    return generated


class Settings(BaseSettings):
    secret_key: str = ""
    database_url: str = ""
    data_dir: str = str(DATA_DIR)
    admin_username: str = "admin"
    admin_password: str = ""
    sample_interval: float = 1.0
    history_retention_days: int = 7
    readonly_mode: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    max_login_attempts: int = 5
    lockout_minutes: int = 15
    log_file: str = str(LOG_DIR / "routerpanel.log")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "case_sensitive": False}

    @property
    def resolved_database_url(self) -> str:
        if self.database_url.strip():
            return self.database_url.strip()
        # 四斜杠 = 绝对路径，避免受启动工作目录影响
        return f"sqlite+aiosqlite:///{DATA_DIR / 'routerpanel.db'}"


settings = Settings()

# 环境变量没给 SECRET_KEY 时，用持久化密钥覆盖（放在 Settings 实例上供全局使用）
if not settings.secret_key.strip() or settings.secret_key == "change-me":
    settings.secret_key = _resolve_secret_key()

if not settings.database_url.strip():
    settings.database_url = settings.resolved_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
