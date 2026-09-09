FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libatspi2.0-0 libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 && rm -rf /var/lib/apt/lists/*
COPY services/maps-engine/google-maps-scraper-bin /usr/local/bin/google-maps-scraper
RUN chmod +x /usr/local/bin/google-maps-scraper
EXPOSE 8080
CMD ["google-maps-scraper","-web","-addr",":8080","-data-folder","/data"]
