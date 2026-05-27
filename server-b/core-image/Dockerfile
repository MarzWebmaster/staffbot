FROM python:3.12-slim

WORKDIR /app

# Install OCR & document processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-msa \
    && rm -rf /var/lib/apt/lists/*

# Python libraries
RUN pip install --no-cache-dir \
    fastapi uvicorn httpx asyncpg \
    pymupdf pymupdf4llm \
    pytesseract Pillow \
    python-docx openpyxl

COPY agent.py /app/agent.py

EXPOSE 8000

CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8000"]
