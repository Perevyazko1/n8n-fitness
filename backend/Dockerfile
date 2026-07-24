FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# ffmpeg — для сборщика Reels (fitness/reels.py); fonts-dejavu — шрифт для drawtext-плашек.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

# gunicorn: 2 воркера на 1 vCPU — нормально; снизить до 1, если RAM впритык.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8001", "--workers", "2", "--timeout", "60"]
