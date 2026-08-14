# Webscraping Toolkit

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

- `OMNIROUTE_TOKEN`: token do serviço de enriquecimento, quando utilizado.
- `N8N_WEBHOOK_URL`: webhook de destino; opcional.
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

## Licença

Uso interno. Os termos de distribuição devem ser definidos antes de tornar o repositório público.
