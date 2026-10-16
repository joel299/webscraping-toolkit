(() => {
  const tokenKey = 'central-leads-jwt';
  const status = document.getElementById('webmcp-status');
  const authForm = document.getElementById('api-auth-form');
  const authSetup = document.getElementById('api-auth-setup');
  const authStatus = document.getElementById('api-auth-status');
  const emailInput = document.getElementById('api-email');
  const passwordInput = document.getElementById('api-password');
  const token = () => sessionStorage.getItem(tokenKey) || '';

  const authenticate = async (path) => {
    const email = emailInput?.value.trim() || '';
    const password = passwordInput?.value || '';
    if (!email || password.length < 12) {
      if (authStatus) authStatus.textContent = 'Informe um e-mail válido e uma senha com pelo menos 12 caracteres.';
      return;
    }
    if (authStatus) authStatus.textContent = 'Conectando…';
    try {
      const response = await fetch(path, {
        method: 'POST', headers: {'Content-Type': 'application/json', Accept: 'application/json'},
        body: JSON.stringify({email, password}),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.message || `HTTP ${response.status}`);
      sessionStorage.setItem(tokenKey, result.access_token);
      passwordInput.value = '';
      window.dispatchEvent(new CustomEvent('central-leads-authenticated', {detail: {token: result.access_token}}));
      if (authStatus) authStatus.textContent = `Sessão iniciada para ${result.subject}; token válido até ${new Date(result.expires_at).toLocaleString()}.`;
      if (status) status.textContent = 'JWT salvo somente nesta sessão do navegador; WebMCP pronto.';
    } catch (error) {
      if (authStatus) authStatus.textContent = error.message;
    }
  };

  authForm?.addEventListener('submit', (event) => {
    event.preventDefault();
    void authenticate('/api/v1/auth/login');
  });
  authSetup?.addEventListener('click', () => void authenticate('/api/v1/auth/setup'));

  const request = async (path, options = {}) => {
    const headers = new Headers(options.headers || {});
    const jwt = token();
    if (jwt) headers.set('Authorization', `Bearer ${jwt}`);
    if (options.body) headers.set('Content-Type', 'application/json');
    const response = await fetch(path, {...options, headers});
    if (!response.ok) {
      const body = await response.text();
      throw new Error(`HTTP ${response.status}: ${body.slice(0, 400)}`);
    }
    return response;
  };

  const tools = [
    {
      name: 'list_jobs', description: 'Lista pesquisas salvas e seus estados.',
      inputSchema: {type: 'object', properties: {}},
      annotations: {readOnlyHint: true, untrustedContentHint: true},
      execute: async () => (await request('/api/v1/jobs')).json(),
    },
    {
      name: 'create_job', description: 'Inicia uma nova pesquisa no Google Maps. Pode usar recursos do scraper e demorar.',
      inputSchema: {type: 'object', properties: {
        name: {type: 'string'}, keywords: {type: 'array', items: {type: 'string'}}, lang: {type: 'string'},
        zoom: {type: 'integer'}, lat: {type: 'string'}, lon: {type: 'string'}, fast_mode: {type: 'boolean'},
        radius: {type: 'integer'}, depth: {type: 'integer'}, email: {type: 'boolean'}, extra_reviews: {type: 'boolean'},
        max_time: {type: 'integer', description: 'Tempo máximo em segundos'}, proxies: {type: 'array', items: {type: 'string'}},
        confirm: {type: 'boolean', description: 'Defina true para confirmar o início da pesquisa'},
      }, required: ['name', 'keywords', 'lang', 'depth', 'max_time', 'confirm']},
      annotations: {readOnlyHint: false, consequentialHint: true, untrustedContentHint: false},
      execute: async (args) => {
        if (args.confirm !== true) throw new Error('Confirme a criação da pesquisa definindo confirm=true.');
        const {confirm, ...payload} = args;
        return (await request('/api/v1/jobs', {method: 'POST', body: JSON.stringify(payload)})).json();
      },
    },
    {
      name: 'list_leads', description: 'Lista leads consolidados com paginação.',
      inputSchema: {type: 'object', properties: {limit: {type: 'integer'}, offset: {type: 'integer'}}},
      annotations: {readOnlyHint: true, untrustedContentHint: true},
      execute: async ({limit = 100, offset = 0} = {}) => (await request(`/api/v1/leads?limit=${encodeURIComponent(limit)}&offset=${encodeURIComponent(offset)}`)).json(),
    },
    {
      name: 'get_job', description: 'Obtém detalhes de uma pesquisa pelo UUID.',
      inputSchema: {type: 'object', properties: {id: {type: 'string'}}, required: ['id']},
      annotations: {readOnlyHint: true, untrustedContentHint: true},
      execute: async ({id}) => (await request(`/api/v1/jobs/${encodeURIComponent(id)}`)).json(),
    },
    {
      name: 'delete_job', description: 'Exclui permanentemente uma pesquisa e seu CSV. Requer confirmação explícita.',
      inputSchema: {type: 'object', properties: {id: {type: 'string'}, confirm: {type: 'boolean'}}, required: ['id', 'confirm']},
      annotations: {readOnlyHint: false, destructiveHint: true, consequentialHint: true, untrustedContentHint: false},
      execute: async ({id, confirm}) => {
        if (confirm !== true) throw new Error('Confirme a exclusão definindo confirm=true.');
        await request(`/api/v1/jobs/${encodeURIComponent(id)}`, {method: 'DELETE'});
        return {deleted: true, id};
      },
    },
    {
      name: 'download_job_csv', description: 'Obtém o CSV de resultados de uma pesquisa.',
      inputSchema: {type: 'object', properties: {id: {type: 'string'}}, required: ['id']},
      annotations: {readOnlyHint: true, untrustedContentHint: true},
      execute: async ({id}) => ({filename: `${id}.csv`, csv: await (await request(`/api/v1/jobs/${encodeURIComponent(id)}/download`)).text()}),
    },
  ];

  if (!document.modelContext?.registerTool) {
    if (status) status.textContent = 'Este navegador não oferece a API WebMCP. O servidor MCP continua disponível em /mcp.';
    return;
  }

  Promise.all(tools.map((tool) => document.modelContext.registerTool(tool)))
    .then(() => { if (status) status.textContent = `WebMCP ativo: ${tools.length} ferramentas registradas. Entre acima para habilitar as chamadas autenticadas.`; })
    .catch((error) => { if (status) status.textContent = `WebMCP não pôde registrar as ferramentas: ${error.message}`; });
})();
