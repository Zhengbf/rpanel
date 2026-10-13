#!/bin/sh
# RPanel 容器入口。
#
# 为什么需要它：用户只改 docker-compose.yaml 里的端口和数据目录，数据目录很可能
# 还不存在。Docker 会以 root 创建这个 bind mount 目录，而应用本体以非 root
# （uid 1000）运行，直接启动会因无法写入而反复重启。
#
# 这里只在启动瞬间做两件事：
#   1) 把 /data 的归属修正给 uid/gid 1000（失败也不阻塞，例如 Windows 挂载点）；
#   2) 立刻降权到 uid 1000，应用本体始终以非 root 身份运行。
set -e

APP_UID=1000
APP_GID=1000

if [ "$(id -u)" = "0" ]; then
    mkdir -p /data/logs 2>/dev/null || true
    chown -R "$APP_UID:$APP_GID" /data 2>/dev/null || true

    exec setpriv \
        --reuid="$APP_UID" \
        --regid="$APP_GID" \
        --clear-groups \
        env HOME=/home/panel "$@"
fi

exec "$@"
