# Arquitetura

## Fluxo principal

```text
Cliente HTTP
    |
    v
Stark Scraper Studio (:8990)
    |
    +--> worker multiprocessing
    |       |
    |       +--> Google Maps via Playwright
    |       +--> pré-filtro barato no card (nicho, rating, avaliações)
|       +--> coleta de detalhes (FULL ou FAST)
|       +--> Resultados da Web renderizados no Maps
    |       +--> enriquecimento opcional (somente FULL/acionado)
    |
    +--> estado temporário dos jobs
    |
    +--> webhook/MCP externo (opcional)
```

## Modos compatíveis

`POST /api/scrape` aceita `mode=full` e `mode=fast`. A ausência de `mode`
resolve para `SCRAPER_DEFAULT_MODE`, cujo fallback é `fast`.

- **FULL**: fluxo legado, incluindo qualificação automática quando
  `auto_enrich=true`.
- **FAST**: coleta candidatos e detalhes principais do Google Maps, deduplica,
  evita abrir candidatos incompatíveis quando os dados estão no card, lê
  `Resultados da Web` sem abrir sites externos, monta o mesmo schema público e
  entrega ao webhook uma única vez. Enrichment externo continua fora do FAST.

## Pré-qualificação do Addendum

O classificador centralizado rejeita sinais fortes de nichos incompatíveis
(pet shop, veterinária, barbearia, manicure e estética automotiva) antes dos
detalhes. Quando disponíveis no card, rating abaixo de `4.5` e menos de `20`
avaliações também são rejeitados antes da navegação. O FAST rejeita da campanha
leads sem WhatsApp após os detalhes; isso não remove o registro de uma base
futura.

## Descoberta incremental de performance

No FAST, a descoberta é consumida query por query: os cards da query atual são
deduplicados, pré-qualificados e enviados imediatamente para detalhes. A próxima
query só começa quando ainda faltam leads. O limite de proteção usa
`SCRAPER_OVERSAMPLING_FACTOR` (padrão `1.5`), mas não bloqueia o processamento
incremental. Cada query respeita `SCRAPER_QUERY_CANDIDATE_LIMIT`,
`SCRAPER_MAX_SCROLLS_PER_QUERY`, `SCRAPER_SCROLL_WAIT_MS` e
`SCRAPER_MAX_NO_NEW_SCROLLS`.

Quando `max_leads` é atingido, o FAST encerra discovery e detalhes imediatamente
(`early_stop_triggered=true`), atualiza o job com os leads já capturados e deixa
o envio único ao webhook para a etapa final existente. Duas queries consecutivas
abaixo de `SCRAPER_LOW_YIELD_QUERY_THRESHOLD` encerram a expansão adaptativa.
O FULL mantém o fluxo legado.

O bloco `Resultados da Web` produz `web_results` com tipo, título, URL, domínio e
snippet. Instagram e CNPJ encontrados ali recebem, respectivamente,
`instagram_source` e `cnpj_source` iguais a `google_web_results`. O indicador
`google_sponsored` usa somente o texto já renderizado no card.

As métricas adicionais incluem `candidates_seen`, rejeições por motivo,
`details_opened`, `details_skipped`, `web_results_found`,
`instagram_found_from_google`, `google_sponsored`, `qualified`,
`pre_filter_rejection_rate`, `detail_open_rate`,
`instagram_google_discovery_rate` e `qualified_leads_per_minute`.

O job expõe métricas monotônicas convertidas em milissegundos (`candidate_search_ms`,
`details_ms`, `scrape_total_ms`, `enrichment_ms`, `webhook_ms` e
`total_pipeline_ms`) e contadores de qualidade. Essas métricas são internas e
não alteram o payload enviado ao n8n.

## Módulos

- `gmaps_playwright_scraper.py`: navegação e extração no Google Maps.
- `gmaps_web_ui.py`: interface web, API de jobs, enriquecimento e exportação.
- `monitor_and_chain_scraper.py`: execução sequencial de lotes e acompanhamento de status.
- `send_leads_to_mcp.py`: transformação de CSV e envio controlado para MCP.

## Limites conhecidos

- Seletores do Google Maps podem mudar sem aviso.
- O estado dos jobs é em memória e não substitui uma fila persistente.
- A execução em produção precisa de autenticação, rate limiting e armazenamento adequado.
