import json
import os
import re
import time
import subprocess
import tempfile
import threading
import urllib.parse
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from threading import Thread

try:
    from . import gmaps_playwright_scraper
except ImportError:
    import gmaps_playwright_scraper

import multiprocessing

MANAGER = None
SCRAPER_JOBS = {}

def get_jobs_dict():
    global MANAGER, SCRAPER_JOBS
    if MANAGER is None:
        MANAGER = multiprocessing.Manager()
        SCRAPER_JOBS = MANAGER.dict()
    return SCRAPER_JOBS
OMNIROUTE_URL = os.environ.get("OMNIROUTE_URL", "")
OMNIROUTE_TOKEN = os.environ.get("OMNIROUTE_TOKEN", "")
DEFAULT_N8N_WEBHOOK = os.environ.get("N8N_WEBHOOK_URL", "")
BRASILAPI_CNPJ_URL = os.environ.get("BRASILAPI_CNPJ_URL", "")
BRASILAPI_MIN_INTERVAL_SECONDS = float(os.environ.get("BRASILAPI_MIN_INTERVAL_SECONDS", "3"))
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "")
FIRECRAWL_API_URL = os.environ.get("FIRECRAWL_API_URL", "https://api.firecrawl.dev/v1/scrape")
BRASILAPI_LOCK = threading.Lock()
BRASILAPI_LAST_CALL = 0.0
BRASILAPI_CACHE = {}

