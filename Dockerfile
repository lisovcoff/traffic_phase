FROM python:3.12-slim

WORKDIR /app

COPY requirements-tested-py312.txt .
RUN python -m pip install --no-cache-dir --upgrade "pip>=26.2" \
    && python -m pip install --no-cache-dir -r requirements-tested-py312.txt

COPY app ./app
COPY scripts ./scripts
COPY config ./config

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
