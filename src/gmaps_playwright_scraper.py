import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
from playwright.sync_api import sync_playwright

TARGET_NICHE_POSITIVE_TERMS = (
    'clinica de estetica', 'clínica de estética', 'clinica estetica', 'clínica estética',
    'estetica avancada', 'estética avançada', 'medicina estetica', 'medicina estética',
    'dermatologia estetica', 'dermatologia estética', 'clinica dermatologica', 'clínica dermatológica',
    'harmonizacao facial', 'harmonização facial', 'harmonizacao orofacial', 'harmonização orofacial',
    'estetica facial', 'estética facial', 'estetica corporal', 'estética corporal',
    'dermatologista', 'rejuvenescimento', 'botox', 'toxina botulinica', 'toxina botulínica',
    'preenchimento', 'bioestimulador', 'skinbooster', 'laser', 'depilacao a laser', 'depilação a laser',
)
TARGET_NICHE_NEGATIVE_TERMS = (
    'estetica animal', 'estética animal', 'banho e tosa', 'banho e tosa', 'pet shop',
    'veterinaria', 'veterinária', 'barbearia', 'barber shop', 'manicure', 'esmalteria',
    'cabeleireiro', 'estetica automotiva', 'estética automotiva',
)

def only_digits(s):
    return re.sub(r'\D+', '', str(s or ''))

def format_whatsapp(phone):
    d = only_digits(phone)
    if not d:
        return ''
    d = d.lstrip('0')
    if d.startswith('0055'):
        d = d[2:]
    if not d.startswith('55'):
        d = '55' + d
    return d if 12 <= len(d) <= 13 else d

def clean_google_redirect_url(url):
    url = str(url or '').strip()
    if not url:
        return ''
    if url.startswith('/url?') or 'google.com/url?' in url:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        if qs.get('q'):
            return qs['q'][0]
    m = re.search(r'https?://[^\s`"<>]+', url)
    return m.group(0).rstrip(').,;]') if m else url

def parse_google_web_result_payload(payload):
    """Normalize the useful fields from Google's in-place web results block."""
    payload = payload or {}
    text = str(payload.get('text') or '')
    links = payload.get('links') or []
    website = ''
    instagram = []
    cnpj = ''
    web_results = []
    for raw_link in links:
        if isinstance(raw_link, dict):
            raw_url = raw_link.get('url') or raw_link.get('href') or ''
            title = str(raw_link.get('title') or '').strip()
            snippet = str(raw_link.get('snippet') or '').strip()
        else:
            raw_url = raw_link
            title = ''
            snippet = ''
        url = clean_google_redirect_url(raw_url)
        lower = url.lower()
        parsed_url = urllib.parse.urlparse(url)
        domain = parsed_url.netloc.lower().removeprefix('www.')
        if not url or parsed_url.scheme not in ('http', 'https'):
            continue
        if 'instagram.com' in lower:
            result_type = 'instagram'
        elif any(domain_name in lower for domain_name in ('facebook.com', 'linkedin.com', 'youtube.com', 'tiktok.com')):
            result_type = 'social'
        elif any(domain_name in lower for domain_name in ('doctoralia.com', 'guiasaude', 'telelistas', 'yelp.com')):
            result_type = 'directory'
        elif 'google.com' in lower:
            continue
        else:
            result_type = 'website'
        web_results.append({'type': result_type, 'title': title, 'url': url, 'domain': domain, 'snippet': snippet})
        if 'instagram.com' in lower:
            if url not in instagram:
                instagram.append(url)
        elif not website and urllib.parse.urlparse(url).scheme in ('http', 'https'):
            if not any(domain in lower for domain in (
                'google.com', 'facebook.com', 'linkedin.com', 'youtube.com',
                'tiktok.com', 'twitter.com', 'x.com', 'instagram.com',
            )):
                website = url
    match = re.search(r'\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b', text)
    if match:
        digits = only_digits(match.group(0))
        if len(digits) == 14:
            cnpj = f'{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}'
    return {'website': website, 'instagram': instagram, 'cnpj': cnpj, 'web_results': web_results}

def classify_business_niche(candidate):
    """Classify a Maps candidate using centralized positive/negative niche signals."""
    text = ' '.join(str(candidate.get(key) or '') for key in ('title', 'place_name', 'category', 'card_text')).lower()
    if any(term in text for term in TARGET_NICHE_NEGATIVE_TERMS):
        return False
    if any(term in text for term in TARGET_NICHE_POSITIVE_TERMS):
        return True
    # Generic "estética" is accepted until details provide a stronger signal.
    return 'estetica' in text or 'estética' in text

def parse_rating(value):
    match = re.search(r'\b([0-5](?:[.,]\d)?)\b', str(value or ''))
    return float(match.group(1).replace(',', '.')) if match else None

def parse_reviews(value):
    text = str(value or '').lower()
    matches = list(re.finditer(r'(\d+(?:[.,]\d+)?)\s*(mil|k)?', text))
    if not matches:
        return None
    match = matches[-1]
    number = float(match.group(1).replace(',', '.'))
    return int(number * 1000) if match.group(2) else int(number)


