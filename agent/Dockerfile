# melos-composer-agent: Claude Agent SDK (Python) + the Melos tools, on port 8800 (internal network only).
# The claude-agent-sdk manylinux wheel bundles the native Claude Code CLI binary, so no Node or npm is needed.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HOME=/state/home COMPOSER_AGENT_STATE=/state TMPDIR=/tmp
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 1000 --create-home --home-dir /home/agent agent && mkdir -p /state && chown agent:agent /state
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt \
 && python -c "import claude_agent_sdk, pathlib; p = pathlib.Path(claude_agent_sdk.__file__).parent / '_bundled' / 'claude'; assert p.exists(), p"
COPY composer_agent ./composer_agent
USER agent
EXPOSE 8800
CMD ["python", "-m", "composer_agent.app"]
