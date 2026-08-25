FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --break-system-packages

COPY . .

# Note: this container needs the host's docker.sock mounted (see
# docker-compose.yml) so SandboxExecutor can launch sibling containers
# for task execution. It talks to Ollama on the host via
# host.docker.internal, not a containerized Ollama — see the note in
# docker-compose.yml for why.

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
