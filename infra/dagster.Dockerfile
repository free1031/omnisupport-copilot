FROM python:3.11-slim

WORKDIR /workspace

# 补充 gcc 编译依赖 + 保留 git，清理缓存
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# ------------ 第一步：仅拷贝【依赖文件】(利用Docker缓存) ------------
COPY pyproject.toml README.md ./
COPY services/rag_api/requirements.txt /tmp/rag_api_requirements.txt
COPY services/tool_api/requirements.txt /tmp/tool_api_requirements.txt

# 升级 pip，避免版本兼容问题
RUN pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple

# ------------ 第二步：安装所有依赖（增加清华源，解决下载超时） ------------
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r /tmp/rag_api_requirements.txt \
    -r /tmp/tool_api_requirements.txt \
    -e ".[dev]"

# ------------ 第三步：最后拷贝【业务源码】(代码变更不重跑依赖层) ------------
COPY contracts ./contracts
COPY data ./data
COPY analytics ./analytics
COPY pipelines ./pipelines
COPY services ./services

# 创建 Dagster 运行目录
RUN mkdir -p /opt/dagster/app /opt/dagster/dagster_home

# 切换到 Dagster 工作目录
WORKDIR /opt/dagster/app

# 原有启动命令保持不变
CMD ["dagster", "dev", "-h", "0.0.0.0", "-p", "3000", "-m", "pipelines.definitions"]