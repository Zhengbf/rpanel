from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, Text
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime, timezone


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """统一使用无时区 UTC，避免与 SQLite 读回值比较时 naive/aware 冲突。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=utcnow)
    failed_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)


class RouterDevice(Base):
    __tablename__ = "router_devices"
    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    host = Column(String(256), nullable=False)
    port = Column(Integer, nullable=False, default=443)
    username = Column(String(128), nullable=False)
    encrypted_password = Column(Text, nullable=False)
    auth_method = Column(String(8), nullable=False, default="rest")
    verify_tls = Column(Boolean, default=False)
    timeout = Column(Float, default=10.0)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    username = Column(String(64), nullable=True)
    action = Column(String(64), nullable=False, index=True)
    target = Column(String(256), nullable=True)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, index=True)


class DeviceNote(Base):
    __tablename__ = "device_notes"
    # 备注跟着"哪台路由器"走：同一台设备在两台路由器上可以有不同的备注
    device_id = Column(Integer, primary_key=True)
    ip = Column(String(64), primary_key=True)
    mac = Column(String(32), nullable=True, index=True)
    note = Column(Text, default="")
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class TrafficHistory(Base):
    __tablename__ = "traffic_history"
    id = Column(Integer, primary_key=True)
    # 属于哪台路由器。没绑定设备时为 NULL；换绑设备后统计不会串台。
    device_id = Column(Integer, nullable=True, index=True)
    ts = Column(DateTime, nullable=False, index=True)
    dimension = Column(String(16), nullable=False, index=True)
    key = Column(String(128), nullable=False, index=True)
    rx_bytes = Column(Integer, default=0)
    tx_bytes = Column(Integer, default=0)


class BlockedIp(Base):
    __tablename__ = "blocked_ips"
    # 封禁是路由器上的状态，必须按设备分开存，
    # 否则换绑后旧路由器的封禁列表会被对账下发到新路由器上。
    device_id = Column(Integer, primary_key=True)
    ip = Column(String(64), primary_key=True)
    reason = Column(Text, default="")
    blocked_by = Column(String(64), nullable=True)
    blocked_at = Column(DateTime, default=utcnow)


class KnownDevice(Base):
    __tablename__ = "known_devices"
    # 新设备告警也按设备分开：另一台路由器上的 MAC 不该让这台静音
    device_id = Column(Integer, primary_key=True)
    mac = Column(String(32), primary_key=True)
    first_ip = Column(String(64), nullable=True)
    hostname = Column(String(128), nullable=True)
    first_seen = Column(DateTime, default=utcnow, index=True)
    alerted = Column(Boolean, default=False)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key = Column(String(128), primary_key=True)
    value = Column(Text, nullable=True)

