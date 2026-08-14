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
    |       +--> coleta de detalhes
    |       +--> enriquecimento opcional
    |
    +--> estado temporário dos jobs
    |
    +--> webhook/MCP externo (opcional)
```

## Módulos

- `gmaps_playwright_scraper.py`: navegação e extração no Google Maps.
- `gmaps_web_ui.py`: interface web, API de jobs, enriquecimento e exportação.
- `monitor_and_chain_scraper.py`: execução sequencial de lotes e acompanhamento de status.
- `send_leads_to_mcp.py`: transformação de CSV e envio controlado para MCP.

## Limites conhecidos

- Seletores do Google Maps podem mudar sem aviso.
- O estado dos jobs é em memória e não substitui uma fila persistente.
- A execução em produção precisa de autenticação, rate limiting e armazenamento adequado.
