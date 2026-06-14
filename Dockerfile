# syntax=docker/dockerfile:1
# 统一 Dockerfile（合并原 Dockerfile 与 Dockerfile国际源版）
#
# 通过 build-arg MIRROR 选择镜像源：
#   MIRROR=cn   （默认）国内加速：apt 阿里云、Node npmmirror 二进制、pip 清华源
#   MIRROR=intl 国际源：apt 默认 debian、Node nodesource、pip 官方 PyPI
# 国际源构建示例： docker build --build-arg MIRROR=intl -t aiagents-stock .
ARG MIRROR=cn

# 使用国内可访问的 Python 基础镜像
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim

ARG MIRROR
ENV TZ=Asia/Shanghai
WORKDIR /app

# 按 MIRROR 选择 apt 源（cn=阿里云镜像，intl=保持默认 debian 源）
RUN if [ "$MIRROR" = "cn" ]; then \
        echo "deb https://mirrors.aliyun.com/debian/ bookworm main" > /etc/apt/sources.list && \
        echo "deb https://mirrors.aliyun.com/debian/ bookworm-updates main" >> /etc/apt/sources.list && \
        echo "deb https://mirrors.aliyun.com/debian-security bookworm-security main" >> /etc/apt/sources.list && \
        rm -rf /etc/apt/sources.list.d/* || true; \
    fi

# 安装基础依赖、中文字体（PDF 生成需要）、时区数据、libgomp1（lightgbm 运行时依赖 libgomp.so.1）
RUN apt-get update && apt-get install -y \
    curl \
    tar \
    xz-utils \
    gnupg \
    ca-certificates \
    fonts-noto-cjk \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    fontconfig \
    tzdata \
    libgomp1 \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && fc-cache -fv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 安装 Node.js 18（pywencai 需要）：cn 用 npmmirror 预编译二进制，intl 用 nodesource
RUN NODE_VERSION=18.20.4 && \
    if [ "$MIRROR" = "cn" ]; then \
        ARCH=$(dpkg --print-architecture) && \
        if [ "$ARCH" = "amd64" ]; then NODE_ARCH="x64"; \
        elif [ "$ARCH" = "arm64" ]; then NODE_ARCH="arm64"; \
        else NODE_ARCH="$ARCH"; fi && \
        curl -fsSL https://registry.npmmirror.com/-/binary/node/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.gz -o /tmp/node.tar.gz && \
        tar -xzf /tmp/node.tar.gz -C /usr/local --strip-components=1 && \
        rm /tmp/node.tar.gz && \
        ln -sf /usr/local/bin/node /usr/local/bin/nodejs && \
        npm config set registry https://registry.npmmirror.com/; \
    else \
        curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
        apt-get install -y nodejs && \
        apt-get clean && rm -rf /var/lib/apt/lists/*; \
    fi

# 验证 Node 安装
RUN node --version && npm --version

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖：cn 用清华源，intl 用官方 PyPI
RUN if [ "$MIRROR" = "cn" ]; then \
        pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple/ && \
        pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn; \
    fi && \
    pip install --no-cache-dir --default-timeout=1000 -r requirements.txt

# 复制项目文件
COPY . .

# 创建必要的目录
RUN mkdir -p /app/data && chmod 777 /app/data

# 暴露 Streamlit 端口（与 docker-compose.yml / run.py 一致）
EXPOSE 8503

# 健康检查
HEALTHCHECK CMD curl --fail http://localhost:8503/_stcore/health || exit 1

# 启动应用
CMD ["streamlit", "run", "app.py", "--server.port=8503", "--server.address=0.0.0.0"]
