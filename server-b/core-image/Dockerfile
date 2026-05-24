FROM python:3.12-slim

WORKDIR /app

# Minimal agent runtime
RUN pip install --no-cache-dir fastapi uvicorn httpx asyncpg

COPY agent.py /app/agent.py

EXPOSE 8000

CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8000"]
