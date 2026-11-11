# agent-runtime — the program inside an agent-sandbox Job (scripts/agentrunner/CONTRACT.md §6).
# Build context is the repo root: docker build -f scripts/agentruntime/Dockerfile .
# Stdlib-only Python: no pip install. Runs as uid 10001 on a read-only root filesystem
# (HOME=/work/home, TMPDIR=/work/tmp come from the Job's emptyDir).
FROM python:3.12-slim

# tini as PID 1: forwards SIGTERM (activeDeadlineSeconds) so the agent can still emit a failed Result.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY scripts/agentruntime/agent_run.py scripts/agentruntime/common.py \
     scripts/agentruntime/mcp_client.py scripts/agentruntime/result.py \
     scripts/agentruntime/VERSION /app/
# Precompile so nothing tries to write __pycache__ on the read-only root fs.
RUN python -m compileall -q /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/work/home \
    TMPDIR=/work/tmp
USER 10001:10001
ENTRYPOINT ["/usr/bin/tini", "--", "python", "/app/agent_run.py"]