def scraper_int_env(name, default, minimum=0):
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def scraper_float_env(name, default, minimum=0.0):
    try:
        return max(minimum, float(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def discovery_limits(max_leads):
    oversampling = scraper_float_env('SCRAPER_OVERSAMPLING_FACTOR', 1.5, 1.0)
    query_limit = scraper_int_env('SCRAPER_QUERY_CANDIDATE_LIMIT', 50, 1)
    return {
        'max_pool': max(int(max_leads * oversampling), 30),
        'query_limit': query_limit,
        'max_scrolls': scraper_int_env('SCRAPER_MAX_SCROLLS_PER_QUERY', 18),
        'scroll_wait_ms': scraper_int_env('SCRAPER_SCROLL_WAIT_MS', 1500),
        'max_no_new_scrolls': scraper_int_env('SCRAPER_MAX_NO_NEW_SCROLLS', 3),
        'low_yield_threshold': scraper_int_env('SCRAPER_LOW_YIELD_QUERY_THRESHOLD', 5),
        'max_low_yield_queries': scraper_int_env('SCRAPER_MAX_LOW_YIELD_QUERIES', 2),
        'reuse_detail_page': os.environ.get('SCRAPER_REUSE_DETAIL_PAGE', 'true').lower() == 'true',
    }


def adaptive_query_limit(remaining_leads, configured_limit=50):
    return min(configured_limit, max(20, remaining_leads * 2))


def discovery_should_stop(current_count, target):
    return current_count >= target


def low_yield_should_stop(consecutive_queries, threshold, maximum):
    return consecutive_queries >= maximum and maximum > 0


def preserve_google_instagram(values):
    return list(dict.fromkeys(values or []))


def candidate_identity(item):
    href = clean_google_redirect_url(item.get('href') or '')
    if href:
        return 'url:' + href.split('?')[0].rstrip('/').lower()
    phone = format_whatsapp(item.get('phone_raw') or item.get('whatsapp'))
    if phone:
        return 'phone:' + phone
    name = str(item.get('title') or item.get('place_name') or '').strip().lower()
    address = str(item.get('address') or item.get('street') or '').strip().lower()
    return 'name:' + name + '|' + address if name or address else ''


def initialize_discovery_metrics(job_dict, target):
    if job_dict is None:
        return
    job_dict.update({
        'queries_started': 0, 'queries_completed': 0, 'queries_skipped': 0,
        'candidate_cards_seen': 0, 'candidates_unique': 0, 'candidates_duplicate': 0,
        'candidates_prequalified': 0, 'candidates_rejected_pre_detail': 0,
        'details_avoided': 0, 'qualified_leads': 0, 'target_leads': target,
        'target_reached': False, 'early_stop_triggered': False,
        'time_to_first_candidate_ms': None, 'time_to_first_qualified_lead_ms': None,
        'query_discovery_ms': 0.0, 'detail_processing_ms': 0.0,
    })

def candidate_card_metadata(element):
    """Read only metadata already rendered in a Maps result card."""
    try:
        return element.evaluate('''el => {
            let root = el;
            for (let i = 0; i < 5 && root.parentElement; i++) {
                root = root.parentElement;
                if (root.getAttribute('role') === 'article' || root.querySelector('[role="img"]')) break;
            }
            return {text: root.innerText || '', aria: root.getAttribute('aria-label') || ''};
        }''') or {}
    except Exception:
        return {}

def extract_google_web_results(page):
    """Read Google's optional "Resultados da Web" block without fixed XPaths."""
    max_scrolls = max(0, int(os.environ.get('WEB_RESULTS_MAX_SCROLLS', '3')))
    try:
        payload = page.evaluate('''() => {
            const headings = [...document.querySelectorAll('h1,h2,h3,[role="heading"]')];
            const heading = headings.find(el => /resultados da web/i.test(el.innerText || ''));
            if (!heading) return {text: '', links: []};
            let root = heading;
            for (let i = 0; i < 5 && root.parentElement; i++) {
                root = root.parentElement;
                if (root.querySelectorAll('a[href]').length >= 1) break;
            }
            return {
                text: root.innerText || '',
                links: [...root.querySelectorAll('a[href]')].map(a => ({url: a.href, title: a.innerText || a.getAttribute('aria-label') || '', snippet: a.parentElement?.innerText || ''})).filter(x => x.url)
            };
        }''')
        result = parse_google_web_result_payload(payload)
        for _ in range(max_scrolls):
            if result['web_results']:
                break
            page.mouse.wheel(0, 500)
            time.sleep(0.2)
            payload = page.evaluate('''() => ({
                text: document.body.innerText || '',
                links: [...document.querySelectorAll('a[href]')].map(a => ({url: a.href, title: a.innerText || '', snippet: a.parentElement?.innerText || ''})).filter(x => x.url)
            })''')
            result = parse_google_web_result_payload(payload)
        return result
    except Exception:
        return {'website': '', 'instagram': [], 'cnpj': '', 'web_results': []}

def resolve_shortener_url(url, timeout=3):
    if not url or not url.startswith('http'):
        return url
    try:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.lower()
        shorteners = ['bit.ly', 'tinyurl.com', 't.co', 'cutt.ly', 'is.gd', 'shorturl.at', 'rb.gy']
        if any(s in domain for s in shorteners):
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}, method='HEAD')
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.geturl()
    except Exception:
        pass
    return url

def is_messaging_or_social_app(url):
    url_lower = str(url or '').lower()
    blocked_domains = [
        'api.whatsapp.com', 'wa.me', 'web.whatsapp.com', 'whatsapp.com',
        'instagram.com', 'facebook.com', 'linkedin.com', 't.me', 'telegram.me',
        'youtube.com', 'tiktok.com', 'twitter.com', 'x.com'
    ]
    return any(b in url_lower for b in blocked_domains)

