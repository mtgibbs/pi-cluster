# review-hub — reactive PR-evaluator webhook receiver.
# Build context is the repo root: docker build -f scripts/reviewhub/Dockerfile .
FROM python:3.12-slim

RUN pip install --no-cache-dir "pyjwt[crypto]" pyyaml

WORKDIR /app
# triggerable_judge.py imports cronjob_parse from <root>/.github/scripts; keep the layout.
COPY .github/scripts/cronjob_parse.py .github/scripts/cronjob_parse.py
COPY scripts/triggerable_judge.py scripts/triggerable_judge.py
COPY scripts/reviewhub/ scripts/reviewhub/
# Prompt templates (loaded at runtime) live next to each validator's eval set.
COPY specs/validators/ specs/validators/

ENV PORT=8080
EXPOSE 8080
USER 1000:1000
CMD ["python", "scripts/reviewhub/receiver.py"]
