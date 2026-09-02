FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy
RUN apt-get update && apt-get install -y tini && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir playwright
RUN playwright install chromium
WORKDIR /app
COPY src/gmaps_playwright_scraper.py src/gmaps_web_ui.py ./
ENV PYTHONUNBUFFERED=1
EXPOSE 8990
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "/app/gmaps_web_ui.py"]