HTML_PORTAL = r'''<!DOCTYPE html>
<html lang="pt-BR" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Stark Scraper Studio</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = { darkMode: 'class', theme: { extend: { colors: { brand: {500:'#C9A227',600:'#a3811c'}, darkbg:'#0f172a', cardbg:'#1e293b' } } } };
  </script>
  <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
  <style>
    .leads-grid { display:grid; grid-template-columns: minmax(150px,1.15fr) minmax(145px,1.05fr) minmax(125px,.9fr) minmax(112px,.8fr) minmax(220px,1.45fr) minmax(78px,.55fr); }
    .lead-cell { min-width:0; overflow-wrap:anywhere; word-break:break-word; }
    .lead-link { display:block; line-height:1.45; }
    @media (max-width: 1180px) { .leads-grid { grid-template-columns: minmax(170px,1fr) minmax(150px,1fr) minmax(130px,.9fr); } .hide-md { display:none; } }
    @media (max-width: 760px) { .leads-grid { display:block; } .lead-row { padding:1rem; } .lead-cell { margin-bottom:.75rem; } .lead-head { display:none; } }
  </style>
</head>
<body class="bg-darkbg text-slate-100 min-h-screen font-sans">
<header class="border-b border-slate-800 bg-slate-900/80 sticky top-0 z-50">
  <div class="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
    <div class="flex items-center gap-3">
      <div class="w-10 h-10 rounded-xl bg-brand-500 flex items-center justify-center text-slate-950 font-black text-xl">S</div>
      <div>
        <h1 class="text-xl font-bold text-white">Stark Studio <span id="phaseBadge" class="text-xs px-2 py-0.5 rounded-full bg-brand-500/20 text-brand-500 border border-brand-500/30">Scrape + Fila</span></h1>
        <p class="text-xs text-slate-400">Captura e qualificação automática de leads</p>
      </div>
    </div>
    <span class="px-3 py-1 rounded-full text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">Sistema Pronto</span>
  </div>
</header>

<main class="max-w-[1600px] mx-auto px-4 xl:px-8 py-8 grid grid-cols-1 xl:grid-cols-12 gap-6">
  <section class="xl:col-span-3 space-y-6">
    <div class="bg-cardbg rounded-2xl p-5 border border-slate-800 shadow-xl">
      <h2 class="text-lg font-semibold mb-4"><i class="fa-solid fa-sliders text-brand-500"></i> Parâmetros da Busca</h2>
      <form id="scraperForm" class="space-y-4">
        <div>
          <label class="block text-xs text-slate-300 mb-1">Categoria / Ramo</label>
          <input id="category" value="estética" required class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white">
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div><label class="block text-xs text-slate-300 mb-1">Cidade</label><input id="city" value="Campo Grande" required class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white"></div>
          <div><label class="block text-xs text-slate-300 mb-1">Estado</label><input id="state" value="Mato Grosso do Sul" required class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white"></div>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div><label class="block text-xs text-slate-300 mb-1">Qtd Máxima Leads</label><input type="number" id="max_leads" value="15" min="1" max="500" required class="w-full bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white"></div>
          <div><label class="block text-xs text-slate-300 mb-1">País</label><input value="Brasil (BR)" disabled class="w-full bg-slate-900/50 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-500"></div>
        </div>
        <input type="hidden" id="webhook" value="">
        <button type="submit" id="btnScrape" class="w-full bg-brand-500 hover:bg-brand-600 text-slate-950 font-bold py-3 rounded-xl flex items-center justify-center gap-2"><i class="fa-solid fa-play"></i> Iniciar Coleta de Leads</button>
        <button type="button" id="btnEnrich" disabled class="hidden w-full bg-slate-700 text-slate-400 font-bold py-3 rounded-xl flex items-center justify-center gap-2 cursor-not-allowed"><i class="fa-solid fa-list-check"></i> Qualificação automática</button>
      </form>
    </div>

    <div id="statusCard" class="hidden bg-cardbg rounded-2xl p-5 border border-slate-800 shadow-xl space-y-4">
      <div class="flex items-center justify-between"><span class="text-xs uppercase text-slate-400">Status</span><span id="jobBadge" class="px-2.5 py-1 rounded-full text-xs bg-amber-500/10 text-amber-400 border border-amber-500/20">Aguardando</span></div>
      <div><div class="flex justify-between text-xs text-slate-300 mb-1"><span id="progressLabel">Progresso</span><span id="jobProgressText">0 / 0</span></div><div class="w-full bg-slate-900 rounded-full h-2"><div id="jobProgressBar" class="bg-brand-500 h-2 rounded-full" style="width:0%"></div></div></div>
      <div id="jobLog" class="text-xs font-mono text-slate-400 bg-slate-900 p-3 rounded-xl border border-slate-800 whitespace-pre-wrap">Aguardando início...</div>
    </div>
  </section>

  <section class="xl:col-span-9 space-y-6">
    <div class="bg-cardbg rounded-2xl p-5 border border-slate-800 shadow-xl">
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
        <div><h2 class="text-lg font-semibold"><i class="fa-solid fa-database text-brand-500"></i> Leads Capturados</h2><p id="resultsCountText" class="text-xs text-slate-400">Nenhum lead carregado ainda.</p></div>
        <div class="flex gap-2"><button id="btnCSV" class="px-3.5 py-2 rounded-xl bg-slate-800 text-xs border border-slate-700">Exportar CSV</button><button id="btnJSON" class="px-3.5 py-2 rounded-xl bg-slate-800 text-xs border border-slate-700">Exportar JSON</button></div>
      </div>
      <div class="rounded-xl border border-slate-800 overflow-hidden">
        <div class="lead-head leads-grid bg-slate-900/90 text-slate-400 uppercase tracking-wider border-b border-slate-800 text-[11px] font-bold">
          <div class="lead-cell px-3 py-3">Empresa / Categoria</div>
          <div class="lead-cell px-3 py-3">Razão Social / CNPJ</div>
          <div class="lead-cell px-3 py-3">Representante / Admin</div>
          <div class="lead-cell px-3 py-3">WhatsApp / Fone</div>
          <div class="lead-cell px-3 py-3">Endereço</div>
          <div class="lead-cell px-3 py-3">Mídias</div>
        </div>
        <div id="leadsTableBody" class="divide-y divide-slate-800/60 bg-slate-900/40 text-xs text-slate-300"><div class="px-4 py-12 text-center text-slate-500">Preencha os parâmetros e inicie a coleta.</div></div>
      </div>
    </div>
  </section>
</main>

<script>
'use strict';
var currentJobId = null;
var pollTimer = null;
var currentLeads = [];

function el(id){ return document.getElementById(id); }
function text(v){ return (v === null || v === undefined || v === '') ? '-' : String(v); }
function arr(v){ return Array.isArray(v) ? v : (v ? [v] : []); }
function esc(s){ return text(s).replace(/[&<>"']/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
function setBadge(label, mode){
  var cls = 'px-2.5 py-1 rounded-full text-xs border ';
  if (mode === 'ok') cls += 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
  else if (mode === 'err') cls += 'bg-rose-500/10 text-rose-400 border-rose-500/20';
  else cls += 'bg-amber-500/10 text-amber-400 border-amber-500/20';
  el('jobBadge').className = cls;
  el('jobBadge').textContent = label;
}
function setProgress(count, total, label){
  total = total || 0; count = count || 0;
  el('progressLabel').textContent = label || 'Progresso';
  el('jobProgressText').textContent = count + ' / ' + total;
  el('jobProgressBar').style.width = total ? Math.min(100, Math.round((count / total) * 100)) + '%' : '5%';
}
function enableEnrich(enable){
  var btn = el('btnEnrich');
  btn.disabled = !enable;
  btn.className = 'hidden';
}

async function startExtraction(ev){
  ev.preventDefault();
  if (pollTimer) clearTimeout(pollTimer);
  currentJobId = null; currentLeads = []; renderLeadsTable([]); enableEnrich(false);
  el('statusCard').classList.remove('hidden');
  el('btnScrape').disabled = true;
  el('btnScrape').innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Iniciando busca...';
  setBadge('Iniciando coleta', 'warn');
  setProgress(0, parseInt(el('max_leads').value, 10), 'Coleta');
  el('jobLog').textContent = 'Iniciando coleta no Google Maps via Playwright...';

  var payload = { category: el('category').value, city: el('city').value, state: el('state').value, max_leads: parseInt(el('max_leads').value, 10), mode: 'fast', auto_enrich: false, webhook: el('webhook').value };
  try {
    var res = await fetch('/api/scrape', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    var data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Falha ao iniciar');
    currentJobId = data.job_id;
    pollJobStatus();
  } catch(err) {
    setBadge('Erro', 'err'); el('jobLog').textContent = err.message; el('btnScrape').disabled = false; el('btnScrape').innerHTML = '<i class="fa-solid fa-play"></i> Tentar novamente';
  }
}

async function startEnrichment(){
  if (!currentJobId) return alert('Nenhum job ativo.');
  enableEnrich(false);
  el('btnEnrich').innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Enriquecendo fila...';
  setBadge('Fila de enriquecimento', 'warn');
  el('jobLog').textContent = 'Enviando leads para fila OmniRoute...';
  try {
    var res = await fetch('/api/enrich/' + encodeURIComponent(currentJobId), { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ webhook: el('webhook').value }) });
    var data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Falha ao iniciar enriquecimento');
    pollJobStatus();
  } catch(err) {
    setBadge('Erro', 'err'); el('jobLog').textContent = err.message; enableEnrich(true); el('btnEnrich').innerHTML = '<i class="fa-solid fa-list-check"></i> Enriquecer Leads com OmniRoute';
  }
}

async function pollJobStatus(){
  if (!currentJobId) return;
  try {
    var res = await fetch('/api/job/' + encodeURIComponent(currentJobId));
    var job = await res.json();
    currentLeads = job.leads || [];
    renderLeadsTable(currentLeads);
    el('jobLog').textContent = job.log || job.message || 'Processando...';
    var phase = job.phase || 'scrape';
    var count = phase === 'enrich' ? (job.enriched_count || 0) : (job.current_count || 0);
    var total = phase === 'enrich' ? (job.enrich_total || currentLeads.length) : job.max_leads;
    setProgress(count, total, phase === 'enrich' ? 'Enriquecimento' : 'Coleta');
    if (job.status === 'pending' || job.status === 'running' || job.status === 'enriching') {
      setBadge(phase === 'enrich' ? 'Enriquecendo fila' : 'Coletando leads', 'warn');
      pollTimer = setTimeout(pollJobStatus, 1500);
    } else if (job.status === 'completed') {
      setBadge('Coleta concluída', 'ok');
      if (currentLeads.length > 0 && job.mode === 'full' && job.auto_enrich === true && !job.enrichment_started) {
        el('jobLog').textContent = 'Coleta concluída. Iniciando qualificação automática...';
        startEnrichment();
      } else {
        el('btnScrape').disabled = false; el('btnScrape').innerHTML = '<i class="fa-solid fa-play"></i> Iniciar Nova Coleta';
      }
    } else if (job.status === 'enriched') {
      setBadge('Enriquecimento concluído', 'ok');
      el('btnScrape').disabled = false; el('btnScrape').innerHTML = '<i class="fa-solid fa-play"></i> Iniciar Nova Coleta';
      el('btnEnrich').innerHTML = '<i class="fa-solid fa-check"></i> Leads Enriquecidos';
    } else if (job.status === 'error') {
      setBadge('Erro', 'err'); el('btnScrape').disabled = false; el('btnScrape').innerHTML = '<i class="fa-solid fa-play"></i> Tentar novamente'; if (currentLeads.length) enableEnrich(true);
    }
  } catch(err) {
    console.error(err);
    setBadge('Erro', 'err');
    el('jobLog').textContent = err.message || 'Falha de comunicação com o servidor.';
    el('btnScrape').disabled = false;
    el('btnScrape').innerHTML = '<i class="fa-solid fa-play"></i> Tentar novamente';
  }
}

function renderLeadsTable(leads){
  var tbody = el('leadsTableBody');
  el('resultsCountText').textContent = leads.length ? leads.length + ' lead(s) carregado(s).' : 'Nenhum lead carregado ainda.';
  if (!leads.length) { tbody.innerHTML = '<div class="px-4 py-12 text-center text-slate-500">Aguardando leads...</div>'; return; }
  tbody.innerHTML = leads.map(function(item){
    var links = [];
    arr(item.instagram).forEach(function(u){ links.push('<a target="_blank" class="lead-link text-pink-400" href="'+esc(u)+'">Instagram</a>'); });
    arr(item.facebook).forEach(function(u){ links.push('<a target="_blank" class="lead-link text-blue-400" href="'+esc(u)+'">Facebook</a>'); });
    arr(item.linkedin).forEach(function(u){ links.push('<a target="_blank" class="lead-link text-sky-400" href="'+esc(u)+'">LinkedIn</a>'); });
    if (item.website) links.push('<a target="_blank" class="lead-link text-slate-300" href="'+esc(item.website)+'">Site</a>');
    if (item.google_maps_url) links.push('<a target="_blank" class="lead-link text-slate-300" href="'+esc(item.google_maps_url)+'">Maps</a>');
    return '<div class="lead-row leads-grid hover:bg-slate-800/40">'
      + '<div class="lead-cell px-3 py-3"><div class="md:hidden text-[10px] uppercase text-slate-500 mb-1">Empresa</div><div class="font-bold text-white leading-snug">'+esc(item.place_name)+'</div><div class="text-slate-500 mt-1">'+esc(item.category)+'</div></div>'
      + '<div class="lead-cell px-3 py-3"><div class="md:hidden text-[10px] uppercase text-slate-500 mb-1">Razão Social / CNPJ</div><div class="leading-snug">'+esc(item.legal_name)+'</div><div class="font-mono text-brand-500 mt-1">'+esc(item.cnpj)+'</div></div>'
      + '<div class="lead-cell px-3 py-3"><div class="md:hidden text-[10px] uppercase text-slate-500 mb-1">Representante</div><div class="leading-snug">'+esc(item.owner_name)+'</div><div class="text-slate-500 mt-1">'+esc(item.administrator_name)+'</div></div>'
      + '<div class="lead-cell px-3 py-3"><div class="md:hidden text-[10px] uppercase text-slate-500 mb-1">WhatsApp</div><div class="font-mono text-emerald-400">'+esc(item.whatsapp)+'</div><div class="text-slate-500 mt-1">'+esc(item.phone_raw)+'</div></div>'
      + '<div class="lead-cell px-3 py-3"><div class="md:hidden text-[10px] uppercase text-slate-500 mb-1">Endereço</div><div class="leading-snug">'+esc(item.address || item.street)+'</div></div>'
      + '<div class="lead-cell px-3 py-3"><div class="md:hidden text-[10px] uppercase text-slate-500 mb-1">Mídias</div><div>'+((links.join('')) || '-')+'</div></div>'
      + '</div>';
  }).join('');
}

function exportJSON(){ if (!currentLeads.length) return alert('Sem leads para exportar.'); download('gmaps_leads_' + Date.now() + '.json', 'application/json', JSON.stringify(currentLeads, null, 2)); }
function exportCSV(){
  if (!currentLeads.length) return alert('Sem leads para exportar.');
  var headers = ['place_name','category','legal_name','cnpj','owner_name','administrator_name','total_score','reviews_count','whatsapp','phone_raw','address','website','instagram','facebook','linkedin','emails','google_maps_url'];
  var rows = [headers.join(',')];
  currentLeads.forEach(function(row){ rows.push(headers.map(function(h){ var v = row[h] || ''; if (Array.isArray(v)) v = v.join('; '); return '"' + String(v).replace(/"/g, '""') + '"'; }).join(',')); });
  download('gmaps_leads_' + Date.now() + '.csv', 'text/csv', rows.join('\n'));
}
function download(name, type, content){ var a = document.createElement('a'); a.href = 'data:' + type + ';charset=utf-8,' + encodeURIComponent(content); a.download = name; document.body.appendChild(a); a.click(); a.remove(); }

document.addEventListener('DOMContentLoaded', function(){ el('scraperForm').addEventListener('submit', startExtraction); el('btnEnrich').addEventListener('click', startEnrichment); el('btnCSV').addEventListener('click', exportCSV); el('btnJSON').addEventListener('click', exportJSON); });
</script>
</body>
</html>
'''

