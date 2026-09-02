# Operação segura

## Antes de executar

1. Confirmar que a origem permite a coleta.
2. Copiar `.env.example` para `.env` e preencher somente os segredos necessários.
3. Executar primeiro com poucos leads.
4. Usar `--dry-run` no envio para MCP.
5. Verificar logs sem publicar dados reais.

## Dados que não devem ir para o GitHub

- CSV/JSON de leads reais.
- Logs com telefone, e-mail, CNPJ ou nome de pessoa.
- Cookies e sessões do navegador.
- Tokens, webhooks privados e credenciais.
- Backups da VPS ou dumps de jobs.

## Rollback

Se um lote externo estiver incorreto, interromper o processo no executor, preservar o `job_id` e revisar o payload antes de qualquer reenvio. Não executar novamente um lote inteiro sem deduplicação.

## Rollout da Etapa 1

1. O padrão operacional é `SCRAPER_DEFAULT_MODE=fast`; use FULL somente em uma
   requisição explicitamente autorizada para enrichment.
2. Rodar três execuções de `full` e três de `fast` com a mesma categoria,
   cidade, estado, quantidade e infraestrutura.
3. Comparar a mediana de `total_pipeline_ms`, `scrape_total_ms`, leads/minuto,
   leads com telefone/WhatsApp, status HTTP do webhook e número de entregas.
4. Só mudar clientes para `mode=fast` se todos os testes chegarem ao webhook
   esperado, com HTTP 2xx, schema compatível e nenhuma duplicidade.

O retorno para o comportamento anterior é imediato:

```bash
export SCRAPER_DEFAULT_MODE=full
```

ou enviando explicitamente `{"mode":"full","auto_enrich":true}`. O frontend
envia FAST explicitamente para evitar que a captura inicial bloqueie em
enrichment. A qualificação permanece disponível pelo endpoint manual de
enrichment quando for desejada.
