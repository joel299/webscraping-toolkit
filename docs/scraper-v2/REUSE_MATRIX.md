# Matriz de reuse da Scraper V2

| Componente | Origem pinada | Estratégia inicial | Decisão
|---|---|---|---|
| Maps crawler | `gosom/google-maps-scraper` | fork/adapter | reutilizar engine Go + Playwright
| Browser pool/concurrency | gosom; Crawlee como referência | reuse/adaptar | avaliar somente se reduzir complexidade
| Maps result writer | `gosom/google-maps-scraper` `CentralWriter` | adaptar | emitir eventos incrementais
| Maps job flow | `Mahanaicoach/google-maps-scraper-kit` | adaptar | Docker, health, create/poll/retrieve
| Reviews crawler | `georgekhananaev/google-reviews-scraper-pro` | reuse/adaptar | scraper, retry, change detection, selector health
| Control plane | produto Stark | construir | jobs, shards, contratos e segurança
| Domain/persistence | produto Stark | construir/adaptar | Supabase/Postgres e idempotência
| RequestQueue/autoscale | Crawlee | reuse somente se necessário | não adicionar runtime sem ganho comprovado

## Pins auditados

- `gosom/google-maps-scraper`: `beca11f148c7dc9651ee2da9aa9ce111f3dd3bea` — MIT
- `Mahanaicoach/google-maps-scraper-kit`: `a6a39d1c64793c87cdafc834e9ef89a1314f4778` — MIT
- `georgekhananaev/google-reviews-scraper-pro`: `09bfa6215cb37edecc777bb40055d100e88ef767` — verificar notices na integração
- `apify/crawlee`: `3924163a817b428e3cab692140e4047a12c4c69f` — Apache-2.0

Os repositórios foram clonados em `/root/scraper-v2-reference/`, fora do source tree do produto.