def extract_socials_from_website(context, website_url):
    socials = {'instagram': [], 'facebook': [], 'linkedin': [], 'emails': []}
    if not website_url or not website_url.startswith('http'):
        return socials

    target_url = resolve_shortener_url(website_url, timeout=3)
    if is_messaging_or_social_app(target_url):
        if 'instagram.com' in target_url:
            socials['instagram'].append(target_url)
        elif 'facebook.com' in target_url:
            socials['facebook'].append(target_url)
        elif 'linkedin.com' in target_url:
            socials['linkedin'].append(target_url)
        return socials

    page = None
    try:
        page = context.new_page()
        page.set_default_timeout(8000)
        page.on("dialog", lambda dialog: dialog.dismiss())

        page.goto(target_url, wait_until="commit", timeout=8000)
        time.sleep(1.0)

        for a in page.query_selector_all('a[href]'):
            href = (a.get_attribute('href') or '').strip()
            if 'instagram.com' in href and href not in socials['instagram']:
                socials['instagram'].append(href)
            if 'facebook.com' in href and href not in socials['facebook']:
                socials['facebook'].append(href)
            if 'linkedin.com' in href and href not in socials['linkedin']:
                socials['linkedin'].append(href)
            if href.startswith('mailto:'):
                email = href.replace('mailto:', '').split('?')[0].strip()
                if email and email not in socials['emails']:
                    socials['emails'].append(email)

        content = page.content()
        found_emails = re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', content)
        for em in found_emails:
            em_clean = em.strip().lower()
            if not em_clean.endswith(('.png', '.jpg', '.jpeg', '.svg', '.webp')) and em_clean not in socials['emails']:
                socials['emails'].append(em_clean)

    except Exception as e:
        print(f"⚠️ Website social scrape skipped for {website_url}: {e}", flush=True)
    finally:
        if page:
            try:
                page.close(timeout=2000)
            except Exception:
                pass

    return socials

def enrich_with_cnpj_and_owner(context, lead):
    name = lead.get('place_name', '')
    street = lead.get('street', '') or lead.get('address', '')
    city = lead.get('city', 'Campo Grande')
    state = lead.get('state', 'Mato Grosso do Sul')

    query = f"{name} {street} {city} {state} CNPJ sócio administrador"
    google_search_url = f"https://www.google.com.br/search?q={urllib.parse.quote(query)}"

    owner = ""
    admin = ""
    legal_name = ""
    cnpj = ""

    page = None
    try:
        page = context.new_page()
        page.set_default_timeout(10000)
        page.on("dialog", lambda dialog: dialog.dismiss())
        page.goto(google_search_url, wait_until="domcontentloaded", timeout=10000)
        time.sleep(1.5)

        text = page.evaluate('''() => {
            const searchEl = document.querySelector('#search') || document.body;
            return searchEl.innerText || '';
        }''')

        cnpj_m = re.search(r'\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b', text)
        if cnpj_m:
            cnpj = cnpj_m.group(0)

        razao_m = re.search(r'([A-Z0-9\s.&-]{3,60}\s+(?:LTDA|S/A|EIRELI|ME|EPP))\b', text, re.IGNORECASE)
        if razao_m:
            legal_name = razao_m.group(1).strip()

        socio_m = re.search(r'(?:Sócio-Administrador|Administrador|Sócio|Proprietário):\s*([A-Za-z\s]{3,40})', text, re.IGNORECASE)
        if socio_m:
            owner = socio_m.group(1).strip()
            admin = owner

    except Exception as e:
        print(f"⚠️ Search CNPJ enrichment skipped for {name}: {e}", flush=True)
    finally:
        if page:
            try:
                page.close(timeout=2000)
            except Exception:
                pass

    lead['owner_name'] = owner
    lead['administrator_name'] = admin
    lead['legal_name'] = legal_name
    lead['cnpj'] = cnpj
    return lead

