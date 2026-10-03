FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc curl fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# nehnutelnosti.sk is only reachable through a real browser (Imperva WAF), so
# the scraper drives Chromium via Playwright. The pip package ships without the
# browser; --with-deps also pulls the system libraries Chromium needs.
RUN python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN mkdir -p data contracts logs

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1
