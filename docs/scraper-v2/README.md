# Scraper V2 — estrutura inicial

Esta linha contém somente a arquitetura V2 lado a lado. O legado (`src/gmaps_playwright_scraper.py` e `src/gmaps_web_ui.py`) permanece como fallback e não é dependência estrutural da V2.

## Componentes

- `services/stark-api`: control plane, jobs duráveis e contratos HTTP.
- `services/maps-engine`: adapter/fork pinado de `gosom/google-maps-scraper`.
- `services/reviews-worker`: adapter dos módulos maduros de `google-reviews-scraper-pro`.
- `packages/domain`: identidade, dedupe, estados e eventos do domínio.
- `packages/persistence`: adapters Postgres/Supabase idempotentes.
- `packages/normalization`: normalização de places, leads e reviews.
- `migrations`: schema V2, sem alterar o schema legado nesta fase.
- `tests`: contratos, unidade, integração e E2E controlado.

## Fluxo

`stark-api → shard-planner → maps-engine (A/B) → aggregator/dedupe → persistence/event stream`

Reviews entram por worker separado e compartilham apenas contratos/eventos e persistência; não compartilham browser/page.

## Regra operacional

Reuse first → adapt second → build last. Cada componente novo deve apontar para a origem auditada ou justificar por que a reutilização não é segura.
