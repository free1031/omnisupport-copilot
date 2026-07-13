FROM python:3.11-slim

WORKDIR /workspace

# 安装系统依赖：仅保留git，psycopg2-binary无需pg_config编译库
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
    && rm -rf /var/lib/apt/lists/*

# ==========第一步：只拷贝依赖相关文件（缓存层，代码变更不触发重装）==========
COPY pyproject.toml README.md ./
# 拷贝两个服务的requirements到临时目录
COPY services/rag_api/requirements.txt /tmp/rag_api_requirements.txt
COPY services/tool_api/requirements.txt /tmp/tool_api_requirements.txt

# ==========第二步：安装所有依赖（主服务依赖 + pyproject.dev可选依赖）==========
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r /tmp/rag_api_requirements.txt \
    -r /tmp/tool_api_requirements.txt \
    -e ".[dev]"

# ==========第三步：所有源码目录延后拷贝（日常改代码只触发这一层重建）==========
COPY contracts ./contracts
COPY data ./data
COPY analytics ./analytics
COPY pipelines ./pipelines
COPY services ./services
COPY observability ./observability
COPY agent ./agent
COPY tools ./tools
COPY evals ./evals
COPY tests ./tests

CMD ["sh"]