def extract_detail_from_place_page(page, fast=False):
    if not fast:
        time.sleep(2.0)
    data = {}

    # 1. Place Name
    title_el = page.query_selector('h1.DUwDvf, h1.fontTitleLarge, div[role="main"] h1, h1')
    if title_el and title_el.inner_text().strip():
        data['place_name'] = title_el.inner_text().strip()
    else:
        try:
            pg_title = (page.title() or '').split('- Google Maps')[0].split('- Google')[0].strip()
            data['place_name'] = pg_title
        except Exception:
            data['place_name'] = ''

    # 2. Rating & Review Count
    score_el = page.query_selector('div.F7vEfc span.ceNzKf, div.fontBodyMedium span[aria-hidden="true"]')
    if score_el:
        txt = score_el.inner_text().strip()
        if re.match(r'^\d[.,]\d$', txt):
            data['total_score'] = txt.replace(',', '.')
    if not data.get('total_score'):
        data['total_score'] = ''

    reviews_btn = page.query_selector('button[jsaction*="review"], button[aria-label*="avaliações"]')
    if reviews_btn:
        txt = reviews_btn.inner_text().strip()
        m = re.search(r'\((\d+)\)', txt)
        if m:
            data['reviews_count'] = m.group(1)
    if not data.get('reviews_count'):
        data['reviews_count'] = ''

    # 3. Category
    cat_btn = page.query_selector('button[jsaction*="category"]')
    if cat_btn:
        data['category'] = cat_btn.inner_text().strip()
    else:
        data['category'] = ''

    # 4. Address & Street
    addr_btn = page.query_selector('button[data-item-id="address"], button[aria-label*="Endereço:"]')
    if addr_btn:
        aria = addr_btn.get_attribute('aria-label') or ''
        if 'Endereço:' in aria:
            data['address'] = aria.split('Endereço:')[-1].strip()
        else:
            lines = [l.strip() for l in addr_btn.inner_text().split('\n') if l.strip() and l.strip() != '']
            data['address'] = ' '.join(lines)
    else:
        text_body = page.content()
        m_addr = re.search(r'(Rua|R\.|Av\.|Avenida|Travessa|Tv\.)\s+[^,<"\n]+,\s*\d+[^<"\n]*Campo Grande', text_body, re.IGNORECASE)
        data['address'] = m_addr.group(0).strip() if m_addr else ''

    if data.get('address'):
        parts = data['address'].split('-')
        data['street'] = parts[0].strip() if parts else data['address']
    else:
        data['street'] = ''

    # 5. Phone & WhatsApp
    phone_btn = page.query_selector('button[data-tooltip*="telefone"], button[data-item-id^="phone:tel:"]')
    if phone_btn:
        aria = phone_btn.get_attribute('aria-label') or ''
        if 'Telefone:' in aria:
            raw_phone = aria.split('Telefone:')[-1].strip()
        else:
            lines = [l.strip() for l in phone_btn.inner_text().split('\n') if l.strip() and l.strip() != '']
            raw_phone = ' '.join(lines)
        data['phone_raw'] = raw_phone
        data['whatsapp'] = format_whatsapp(raw_phone)
    else:
        text_body = page.content()
        m_phone = re.search(r'\+55\s*\(?\d{2}\)?\s*9?\d{4}[-\s]?\d{4}', text_body)
        raw_phone = m_phone.group(0).strip() if m_phone else ''
        data['phone_raw'] = raw_phone
        data['whatsapp'] = format_whatsapp(raw_phone)

    # 6. Website and results already rendered by Google Maps. This never
    # opens the external website; FULL may still enrich it later.
    web_btn = page.query_selector('a[data-item-id="authority"], a[aria-label*="site"], a[aria-label*="Website"]')
    if web_btn:
        data['website'] = clean_google_redirect_url(web_btn.get_attribute('href') or '')
    else:
        data['website'] = ''
    web_results = extract_google_web_results(page)
    if not data['website']:
        data['website'] = web_results['website']
    data['instagram'] = web_results['instagram']
    data['google_result_cnpj'] = web_results['cnpj']
    data['web_results'] = web_results['web_results']
    data['instagram_source'] = 'google_web_results' if data['instagram'] else ''
    data['cnpj_source'] = 'google_web_results' if data['google_result_cnpj'] else ''

    # 7. Plus Code
    code_btn = page.query_selector('button[data-item-id="oloc"]')
    if code_btn:
        aria = code_btn.get_attribute('aria-label') or ''
        if aria.startswith('Plus Code:'):
            data['plus_code'] = aria.replace('Plus Code:', '').strip()
        else:
            lines = [l.strip() for l in code_btn.inner_text().split('\n') if l.strip() and not l.startswith('󰔎')]
            data['plus_code'] = ' '.join(lines)
    else:
        data['plus_code'] = ''

    data['google_maps_url'] = page.url
    return data

def generate_query_variations(category, city, state):
    cat_clean = category.strip()
    cat_lower = cat_clean.lower()
    queries = [f"clínica de estética {city} {state}"] if any(k in cat_lower for k in ('estetica', 'estética')) else [f"{cat_clean} {city} {state}"]

    if 'dentista' in cat_lower or 'odontolog' in cat_lower:
        queries.extend([
            f"Clínica odontológica {city} {state}",
            f"Consultório odontológico {city} {state}",
            f"Ortodontista {city} {state}",
            f"Implantodontia {city} {state}",
            f"Dentista Centro {city} {state}",
            f"Dentista Jardim dos Estados {city} {state}",
            f"Cirurgião dentista {city} {state}",
            f"Odontologia estética {city} {state}"
        ])
    elif any(k in cat_lower for k in ['clínica médica', 'consultório', 'médico', 'diversos', 'medica', 'medico', 'clinica']):
        queries.extend([
            f"Clínica médica {city} {state}",
            f"Consultório médico {city} {state}",
            f"Centro médico {city} {state}",
            f"Clínica de especialidades {city} {state}",
            f"Médico especialista {city} {state}",
            f"Clínica médica Centro {city} {state}",
            f"Clínica médica Jardim dos Estados {city} {state}",
            f"Consultório médico Centro {city} {state}"
        ])
    elif any(k in cat_lower for k in ('estetica', 'estética')):
        queries.extend([
            f"clínica de estética {city} {state}",
            f"estética avançada {city} {state}",
            f"harmonização facial {city} {state}",
            f"medicina estética {city} {state}",
            f"estética Centro {city} {state}",
            f"estética Jardim dos Estados {city} {state}",
        ])
    else:
        queries.extend([
            f"Clínica de {cat_clean} {city} {state}",
            f"Consultório de {cat_clean} {city} {state}",
            f"{cat_clean} Centro {city} {state}",
            f"{cat_clean} Jardim dos Estados {city} {state}",
            f"{cat_clean} Chácara Cachoeira {city} {state}",
            f"Especialista em {cat_clean} {city} {state}"
        ])

    seen = set()
    result = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            result.append(q)
    return result


def _prequalify_card(item, category):
    if not classify_business_niche({'title': item.get('title'), 'category': category, 'card_text': item.get('card_text')}):
        return 'category'
    if item.get('rating') is not None and item['rating'] < 4.5:
        return 'rating'
    if item.get('reviews_count') is not None and item['reviews_count'] < 20:
        return 'reviews'
    return ''