def clean_text(value):
    return str(value or '').strip()

def as_list(value):
    if value is None or value == '':
        return []
    if isinstance(value, list):
        return value
    return [value]

def clean_url_value(value):
    value = str(value or '').strip()
    if value.startswith('@url:`') and value.endswith('`'):
        value = value[6:-1]
    if value.startswith('/url?') or 'google.com/url?' in value:
        parsed = urllib.parse.urlparse(value)
        qs = urllib.parse.parse_qs(parsed.query)
        if qs.get('q'):
            value = qs['q'][0]
    return value.strip()

def clean_social_url(raw_url, kind):
    if not raw_url:
        return None
    url = clean_url_value(raw_url)
    if not url:
        return None
    if url.startswith('@url:`') and url.endswith('`'):
        url = url[6:-1]
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return None

    domain = (parsed.netloc or '').lower()
    path = parsed.path or ''

    if kind == 'instagram':
        if 'instagram.com' not in domain:
            return None
        bad_paths = {'p', 'reel', 'reels', 'stories', 'story', 'tv', 'share', 'explore', 'direct', 'accounts', 'developer', 'about', 'help', 'legal', 'terms', 'privacy', 'popular', 'web'}
        parts = [p for p in path.strip('/').split('/') if p]
        if not parts:
            return None
        first_part = parts[0].lower()
        if first_part in bad_paths:
            return None
        username = parts[0]
        if re.match(r'^[A-Za-z0-9._]{1,30}$', username):
            return f"https://www.instagram.com/{username}/"
        return None

    elif kind == 'facebook':
        if 'facebook.com' not in domain and 'fb.com' not in domain:
            return None
        bad_paths = {'posts', 'post', 'photos', 'photo', 'videos', 'video', 'watch', 'groups', 'events', 'sharer', 'share', 'permalink.php', 'story.php', 'help', 'legal', 'pages/category', 'login', 'signup', 'dialog', 'developers'}
        parts = [p for p in path.strip('/').split('/') if p]
        if not parts:
            qs = urllib.parse.parse_qs(parsed.query)
            if 'id' in qs and qs['id'][0].isdigit():
                return f"https://www.facebook.com/profile.php?id={qs['id'][0]}"
            return None
        first_part = parts[0].lower()
        if first_part in bad_paths:
            return None
        if first_part == 'profile.php':
            qs = urllib.parse.parse_qs(parsed.query)
            if 'id' in qs and qs['id'][0].isdigit():
                return f"https://www.facebook.com/profile.php?id={qs['id'][0]}"
            return None
        page_name = parts[0]
        if re.match(r'^[A-Za-z0-9._-]{1,100}$', page_name):
            return f"https://www.facebook.com/{page_name}/"
        return None

    elif kind == 'linkedin':
        if 'linkedin.com' not in domain:
            return None
        bad_paths = {'posts', 'post', 'pulse', 'jobs', 'feed', 'share', 'help', 'legal'}
        parts = [p for p in path.strip('/').split('/') if p]
        if len(parts) < 2:
            return None
        prefix = parts[0].lower()
        if prefix in bad_paths:
            return None
        if prefix in ('in', 'company', 'school'):
            name = parts[1]
            if re.match(r'^[A-Za-z0-9._-]{1,100}$', name):
                return f"https://www.linkedin.com/{prefix}/{name}/"
        return None

    return None

