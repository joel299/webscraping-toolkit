# Project State — Scraper V2

## Identidade validada

- Host: `vps-b` / `216.22.13.46`
- Projeto: `/root/webscraping-toolkit`
- Serviço legado ativo: `scraper-ui_app`
- Branch base lida: `feat/google-maps-scraper-v4`
- HEAD base lido: `1bed948522bbc6a6b6eec3f61f387b511e817269`
- Branch V2: `refactor/scraper-v2-maps-reviews`

## Isolamento

A V2 será construída nesta branch e em serviços separados. Não alterar `scraper-ui_app` até benchmark, E2E, shadow validation e cutover aprovados.

## Referências

Os clones e SHAs estão em `docs/scraper-v2/REUSE_MATRIX.md`. O upstream não é importado diretamente para o source tree sem adapter, pin e licença registrados.

## Estado desta fase

Fase controlada executada: Gosom vanilla compilado e validado; adapter real e 2 processos independentes testados; migration aplicada no Supabase; job V2 e eventos persistidos; 5 leads gravados e lidos de volta. Ainda não há cutover público.