def _scrape_gmaps_incremental(job_id, category, city, state, max_leads, job_dict, mode):
    limits = discovery_limits(max_leads)
    initialize_discovery_metrics(job_dict, max_leads)
    results, seen_candidates, seen_places, seen_phones = [], set(), set(), set()
    queries = generate_query_variations(category, city, state)
    started = time.perf_counter()
    low_yield = 0
    detail_page = None
    query_metrics = []

    def inc(key, amount=1):
        if job_dict is not None:
            job_dict[key] = int(job_dict.get(key, 0)) + amount

    def progress(q_idx):
        if job_dict is not None:
            job_dict['leads'] = json.loads(json.dumps(results, ensure_ascii=False))
            job_dict['current_count'] = len(results)
            job_dict['log'] = (f'Query {q_idx}/{len(queries)} | Candidatos vistos: '
                               f'{job_dict.get("candidate_cards_seen", 0)} | Pré-qualificados: '
                               f'{job_dict.get("candidates_prequalified", 0)} | Detalhes abertos: '
                               f'{job_dict.get("details_opened", 0)} | Leads válidos: {len(results)}/{max_leads}')
            job_dict['last_activity'] = time.time()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            context = browser.new_context(locale='pt-BR', ignore_https_errors=True)
            context.on('page', lambda page: page.on('dialog', lambda dialog: dialog.dismiss()))
            for q_idx, query in enumerate(queries, 1):
                if len(results) >= max_leads:
                    break
                query_started = time.perf_counter()
                inc('queries_started')
                page_search = None
                unique_in_query = 0
                cards_before = int(job_dict.get('candidate_cards_seen', 0)) if job_dict else 0
                prequalified_before = int(job_dict.get('candidates_prequalified', 0)) if job_dict else 0
                leads_before = len(results)
                try:
                    page_search = context.new_page()
                    page_search.set_default_timeout(30000)
                    page_search.goto(f'https://www.google.com.br/maps/search/{urllib.parse.quote(query)}', wait_until='domcontentloaded', timeout=45000)
                    feed = page_search.wait_for_selector('div[role="feed"]', timeout=15000)
                    if not feed:
                        continue
                    limit = adaptive_query_limit(max_leads - len(results), limits['query_limit'])
                    no_new = 0
                    previous_cards = 0
                    query_seen_hrefs = set()
                    for _ in range(limits['max_scrolls']):
                        if len(results) >= max_leads or len(seen_candidates) >= limits['max_pool']:
                            break
                        links = feed.query_selector_all('a.hfpxzc[href*="/maps/place/"], a[href*="/maps/place/"]')
                        new_count = 0
                        for link in links:
                            href = link.get_attribute('href') or ''
                            if href in query_seen_hrefs:
                                continue
                            if len(query_seen_hrefs) >= limit:
                                break
                            query_seen_hrefs.add(href)
                            inc('candidate_cards_seen')
                            card = candidate_card_metadata(link)
                            card_text = f'{card.get("text", "")} {card.get("aria", "")}'
                            item = {'href': href, 'title': link.get_attribute('aria-label') or '', 'card_text': card_text, 'rating': parse_rating(card_text), 'reviews_count': parse_reviews(card_text) if re.search(r'avaliações|reviews?', card_text, re.I) else None, 'google_sponsored': bool(re.search(r'patrocinado', card_text, re.I))}
                            identity = candidate_identity(item)
                            if not identity or identity in seen_candidates:
                                inc('candidates_duplicate')
                                continue
                            seen_candidates.add(identity)
                            unique_in_query += 1
                            new_count += 1
                            inc('candidates_unique')
                            if job_dict is not None and job_dict.get('time_to_first_candidate_ms') is None:
                                job_dict['time_to_first_candidate_ms'] = round((time.perf_counter() - started) * 1000, 2)
                            reason = _prequalify_card(item, category)
                            if reason:
                                inc('rejected_' + reason)
                                inc('candidates_rejected_pre_detail')
                                inc('details_avoided')
                                continue
                            inc('candidates_prequalified')
                            if detail_page is None or not limits['reuse_detail_page']:
                                if detail_page is not None:
                                    detail_page.close()
                                detail_page = context.new_page()
                                detail_page.set_default_timeout(15000)
                                detail_page.on('dialog', lambda dialog: dialog.dismiss())
                            inc('details_opened')
                            detail_started = time.perf_counter()
                            detail_page.goto(item['href'], wait_until='commit', timeout=10000)
                            detail = extract_detail_from_place_page(detail_page, fast=True)
                            if job_dict is not None:
                                job_dict['detail_processing_ms'] = round(job_dict.get('detail_processing_ms', 0.0) + (time.perf_counter() - detail_started) * 1000, 2)
                            detail.update({'place_name': detail.get('place_name') or item['title'], 'city': city, 'state': state, 'country_code': 'BR', 'google_sponsored': item['google_sponsored']})
                            wa = detail.get('whatsapp') or ''
                            if not wa:
                                inc('rejected_whatsapp')
                                inc('without_whatsapp')
                                continue
                            place_key = f'{detail.get("place_name", "")}|{detail.get("street") or detail.get("address") or ""}'.lower()
                            if (place_key != '|' and place_key in seen_places) or wa in seen_phones:
                                inc('candidates_duplicate')
                                continue
                            seen_places.add(place_key)
                            seen_phones.add(wa)
                            detail['qualification_status'] = 'qualified'
                            detail['with_whatsapp'] = True
                            detail['instagram'] = preserve_google_instagram(detail.get('instagram'))
                            detail['facebook'], detail['linkedin'], detail['emails'] = [], [], []
                            results.append(detail)
                            inc('qualified_leads')
                            if job_dict is not None and len(results) == 1:
                                job_dict['time_to_first_qualified_lead_ms'] = round((time.perf_counter() - started) * 1000, 2)
                            progress(q_idx)
                            if discovery_should_stop(len(results), max_leads):
                                if job_dict is not None:
                                    job_dict['target_reached'] = True
                                    job_dict['early_stop_triggered'] = True
                                break
                        if len(results) >= max_leads or len(links) >= limit:
                            break
                        no_new = no_new + 1 if new_count == 0 and len(links) <= previous_cards else 0
                        previous_cards = len(links)
                        if no_new >= limits['max_no_new_scrolls']:
                            break
                        if links:
                            links[-1].scroll_into_view_if_needed()
                        feed.evaluate('el => el.scrollTo(0, el.scrollHeight)')
                        page_search.mouse.wheel(0, 3500)
                        try:
                            page_search.wait_for_function('''([selector, count]) => document.querySelector(selector)?.querySelectorAll('a[href*="/maps/place/"]').length > count''', arg=['div[role="feed"]', len(links)], timeout=limits['scroll_wait_ms'])
                        except Exception:
                            no_new += 1
                    low_yield = low_yield + 1 if unique_in_query < limits['low_yield_threshold'] else 0
                    if low_yield_should_stop(low_yield, limits['low_yield_threshold'], limits['max_low_yield_queries']):
                        break
                except Exception as exc:
                    print(f"⚠️ Error collecting query '{query}': {exc}", flush=True)
                finally:
                    inc('queries_completed')
                    if job_dict is not None:
                        job_dict['query_discovery_ms'] = round(job_dict.get('query_discovery_ms', 0.0) + (time.perf_counter() - query_started) * 1000, 2)
                    query_metrics.append({
                        'query': query, 'raw_candidates_found': (int(job_dict.get('candidate_cards_seen', 0)) - cards_before) if job_dict else 0,
                        'new_unique_candidates': unique_in_query,
                        'prequalified_candidates': (int(job_dict.get('candidates_prequalified', 0)) - prequalified_before) if job_dict else 0,
                        'qualified_leads_generated': len(results) - leads_before,
                    })
                    if page_search:
                        page_search.close(timeout=2000)
            if detail_page:
                detail_page.close()
            browser.close()
    finally:
        if job_dict is not None:
            elapsed = (time.perf_counter() - started) * 1000
            job_dict['leads'] = results
            job_dict['current_count'] = len(results)
            job_dict['candidates_found'] = len(seen_candidates)
            job_dict['details_skipped'] = job_dict.get('details_avoided', 0)
            job_dict['qualified'] = len(results)
            job_dict['target_reached'] = len(results) >= max_leads
            job_dict['detail_efficiency_rate'] = round(len(results) / max(job_dict.get('details_opened', 0), 1) * 100, 2)
            job_dict['details_avoided_rate'] = round(job_dict.get('details_avoided', 0) / max(len(seen_candidates), 1) * 100, 2)
            job_dict['qualified_leads_per_minute'] = round(len(results) / max(elapsed / 60000, 0.001), 2)
            job_dict['scrape_total_ms'] = round(elapsed, 2)
            job_dict['query_metrics'] = query_metrics
            job_dict['status'] = 'running'
    return results


