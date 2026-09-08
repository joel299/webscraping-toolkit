# Correção `/api/job/{id}` — `ERR_CONNECTION_REFUSED`

- **Projeto:** `joel299/webscraping-toolkit`
- **Commit:** `4931ef5`
- **Data:** 2026-09-08
- **Escopo:** disponibilidade da API HTTP, lifecycle do job, healthcheck, polling e testes

## Causa raiz comprovada

A API não chegava ao `serve_forever()` quando executada pelo comando documentado:

```bash
python3 src/gmaps_web_ui.py
```

O processo caía durante o import:

```text
ImportError: attempted relative import with no known parent package
```

A cadeia era:

```text
gmaps_web_ui.py
→ fallback import supabase_writer
→ supabase_writer.py import relativo de gmaps_playwright_scraper
→ ImportError
→ processo encerra antes de ThreadingHTTPServer
→ porta 8990 não escuta
→ frontend recebe ERR_CONNECTION_REFUSED em /api/job/{id}
```

Também foi comprovado antes da correção:

```text
curl http://127.0.0.1:8990/api/job/teste
curl: (7) Failed to connect to 127.0.0.1 port 8990
```

## Correção aplicada

### `src/supabase_writer.py`

Adicionado fallback de import para execução direta do script:

```python
try:
    from .gmaps_playwright_scraper import format_whatsapp, parse_reviews, stable_source_key
except ImportError:
    from gmaps_playwright_scraper import format_whatsapp, parse_reviews, stable_source_key
```

### `Dockerfile`

O servidor importava `supabase_writer.py`, mas o arquivo não era copiado para a imagem. O `COPY` foi corrigido para incluir o módulo:

```dockerfile
COPY src/gmaps_playwright_scraper.py src/gmaps_web_ui.py src/supabase_writer.py ./
```

### `src/gmaps_web_ui.py`

- endpoint `GET /api/health`;
- logs mínimos de startup, criação, polling, início, conclusão e erro do worker;
- retry limitado no `pollJobStatus()`;
- backoff de `1.5s`, `2s`, `3s`, `5s`, `5s`;
- máximo de 5 tentativas;
- mesmo `job_id` durante retry;
- nenhum novo `POST /api/scrape` durante falha de polling;
- resposta HTTP não-2xx no polling agora entra no mesmo fluxo de retry;
- erro terminal informa perda de conectividade e libera o botão.

## Arquivo de testes

Criado:

```text
tests/test_api_job_connectivity.py
```

Cobertura:

- `GET /api/health` retorna 200;
- `POST /api/scrape` retorna `job_id` e `started`;
- `GET /api/job/{id}` responde 200 pelo mesmo servidor;
- job pendente permanece consultável;
- health continua disponível;
- job desconhecido retorna 404, não connection refused.

## Testes automatizados

```text
python -m pytest -q
38 passed

python -m compileall -q src
passed

git diff --check
passed
```

## Teste HTTP real local

Servidor iniciado com:

```bash
python3 src/gmaps_web_ui.py
```

Logs confirmados:

```text
[HTTP] server started :8990
[API] scrape created job=...
[WORKER] job started
[API] job poll id=...
[WORKER] job completed
```

Fluxo real:

```text
GET /api/health
HTTP 200

POST /api/scrape
HTTP 200
status: started
job_id: 1788893194573

GET /api/job/{id}
HTTP 200
estado inicial: running

GET /api/job/{id}
HTTP 200
estado final: completed

GET /api/health após o job
HTTP 200
```

Parâmetros usados:

```json
{
  "category": "clínica",
  "city": "Campo Grande",
  "state": "Mato Grosso do Sul",
  "max_leads": 1,
  "mode": "fast",
  "auto_enrich": false
}
```

Resultado do scraper:

```text
capturados: 1
qualificados: 1
```

O Supabase local estava sem configuração e retornou falha controlada de persistência, sem derrubar API ou worker:

```text
supabase_enabled: false
supabase_failed: 1
```

Isso confirma que falha do writer não causa `ERR_CONNECTION_REFUSED`.

## Teste pelo navegador

Executado com Google Chrome/Playwright contra `http://127.0.0.1:8990`.

Resultado:

```text
POST /api/scrape: 200
GET /api/job/{id}: 200
estado final: Coleta concluída
leads exibidos: 1
botão liberado: sim
ERR_CONNECTION_REFUSED: não
```

O único 404 observado foi `GET /favicon.ico`, sem relação com a API ou polling.

## Regressões não alteradas

Não foram alterados:

- scraper Google Maps;
- scroll dinâmico;
- captura de nome, telefone e endereço;
- Resultados da Web;
- Supabase writer/upsert;
- deduplicação;
- normalização de telefone;
- filtros comerciais;
- FAST/FULL;
- enrichment;
- webhook;
- layout do frontend;
- payloads existentes.

## Publicação

Commit publicado no remote correto:

```text
https://github.com/joel299/webscraping-toolkit
```

```text
4931ef5 fix: keep job api available during scraping
```

## Limite de deploy

Foi verificado o host `vps-b`/Swarm. Não existe serviço Python do `webscraping-toolkit` escutando ou publicado na porta `8990`.

Os serviços encontrados pertencem ao projeto TypeScript `webscrapper` e não foram alterados para evitar publicar a aplicação errada.

Portanto:

```text
GitHub: publicado
Teste HTTP local: aprovado
Teste pelo navegador local: aprovado
Deploy público deste projeto Python: não realizado, pois não existe serviço alvo identificado
```

Não foi feito deploy especulativo em `scraper-ui_webscrapper`.

## Rollback

O commit pode ser revertido normalmente no repositório correto:

```bash
git revert 4931ef5
```
