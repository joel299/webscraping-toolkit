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
    |       +--> coleta de detalhes (FULL ou FAST)
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
  monta o mesmo schema público e entrega ao webhook uma única vez. Campos de
  redes sociais, e-mails e dados cadastrais ficam vazios.

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
