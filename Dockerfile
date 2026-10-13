# RPanel 镜像：多阶段构建（前端 → 后端运行时）
# - 前端在构建阶段编译，镜像里只有 dist，不含源码与 node_modules
# - 运行时非 root；所有可写数据落在 /data 卷（数据库、密钥、日志、首次密码）
# - 用户只需决定「数据目录」和「对外端口」，见 docker-compose.yml

# ---------- 阶段 1：构建前端 ----------
FROM node:20.18-alpine3.20 AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 阶段 2：后端运行时 ----------
FROM python:3.11.10-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

# 依赖单独一层，改业务代码不必重装依赖
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --no-compile -r requirements.txt \
    && find /usr/local/lib/python3.11 -type d -name "__pycache__" -prune -exec rm -rf {} +

# 后端代码 + 前端产物
# 静态目录必须是 app/static（代码用 Path(__file__).parent / "static" 定位）
COPY backend/app/ ./app/
COPY backend/reset_admin.py ./
COPY --from=frontend /fe/dist ./app/static

# 入口脚本：bind mount 的数据目录可能属于 root，启动瞬间修正归属后立刻降权
COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh

# 运行账号固定 uid/gid=1000：应用本体始终以非 root 运行，便于宿主机目录对齐权限
RUN groupadd --gid 1000 panel \
    && useradd --uid 1000 --gid 1000 --create-home --shell /usr/sbin/nologin panel \
    && mkdir -p /data/logs \
    && chown -R 1000:1000 /app /data

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
