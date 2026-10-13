from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
import logging
from app.config import settings, DATA_DIR

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _migrate_sqlite(conn) -> None:
    """轻量迁移：给老库补上后加的列。

    项目没有引入 Alembic，SQLite 的 ADD COLUMN 又足够便宜，
    所以在这里显式补齐，避免老用户升级后直接报 "no such column"。
    """
    logger = logging.getLogger(__name__)
    rows = (await conn.exec_driver_sql("PRAGMA table_info(traffic_history)")).fetchall()
    columns = {row[1] for row in rows}
    devices = (await conn.exec_driver_sql("SELECT id FROM router_devices")).fetchall()
    only_device = devices[0][0] if len(devices) == 1 else None

    if "device_id" not in columns:
        await conn.exec_driver_sql("ALTER TABLE traffic_history ADD COLUMN device_id INTEGER")
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_traffic_history_device_id ON traffic_history (device_id)")

        # 老数据没有设备标记。库里只有一台设备时，这些数据必然是它的，直接归属过去；
        # 有多台（说明以前混过）就留空，宁可不显示，也不要把两台路由器的流量加在一起。
        if only_device is not None:
            await conn.exec_driver_sql("UPDATE traffic_history SET device_id = ?", (only_device,))
            logger.info("流量历史已归属到唯一设备 #%s", only_device)
        elif devices:
            logger.info("存在 %s 台设备，未标记归属的历史流量行不再参与统计", len(devices))

    # 以下三张表的主键从「ip/mac」变成「device_id + ip/mac」，
    # SQLite 不能改主键，只能重建表。
    rebuilds = [
        ("blocked_ips", "ip", "VARCHAR(64) NOT NULL",
         ["reason", "blocked_by", "blocked_at"],
         "reason TEXT, blocked_by VARCHAR(64), blocked_at DATETIME"),
        ("device_notes", "ip", "VARCHAR(64) NOT NULL",
         ["mac", "note", "updated_at"],
         "mac VARCHAR(32), note TEXT, updated_at DATETIME"),
        ("known_devices", "mac", "VARCHAR(32) NOT NULL",
         ["first_ip", "hostname", "first_seen", "alerted"],
         "first_ip VARCHAR(64), hostname VARCHAR(128), first_seen DATETIME, alerted BOOLEAN"),
    ]
    for table, key_col, key_type, move_cols, rest in rebuilds:
        info = (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()
        if not info:
            continue  # 表还不存在（全新库由 create_all 建好），跳过
        if "device_id" in {row[1] for row in info}:
            continue

        await conn.exec_driver_sql(
            f"CREATE TABLE {table}_new (device_id INTEGER NOT NULL, "
            f"{key_col} {key_type}, {rest}, PRIMARY KEY (device_id, {key_col}))")
        # 只有一台设备时把旧记录交给它；多台时这些记录无法判断归属，
        # 直接不带过去（封禁列表下次对账会从路由器重新读回来）。
        if only_device is not None:
            cols = ", ".join([key_col] + move_cols)
            await conn.exec_driver_sql(
                f"INSERT INTO {table}_new (device_id, {cols}) "
                f"SELECT ?, {cols} FROM {table}",
                (only_device,))
        await conn.exec_driver_sql(f"DROP TABLE {table}")
        await conn.exec_driver_sql(f"ALTER TABLE {table}_new RENAME TO {table}")
        logger.info("%s 已重建为按设备隔离（旧记录%s）", table,
                    "归属到唯一设备" if only_device is not None else "已丢弃，无法判断归属")

    # 重建后补回索引
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_device_notes_mac ON device_notes (mac)")
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_known_devices_first_seen ON known_devices (first_seen)")


async def init_db() -> None:
    from app.db.models import Base, User, AuditLog
    from sqlalchemy import text, select
    from app.security import hash_password

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if "sqlite" in settings.database_url:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await _migrate_sqlite(conn)

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
