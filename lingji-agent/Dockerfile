# lingji-agent — Sprint 6 / 三期 3.3 本地 compose 镜像
FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src ./src
COPY config/default_config.yaml.example ./config/default_config.yaml

RUN pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1 \
    LINGJI_GATEWAY_HOST=gateway \
    LINGJI_GATEWAY_PORT=8765 \
    LINGJI_MEMORY_ENABLED=true \
    LINGJI_MEMORY_DB_PATH=/data/lingji/memory_db

RUN mkdir -p /data/lingji
VOLUME ["/data/lingji"]

# DockerSandbox：挂载宿主机 docker.sock（compose 中配置）
CMD ["python", "-m", "lingji_agent.main"]