def scrape_gmaps(job_id_or_callback, category, city, state, max_leads=10, webhook_url=None, job_dict=None, mode='full'):
    print(f"DEBUG: Starting scrape_gmaps with max_leads={max_leads}, webhook_url={webhook_url}", flush=True)
    job_started = time.perf_counter()
    if job_dict is not None:
        job_dict['status'] = 'running'
        job_dict['started_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        job_dict['job_started_at'] = time.time()
        job_dict['mode'] = mode
        job_dict['last_activity'] = time.time()

    if mode == 'fast':
        return _scrape_gmaps_incremental(job_id_or_callback, category, city, state, max_leads, job_dict, mode)

    results = []
    seen_urls = set()
    seen_places = set()
    seen_phones = set()
    duplicates_removed = 0

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-gpu',
                    '--disable-dev-shm-usage'
                ]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="pt-BR",
                ignore_https_errors=True
            )
            context.on("page", lambda new_p: new_p.on("dialog", lambda d: d.dismiss()))

            # Step 1: Collect place URLs from feed using multi-query expansion
            candidate_started = time.perf_counter()
            if job_dict:
                job_dict['candidate_search_started_at'] = time.time()
            queries_to_run = generate_query_variations(category, city, state) if max_leads > 35 else [f"{category} {city} {state}"]
            place_items = []
            max_pool = max(max_leads * 3, 30)

            for q_idx, q_str in enumerate(queries_to_run):
                if len(place_items) >= max_pool:
                    break
                print(f"🚀 [Query {q_idx+1}/{len(queries_to_run)}] Searching Google Maps: '{q_str}'...", flush=True)
                if job_dict:
                    job_dict['log'] = f"Buscando candidatos {q_idx+1}/{len(queries_to_run)}: {q_str}"
                    job_dict['last_activity'] = time.time()
                s_url = f"https://www.google.com.br/maps/search/{urllib.parse.quote(q_str)}"
                page_search = None
                try:
                    page_search = context.new_page()
                    page_search.set_default_timeout(30000)
                    page_search.on("dialog", lambda d: d.dismiss())
                    page_search.goto(s_url, wait_until="domcontentloaded", timeout=45000)
                    try:
                        page_search.wait_for_selector('div[role="feed"]', timeout=15000)
                    except Exception:
                        print(f"⚠️ Feed element not found for query '{q_str}', skipping...", flush=True)
                        continue

                    feed = page_search.query_selector('div[role="feed"]')
                    if not feed:
                        print(f"⚠️ Feed disappeared for query '{q_str}', skipping...", flush=True)
                        continue
                    consecutive_no_new = 0
                    previous_count = 0
                    for scroll_step in range(60):
                        if job_dict:
                            job_dict['log'] = f"Buscando candidatos {q_idx+1}/{len(queries_to_run)}: {len(place_items)}/{max_pool} candidatos"
                            job_dict['last_activity'] = time.time()
                        if len(place_items) >= max_pool:
                            break
                        links = feed.query_selector_all('a.hfpxzc[href*="/maps/place/"], a[href*="/maps/place/"]')
                        new_found = False
                        for l in links:
                            href = l.get_attribute('href')
                            title = l.get_attribute('aria-label') or ''
                            card = candidate_card_metadata(l)
                            card_text = f"{card.get('text', '')} {card.get('aria', '')}"
                            if href and href in seen_urls:
                                duplicates_removed += 1
                            elif href:
                                seen_urls.add(href)
                                place_items.append({
                                    'href': href,
                                    'title': title,
                                    'card_text': card_text,
                                    'rating': parse_rating(card_text),
                                    'reviews_count': parse_reviews(card_text),
                                    'google_sponsored': bool(re.search(r'patrocinado', card_text, re.I)),
                                })
                                new_found = True
                                if len(place_items) >= max_pool:
                                    break
                        current_count = len(place_items)
                        if not new_found and current_count <= previous_count:
                            consecutive_no_new += 1
                        else:
                            consecutive_no_new = 0
                        previous_count = current_count

                        if consecutive_no_new >= 5:
                            break

                        if links:
                            try:
                                links[-1].scroll_into_view_if_needed()
                            except Exception:
                                pass
                        feed.hover()
                        feed.evaluate('el => el.scrollTo(0, el.scrollHeight)')
                        page_search.mouse.wheel(0, 3500)
                        try:
                            page_search.wait_for_function(
                                '''([selector, count]) => document.querySelector(selector)?.querySelectorAll('a[href*="/maps/place/"]').length > count''',
                                arg=['div[role="feed"]', len(links)], timeout=4000
                            )
                        except Exception:
                            time.sleep(1.0)
                except Exception as ex_q:
                    print(f"⚠️ Error collecting from query '{q_str}': {ex_q}", flush=True)
                finally:
                    if page_search:
                        try:
                            page_search.close(timeout=2000)
                        except Exception:
                            pass

            candidate_finished = time.perf_counter()
            if job_dict:
                job_dict['candidate_search_finished_at'] = time.time()
                job_dict['candidate_search_ms'] = round((candidate_finished - candidate_started) * 1000, 2)
                job_dict['candidates_found'] = len(place_items)
                job_dict['duplicates_removed'] = duplicates_removed
                job_dict['details_started_at'] = time.time()
            if job_dict:
                job_dict['log'] = f"{len(place_items)} candidatos coletados. Extraindo detalhes..."
                job_dict['last_activity'] = time.time()

            # Step 2: Navigate directly to each place page and extract details
            for idx, item in enumerate(place_items):
                if len(results) >= max_leads:
                    break

                target_url = item['href']
                candidate_for_filter = {'title': item.get('title'), 'category': category, 'card_text': item.get('card_text')}
                if not classify_business_niche(candidate_for_filter):
                    if job_dict:
                        job_dict['rejected_category'] = int(job_dict.get('rejected_category', 0)) + 1
                        job_dict['details_skipped'] = int(job_dict.get('details_skipped', 0)) + 1
                    continue
                if item.get('rating') is not None and item['rating'] < 4.5:
                    if job_dict:
                        job_dict['rejected_rating'] = int(job_dict.get('rejected_rating', 0)) + 1
                        job_dict['details_skipped'] = int(job_dict.get('details_skipped', 0)) + 1
                    continue
                if item.get('reviews_count') is not None and item['reviews_count'] < 20:
                    if job_dict:
                        job_dict['rejected_reviews'] = int(job_dict.get('rejected_reviews', 0)) + 1
                        job_dict['details_skipped'] = int(job_dict.get('details_skipped', 0)) + 1
                    continue
                if job_dict:
                    job_dict['details_opened'] = int(job_dict.get('details_opened', 0)) + 1
                print(f"--> Processing candidate {idx+1}/{len(place_items)}: {item['title']}", flush=True)
                page_place = None
                try:
                    page_place = context.new_page()
                    page_place.set_default_timeout(15000)
                    page_place.on("dialog", lambda d: d.dismiss())

                    page_place.goto(target_url, wait_until="commit", timeout=10000)
                    detail = extract_detail_from_place_page(page_place, fast=mode == 'fast')

                    name = detail.get('place_name') or item.get('title') or f"Estabelecimento {idx+1}"
                    detail['place_name'] = name
                    detail['city'] = city
                    detail['state'] = state
                    detail['country_code'] = 'BR'
                    detail['google_sponsored'] = bool(item.get('google_sponsored'))
                    detail['qualification_status'] = 'candidate'

                    wa = detail.get('whatsapp') or ''
                    if mode == 'fast' and not wa:
                        detail['qualification_status'] = 'rejected_whatsapp'
                        if job_dict:
                            job_dict['rejected_whatsapp'] = int(job_dict.get('rejected_whatsapp', 0)) + 1
                            job_dict['without_whatsapp'] = int(job_dict.get('without_whatsapp', 0)) + 1
                        continue
                    detail['qualification_status'] = 'qualified'
                    detail['with_whatsapp'] = bool(wa)
                    street = detail.get('street') or detail.get('address') or ''
                    place_key = f"{name}|{street}".lower()

                    if name and place_key in seen_places and place_key != "|":
                        continue
                    if wa and wa in seen_phones:
                        continue

                    if place_key != "|":
                        seen_places.add(place_key)
                    if wa:
                        seen_phones.add(wa)

                    # Step 3: Secondary website/social scraping remains part
                    # of FULL only. FAST returns the same schema with blanks.
                    if mode == 'fast':
                        detail['instagram'] = list(dict.fromkeys(detail.get('instagram') or []))
                        detail['facebook'] = []
                        detail['linkedin'] = []
                        detail['emails'] = []
                    else:
                        website_url = detail.get('website') or ''
                        socials = extract_socials_from_website(context, website_url)
                        detail['instagram'] = list(dict.fromkeys((detail.get('instagram') or []) + socials['instagram']))
                        detail['facebook'] = socials['facebook']
                        detail['linkedin'] = socials['linkedin']
                        detail['emails'] = socials['emails']

                    detail.setdefault('owner_name', '')
                    detail.setdefault('administrator_name', '')
                    detail.setdefault('legal_name', '')
                    detail.setdefault('cnpj', '')
                    if mode != 'fast' and detail.get('google_result_cnpj') and not detail['cnpj']:
                        detail['cnpj'] = detail['google_result_cnpj']

                    raw_gmaps_url = detail.get('google_maps_url') or target_url
                    m_url = re.search(r'https?://[^\s`"]+', raw_gmaps_url)
                    detail['google_maps_url'] = m_url.group(0) if m_url else raw_gmaps_url

                    results.append(detail)

                    if job_dict:
                        if len(results) == 1 and job_dict.get('job_started_at'):
                            job_dict['time_to_first_lead_ms'] = round((time.time() - job_dict['job_started_at']) * 1000, 2)
                        job_dict['leads'] = json.loads(json.dumps(results, ensure_ascii=False))
                        job_dict['current_count'] = len(results)
                        job_dict['log'] = f"Extraído {len(results)}/{max_leads}: {name} (Fone: {wa or 'N/A'})"
                        job_dict['last_activity'] = time.time()

                    print(f"✅ [{len(results)}/{max_leads}] Extracted: {name} | Fone: {wa} | Insta: {len(detail.get('instagram') or [])}", flush=True)

                except Exception as ex_place:
                    print(f"⚠️ Error extracting place {target_url}: {ex_place}", flush=True)
                finally:
                    if page_place:
                        try:
                            page_place.close(timeout=2000)
                        except Exception:
                            pass

            browser.close()

        if job_dict:
            job_dict['details_finished_at'] = time.time()
            job_dict['details_ms'] = round((time.perf_counter() - candidate_finished) * 1000, 2)
            job_dict['scrape_total_ms'] = round((time.perf_counter() - job_started) * 1000, 2)
            job_dict['job_finished_at'] = time.time()
            job_dict['leads_extracted'] = len(results)
            job_dict['leads_with_phone'] = sum(bool(r.get('phone_raw')) for r in results)
            job_dict['leads_with_whatsapp'] = sum(bool(r.get('whatsapp')) for r in results)
            job_dict['leads_with_website'] = sum(bool(r.get('website')) for r in results)
            job_dict['candidates_seen'] = len(place_items)
            job_dict.setdefault('details_opened', 0)
            job_dict.setdefault('details_skipped', 0)
            job_dict['web_results_found'] = sum(bool(r.get('web_results')) for r in results)
            job_dict['instagram_found_from_google'] = sum(bool(r.get('instagram_source') == 'google_web_results') for r in results)
            job_dict['google_sponsored'] = sum(bool(r.get('google_sponsored')) for r in results)
            job_dict['qualified'] = sum(r.get('qualification_status') == 'qualified' for r in results)
            job_dict['pre_filter_rejection_rate'] = round(
                ((job_dict.get('rejected_category', 0) + job_dict.get('rejected_rating', 0) + job_dict.get('rejected_reviews', 0)) / len(place_items)) * 100,
                2,
            ) if place_items else 0.0
            job_dict['detail_open_rate'] = round((job_dict['details_opened'] / len(place_items)) * 100, 2) if place_items else 0.0
            job_dict['instagram_google_discovery_rate'] = round((job_dict['instagram_found_from_google'] / len(results)) * 100, 2) if results else 0.0
            job_dict['qualified_leads_per_minute'] = round(job_dict['qualified'] / max(job_dict.get('scrape_total_ms', 0) / 60000, 0.001), 2)
            job_dict['sent_to_webhook'] = False
            job_dict['status'] = 'completed'
            job_dict['leads'] = results
            job_dict['current_count'] = len(results)
            job_dict['finished_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
            job_dict['last_activity'] = time.time()

            payload = {
                "event": "google_places_playwright_clean_v1",
                "source": "playwright_headless_scraper",
                "schema": "google_places_leads_clean_v2",
                "filters": {"category": category, "city": city, "state": state, "country_code": "BR"},
                "dedupe": {"total_leads": len(results), "with_whatsapp": sum(bool(r.get('whatsapp')) for r in results)},
                "format_notes": {"no_binary_files": True, "phone_format": "whatsapp digits only, e.g. 5567992466329"},
                "leads": results
            }
            json_path = f"/tmp/webscrapper_job_{job_dict['job_id']}.json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            job_dict['json_path'] = json_path

            if webhook_url:
                sent_ok = send_to_n8n(payload, webhook_url)
                job_dict['webhook_sent'] = sent_ok

        return results

    except Exception as ex:
        if job_dict:
            job_dict['status'] = 'error'
            job_dict['error'] = str(ex)
        print(f"❌ Scraper fatal error: {ex}", flush=True)
        return []

def send_to_n8n(payload, webhook_url):
    print(f"\n📡 Sending {len(payload.get('leads', []))} leads to n8n webhook: {webhook_url}...", flush=True)
    data_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(webhook_url, data=data_bytes, method='POST')
    req.add_header('Content-Type', 'application/json; charset=utf-8')
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode('utf-8')
            print(f"🎉 n8n Response: HTTP {resp.status} - {body}", flush=True)
            return True
    except Exception as e:
        print(f"❌ Failed to send payload to n8n webhook: {e}", flush=True)
        return False
