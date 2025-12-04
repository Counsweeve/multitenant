# 基础阶段：设置Python环境和uv工具
FROM python:3.12-slim-bookworm AS base

WORKDIR /app/api

# 安装uv工具
ENV UV_VERSION=0.8.9
ENV UV_HTTP_TIMEOUT=120

RUN pip install --upgrade pip -i https://artifact.srdcloud.cn/artifactory/api/pypi/public-pypi-virtual/simple

RUN pip install --no-cache-dir \
    -i https://artifact.srdcloud.cn/artifactory/api/pypi/public-pypi-virtual/simple \
    --trusted-host artifact.srdcloud.cn \
    uv==${UV_VERSION}

# 依赖安装阶段：安装系统包和Python依赖
FROM base AS packages

# 一次性配置Debian镜像源并安装编译依赖
RUN sed -i "s|http://deb.debian.org|https://artifact.srdcloud.cn/artifactory/huawei-release-debian-remote|g" /etc/apt/sources.list.d/debian.sources && \
    sed -i "s|http://security.debian.org|https://artifact.srdcloud.cn/artifactory/huawei-release-debian-remote|g" /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        apt-transport-https ca-certificates \
        gcc g++ libc-dev libffi-dev libgmp-dev libmpfr-dev libmpc-dev && \
    rm -rf /var/lib/apt/lists/*

# 同步Python依赖（使用uv）
COPY pyproject.toml uv.lock ./
RUN UV_HTTP_TIMEOUT=600 uv sync --no-dev -i https://artifact.srdcloud.cn/artifactory/api/pypi/public-pypi-virtual/simple --trusted-host artifact.srdcloud.cn

# 生产阶段：构建最终镜像
FROM base AS production

# 环境变量（硬编码部分可通过研发云流水线动态覆盖）
ENV FLASK_APP=app.py
ENV EDITION=SELF_HOSTED
ENV DEPLOY_ENV=PRODUCTION
ENV CONSOLE_API_URL=http://127.0.0.1:5001
ENV CONSOLE_WEB_URL=http://127.0.0.1:3000
ENV SERVICE_API_URL=http://127.0.0.1:5001
ENV APP_WEB_URL=http://127.0.0.1:3000
ENV TZ=UTC
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV PYTHONIOENCODING=utf-8
EXPOSE 5001

WORKDIR /app/api

# 配置Debian源并安装运行时依赖
RUN sed -i "s|http://deb.debian.org|https://artifact.srdcloud.cn/artifactory/huawei-release-debian-remote|g" /etc/apt/sources.list.d/debian.sources && \
    sed -i "s|http://security.debian.org|https://artifact.srdcloud.cn/artifactory/huawei-release-debian-remote|g" /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        curl nodejs libgmp-dev libmpfr-dev libmpc-dev \
        expat libldap-2.5-0 perl libsqlite3-0 zlib1g \
        fonts-noto-cjk media-types libmagic1 unzip && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# 从packages阶段复制Python虚拟环境
ENV VIRTUAL_ENV=/app/api/.venv
COPY --from=packages ${VIRTUAL_ENV} ${VIRTUAL_ENV}
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

# 安装Python包（合并setuptools、wheel和nltk到单层）
RUN pip install --no-cache-dir "setuptools>=40.8.0" wheel nltk \
    -i https://artifact.srdcloud.cn/artifactory/api/pypi/public-pypi-virtual/simple --trusted-host artifact.srdcloud.cn

# 解决方案：预下载NLTK数据到镜像中，避免在线下载失败
# 假设项目根目录已提前下载好nltk_data目录（包含punkt和averaged_perceptron_tagger）
# 复制并解压NLTK数据包

RUN mkdir -p /usr/local/nltk_data/taggers/
RUN mkdir -p /usr/local/nltk_data/tokenizers/

COPY ./nltk_data/taggers/averaged_perceptron_tagger.zip /usr/local/nltk_data/taggers/
COPY ./nltk_data/tokenizers/punkt.zip /usr/local/nltk_data/tokenizers/


RUN unzip -q /usr/local/nltk_data/taggers/averaged_perceptron_tagger.zip -d /usr/local/nltk_data/taggers/ && \
    unzip -q /usr/local/nltk_data/tokenizers/punkt.zip -d /usr/local/nltk_data/tokenizers/ && \
    rm /usr/local/nltk_data/taggers/averaged_perceptron_tagger.zip /usr/local/nltk_data/tokenizers/punkt.zip

# 配置tiktoken（使用预置的资源文件）

RUN mkdir -p /tiktoken_cache
ENV TIKTOKEN_CACHE_DIR=/tiktoken_cache
COPY ./tiktoken_cache/vocab.bpe /tiktoken_cache/vocab.bpe

RUN pip install --no-cache-dir tiktoken \
    -i https://artifact.srdcloud.cn/artifactory/api/pypi/public-pypi-virtual/simple --trusted-host artifact.srdcloud.cn
	
# 复制源代码和入口脚本
COPY . /app/api/
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 注入提交SHA（研发云流水线自动设置）
ARG COMMIT_SHA
ENV COMMIT_SHA=${COMMIT_SHA}

ENTRYPOINT ["/bin/bash", "/entrypoint.sh"]