def clean_social_list(values, kind):
    cleaned = []
    for raw in as_list(values):
        cleaned_url = clean_social_url(raw, kind)
        if cleaned_url and cleaned_url not in cleaned:
            cleaned.append(cleaned_url)
    return cleaned

def clean_email_list(values):
    cleaned = []
    for raw in as_list(values):
        email = str(raw or '').strip().lower()
        if not email or 'sentry' in email or email.endswith(('.png', '.jpg', '.jpeg', '.webp', '.svg')):
            continue
        if email not in cleaned:
            cleaned.append(email)
    return cleaned

def public_lead(item):
    return {
        'nome': clean_text(item.get('place_name')),
        'categoria': clean_text(item.get('category')),
        'nota': clean_text(item.get('total_score')),
        'avaliacoes': clean_text(item.get('reviews_count')),
        'endereco': clean_text(item.get('address')),
        'rua': clean_text(item.get('street')),
        'cidade': clean_text(item.get('city')),
        'estado': clean_text(item.get('state')),
        'pais': clean_text(item.get('country_code') or 'BR'),
        'telefone': clean_text(item.get('phone_raw')),
        'whatsapp': clean_text(item.get('whatsapp')),
        'site': clean_url_value(item.get('website')),
        'google_maps': clean_url_value(item.get('google_maps_url')),
        'instagram': clean_social_list(item.get('instagram'), 'instagram'),
        'facebook': clean_social_list(item.get('facebook'), 'facebook'),
        'linkedin': clean_social_list(item.get('linkedin'), 'linkedin'),
        'emails': clean_email_list(item.get('emails')),
        'google_sponsored': bool(item.get('google_sponsored', False)),
        'web_results': item.get('web_results') or [],
        'instagram_source': clean_text(item.get('instagram_source')),
        'cnpj_source': clean_text(item.get('cnpj_source')),
        'qualification_status': clean_text(item.get('qualification_status') or 'candidate'),
        'qualification': clean_text(item.get('qualification')),
        'razao_social': clean_text(item.get('legal_name')),
        'cnpj': clean_text(item.get('cnpj')),
        'representante_legal': clean_text(item.get('owner_name')),
        'administrador': clean_text(item.get('administrator_name')),
        'situacao_cadastral': clean_text(item.get('situacao_cadastral')),
        'data_abertura': clean_text(item.get('data_abertura')),
        'atividade_principal': clean_text(item.get('atividade_principal')),
        'natureza_juridica': clean_text(item.get('natureza_juridica')),
        'quadro_societario': item.get('quadro_societario') or [],
    }

def looks_like_person(value):
    value = re.sub(r'\s+', ' ', str(value or '')).strip(' .,-:;')
    if not value:
        return ''
    bad = ['representante legal', 'instagram', 'facebook', 'linkedin', 'email', 'cnpj', 'sócio', 'socio', 'administrador']
    if any(b in value.lower() for b in bad):
        return ''
    parts = value.split()
    if len(parts) < 2 or len(parts) > 6:
        return ''
    if not all(re.match(r'^[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-zÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç.-]+$', p) for p in parts):
        return ''
    return value

def parse_enrichment_text(text):
    text = clean_text(text)
    out = {'cnpj': '', 'legal_name': '', 'owner_name': '', 'administrator_name': '', 'instagram': [], 'facebook': [], 'linkedin': [], 'emails': []}
    cnpj = re.search(r'\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b', text)
    if cnpj:
        digits = re.sub(r'\D+', '', cnpj.group(0))
        if len(digits) == 14:
            out['cnpj'] = f'{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}'
    legal_patterns = [
        r'(?:Razão Social|Nome Empresarial|Empresa)[:\s-]+([A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9][A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9\s.&,-]{3,90}\s(?:LTDA|EIRELI|EPP|ME|S/A|SA))\b',
        r'([A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9][A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9\s.&,-]{3,90}\s(?:LTDA|EIRELI|EPP|ME|S/A|SA))\b',
    ]
    for pat in legal_patterns:
        m = re.search(pat, text, re.I)
        if m:
            out['legal_name'] = re.sub(r'\s+', ' ', m.group(1)).strip(' ,-')
            break
    owner_patterns = [
        r'(?:Sócio-Administrador|Sócio Administrador|Representante Legal|Administrador|Proprietário|Sócio)[:\s-]+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-zÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç.\s-]{5,80})',
        r'(?:QSA|Quadro de Sócios).*?([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-Za-zÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç.\s-]{5,80})',
    ]
    for pat in owner_patterns:
        m = re.search(pat, text, re.I | re.S)
        if m:
            person = looks_like_person(m.group(1))
            if person:
                out['owner_name'] = person
                out['administrator_name'] = person
                break
    for url in re.findall(r'https?://[^\s"\'<>]+', text):
        u = clean_url_value(url.rstrip(').,;]'))
        if 'instagram.com' in u and u not in out['instagram']:
            out['instagram'].append(u)
        elif 'facebook.com' in u and u not in out['facebook']:
            out['facebook'].append(u)
        elif 'linkedin.com' in u and u not in out['linkedin']:
            out['linkedin'].append(u)
    for email in re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', text):
        em = email.lower()
        if 'sentry' not in em and em not in out['emails'] and not em.endswith(('.png', '.jpg', '.jpeg', '.webp', '.svg')):
            out['emails'].append(em)
    out['instagram'] = clean_social_list(out['instagram'], 'instagram')
    out['facebook'] = clean_social_list(out['facebook'], 'facebook')
    out['linkedin'] = clean_social_list(out['linkedin'], 'linkedin')
    out['emails'] = clean_email_list(out['emails'])
    return out

def normalize_cnpj(value):
    digits = re.sub(r'\D+', '', str(value or ''))
    return digits if len(digits) == 14 else ''

def format_cnpj(value):
    digits = normalize_cnpj(value)
    if not digits:
        return ''
    return f'{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}'

