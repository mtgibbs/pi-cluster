# agent-runner — launches one ephemeral least-privilege Job per (event, agent).
# Build context is the repo root: docker build -f scripts/agentrunner/Dockerfile .
FROM python:3.12-slim

RUN pip install --no-cache-dir "pyyaml==6.0.2"

# Read-only root filesystem: never write .pyc files, never buffer stdout (JSON log lines).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app
COPY scripts/agentrunner/VERSION \
     scripts/agentrunner/runner.py \
     scripts/agentrunner/agentspec.py \
     scripts/agentrunner/jobspec.py \
     scripts/agentrunner/kubeapi.py \
     scripts/agentrunner/ledger.py \
     scripts/agentrunner/results.py \
     /app/

# The ledger (RUNNER_LEDGER_PATH, default /data/ledger.jsonl) must live on a writable mount.
EXPOSE 8080
USER 10001:10001
CMD ["python", "/app/runner.py"]
