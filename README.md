# Webscraping Toolkit

[![CI](https://github.com/joel299/webscraping-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/joel299/webscraping-toolkit/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/Playwright-1.41%2B-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev/python/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Tests](https://img.shields.io/badge/Tests-pytest-0A9EDC?logo=pytest&logoColor=white)](https://pytest.org/)

Toolkit para coleta automatizada de dados públicos, enriquecimento de leads e integração com fluxos de automação.

> Repositório privado. Os dados coletados, logs operacionais, credenciais e configurações de infraestrutura não fazem parte do versionamento.

## Componentes

- **Google Maps scraper** com Playwright.
- **Stark Scraper Studio**, interface HTTP para iniciar jobs e acompanhar progresso.
- Enriquecimento opcional de leads com dados públicos de CNPJ, website e redes sociais.
- Exportação e envio controlado para automações externas via webhook/MCP.
- Monitor de jobs em lote.
- Imagem Docker baseada no Playwright para execução reproduzível.

## Estrutura

```text
.
├── src/
│   ├── gmaps_playwright_scraper.py
│   ├── gmaps_web_ui.py
│   ├── monitor_and_chain_scraper.py
│   └── send_leads_to_mcp.py
├── docs/
│   ├── architecture.md
│   └── operations.md
├── examples/
│   └── leads.example.csv
├── tests/
├── .env.example
├── Dockerfile
└── requirements.txt
```

## Requisitos

- Python 3.11+
- Playwright/Chromium
- Docker opcional para execução isolada
- Endpoint de automação opcional, configurado por variável de ambiente

## Execução local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python src/gmaps_web_ui.py
```

A interface ficará disponível em `http://127.0.0.1:8990`.

## Execução com Docker

```bash
docker build -t webscraping-toolkit .
docker run --rm -p 8990:8990 --env-file .env webscraping-toolkit
```

## Configuração

```bash
cp .env.example .env
```

Nunca versione `.env`. Variáveis principais:

- `OMNIROUTE_URL` e `OMNIROUTE_RESPONSES_URL`: endpoints do serviço de enriquecimento, quando utilizado.
- `OMNIROUTE_TOKEN`: token do serviço de enriquecimento, quando utilizado.
- `N8N_WEBHOOK_URL`: webhook externo de destino; opcional.
- `SCRAPER_DEFAULT_MODE`: modo padrão da API (`fast`; use `full` somente quando enrichment for explicitamente desejado).

O FAST usa descoberta incremental por query, com early stop ao atingir
`max_leads`, deduplicação e pré-filtro antes dos detalhes. Os limites podem ser
ajustados por `SCRAPER_OVERSAMPLING_FACTOR`, `SCRAPER_QUERY_CANDIDATE_LIMIT`,
`SCRAPER_MAX_SCROLLS_PER_QUERY`, `SCRAPER_SCROLL_WAIT_MS`,
`SCRAPER_MAX_NO_NEW_SCROLLS`, `SCRAPER_LOW_YIELD_QUERY_THRESHOLD`,
`SCRAPER_MAX_LOW_YIELD_QUERIES` e `SCRAPER_REUSE_DETAIL_PAGE`. O FULL continua
com o fluxo legado.
- `WEB_RESULTS_MAX_SCROLLS`: tentativas de scroll do painel semântico `Resultados da Web` (padrão `3`).
- `BRASILAPI_CNPJ_URL`: endpoint da API de CNPJ, quando utilizado.
- `BRASILAPI_MIN_INTERVAL_SECONDS`: intervalo mínimo entre consultas de CNPJ.
- `SCRAPER_API_BASE_URL`: URL da API do Scraper Studio para o monitor de jobs.

## Envio de leads

O utilitário aceita CSV e possui modo seguro de simulação:

```bash
python src/send_leads_to_mcp.py \
  --input examples/leads.example.csv \
  --dry-run
```

Para envio real, informe explicitamente o endpoint e revise o payload antes da execução:

```bash
python src/send_leads_to_mcp.py \
  --input /caminho/para/leads.csv \
  --webhook "$LEADS_WEBHOOK_URL" \
  --interval 20
```

## Segurança e conformidade

- Coletar somente dados públicos e permitidos pela legislação e pelos termos de uso aplicáveis.
- Não versionar leads reais, cookies, tokens, logs com PII ou dumps de jobs.
- Usar `--dry-run` antes de qualquer envio externo.
- Aplicar delays, limites de volume e monitoramento para evitar sobrecarga.
- Validar o endpoint de destino antes de executar lotes.

## Desenvolvimento

Validação mínima antes de abrir um pull request:

```bash
python -m compileall -q src
python -m pytest -q
```

### Benchmark da Etapa 1

O modo `fast` mantém o contrato de payload do n8n, mas não executa
enriquecimento, abertura dos websites para redes sociais, BrasilAPI, OmniRoute
ou LLM durante a captura. Ele faz somente pré-qualificação barata, lê
`Resultados da Web` já renderizados no Maps e preserva os novos sinais no
payload. O modo `full` permanece disponível mediante solicitação explícita.

Execute o benchmark em uma infraestrutura autorizada. O webhook é opcional;
para validar HTTP 2xx, informe um endpoint de teste controlado:

```bash
python scripts/benchmark_scraper.py \
  --category "clínica de estética" \
  --city "Campo Grande" \
  --state "Mato Grosso do Sul" \
  --max-leads 50 \
  --mode fast \
  --runs 3 \
  --webhook "$N8N_WEBHOOK_URL"
```

O script imprime somente métricas agregadas na saída. Não salve a saída com
leads reais no repositório.

## Licença

Distribuído sob a licença [MIT](LICENSE).
