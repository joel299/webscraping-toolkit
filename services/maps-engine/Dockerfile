FROM ubuntu:20.04 AS playwright-deps
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
ENV PLAYWRIGHT_DRIVER_PATH=/opt/ms-playwright-go
ARG TARGETARCH
ARG PLAYWRIGHT_GO_VERSION=v0.6100.0
RUN export PATH=$PATH:/usr/local/go/bin:/root/go/bin \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl wget \
    && if [ "$TARGETARCH" = "arm64" ]; then GO_ARCH="arm64"; else GO_ARCH="amd64"; fi \
    && wget -q "https://go.dev/dl/go1.26.6.linux-${GO_ARCH}.tar.gz" \
    && tar -C /usr/local -xzf "go1.26.6.linux-${GO_ARCH}.tar.gz" \
    && rm "go1.26.6.linux-${GO_ARCH}.tar.gz" \
    && apt-get clean && rm -rf /var/lib/apt/lists/* \
    && go install github.com/mxschmitt/playwright-go/cmd/playwright@${PLAYWRIGHT_GO_VERSION} \
    && mkdir -p /opt/browsers \
    && playwright install chromium --with-deps
FROM golang:1.26.6-trixie AS builder
ARG UPSTREAM_SHA=beca11f148c7dc9651ee2da9aa9ce111f3dd3bea
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/* \
    && git clone --filter=blob:none https://github.com/gosom/google-maps-scraper.git src \
    && cd src && git checkout ${UPSTREAM_SHA}
COPY services/maps-engine/gosom-stark.patch /build/gosom-stark.patch
COPY services/maps-engine/starkwriter /build/src/starkwriter
RUN cd /build/src && git apply /build/gosom-stark.patch && go mod download && CGO_ENABLED=0 go build -ldflags="-w -s" -o /usr/bin/google-maps-scraper
FROM debian:trixie-slim
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
ENV PLAYWRIGHT_DRIVER_PATH=/opt/ms-playwright-go
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libatspi2.0-0 libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 && apt-get clean && rm -rf /var/lib/apt/lists/*
COPY --from=playwright-deps /opt/browsers /opt/browsers
COPY --from=playwright-deps /opt/ms-playwright-go /opt/ms-playwright-go
RUN chmod -R 755 /opt/browsers /opt/ms-playwright-go
COPY --from=builder /usr/bin/google-maps-scraper /usr/bin/google-maps-scraper
ENTRYPOINT ["google-maps-scraper"]
CMD ["-web","-addr",":8080","-data-folder","/data"]
