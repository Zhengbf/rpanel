#!/usr/bin/env python
"""面板账号自救工具：解锁 / 重置密码。

用法（在 backend 目录下执行）：
    python reset_admin.py --unlock                  # 只解除锁定，密码不变
    python reset_admin.py --password 新密码          # 重置密码并解锁
    python reset_admin.py --user admin --password x  # 指定用户名

不需要启动面板服务，直接读写数据库。
"""
from __future__ import annotations
import argparse
import sqlite3
import sys
from pathlib import Path


def db_path() -> Path:
    """与 app.config 保持一致地解析数据库位置（支持绝对路径，Docker 卷里也适用）。

    解析顺序：DATABASE_URL 环境变量 > app.config.settings > 回退到脚本同目录。
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from sqlalchemy.engine.url import make_url
        from app.config import settings

        url = make_url(settings.database_url)
        if url.database:
            candidate = Path(url.database)
            if not candidate.is_absolute():
                candidate = Path(__file__).resolve().parent / candidate
            return candidate
    except Exception:
        pass
    return Path(__file__).resolve().parent / "routerpanel.db"


def main() -> int:
    parser = argparse.ArgumentParser(description="RouterPanel 账号解锁/改密")
    parser.add_argument("--user", default="admin", help="用户名（默认 admin）")
    parser.add_argument("--password", help="设置新密码；不填则只解锁")
    parser.add_argument("--unlock", action="store_true", help="只解除锁定")
    parser.add_argument("--show-initial", action="store_true",
                        help="打印首次启动自动生成的初始密码文件内容与路径")
    args = parser.parse_args()

    from app.config import DATA_DIR
    log = DATA_DIR / "logs" / "routerpanel.log"
    if args.show_initial:
        if log.exists():
            print("初始密码只记录在系统日志中：")
            print(f'grep "首次登录" {log}')
        else:
            print(f"没有找到日志文件：{log}")
        return 0

    path = db_path()
    if not path.exists():
        print(f"找不到数据库：{path}")
        return 1

    if not args.password and not args.unlock:
        print("用法：")
        print("  python reset_admin.py --show-initial        # 查看首次启动的初始密码")
        print("  python reset_admin.py --unlock              # 只解除登录锁定")
        print("  python reset_admin.py --password 新密码      # 重置密码")
        print()
        print(f"数据目录：{DATA_DIR}")
        print(f"数据库：  {path}")
        print(f"初始密码：见 {log} 中的“首次登录”记录")
        return 0

    conn = sqlite3.connect(path)
    try:
        row = conn.execute(
            "SELECT id, failed_attempts, locked_until FROM users WHERE username = ?",
            (args.user,)).fetchone()
        if row is None:
            names = [r[0] for r in conn.execute("SELECT username FROM users").fetchall()]
            print(f"用户 {args.user!r} 不存在。现有用户：{names}")
            return 1

        if args.password:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from app.security import hash_password
            conn.execute(
                "UPDATE users SET password_hash = ?, failed_attempts = 0, locked_until = NULL "
                "WHERE username = ?", (hash_password(args.password), args.user))
            print(f"已重置 {args.user} 的密码并解除锁定")
        else:
            conn.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE username = ?",
                (args.user,))
            print(f"已解除 {args.user} 的锁定（密码未改动）")

        conn.commit()
        state = conn.execute(
            "SELECT failed_attempts, locked_until FROM users WHERE username = ?",
            (args.user,)).fetchone()
        print(f"当前状态：失败次数={state[0]}，锁定至={state[1]}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
