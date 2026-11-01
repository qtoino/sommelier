# Isolated runner for generated tests: run with --network none and resource limits.
FROM python:3.12-slim
RUN pip install --no-cache-dir pytest==8.3.4
USER nobody
