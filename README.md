# Google Maps Scraper — Persistent Lead Prospecting System

Official Repository: [joel299/webscraping-toolkit](https://github.com/joel299/webscraping-toolkit)

## Overview
High-performance Google Maps lead scraper with parallel web application, interactive Leaflet mapping, HTMX dynamic UI, and automated incremental shadow persistence directly to PostgreSQL/Supabase (`public.prospect_leads_google`).

## Quick Start & Architecture
- **Baseline Version (GRU-84)**: Running on port `:8080` (`http://localhost:8080`)
- **Persistent Version (GRU-86)**: Running on port `:8086` (`http://localhost:8086`)
- **Database**: PostgreSQL / Supabase (`wuyvgmzbmuwcjjzmgccs`) with Row Level Security (RLS) enabled.

## Secret Management
Credentials are read server-side via `PROSPECT_DATABASE_URL_FILE=/run/secrets/prospect_database_url` (or `/tmp/prospect_database_url`). Passwords are NEVER printed in logs, committed to Git, or exposed to the frontend.

## Environment Variables
- `PROSPECT_DATABASE_URL_FILE`: Path to secret file containing PostgreSQL connection string URI.
- `PROSPECT_DATABASE_URL`: Direct DSN fallback (for containerized deployments).

## Running via Docker
```bash
docker build -t google-maps-scraper:gru-86 .
docker run -d --name google-maps-scraper-gru86 -p 8086:8086 \
  -e PROSPECT_DATABASE_URL_FILE=/tmp/prospect_database_url \
  -v /tmp/prospect_database_url:/tmp/prospect_database_url \
  google-maps-scraper:gru-86 -web -addr :8086
```

## Verification & Testing
```bash
# Run unit & integration scaling tests (1, 5, 20 leads + RLS + Shadow fallback)
go test -v ./shadow/...
```
