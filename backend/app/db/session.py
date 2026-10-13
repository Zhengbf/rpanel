from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
import logging
from app.config import settings, DATA_DIR

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    from app.db.models import Base, User, AuditLog
    from sqlalchemy import text, select
    from app.security import hash_password

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if "sqlite" in settings.database_url:
            await conn.execute(text("PRAGMA journal_mode=WAL"))

    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(User).where(User.username == settings.admin_username))
        user = existing.scalar_one_or_none()
        if user is None:
            password = settings.admin_password.strip() or _generate_initial_password()
            session.add(User(username=settings.admin_username, password_hash=hash_password(password)))
            await session.commit()
        else:
            # 正常重启走这里：不是异常，用 INFO。忘记密码见 reset_admin.py。
            logging.getLogger(__name__).info(
                "管理员账号已存在，沿用原密码（忘记密码可用 reset_admin.py --password 重置）")


def _generate_initial_password() -> str:
    """首次启动生成随机管理员密码；只进日志，不落密码文件。"""
    import secrets
    import logging

    password = secrets.token_urlsafe(12)
    logger = logging.getLogger(__name__)
    logger.info("RPanel 首次启动：已创建管理员账号 %s", settings.admin_username)
    logger.info("首次登录用户名=%s 密码=%s（登录后请立即修改）",
                settings.admin_username, password)
    return password