def brasilapi_lookup_cnpj(cnpj):
    global BRASILAPI_LAST_CALL
    digits = normalize_cnpj(cnpj)
    if not digits:
        return None
    if digits in BRASILAPI_CACHE:
        return BRASILAPI_CACHE[digits]
    with BRASILAPI_LOCK:
        elapsed = time.time() - BRASILAPI_LAST_CALL
        if elapsed < BRASILAPI_MIN_INTERVAL_SECONDS:
            time.sleep(BRASILAPI_MIN_INTERVAL_SECONDS - elapsed)
        attempts = 0
        while attempts < 4:
            attempts += 1
            req = urllib.request.Request(BRASILAPI_CNPJ_URL + digits, method='GET')
            req.add_header('Accept', 'application/json')
            req.add_header('User-Agent', 'StarkLeadEnrichment/1.0')
            BRASILAPI_LAST_CALL = time.time()
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    BRASILAPI_CACHE[digits] = data
                    return data
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    retry_after = exc.headers.get('Retry-After')
                    wait = int(retry_after) if retry_after and retry_after.isdigit() else min(60, 10 * attempts)
                    time.sleep(wait)
                    continue
                BRASILAPI_CACHE[digits] = None
                return None
            except Exception:
                if attempts >= 4:
                    BRASILAPI_CACHE[digits] = None
                    return None
                time.sleep(min(30, 5 * attempts))
    return None

def apply_brasilapi_data(enriched, data):
    if not data:
        return enriched
    cnpj = format_cnpj(data.get('cnpj'))
    if cnpj:
        enriched['cnpj'] = cnpj
    if data.get('razao_social'):
        enriched['legal_name'] = str(data.get('razao_social')).strip()
    enriched['situacao_cadastral'] = clean_text(data.get('descricao_situacao_cadastral') or data.get('situacao_cadastral'))
    enriched['data_abertura'] = clean_text(data.get('data_inicio_atividade'))
    enriched['natureza_juridica'] = clean_text(data.get('natureza_juridica'))
    atividade = data.get('cnae_fiscal_descricao') or ''
    if not atividade and isinstance(data.get('cnaes_secundarios'), list) and data['cnaes_secundarios']:
        atividade = data['cnaes_secundarios'][0].get('descricao', '')
    enriched['atividade_principal'] = clean_text(atividade)
    socios = []
    admin_name = ''
    for socio in data.get('qsa') or []:
        nome = clean_text(socio.get('nome_socio'))
        qual = clean_text(socio.get('qualificacao_socio'))
        rep = clean_text(socio.get('nome_representante_legal'))
        if nome:
            socios.append({
                'nome': nome,
                'qualificacao': qual,
                'representante_legal': rep,
                'data_entrada': clean_text(socio.get('data_entrada_sociedade')),
                'faixa_etaria': clean_text(socio.get('faixa_etaria')),
            })
            if not admin_name and 'administrador' in qual.lower():
                admin_name = nome
    enriched['quadro_societario'] = socios
    if admin_name:
        enriched['owner_name'] = admin_name
        enriched['administrator_name'] = admin_name
    elif socios and not enriched.get('owner_name'):
        enriched['owner_name'] = socios[0]['nome']
        enriched['administrator_name'] = socios[0]['nome']
    return enriched

