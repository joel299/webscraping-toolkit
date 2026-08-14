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
