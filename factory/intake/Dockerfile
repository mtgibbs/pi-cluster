# factory-intake — admission control between the research agents (via n8n) and Fabro.
# Build context is the repo root: docker build -f factory/intake/Dockerfile .
# Stdlib only. The whole factory/ tree is copied because submit.py uploads the target's workflow
# files (and code_sha covers steps.py + classify.sh): the image version pins what gets submitted.
FROM python:3.12-slim
WORKDIR /app
COPY factory/ factory/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FACTORY_INTAKE_PORT=8080 FACTORY_INTAKE_DB=/data/intake.db
EXPOSE 8080
USER 1000:1000
CMD ["python", "factory/intake/service.py", "serve"]
