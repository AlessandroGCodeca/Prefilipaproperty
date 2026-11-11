FROM python:3.12-slim

WORKDIR /app

# Playwright's Chromium goes here rather than under /root, where the
# unprivileged user below could not run it.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# curl: the HEALTHCHECK. No compiler: every pinned package ships a wheel for
# Python 3.12 on x86_64 and arm64.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# nehnutelnosti.sk is only reachable through a real browser (Imperva WAF), so
# the scraper drives Chromium via Playwright. The pip package ships without the
# browser; --with-deps also pulls the system libraries Chromium needs.
RUN python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# The app runs as this user, not root (docker/entrypoint.sh drops root after
# handing it the folders it writes).
RUN useradd --create-home --uid 1000 sovereign

COPY . .

RUN mkdir -p data logs backups && chown -R sovereign:sovereign /app \
    && chmod +x docker/entrypoint.sh

EXPOSE 8501

ENTRYPOINT ["/app/docker/entrypoint.sh"]

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1