def firecrawl_fetch_text(url):
    """Use Firecrawl only when the local/browser path cannot read a site."""
    if not FIRECRAWL_API_KEY or not url:
        return ''
    payload = json.dumps({'url': url, 'formats': ['markdown']}).encode('utf-8')
    req = urllib.request.Request(
        FIRECRAWL_API_URL,
        data=payload,
        headers={'Authorization': f'Bearer {FIRECRAWL_API_KEY}', 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            result = data.get('data') or data.get('result') or data
            return clean_text((result or {}).get('markdown') or (result or {}).get('content'))
    except Exception:
        return ''

def omniroute_search(query, max_results=5, provider=None):
    if SERPER_API_KEY and not provider:
        req = urllib.request.Request(
            'https://google.serper.dev/search',
            data=json.dumps({'q': query, 'num': max_results}, ensure_ascii=False).encode('utf-8'),
            headers={'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return {
                    'provider': 'serper',
                    'results': [
                        {'title': x.get('title', ''), 'url': x.get('link', ''), 'snippet': x.get('snippet', '')}
                        for x in data.get('organic', [])
                    ],
                }
        except Exception:
            pass
    if not OMNIROUTE_URL or not OMNIROUTE_TOKEN:
        return {}
    providers_to_try = [provider] if provider else [None, 'serper-search', 'duckduckgo-free']
    last_res = {}
    for p in providers_to_try:
        body = {'query': query, 'max_results': max_results}
        if p:
            body['provider'] = p
        payload = json.dumps(body, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(OMNIROUTE_URL, data=payload, method='POST')
        req.add_header('Authorization', 'Bearer ' + OMNIROUTE_TOKEN)
        req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                last_res = data
                if data and (data.get('results') or data.get('answer')):
                    return data
        except Exception:
            continue
    return last_res

def lead_domain(lead):
    site = clean_url_value(lead.get('website'))
    if not site:
        return ''
    try:
        return urllib.parse.urlparse(site).netloc.replace('www.', '')
    except Exception:
        return ''

def merge_parsed(dst, parsed):
    for key in ('cnpj', 'legal_name', 'owner_name', 'administrator_name'):
        if parsed.get(key) and not dst.get(key):
            dst[key] = format_cnpj(parsed[key]) if key == 'cnpj' else parsed[key]
    for key, kind in (('instagram','instagram'), ('facebook','facebook'), ('linkedin','linkedin')):
        merged = clean_social_list(dst.get(key), kind)
        for item in clean_social_list(parsed.get(key), kind):
            if item not in merged:
                merged.append(item)
        dst[key] = merged
    emails = clean_email_list(dst.get('emails'))
    for item in clean_email_list(parsed.get('emails')):
        if item not in emails:
            emails.append(item)
    dst['emails'] = emails
    return dst

def fetch_website_content(url):
    url = clean_url_value(url)
    if not url or any(dom in url.lower() for dom in ('instagram.com', 'facebook.com', 'google.com/maps', 'wa.me', 'api.whatsapp.com')):
        return ''
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get('Content-Type', '').lower()
            if 'text/html' in content_type or 'text/plain' in content_type or not content_type:
                html = resp.read().decode('utf-8', errors='ignore')
                text = re.sub(r'<script.*?</script>', ' ', html, flags=re.DOTALL | re.I)
                text = re.sub(r'<style.*?</style>', ' ', text, flags=re.DOTALL | re.I)
                text = re.sub(r'<[^>]+>', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                return text
    except Exception:
        pass
    return ''

def omniroute_extract_website_data(website_url, page_text):
    if not OMNIROUTE_TOKEN or not page_text or len(page_text.strip()) < 50:
        return {}
    url = os.environ.get("OMNIROUTE_RESPONSES_URL", "")
    if not url:
        return {}
    headers = {
        "Authorization": f"Bearer {OMNIROUTE_TOKEN}",
        "Content-Type": "application/json"
    }
    prompt = (
        "Analise o texto extraído do website da empresa e extraia as seguintes informações em JSON estrito (sem markdown):\n"
        "{\n"
        '  "cnpj": "CNPJ de 14 dígitos com pontuação ou string vazia",\n'
        '  "legal_name": "Razão Social ou string vazia",\n'
        '  "owner_name": "Nome do proprietário/sócio/administrador ou string vazia",\n'
        '  "instagram": ["URL do perfil do Instagram"],\n'
        '  "facebook": ["URL do perfil do Facebook"],\n'
        '  "linkedin": ["URL do perfil do LinkedIn"],\n'
        '  "emails": ["Endereço de e-mail"]\n'
        "}\n\n"
        f"URL: {website_url}\n"
        f"Conteúdo:\n{page_text[:6000]}"
    )
    payload = {"model": "auto/best-coding", "input": prompt}
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            output_text = data.get('output_text') or ''
            json_match = re.search(r'\{.*\}', output_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
    except Exception:
        pass
    return {}

def enrich_lead_with_omniroute(lead, city, state):
    name = clean_text(lead.get('place_name'))
    address = clean_text(lead.get('address') or lead.get('street'))
    street = clean_text(lead.get('street'))
    domain = lead_domain(lead)
    queries = []
    base = f'{name} {address} {city} {state}'
    queries.append(f'{name}+{address}+cnpj')
    queries.append(f'{name} {address} cnpj')
    queries.append(f'{base} CNPJ razão social sócio administrador')
    if domain:
        queries.append(f'{domain} CNPJ razão social sócio administrador')
    queries.append(f'site:cnpj.biz {name} {city}')
    queries.append(f'site:empresascnpj.com {name} {city}')

    enriched = dict(lead)
    for key in ('owner_name', 'administrator_name', 'legal_name', 'cnpj'):
        enriched[key] = clean_text(enriched.get(key))
    enriched['website'] = clean_url_value(enriched.get('website'))
    enriched['google_maps_url'] = clean_url_value(enriched.get('google_maps_url'))
    enriched['instagram'] = clean_social_list(enriched.get('instagram'), 'instagram')
    enriched['facebook'] = clean_social_list(enriched.get('facebook'), 'facebook')
    enriched['linkedin'] = clean_social_list(enriched.get('linkedin'), 'linkedin')
    enriched['emails'] = clean_email_list(enriched.get('emails'))

    # Google Maps is the primary source. Do not spend external quota for
    # fields already present in the Maps profile or its web-results block.
    google_cnpj = clean_text(enriched.get('google_result_cnpj'))
    if google_cnpj and not enriched.get('cnpj'):
        enriched['cnpj'] = format_cnpj(google_cnpj)

    search_ids = []
    provider = ''
    if not (enriched.get('cnpj') and enriched.get('website') and enriched.get('instagram')):
        for q in queries:
            try:
                response = omniroute_search(q, max_results=5)
                provider = response.get('provider') or provider
                if response.get('id'):
                    search_ids.append(response.get('id'))
                chunks = [json.dumps(response.get('answer') or '', ensure_ascii=False)]
                for result in response.get('results') or []:
                    chunks.append(' '.join(clean_text(result.get(k)) for k in ('title', 'url', 'snippet', 'description', 'content')))
                parsed = parse_enrichment_text('\n'.join(chunks))
                enriched = merge_parsed(enriched, parsed)
                if enriched.get('cnpj') and enriched.get('website') and enriched.get('instagram'):
                    break
                time.sleep(0.5)
            except Exception as exc:
                enriched['enrichment_error'] = str(exc)
    if not enriched.get('cnpj') and enriched.get('website'):
        web_text = fetch_website_content(enriched.get('website'))
        if not web_text:
            web_text = firecrawl_fetch_text(enriched.get('website'))
        if web_text:
            parsed_web = parse_enrichment_text(web_text)
            enriched = merge_parsed(enriched, parsed_web)
            if not enriched.get('cnpj'):
                llm_web = omniroute_extract_website_data(enriched.get('website'), web_text)
                enriched = merge_parsed(enriched, llm_web)

    cnpj_digits = normalize_cnpj(enriched.get('cnpj'))
    if cnpj_digits:
        enriched = apply_brasilapi_data(enriched, brasilapi_lookup_cnpj(cnpj_digits))
    # Internal state only; stripped from final payload
    enriched['_enrichment_provider'] = provider
    enriched['_enrichment_search_ids'] = search_ids
    enriched['_enrichment_status'] = 'found' if enriched.get('cnpj') else 'not_found'
    return enriched

def send_to_n8n(payload, webhook_url):
    if not payload.get('leads'):
        return {'ok': False, 'error': 'payload sem leads'}
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    # Use curl because urllib occasionally hangs inside the Swarm container on this route.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.json') as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        cmd = [
            'curl', '-sS', '--max-time', '60', '-w', '\nHTTP:%{http_code}\nTIME:%{time_total}\n',
            '-X', 'POST', webhook_url,
            '-H', 'Content-Type: application/json; charset=utf-8',
            '--data-binary', '@' + tmp_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=70)
        out = (res.stdout or '') + (res.stderr or '')
        status_match = re.search(r'HTTP:(\d+)', out)
        http_status = int(status_match.group(1)) if status_match else 0
        return {'ok': res.returncode == 0 and 200 <= http_status < 300, 'status': http_status, 'body': out[:2000]}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

def make_payload(job):
    leads = [public_lead(item) for item in (job.get('leads') or [])]
    return {
        'categoria': clean_text(job.get('category')),
        'cidade': clean_text(job.get('city')),
        'estado': clean_text(job.get('state')),
        'total': len(leads),
        'leads': leads,
    }

def _mark_timing(job, prefix, started=False):
    if started:
        job[f'{prefix}_started_at'] = time.time()
    else:
        job[f'{prefix}_finished_at'] = time.time()

def _send_webhook_once(job, payload, webhook_url):
    if job.get('webhook_sent'):
        return job.get('n8n_response') or {'ok': True, 'duplicate_prevented': True}
    if not webhook_url:
        return {'ok': False, 'error': 'webhook não configurado'}
    _mark_timing(job, 'webhook', started=True)
    response = send_to_n8n(payload, webhook_url)
    _mark_timing(job, 'webhook')
    job['webhook_ms'] = round((job['webhook_finished_at'] - job['webhook_started_at']) * 1000, 2)
    job['n8n_response'] = response
    job['webhook_sent'] = bool(response.get('ok'))
    return response


class JobProxy(dict):
    def __init__(self, job_id, jobs_dict, initial_data):
        super().__init__(initial_data)
        self.job_id = job_id
        self.jobs_dict = jobs_dict
        self.sync()

    def sync(self):
        if self.jobs_dict is not None:
            try:
                self.jobs_dict[self.job_id] = dict(self)
            except Exception:
                pass

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.sync()

def run_enrich_inline(job_proxy, webhook_url=None):
    leads = list(job_proxy.get('leads') or [])
    if not leads:
        job_proxy['status'] = 'completed'
        job_proxy['log'] = 'Coleta concluída, nenhum lead para qualificar.'
        job_proxy.sync()
        return

    job_proxy['enrichment_started_at'] = time.time()
    job_proxy['status'] = 'enriching'
    job_proxy['phase'] = 'enrich'
    job_proxy['enrichment_started'] = True
    job_proxy['enriched_count'] = 0
    job_proxy['enrich_total'] = len(leads)
    job_proxy['log'] = 'Qualificação automática iniciada...'
    job_proxy.sync()

    enriched = []
    try:
        for idx, lead in enumerate(leads, start=1):
            name = lead.get('place_name') or 'lead sem nome'
            job_proxy['log'] = f'Qualificando {idx}/{job_proxy["enrich_total"]}: {name}'
            job_proxy.sync()
            try:
                enriched_lead = enrich_lead_with_omniroute(lead, job_proxy.get('city'), job_proxy.get('state'))
            except Exception as exc:
                enriched_lead = dict(lead)
                enriched_lead['_enrichment_status'] = 'error'
                enriched_lead['_enrichment_error'] = str(exc)
            enriched.append(enriched_lead)
            remaining = leads[idx:]
            job_proxy['leads'] = enriched + remaining
            job_proxy['enriched_count'] = idx
            job_proxy['payload'] = make_payload(job_proxy)
            job_proxy.sync()
            if idx < job_proxy['enrich_total']:
                time.sleep(1.5)

        final_payload = make_payload(job_proxy)
        job_proxy['payload'] = final_payload
        json_path = f"/tmp/webscrapper_job_{job_proxy['job_id']}.json"
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(final_payload, f, ensure_ascii=False, indent=2)
            job_proxy['json_path'] = json_path
        except Exception:
            pass

        job_proxy['status'] = 'enriched'
        job_proxy['phase'] = 'enrich'
        job_proxy['finished_enrichment_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        job_proxy['log'] = 'Qualificação concluída. Enviando leads para automação...'
        job_proxy.sync()

        if not final_payload.get('leads'):
            job_proxy['n8n_response'] = {'ok': False, 'error': 'payload sem leads; envio bloqueado'}
            job_proxy['webhook_sent'] = False
            job_proxy['log'] = 'Qualificação concluída, mas nenhum lead foi enviado.'
        else:
            try:
                webhook_target = webhook_url or job_proxy.get('webhook') or DEFAULT_N8N_WEBHOOK
                response = _send_webhook_once(job_proxy, final_payload, webhook_target)
                job_proxy['n8n_response'] = response
                job_proxy['webhook_sent'] = bool(response.get('ok'))
            except Exception as exc:
                job_proxy['n8n_response'] = {'ok': False, 'error': str(exc)}
                job_proxy['webhook_sent'] = False
            job_proxy['enrichment_finished_at'] = time.time()
        job_proxy['enrichment_ms'] = round((job_proxy['enrichment_finished_at'] - job_proxy['enrichment_started_at']) * 1000, 2)
        job_proxy['log'] = 'Leads qualificados enviados para automação.' if job_proxy.get('webhook_sent') else 'Leads qualificados, mas o envio para automação falhou.'
        if job_proxy.get('job_started_at'):
            job_proxy['total_pipeline_ms'] = round((time.time() - job_proxy['job_started_at']) * 1000, 2)
        job_proxy.sync()

    except Exception as exc:
        job_proxy['status'] = 'error'
        job_proxy['error'] = str(exc)
        job_proxy['log'] = 'Erro na qualificação: ' + str(exc)
        job_proxy.sync()

def worker_scrape_process(job_id, category, city, state, max_leads, webhook_url, jobs_dict, mode='full'):
    initial_job = dict(jobs_dict.get(job_id) or {})
    job_proxy = JobProxy(job_id, jobs_dict, initial_job)
    try:
        leads = gmaps_playwright_scraper.scrape_gmaps(job_id, category, city, state, max_leads, None, job_proxy, mode=mode)
        job_proxy['leads'] = leads or job_proxy.get('leads') or []
        job_proxy['current_count'] = len(job_proxy['leads'])
        job_proxy['status'] = 'completed'
        job_proxy['phase'] = 'scrape'
        job_proxy['finished_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        job_proxy['log'] = f'Coleta concluída: {len(job_proxy["leads"])} leads.'
        job_proxy.sync()
        if mode == 'fast':
            final_payload = make_payload(job_proxy)
            job_proxy['payload'] = final_payload
            webhook_target = webhook_url or job_proxy.get('webhook') or DEFAULT_N8N_WEBHOOK
            if final_payload.get('leads') and webhook_target:
                response = _send_webhook_once(job_proxy, final_payload, webhook_target)
                job_proxy['sent_to_webhook'] = bool(response.get('ok'))
                job_proxy['log'] = 'Coleta concluída e leads enviados para automação.' if response.get('ok') else 'Coleta concluída, mas o envio para automação falhou.'
            else:
                job_proxy['n8n_response'] = {'ok': False, 'error': 'webhook não configurado ou payload sem leads'}
                job_proxy['webhook_sent'] = False
            if job_proxy.get('job_started_at'):
                job_proxy['total_pipeline_ms'] = round((time.time() - job_proxy['job_started_at']) * 1000, 2)
            job_proxy['job_finished_at'] = time.time()
            job_proxy.sync()
        elif job_proxy.get('auto_enrich', True):
            run_enrich_inline(job_proxy, webhook_url)
        else:
            job_proxy['log'] = 'Coleta concluída. Enriquecimento aguardando acionamento manual.'
            job_proxy.sync()
    except Exception as exc:
        job_proxy['status'] = 'error'
        job_proxy['error'] = str(exc)
        job_proxy['log'] = 'Erro na coleta: ' + str(exc)
        job_proxy.sync()

def start_enrichment_job(job_id, webhook_url=None):
    jobs_dict = get_jobs_dict()
    job = jobs_dict.get(job_id)
    if job and job.get('mode') == 'fast':
        return False
    if not job or not job.get('leads') or job.get('status') == 'enriching':
        return False
    webhook_url = webhook_url or job.get('webhook') or DEFAULT_N8N_WEBHOOK
    job_copy = dict(job)
    job_copy['webhook'] = webhook_url
    job_copy['status'] = 'enriching'
    job_copy['phase'] = 'enrich'
    job_copy['enrichment_started'] = True
    job_copy['enriched_count'] = 0
    job_copy['enrich_total'] = len(job_copy['leads'])
    job_copy['log'] = 'Qualificação automática iniciada...'
    jobs_dict[job_id] = job_copy

    def run_enrich():
        jobs_dict = get_jobs_dict()
        job = dict(jobs_dict.get(job_id) or {})
        enriched = []
        try:
            for idx, lead in enumerate(list(job.get('leads') or []), start=1):
                name = lead.get('place_name') or 'lead sem nome'
                job['log'] = f'Qualificando {idx}/{job["enrich_total"]}: {name}'
                try:
                    enriched_lead = enrich_lead_with_omniroute(lead, job.get('city'), job.get('state'))
                except Exception as exc:
                    enriched_lead = dict(lead)
                    enriched_lead['_enrichment_status'] = 'error'
                    enriched_lead['_enrichment_error'] = str(exc)
                enriched.append(enriched_lead)
                remaining = list(job.get('leads') or [])[idx:]
                job['leads'] = enriched + remaining
                job['enriched_count'] = idx
                job['payload'] = make_payload(job)
                jobs_dict[job_id] = dict(job)
                if idx < job['enrich_total']:
                    time.sleep(2)
            final_payload = make_payload(job)
            job['payload'] = final_payload
            json_path = f'/root/webscrapper_job_{job_id}.json'
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(final_payload, f, ensure_ascii=False, indent=2)
            job['json_path'] = json_path
            job['status'] = 'enriched'
            job['phase'] = 'enrich'
            job['finished_enrichment_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
            job['log'] = 'Qualificação concluída. Enviando leads para automação...'
            if not final_payload.get('leads'):
                job['n8n_response'] = {'ok': False, 'error': 'payload sem leads; envio bloqueado'}
                job['webhook_sent'] = False
                job['log'] = 'Qualificação concluída, mas nenhum lead foi enviado.'
            else:
                try:
                    job['n8n_response'] = send_to_n8n(final_payload, webhook_url)
                    job['webhook_sent'] = bool(job['n8n_response'].get('ok'))
                except Exception as exc:
                    job['n8n_response'] = {'ok': False, 'error': str(exc)}
                    job['webhook_sent'] = False
                job['log'] = 'Leads qualificados enviados para automação.' if job.get('webhook_sent') else 'Leads qualificados, mas o envio para automação falhou.'
            jobs_dict[job_id] = dict(job)
        except Exception as exc:
            job['status'] = 'error'
            job['error'] = str(exc)
            job['log'] = 'Erro na qualificação: ' + str(exc)
            jobs_dict[job_id] = dict(job)
    Thread(target=run_enrich, daemon=True).start()
    return True

class CustomHTTPHandler(SimpleHTTPRequestHandler):
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ('/', '/index.html', '/scraper', '/scraper/'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.end_headers()
            self.wfile.write(HTML_PORTAL.encode('utf-8'))
            return
        if parsed.path == '/debug/threads':
            import sys, traceback, io
            out = io.StringIO()
            for thread_id, stack in sys._current_frames().items():
                out.write(f"=== Thread {thread_id} ===\n")
                traceback.print_stack(stack, file=out)
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(out.getvalue().encode('utf-8'))
            return
        if parsed.path.startswith('/api/job/'):
            job_id = parsed.path.split('/')[-1]
            jobs_dict = get_jobs_dict()
            job = jobs_dict.get(job_id)
            if not job:
                self.send_json({'error': 'job not found'}, 404)
                return
            if job.get('status') == 'running' and time.time() - job.get('last_activity', time.time()) > 180:
                job['status'] = 'error'
                job['error'] = 'Timeout: extração inativa por mais de 3 minutos.'
                job['log'] = 'Erro: extração inativa por mais de 3 minutos. Job interrompido.'
            job['payload'] = make_payload(job)
            self.send_json(job)
            return
        super().do_GET()

    def do_POST(self):
        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len) if content_len else b'{}'
        try:
            payload = json.loads(body.decode('utf-8') or '{}')
        except Exception:
            payload = {}

        if self.path == '/api/scrape':
            jobs_dict = get_jobs_dict()
            job_id = str(int(time.time() * 1000))
            category = payload.get('category') or 'estética'
            city = payload.get('city') or 'Campo Grande'
            state = payload.get('state') or 'Mato Grosso do Sul'
            max_leads = max(1, min(int(payload.get('max_leads') or 15), 500))
            mode = str(payload.get('mode') or os.environ.get('SCRAPER_DEFAULT_MODE', 'fast')).lower()
            if mode not in ('full', 'fast'):
                self.send_json({'error': 'mode must be full or fast'}, 400)
                return
            auto_enrich = payload.get('auto_enrich', mode == 'full') is True
            webhook_url = payload.get('webhook') or DEFAULT_N8N_WEBHOOK
            jobs_dict[job_id] = {'job_id': job_id, 'status': 'pending', 'phase': 'scrape', 'mode': mode, 'auto_enrich': auto_enrich, 'category': category, 'city': city, 'state': state, 'max_leads': max_leads, 'webhook': webhook_url, 'current_count': 0, 'leads': [], 'log': 'Aguardando início da coleta...'}

            proc = multiprocessing.Process(target=worker_scrape_process, args=(job_id, category, city, state, max_leads, webhook_url, jobs_dict, mode), daemon=True)
            proc.start()
            self.send_json({'job_id': job_id, 'status': 'started'})
            return

        if self.path.startswith('/api/enrich/'):
            job_id = self.path.split('/')[-1]
            jobs_dict = get_jobs_dict()
            job = jobs_dict.get(job_id)
            if not job:
                self.send_json({'error': 'job not found'}, 404)
                return
            if not job.get('leads'):
                self.send_json({'error': 'job has no leads to enrich'}, 400)
                return
            if job.get('mode') == 'fast':
                self.send_json({'error': 'enrichment is disabled for fast mode'}, 400)
                return
            if job.get('status') == 'enriching':
                self.send_json({'job_id': job_id, 'status': 'already_enriching'})
                return
            webhook_url = payload.get('webhook') or job.get('webhook') or DEFAULT_N8N_WEBHOOK
            start_enrichment_job(job_id, webhook_url)
            self.send_json({'job_id': job_id, 'status': 'enriching'})
            return

        self.send_json({'error': 'not found'}, 404)

def main():
    get_jobs_dict()
    httpd = ThreadingHTTPServer(('0.0.0.0', 8990), CustomHTTPHandler)
    print('Stark Scraper Studio listening on http://0.0.0.0:8990', flush=True)
    httpd.serve_forever()

if __name__ == '__main__':
    main()
