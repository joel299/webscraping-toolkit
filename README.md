# Central de Leads — Google Maps Prospecting Toolkit

[![CI](https://github.com/joel299/webscraping-toolkit/actions/workflows/build.yml/badge.svg)](https://github.com/joel299/webscraping-toolkit/actions/workflows/build.yml)
[![Go](https://img.shields.io/badge/Go-1.27.1-00ADD8?logo=go&logoColor=white)](https://go.dev/)
[![Google Maps](https://img.shields.io/badge/Google%20Maps-data%20source-4285F4?logo=googlemaps&logoColor=white)](https://www.google.com/maps)
[![Supabase](https://img.shields.io/badge/Supabase-PostgreSQL-3FCF8E?logo=supabase&logoColor=white)](https://supabase.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%2B-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Playwright](https://img.shields.io/badge/Playwright-browser%20automation-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev/)
[![HTMX](https://img.shields.io/badge/HTMX-2.x-3366CC?logo=htmx&logoColor=white)](https://htmx.org/)
[![Leaflet](https://img.shields.io/badge/Leaflet-1.9-199900?logo=leaflet&logoColor=white)](https://leafletjs.com/)
[![SQLite](https://img.shields.io/badge/SQLite-job%20queue-003B57?logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Sistema de prospecção comercial baseado em Google Maps, com scraping em Go, interface web para criação e acompanhamento de pesquisas, mapa interativo, base consolidada de leads e persistência incremental em PostgreSQL/Supabase.

O projeto evolui o motor open source [gosom/google-maps-scraper](https://github.com/gosom/google-maps-scraper) para um fluxo orientado a prospecção, provenance de pesquisas, persistência canônica e leitura controlada a partir do banco.

> Este projeto não é afiliado, patrocinado ou endossado pelo Google. O uso deve respeitar legislação aplicável, termos dos serviços consultados e políticas de tratamento de dados.

## Visão geral

O fluxo principal é:

```text
Frontend (HTMX + Leaflet)
        |
        v
Go Web/API
        |
        +--> SQLite jobs.db
        |      |
        |      +--> atomic job claim
        |
        v
Web Runner
        |
        +--> PROSPECT_READ_MODE=database
        |      |
        |      +--> PostgreSQL/Supabase HIT
        |      |      |
        |      |      +--> CSV + provenance
        |      |
        |      +--> MISS/PARTIAL -> scraper
        |
        +--> PROSPECT_READ_MODE=current
               |
               v
        Google Maps scraping
               |
               v
        Scrapemate result stream
               |
               v
        fanout
          |            |
          v            v
        CSV       PostgreSQL/Supabase
                     |
                     +--> canonical lead
                     +--> search provenance
```

## Principais recursos

- Pesquisa de empresas por segmento e localização.
- Interface comercial em PT-BR para criar e acompanhar pesquisas.
- Opções de busca equivalentes a até 50, 100, 200 ou 500 empresas.
- Status de jobs em tempo real via frontend.
- Base global consolidada de leads.
- Filtros por pesquisa, categoria, telefone e e-mail.
- Visualização em mapa com Leaflet e OpenStreetMap.
- Detalhes comerciais por lead.
- Exportação CSV.
- API HTTP com documentação integrada.
- Persistência incremental em PostgreSQL/Supabase.
- Provenance entre pesquisa e lead por `prospect_search_leads`.
- Identidade canônica baseada em `place_id`, `cid` e telefone/WhatsApp normalizado.
- UPSERT não destrutivo para preservar estado comercial já existente.
- Atomic job claim em SQLite para impedir execução duplicada do mesmo job por múltiplos processos.
- Fanout de resultados para que CSV e persistência recebam o mesmo fluxo.
- Drain de resultados pendentes antes do shutdown.
- Database-first atrás de feature flag server-side, com fallback para scraping quando não há dados suficientes.
- RLS, grants e migrations versionadas para o domínio persistente.
- CI com build, vet, tidy, mod verify, testes unitários e integração PostgreSQL.

## Stack

| Camada | Tecnologia |
| --- | --- |
| Backend | Go |
| Scraping | Scrapemate + Playwright/Chromium |
| Fonte de descoberta | Google Maps |
| Web | Go HTTP server |
| UI dinâmica | HTMX |
| Mapas | Leaflet + OpenStreetMap |
| Job queue local | SQLite |
| Banco persistente | PostgreSQL / Supabase |
| Driver PostgreSQL | pgx / pgxpool |
| Containers | Docker |
| CI | GitHub Actions |
| Testes | Go test + Testify |
| API docs | Swagger / ReDoc |

## Modos de leitura

O comportamento é controlado no servidor por:

```bash
PROSPECT_READ_MODE=current
```

ou:

```bash
PROSPECT_READ_MODE=database
```

### `current`

É o modo seguro/default. A pesquisa executa o scraper normalmente e os resultados são persistidos incrementalmente.

### `database`

Tenta localizar uma pesquisa concluída equivalente no PostgreSQL. Se houver dados suficientes para o depth solicitado, os leads persistidos são usados para gerar o resultado. Se houver miss, resultado parcial ou falha de provenance, o fluxo retorna ao scraper atual.

O modo `database` é controlado por feature flag e deve ser validado antes de ser adotado como default operacional.

## Modelo de dados

As tabelas centrais são:

### `public.prospect_leads_google`

Tabela canônica dos leads encontrados. O scraper usa UPSERT e preserva campos comerciais/enriquecimentos existentes quando apropriado.

### `public.prospect_searches`

Representa uma pesquisa executada, incluindo query, localização, limite solicitado, status e timestamps.

### `public.prospect_search_leads`

Relação N:N entre pesquisa e lead. É a fonte de provenance para saber em quais pesquisas um lead apareceu.

Outras estruturas operacionais, funções, triggers e migrations estão em:

```text
supabase/migrations/
```

Mais detalhes:

- [Arquitetura](docs/ARCHITECTURE.md)
- [Banco de dados](docs/DATABASE.md)
- [Testes](docs/TESTING.md)
- [Segurança](docs/SECURITY.md)
- [Decisões técnicas](docs/DECISIONS.md)

## Quick start com Docker

Docker é o caminho mais simples porque a imagem já prepara Chromium e dependências do Playwright.

### 1. Build

```bash
docker build -t webscraping-toolkit .
```

### 2. Executar somente a interface/scraper

```bash
docker run --rm -p 8086:8086 -v "$PWD/webdata:/data" webscraping-toolkit -web -addr :8086 -data-folder /data
```

Acesse:

```text
http://localhost:8086
```

### 3. Executar com persistência PostgreSQL/Supabase

Crie um arquivo de secret fora do Git contendo somente a connection string PostgreSQL.

Exemplo de montagem:

```bash
docker run --rm -p 8086:8086 -e PROSPECT_DATABASE_URL_FILE=/run/secrets/prospect_database_url -e PROSPECT_READ_MODE=current -v "$PWD/.secrets/prospect_database_url:/run/secrets/prospect_database_url:ro" -v "$PWD/webdata:/data" webscraping-toolkit -web -addr :8086 -data-folder /data
```

Não versione o arquivo de credenciais.

## Execução local

Requisitos principais:

- Go compatível com o `go.mod`.
- Chromium/Playwright instalado.
- PostgreSQL opcional quando a persistência estiver habilitada.

O próprio projeto possui um modo dedicado de instalação do browser:

```bash
PLAYWRIGHT_INSTALL_ONLY=1 go run .
```

Depois:

```bash
go run . -web -addr :8086 -data-folder webdata
```

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
| --- | --- | --- |
| `PROSPECT_DATABASE_URL_FILE` | Não | Caminho para arquivo contendo a DSN PostgreSQL. Preferido para secrets. |
| `PROSPECT_DATABASE_URL` | Não | DSN PostgreSQL direta. Use apenas em ambiente seguro. |
| `PROSPECT_READ_MODE` | Não | `current` ou `database`. Default efetivo: `current`. |
| `PROSPECT_CACHE_ENABLED` | Não | `true`/`1` habilita o cache Redis somente para `GET /api/v1/leads`; default `false`. |
| `PROSPECT_REDIS_URL` | Não | URL do Redis local; default `redis://127.0.0.1:6379/0`. Redis é apenas aceleração; PostgreSQL permanece a fonte de verdade. |
| `DISABLE_TELEMETRY` | Não | Use `1` para desabilitar telemetria do motor upstream. |
| `PLAYWRIGHT_INSTALL_ONLY` | Não | Use `1` para executar apenas a instalação do Chromium via Playwright. |

Consulte também [`.env.example`](.env.example).

## Opções importantes do servidor

O binário preserva os recursos do motor upstream. Algumas flags relevantes:

```text
-web                    inicia o servidor web
-addr                   endereço do servidor (default :8080)
-data-folder            pasta para jobs.db e CSVs
-c                      concorrência
-depth                  profundidade do scraping
-lang                   idioma
-email                  busca e-mails nos sites
-fast-mode              modo rápido
-radius                 raio da pesquisa em metros
-proxies                proxies separados por vírgula
-proxies-file           arquivo com proxies
-browser-pool-size      quantidade de browser contexts
-pages-per-browser      páginas simultâneas por browser context
```

Para a lista completa:

```bash
go run . -h
```

## Persistência e concorrência

### Atomic job claim

Jobs pendentes são reclamados atomicamente no SQLite antes da execução. Isso evita que duas instâncias que compartilham o mesmo `jobs.db` executem simultaneamente o mesmo job.

### Fanout

O fluxo de resultados possui um consumidor upstream único e replica cada resultado para os writers configurados. Atualmente, isso permite que CSV e PostgreSQL recebam o mesmo conjunto de resultados.

### Drain no shutdown

Quando o contexto do scraping é cancelado, o fanout drena os resultados restantes antes de encerrar os writers, evitando perda das últimas entradas processadas.

## Segurança

- Secrets são mantidos server-side.
- Nenhuma credencial PostgreSQL deve ser enviada ao frontend.
- Prefira `PROSPECT_DATABASE_URL_FILE` a DSNs em linha de comando.
- Migrations são a fonte de verdade para alterações de schema.
- RLS e grants do domínio persistente são definidos por migrations.
- Logs de falha de provenance devem ser sanitizados.
- Não versione arquivos de credenciais, dumps ou tokens.
- O frontend não deve acessar diretamente credenciais do Supabase/PostgreSQL.

Veja [docs/SECURITY.md](docs/SECURITY.md).

## Testes e qualidade

Executar a suíte:

```bash
go test ./...
```

Verificações usadas no CI:

```bash
gofmt -s -w .
go vet ./...
go mod tidy
go mod verify
go build ./...
go test -short ./...
go test ./shadow/...
```

O workflow [`.github/workflows/build.yml`](.github/workflows/build.yml) executa testes de integração com PostgreSQL em service container.

## Estrutura principal

```text
.
├── api/                    # API e documentação
├── runner/                 # modos de execução
│   └── webrunner/          # pipeline web, claim, DB-first e fanout
├── shadow/                 # persistência PostgreSQL e provenance
├── web/                    # servidor, SQLite e frontend
│   ├── sqlite/
│   └── static/
├── supabase/
│   └── migrations/         # schema, RLS, functions, triggers e hardening
├── docs/                   # arquitetura, banco, segurança e decisões
├── skills/                 # skill operacional do projeto
├── Dockerfile
├── go.mod
└── main.go
```

## Estado do projeto

A arquitetura de provenance, atomic claim, fanout e persistência incremental está implementada e coberta por testes.

O read path database-first existe atrás de `PROSPECT_READ_MODE=database`. Quando `PROSPECT_CACHE_ENABLED=true`, somente `GET /api/v1/leads` usa Redis local com chave versionada por paginação e TTL de 45 segundos; miss, erro, entrada corrompida ou Redis indisponível fazem fallback transparente para PostgreSQL. O modo `current` e o cache permanecem desabilitados por padrão.

## Contribuição

Antes de enviar alterações:

1. mantenha mudanças pequenas e focadas;
2. execute testes e `go vet`;
3. não inclua secrets;
4. atualize documentação quando contratos ou operação mudarem;
5. preserve backward compatibility da UI/API quando possível;
6. não altere migrations já aplicadas; crie uma nova migration versionada.

## Upstream e licença

Este repositório deriva do projeto [gosom/google-maps-scraper](https://github.com/gosom/google-maps-scraper) e preserva sua licença MIT.

Consulte [LICENSE](LICENSE) para os termos completos.
