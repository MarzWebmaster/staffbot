# StaffBot.my — Sandbox Agent (Client Container)
# ===============================================
# Lightweight container — NO AI, NO Hermes, NO LLM.
# Only executes tools/commands from Gateway.

FROM python:3.12-slim

WORKDIR /app

# ── Create sandbox user FIRST ──
RUN useradd -m -s /bin/bash sandbox

# ── Minimal system deps for tool execution ──
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-msa \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Python deps for sandbox tools ──
RUN pip install --no-cache-dir \
    fastapi uvicorn \
    httpx \
    pymupdf pymupdf4llm \
    pytesseract Pillow \
    python-docx openpyxl

# ── Copy sandbox agent ──
COPY agent.py /app/agent.py

# ── Create workspace + fix ownership ──
RUN mkdir -p /app/data/workspace && \
    chown -R sandbox:sandbox /app

EXPOSE 8000

USER sandbox
CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8000"]
