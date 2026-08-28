FROM python:3.12-slim

# ffmpeg/ffprobe for frame extraction + probing, DejaVu font for sheet labels,
# tini for clean signal handling / zombie reaping.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-dejavu-core \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY web/ ./web/

# Defaults; all of these can be overridden by the Unraid template / compose.
ENV CONFIG_PATH=/config/config.yaml \
    PYTHONUNBUFFERED=1

# /config  -> persistent config.yaml (appdata)
# /output  -> generated .torrent / contact sheet / bbcode
# /media   -> your library, mounted read-only
VOLUME ["/config", "/output", "/media"]

EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
