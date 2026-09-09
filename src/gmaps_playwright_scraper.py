import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import hashlib
import concurrent.futures
from playwright.sync_api import sync_playwright

TARGET_NICHE_POSITIVE_TERMS = (
    'clinica', 'clínica', 'consultorio', 'consultório', 'centro medico', 'centro médico',
    'medico', 'médico', 'medicina', 'odontologia', 'dentista', 'hospital',
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


def _emit_qualified_lead(job_dict, detail):
    callback = getattr(job_dict, '_on_qualified_lead', None) if job_dict is not None else None
    if callable(callback):
        try:
            callback(dict(detail))
        except Exception as exc:
            if job_dict is not None:
                job_dict['supabase_callback_error'] = str(exc)


def _set_job_phase(job_dict, phase, log=None):
    if job_dict is None:
        return
    now = time.time()
    job_dict['last_phase'] = phase
    job_dict['worker_heartbeat_at'] = now
    job_dict['last_activity'] = now
    if log:
        job_dict['log'] = log


def _promote_social_website(detail):
    url = str(detail.get('website') or '').strip()
    if not url:
        return
    lower = url.lower()
    if 'instagram.com' in lower:
        detail['instagram'] = list(dict.fromkeys((detail.get('instagram') or []) + [url]))
        detail['website'] = ''
    elif 'facebook.com' in lower:
        detail['facebook'] = list(dict.fromkeys((detail.get('facebook') or []) + [url]))
        detail['website'] = ''
    elif 'linkedin.com' in lower:
        detail['linkedin'] = list(dict.fromkeys((detail.get('linkedin') or []) + [url]))
        detail['website'] = ''

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
    socials = {'instagram': [], 'facebook': [], 'linkedin': []}
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
        elif 'facebook.com' in lower or 'fb.com' in lower:
            result_type = 'facebook'
        elif 'linkedin.com' in lower:
            result_type = 'linkedin'
        elif any(domain_name in lower for domain_name in ('youtube.com', 'tiktok.com')):
            result_type = 'social'
        elif any(domain_name in lower for domain_name in ('doctoralia.com', 'guiasaude', 'telelistas', 'yelp.com')):
            result_type = 'directory'
        elif 'google.com' in lower:
            continue
        else:
            result_type = 'website'
        web_results.append({'type': result_type, 'title': title, 'url': url, 'domain': domain, 'snippet': snippet})
        social_found = False
        for social in socials:
            if social + '.com' in lower or (social == 'facebook' and 'fb.com' in lower):
                social_found = True
                if url not in socials[social]:
                    socials[social].append(url)
        if not social_found and not website and urllib.parse.urlparse(url).scheme in ('http', 'https'):
            if not any(domain in lower for domain in (
                'google.com', 'facebook.com', 'linkedin.com', 'youtube.com',
                'tiktok.com', 'twitter.com', 'x.com', 'instagram.com',
            )):
                website = url
    snippets = ' '.join(str(x.get('snippet') or '') for x in links if isinstance(x, dict))
    match = re.search(r'\b(?:CNPJ\s*[:\-]?\s*)?\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b', text + ' ' + snippets, re.I)
    if match:
        digits = only_digits(match.group(0))
        if len(digits) == 14:
            cnpj = f'{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}'
    return {
        'website': website, 'instagram': socials['instagram'],
        'facebook': socials['facebook'], 'linkedin': socials['linkedin'],
        'cnpj': cnpj, 'web_results': web_results,
    }

def classify_business_niche(candidate):
    """Classify a Maps candidate using centralized positive/negative niche signals."""
    text = ' '.join(str(candidate.get(key) or '') for key in ('title', 'place_name', 'category', 'card_text')).lower()
    if any(term in text for term in TARGET_NICHE_NEGATIVE_TERMS):
        return False
    if any(term in text for term in TARGET_NICHE_POSITIVE_TERMS):
        return True
    # Generic clinical searches are accepted until profile details provide a stronger signal.
    return any(term in text for term in (
        'estetica', 'estética', 'clinica', 'clínica', 'consultorio', 'consultório',
        'centro medico', 'centro médico', 'especialista',
    ))

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


def stable_source_key(lead):
    """Stable id for idempotent persistence without touching commercial fields."""
    url = clean_google_redirect_url(lead.get('google_maps_url') or '')
    phone = format_whatsapp(lead.get('whatsapp') or lead.get('phone_raw'))
    name = re.sub(r'\s+', ' ', str(lead.get('place_name') or '').strip().lower())
    address = re.sub(r'\s+', ' ', str(lead.get('address') or '').strip().lower())
    seed = url.split('?')[0].rstrip('/').lower() if url else phone or f'{name}|{address}'
    return 'gmaps:' + hashlib.sha256(seed.encode('utf-8')).hexdigest()[:40]


def validate_detail_identity(page, candidate):
    """Prevent stale page data from being assigned to the next candidate."""
    expected_url = clean_google_redirect_url(candidate.get('href') or '')
    current_url = clean_google_redirect_url(getattr(page, 'url', '') or '')
    if expected_url and current_url and expected_url.split('?')[0].rstrip('/') != current_url.split('?')[0].rstrip('/'):
        return False
    expected = normalize_place_name(candidate.get('title'))
    if not expected:
        return True
    try:
        heading = page.query_selector('h1.DUwDvf, h1.fontTitleLarge, div[role="main"] h1, h1')
        actual = normalize_place_name(heading.inner_text() if heading else '')
        return not actual or actual.casefold() == expected.casefold() or expected.casefold() in actual.casefold() or actual.casefold() in expected.casefold()
    except Exception:
        return False


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


def route_fast_resources(route, request):
    if request.resource_type in {'image', 'media', 'font'}:
        route.abort()
    else:
        route.continue_()


def discovery_limits(max_leads):
    oversampling = scraper_float_env('SCRAPER_OVERSAMPLING_FACTOR', 1.5, 1.0)
    query_limit = scraper_int_env('SCRAPER_QUERY_CANDIDATE_LIMIT', 50, 1)
    return {
        'max_pool': max(int(max_leads * oversampling), 30),
        'hard_cap': max(int(max_leads * scraper_float_env('SCRAPER_HARD_CANDIDATE_FACTOR', 4.0, 1.0)), scraper_int_env('SCRAPER_MIN_HARD_CANDIDATES', 50, 1)),
        'query_limit': query_limit,
        'max_scrolls': scraper_int_env('SCRAPER_MAX_SCROLLS_PER_QUERY', 18),
        'scroll_wait_ms': scraper_int_env('SCRAPER_SCROLL_WAIT_MS', 1500),
        'max_no_new_scrolls': scraper_int_env('SCRAPER_MAX_NO_NEW_SCROLLS', 3),
        'low_yield_threshold': scraper_int_env('SCRAPER_LOW_YIELD_QUERY_THRESHOLD', 5),
        'max_low_yield_queries': scraper_int_env('SCRAPER_MAX_LOW_YIELD_QUERIES', 2),
        'reuse_detail_page': os.environ.get('SCRAPER_REUSE_DETAIL_PAGE', 'true').lower() == 'true',
        'detail_ready_wait_ms': scraper_int_env('SCRAPER_DETAIL_READY_WAIT_MS', 1200),
        'phone_retry_wait_ms': scraper_int_env('SCRAPER_PHONE_RETRY_WAIT_MS', 700),
        'fast_web_results_max_scrolls': scraper_int_env('FAST_WEB_RESULTS_MAX_SCROLLS', 1),
        'fast_web_results_scroll_delay_ms': scraper_int_env('FAST_WEB_RESULTS_SCROLL_DELAY_MS', 200),
        'reuse_search_page': os.environ.get('SCRAPER_REUSE_SEARCH_PAGE', 'true').lower() == 'true',
        'hard_candidate_factor': scraper_float_env('SCRAPER_HARD_CANDIDATE_FACTOR', 4.0, 1.0),
        'min_hard_candidates': scraper_int_env('SCRAPER_MIN_HARD_CANDIDATES', 50, 1),
        'pipeline_strategy': os.environ.get('SCRAPER_PIPELINE_STRATEGY', 'interleaved').lower(),
        'warmup_batch_size': scraper_int_env('SCRAPER_WARMUP_BATCH_SIZE', 2, 2),
        'detail_batch_size': scraper_int_env('SCRAPER_DETAIL_BATCH_SIZE', 6, 2),
        'max_detail_batch_size': min(8, scraper_int_env('SCRAPER_MAX_DETAIL_BATCH_SIZE', 8, 2)),
        'dynamic_batch_size': os.environ.get('SCRAPER_DYNAMIC_BATCH_SIZE', 'true').lower() == 'true',
        'card_snapshot': os.environ.get('SCRAPER_CARD_SNAPSHOT', 'true').lower() == 'true',
        'basic_detail_snapshot': os.environ.get('SCRAPER_BASIC_DETAIL_SNAPSHOT', 'true').lower() == 'true',
        'progress_sync_interval_ms': scraper_int_env('SCRAPER_PROGRESS_SYNC_INTERVAL_MS', 500, 0),
        'progress_sync_every_leads': scraper_int_env('SCRAPER_PROGRESS_SYNC_EVERY_LEADS', 2, 1),
    }


def adaptive_query_limit(remaining_leads, configured_limit=50):
    return min(configured_limit, max(20, remaining_leads * 2))


STOP_REASONS = {
    'target_reached', 'source_exhausted', 'queries_exhausted', 'runtime_budget',
    'query_budget', 'blocked_by_google', 'worker_error', 'partial_result',
}


def discovery_should_stop(current_count, target):
    return current_count >= target


def discovery_stop_reason(*, captured, target, source_exhausted=False,
                          queries_exhausted=False, runtime_budget=False,
                          query_budget=False, blocked_by_google=False,
                          worker_error=False):
    """Return an honest terminal reason; a short result is never success."""
    if captured >= target:
        return 'target_reached'
    if worker_error:
        return 'worker_error'
    if blocked_by_google:
        return 'blocked_by_google'
    if runtime_budget:
        return 'runtime_budget'
    if query_budget:
        return 'query_budget'
    if queries_exhausted:
        return 'queries_exhausted'
    if source_exhausted:
        return 'source_exhausted'
    return 'partial_result'


def scroll_observation(feed):
    """Read virtualized-feed progress without treating DOM card count as progress."""
    return feed.evaluate('''feed => {
        const links = [...feed.querySelectorAll('a[href*="/maps/place/"]')];
        const ids = links.map(a => a.href || a.getAttribute('href') || '').filter(Boolean);
        const text = (feed.innerText || '').toLowerCase();
        const endMarker = /(fim dos resultados|não há mais resultados|no more results|end of results|you.?ve reached the end of the list|você chegou ao fim da lista)/i.test(text);
        const state = [feed.scrollTop, feed.clientHeight, feed.scrollHeight, ids.slice(-8).join('|'), endMarker].join('|');
        return {scroll_top: feed.scrollTop, client_height: feed.clientHeight,
            scroll_height: feed.scrollHeight, identity_count: ids.length,
            identity_tail: ids.slice(-8), end_marker: endMarker,
            fingerprint: state};
    }''') or {}


def low_yield_should_stop(consecutive_queries, threshold, maximum):
    return consecutive_queries >= maximum and maximum > 0


def preserve_google_instagram(values):
    return list(dict.fromkeys(values or []))


GENERIC_PLACE_NAMES = {'', 'google', 'google maps', 'maps'}


def normalize_place_name(value):
    value = re.sub(r'\s+', ' ', str(value or '')).strip()
    return '' if value.lower() in GENERIC_PLACE_NAMES else value


def place_name_from_maps_url(url):
    try:
        parsed = urllib.parse.urlparse(str(url or ''))
        path = urllib.parse.unquote(parsed.path)
        match = re.search(r'/maps/place/([^/]+)', path, re.IGNORECASE)
        if not match:
            return ''
        return normalize_place_name(urllib.parse.unquote_plus(match.group(1)).replace('+', ' '))
    except Exception:
        return ''


def resolve_place_name(detail, item=None, page_url=''):
    item = item or {}
    for candidate in (
        detail.get('place_name'), item.get('title'),
        place_name_from_maps_url(page_url),
        place_name_from_maps_url(detail.get('google_maps_url')),
    ):
        candidate = normalize_place_name(candidate)
        if candidate:
            return candidate
    return ''


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
        'queries_started': 0, 'queries_completed': 0, 'queries_skipped': 0, 'query_errors': 0, 'feed_missing': 0,
        'candidate_cards_seen': 0, 'candidates_unique': 0, 'candidates_duplicate': 0,
        'candidates_prequalified': 0, 'candidates_rejected_pre_detail': 0,
        'details_avoided': 0, 'qualified_leads': 0, 'target_leads': target,
        'target_reached': False, 'early_stop_triggered': False,
        'time_to_first_candidate_ms': None, 'time_to_first_qualified_lead_ms': None,
        'query_discovery_ms': 0.0, 'detail_processing_ms': 0.0,
        'detail_total_ms': 0.0, 'detail_goto_ms': 0.0,
        'detail_ready_wait_ms': 0.0, 'basic_extract_ms': 0.0,
        'web_results_ms': 0.0, 'web_results_scroll_ms': 0.0,
        'qualification_ms': 0.0, 'detail_timeouts': 0,
        'web_results_attempted': 0, 'web_results_skipped': 0,
        'web_results_found': 0, 'web_results_instagram_found': 0,
        'rejected_before_web_results': 0,
        'discovery_scrolls': 0, 'dynamic_cards_loaded': 0, 'scroll_fingerprints': [],
        'scroll_no_progress': 0, 'source_end_marker_seen': False, 'candidate_identity_count': 0,
        'unique_candidates': 0, 'candidate_duplicates': 0,
        'detail_queue_size': 0, 'detail_workers': scraper_int_env('SCRAPER_DETAIL_CONCURRENCY', 3, 1),
        'detail_completed': 0, 'detail_failed': 0,
        'supabase_inserted': 0, 'supabase_updated': 0, 'supabase_failed': 0, 'supabase_batches': 0,
        'google_web_results_found': 0, 'instagram_found': 0, 'facebook_found': 0,
        'linkedin_found': 0, 'cnpj_found': 0,
        'detail_performance_samples': [],
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


def extract_candidate_cards_snapshot(feed):
    """Capture all rendered card metadata with one browser round-trip."""
    return feed.evaluate('''feed => {
        const links = [...feed.querySelectorAll('a.hfpxzc[href*="/maps/place/"], a[href*="/maps/place/"]')];
        return links.map(link => {
            let root = link;
            for (let i = 0; i < 5 && root.parentElement; i++) {
                root = root.parentElement;
                if (root.getAttribute('role') === 'article' || root.querySelector('[role="img"]')) break;
            }
            return {
                href: link.href || '',
                title: link.getAttribute('aria-label') || '',
                card_text: root.innerText || '',
                card_aria: root.getAttribute('aria-label') || ''
            };
        });
    }''') or []


def extract_basic_place_snapshot(page):
    """Capture essential detail fields with one browser round-trip."""
    return page.evaluate('''() => {
        const text = (selector) => document.querySelector(selector)?.innerText?.trim() || '';
        const aria = (selector) => document.querySelector(selector)?.getAttribute('aria-label') || '';
        const addressAria = aria('button[data-item-id="address"], button[aria-label*="Endereço:"]');
        const phoneAria = aria('button[data-tooltip*="telefone"], button[data-item-id^="phone:tel:"]');
        const plusAria = aria('button[data-item-id="oloc"]');
        return {
            place_name: text('h1.DUwDvf, h1.fontTitleLarge, div[role="main"] h1, h1'),
            total_score: text('div.F7vEfc span.ceNzKf, div.fontBodyMedium span[aria-hidden="true"]'),
            reviews_count: text('button[jsaction*="review"], button[aria-label*="avaliações"]'),
            category: text('button[jsaction*="category"]'),
            address: addressAria.replace(/^.*Endereço:[ \\t]*/i, '') || text('button[data-item-id="address"], button[aria-label*="Endereço:"]'),
            phone_raw: phoneAria.replace(/^.*Telefone:[ \\t]*/i, '') || text('button[data-tooltip*="telefone"], button[data-item-id^="phone:tel:"]'),
            website: document.querySelector('a[data-item-id="authority"], a[aria-label*="site"], a[aria-label*="Website"]')?.href || '',
            plus_code: plusAria.replace(/^.*Plus Code:[ \\t]*/i, '') || text('button[data-item-id="oloc"]')
        };
    }''') or {}

def extract_google_web_results(page, max_scrolls=None, scroll_delay_ms=None):
    """Read Google's optional web-results block from its semantic container."""
    if max_scrolls is None:
        max_scrolls = max(0, int(os.environ.get('WEB_RESULTS_MAX_SCROLLS', '3')))
    if scroll_delay_ms is None:
        scroll_delay_ms = 200

    def read_block():
        return page.evaluate('''() => {
            const headings = [...document.querySelectorAll('h1,h2,h3,[role="heading"]')];
            const heading = headings.find(el => /resultados da web/i.test(el.innerText || ''));
            if (!heading) return {text: '', links: []};
            let root = heading;
            for (let i = 0; i < 8 && root.parentElement; i++) {
                root = root.parentElement;
                if (root.querySelectorAll('a[href]').length >= 1 && (root.scrollHeight > root.clientHeight || i >= 3)) break;
            }
            return {
                text: root.innerText || '',
                links: [...root.querySelectorAll('a[href]')].map(a => ({url: a.href, title: a.innerText || a.getAttribute('aria-label') || '', snippet: a.parentElement?.innerText || ''})).filter(x => x.url)
            };
        }''') or {'text': '', 'links': []}

    try:
        payload = read_block()
        result = parse_google_web_result_payload(payload)
        for _ in range(max_scrolls):
            if result['web_results']:
                break
            page.evaluate('''() => {
                const heading = [...document.querySelectorAll('h1,h2,h3,[role="heading"]')].find(el => /resultados da web/i.test(el.innerText || ''));
                if (!heading) return false;
                let root = heading;
                for (let i = 0; i < 8 && root.parentElement; i++) {
                    root = root.parentElement;
                    if (root.scrollHeight > root.clientHeight) { root.scrollTop = root.scrollHeight; return true; }
                }
                window.scrollBy(0, 500); return true;
            }''')
            if scroll_delay_ms:
                time.sleep(scroll_delay_ms / 1000)
            payload = read_block()
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

def _extract_place_detail(page, fast=False, item=None, include_optional=True, ready_wait_ms=1200, timings=None):
    if not fast:
        time.sleep(2.0)
    data = {}
    timings = timings if timings is not None else {}

    # 1. Place Name
    if fast:
        ready_started = time.perf_counter()
        try:
            page.wait_for_selector(
                'h1.DUwDvf, h1.fontTitleLarge, div[role="main"] h1, h1,'
                'button[data-item-id="address"], button[data-item-id^="phone:tel:"],'
                'a[data-item-id="authority"], button[jsaction*="category"]',
                timeout=ready_wait_ms,
            )
        except Exception:
            pass
        timings['ready_wait_ms'] = (time.perf_counter() - ready_started) * 1000
    basic_started = time.perf_counter()
    title_el = page.query_selector('h1.DUwDvf, h1.fontTitleLarge, div[role="main"] h1, h1')
    if title_el and title_el.inner_text().strip():
        data['place_name'] = title_el.inner_text().strip()
    else:
        try:
            pg_title = (page.title() or '').split('- Google Maps')[0].split('- Google')[0].strip()
            data['place_name'] = normalize_place_name(pg_title)
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
        txt = ' '.join(filter(None, [
            reviews_btn.inner_text().strip(),
            reviews_btn.get_attribute('aria-label') or '',
        ]))
        parsed_reviews = parse_reviews(txt)
        if parsed_reviews is not None:
            data['reviews_count'] = parsed_reviews
    if not data.get('reviews_count'):
        try:
            body_text = page.inner_text('body')
            review_match = re.search(r'(\d+(?:[.,]\d+)?\s*(?:mil|k)?\s*(?:avaliações|reviews?))', body_text, re.I)
            data['reviews_count'] = parse_reviews(review_match.group(1)) if review_match else ''
        except Exception:
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

    # 6. Website already rendered by Google Maps. Optional web results are
    # deliberately separated so FAST can qualify cheaply first.
    web_btn = page.query_selector('a[data-item-id="authority"], a[aria-label*="site"], a[aria-label*="Website"]')
    if web_btn:
        data['website'] = clean_google_redirect_url(web_btn.get_attribute('href') or '')
    else:
        data['website'] = ''
    if include_optional:
        web_results = extract_google_web_results(page)
        if not data['website']:
            data['website'] = web_results['website']
        data['instagram'] = web_results['instagram']
        data['google_result_cnpj'] = web_results['cnpj']
        data['web_results'] = web_results['web_results']
        data['instagram_source'] = 'google_web_results' if data['instagram'] else ''
        data['cnpj_source'] = 'google_web_results' if data['google_result_cnpj'] else ''
    else:
        data['instagram'] = []
        data['google_result_cnpj'] = ''
        data['web_results'] = []
        data['instagram_source'] = ''
        data['cnpj_source'] = ''

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
    data['place_name'] = resolve_place_name(data, item, data['google_maps_url'])
    timings['basic_extract_ms'] = (time.perf_counter() - basic_started) * 1000
    return data


def _detail_from_snapshot(page, item=None, ready_wait_ms=1200, timings=None):
    started = time.perf_counter()
    try:
        page.wait_for_selector(
            'h1.DUwDvf, h1.fontTitleLarge, div[role="main"] h1, h1,'
            'button[data-item-id="address"], button[data-item-id^="phone:tel:"],'
            'a[data-item-id="authority"], button[jsaction*="category"]',
            timeout=ready_wait_ms,
        )
    except Exception:
        pass
    try:
        raw = extract_basic_place_snapshot(page)
    except Exception:
        return None
    data = {
        'place_name': normalize_place_name(raw.get('place_name')),
        'total_score': (raw.get('total_score') or '').replace(',', '.'),
        'reviews_count': parse_reviews(raw.get('reviews_count')) if raw.get('reviews_count') else '',
        'category': raw.get('category') or '',
        'address': raw.get('address') or '',
        'phone_raw': raw.get('phone_raw') or '',
        'website': clean_google_redirect_url(raw.get('website') or ''),
        'plus_code': raw.get('plus_code') or '',
        'instagram': [], 'facebook': [], 'linkedin': [], 'google_result_cnpj': '', 'web_results': [],
        'instagram_source': '', 'cnpj_source': '',
        'google_maps_url': page.url,
    }
    data['whatsapp'] = format_whatsapp(data['phone_raw'])
    data['street'] = data['address'].split('-')[0].strip() if data['address'] else ''
    data['place_name'] = resolve_place_name(data, item, data['google_maps_url'])
    if not data['place_name'] or not data['phone_raw']:
        return None
    if timings is not None:
        timings['ready_wait_ms'] = (time.perf_counter() - started) * 1000
        timings['basic_extract_ms'] = 0.0
    return data


def extract_basic_place_detail(page, fast=False, item=None, ready_wait_ms=1200, timings=None):
    if fast and os.environ.get('SCRAPER_BASIC_DETAIL_SNAPSHOT', 'true').lower() == 'true':
        snapshot = _detail_from_snapshot(page, item=item, ready_wait_ms=ready_wait_ms, timings=timings)
        if snapshot is not None:
            return snapshot
    return _extract_place_detail(
        page, fast=fast, item=item, include_optional=False,
        ready_wait_ms=ready_wait_ms, timings=timings,
    )


def extract_optional_google_web_results(page, fast=False, timings=None):
    started = time.perf_counter()
    if fast:
        result = extract_google_web_results(
            page,
            max_scrolls=max(0, int(os.environ.get('FAST_WEB_RESULTS_MAX_SCROLLS', '1'))),
            scroll_delay_ms=max(0, int(os.environ.get('FAST_WEB_RESULTS_SCROLL_DELAY_MS', '200'))),
        )
    else:
        result = extract_google_web_results(page)
    if timings is not None:
        timings['web_results_ms'] = (time.perf_counter() - started) * 1000
    return result


def extract_phone_from_place_page(page):
    phone_btn = page.query_selector('button[data-tooltip*="telefone"], button[data-item-id^="phone:tel:"]')
    if not phone_btn:
        return {'phone_raw': '', 'whatsapp': ''}
    aria = phone_btn.get_attribute('aria-label') or ''
    if 'Telefone:' in aria:
        raw_phone = aria.split('Telefone:')[-1].strip()
    else:
        lines = [l.strip() for l in phone_btn.inner_text().split('\n') if l.strip() and l.strip() != '']
        raw_phone = ' '.join(lines)
    return {'phone_raw': raw_phone, 'whatsapp': format_whatsapp(raw_phone)}


def summarize_samples(values):
    values = sorted(float(value) for value in values if value is not None)
    if not values:
        return {'count': 0, 'min_ms': 0.0, 'p50_ms': 0.0, 'p95_ms': 0.0, 'max_ms': 0.0, 'avg_ms': 0.0}
    p50 = values[(len(values) - 1) // 2]
    p95 = values[min(len(values) - 1, max(0, int(len(values) * 0.95) - 1))]
    return {
        'count': len(values), 'min_ms': round(values[0], 2),
        'p50_ms': round(p50, 2), 'p95_ms': round(p95, 2),
        'max_ms': round(values[-1], 2), 'avg_ms': round(sum(values) / len(values), 2),
    }


def detail_prequalification_reason(detail, category):
    if not classify_business_niche(detail):
        return 'category'
    rating = parse_rating(detail.get('total_score'))
    if rating is not None and rating < 4.5:
        return 'rating'
    reviews = parse_reviews(detail.get('reviews_count'))
    if reviews is not None and reviews < 20:
        return 'reviews'
    return ''


def extract_detail_from_place_page(page, fast=False, item=None):
    data = extract_basic_place_detail(page, fast=fast, item=item)
    optional = extract_optional_google_web_results(page, fast=fast)
    if not data.get('website'):
        data['website'] = optional.get('website', '')
    data.update({key: optional.get(key, default) for key, default in {
        'instagram': [], 'facebook': [], 'linkedin': [], 'google_result_cnpj': '', 'web_results': [],
    }.items()})
    data['instagram_source'] = 'google_web_results' if data.get('instagram') else ''
    data['cnpj'] = data.get('google_result_cnpj') or data.get('cnpj') or ''
    data['cnpj_source'] = 'google_web_results' if data.get('cnpj') else ''
    _promote_social_website(data)
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


def deterministic_query_shard(queries, worker_index=0, worker_count=1):
    """Split queries deterministically; each process owns its browser state."""
    worker_count = max(1, int(worker_count or 1))
    worker_index = int(worker_index or 0) % worker_count
    return list(queries)[worker_index::worker_count]


def _prequalify_card(item, category):
    if not classify_business_niche({'title': item.get('title'), 'category': category, 'card_text': item.get('card_text')}):
        return 'category'
    if item.get('rating') is not None and item['rating'] < 4.5:
        return 'rating'
    if item.get('reviews_count') is not None and item['reviews_count'] < 20:
        return 'reviews'
    return ''


def candidate_priority_score(item, category=''):
    text = f"{item.get('title', '')} {item.get('card_text', '')}".lower()
    score = 30 if item.get('google_sponsored') else 0
    reviews = item.get('reviews_count')
    rating = item.get('rating')
    if reviews is not None:
        score += 20 if reviews >= 100 else 10 if reviews >= 50 else 0
    if rating is not None:
        score += 15 if rating >= 4.8 else 5 if rating >= 4.5 else 0
    if classify_business_niche({'title': item.get('title'), 'category': category, 'card_text': text}):
        score += 20
    return score


def next_detail_batch_size(conversion_rate, configured=6, dynamic=True, maximum=8):
    if not dynamic:
        return max(2, min(maximum, configured))
    if conversion_rate >= 0.70:
        return 4
    if conversion_rate >= 0.35:
        return 6
    return max(2, min(maximum, 8))


def _scrape_gmaps_microbatch(job_id, category, city, state, max_leads, job_dict, mode, query_shard=None):
    limits = discovery_limits(max_leads)
    navigation_timeout_ms = max(5000, int(os.environ.get('SCRAPER_NAVIGATION_TIMEOUT_MS', '20000')))
    feed_timeout_ms = max(3000, int(os.environ.get('SCRAPER_FEED_TIMEOUT_MS', '8000')))
    query_budget_seconds = max(15.0, float(os.environ.get('SCRAPER_QUERY_BUDGET_SECONDS', '75')))
    runtime_budget_seconds = max(query_budget_seconds, float(os.environ.get('SCRAPER_RUNTIME_BUDGET_SECONDS', '900')))
    initialize_discovery_metrics(job_dict, max_leads)
    results, seen_candidates, seen_places, seen_phones = [], set(), set(), set()
    detail_samples, query_metrics = [], []
    queries, started = generate_query_variations(category, city, state), time.perf_counter()
    if query_shard:
        queries = deterministic_query_shard(queries, *query_shard)
    local = {key: 0 for key in ('queries_started', 'queries_completed', 'queries_skipped',
        'candidate_cards_seen', 'candidates_unique', 'candidates_duplicate',
        'candidates_prequalified', 'candidates_rejected_pre_detail', 'details_avoided',
        'details_opened', 'qualified_leads', 'without_whatsapp', 'rejected_whatsapp',
        'rejected_before_web_results', 'web_results_attempted', 'web_results_skipped',
        'web_results_found', 'web_results_instagram_found', 'candidate_snapshot_count',
        'basic_detail_snapshot_fallbacks', 'candidate_batches_processed', 'progress_sync_count',
        'discovery_scrolls', 'dynamic_cards_loaded', 'detail_failed', 'google_web_results_found',
        'instagram_found', 'facebook_found', 'linkedin_found', 'cnpj_found')}
    local.update({'candidate_snapshot_ms': [], 'basic_detail_snapshot_ms': [], 'batch_sizes': [],
                  'candidate_priority_used': 0, 'manager_sync_count': 0, 'last_sync': 0.0,
                  'last_synced_leads': 0})

    def sync_job_metrics(q_idx=0, force=False):
        now = time.perf_counter()
        due = ((now - local['last_sync']) * 1000 >= limits['progress_sync_interval_ms'] or
               len(results) - local['last_synced_leads'] >= limits['progress_sync_every_leads'])
        if job_dict is None or (not force and not due):
            return
        for key, value in local.items():
            if key not in ('candidate_snapshot_ms', 'basic_detail_snapshot_ms', 'batch_sizes',
                           'last_sync', 'last_synced_leads') and isinstance(value, (int, float)):
                job_dict[key] = value
        job_dict['leads'] = json.loads(json.dumps(results, ensure_ascii=False))
        job_dict['current_count'] = len(results)
        job_dict['progress_sync_count'] = local['progress_sync_count'] + 1
        job_dict['manager_sync_count'] = local['manager_sync_count'] + 1
        job_dict['log'] = (f'FAST V3 | Query {q_idx}/{len(queries)} | candidatos={local["candidate_cards_seen"]} '
                           f'| buffer | detalhes={local["details_opened"]} | leads={len(results)}/{max_leads}')
        job_dict['last_activity'] = time.time()
        job_dict['worker_heartbeat_at'] = job_dict['last_activity']
        local['last_sync'], local['last_synced_leads'] = now, len(results)
        local['progress_sync_count'] += 1
        local['manager_sync_count'] += 1

    def process_batch(candidates, detail_page, q_idx, batch_number):
        if not candidates:
            return
        candidates.sort(key=lambda item: candidate_priority_score(item, category), reverse=True)
        local['candidate_priority_used'] += 1
        local['candidate_batches_processed'] += 1
        local['batch_sizes'].append(len(candidates))
        qualified_before = len(results)
        details_before = local['details_opened']
        for item in candidates:
            if len(results) >= max_leads:
                local['target_reached'] = 1
                break
            local['details_opened'] += 1
            detail_started, timings = time.perf_counter(), {}
            try:
                goto_started = time.perf_counter()
                detail_page.goto(item['href'], wait_until='commit', timeout=10000)
                timings['goto_ms'] = (time.perf_counter() - goto_started) * 1000
                if not validate_detail_identity(detail_page, item):
                    local['detail_failed'] = local.get('detail_failed', 0) + 1
                    continue
                detail = extract_basic_place_detail(detail_page, fast=True, item=item,
                    ready_wait_ms=limits['detail_ready_wait_ms'], timings=timings)
                if detail is None:
                    local['basic_detail_snapshot_fallbacks'] += 1
                    detail = _extract_place_detail(detail_page, fast=True, item=item,
                        include_optional=False, ready_wait_ms=limits['detail_ready_wait_ms'], timings=timings)
                detail.update({'place_name': detail.get('place_name') or item['title'], 'city': city,
                    'state': state, 'country_code': 'BR', 'google_sponsored': item['google_sponsored']})
                if not detail.get('reviews_count') and item.get('reviews_count') is not None:
                    detail['reviews_count'] = item['reviews_count']
                if not detail.get('total_score') and item.get('rating') is not None:
                    detail['total_score'] = str(item['rating'])
                qualification_started = time.perf_counter()
                if not detail.get('whatsapp'):
                    try:
                        detail_page.wait_for_selector('button[data-tooltip*="telefone"], button[data-item-id^="phone:tel:"]', timeout=limits['phone_retry_wait_ms'])
                    except Exception:
                        pass
                    detail.update(extract_phone_from_place_page(detail_page))
                timings['qualification_ms'] = (time.perf_counter() - qualification_started) * 1000
                reason = 'whatsapp' if not detail.get('whatsapp') else detail_prequalification_reason({**item, **detail}, category)
                if reason:
                    local['rejected_before_web_results'] += 1
                    local['web_results_skipped'] += 1
                    if reason == 'whatsapp':
                        local['without_whatsapp'] += 1
                        local['rejected_whatsapp'] += 1
                    else:
                        local['candidates_rejected_pre_detail'] += 1
                        local['details_avoided'] += 1
                    timings['total_ms'] = (time.perf_counter() - detail_started) * 1000
                    detail_samples.append(timings)
                    continue
                local['web_results_attempted'] += 1
                optional = extract_optional_google_web_results(detail_page, fast=True, timings=timings)
                detail['website'] = detail.get('website') or optional.get('website', '')
                detail.update({key: optional.get(key, default) for key, default in {
                    'instagram': [], 'facebook': [], 'linkedin': [], 'google_result_cnpj': '', 'web_results': [],
                    'instagram_source': '', 'cnpj_source': ''}.items()})
                detail['cnpj'] = detail.get('google_result_cnpj') or detail.get('cnpj') or ''
                detail['cnpj_source'] = 'google_web_results' if detail['cnpj'] else ''
                _promote_social_website(detail)
                local['web_results_found'] += bool(optional.get('web_results'))
                local['web_results_instagram_found'] += bool(optional.get('instagram'))
                local['google_web_results_found'] = local.get('google_web_results_found', 0) + bool(optional.get('web_results'))
                local['instagram_found'] = local.get('instagram_found', 0) + bool(optional.get('instagram'))
                local['facebook_found'] = local.get('facebook_found', 0) + bool(optional.get('facebook'))
                local['linkedin_found'] = local.get('linkedin_found', 0) + bool(optional.get('linkedin'))
                local['cnpj_found'] = local.get('cnpj_found', 0) + bool(detail.get('cnpj'))
                wa = detail.get('whatsapp') or ''
                place_key = f'{detail.get("place_name", "")}|{detail.get("street") or detail.get("address") or ""}'.lower()
                if (place_key != '|' and place_key in seen_places) or wa in seen_phones:
                    local['candidates_duplicate'] += 1
                    continue
                seen_places.add(place_key); seen_phones.add(wa)
                detail.update({'qualification_status': 'qualified', 'with_whatsapp': True,
                    'instagram': preserve_google_instagram(detail.get('instagram')),
                    'facebook': list(dict.fromkeys(detail.get('facebook') or [])),
                    'linkedin': list(dict.fromkeys(detail.get('linkedin') or [])),
                    'emails': list(dict.fromkeys(detail.get('emails') or []))})
                results.append(detail)
                _emit_qualified_lead(job_dict, detail)
                local['qualified_leads'] += 1
                timings['total_ms'] = (time.perf_counter() - detail_started) * 1000
                detail_samples.append(timings)
                if len(results) == 1 and job_dict is not None:
                    job_dict['time_to_first_qualified_lead_ms'] = round((time.perf_counter() - started) * 1000, 2)
                sync_job_metrics(q_idx, force=len(results) == 1)
            except Exception as exc:
                print(f'⚠️ Error processing detail: {exc}', flush=True)
        processed = local['details_opened'] - details_before
        conversion = (len(results) - qualified_before) / max(processed, 1)
        local['last_conversion'] = conversion
        sync_job_metrics(q_idx, force=True)

    try:
        _set_job_phase(job_dict, 'playwright_starting', 'Iniciando Playwright...')
        with sync_playwright() as p:
            _set_job_phase(job_dict, 'playwright_started')
            _set_job_phase(job_dict, 'chromium_launching', 'Iniciando Chromium...')
            browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            _set_job_phase(job_dict, 'chromium_launched')
            _set_job_phase(job_dict, 'context_creating')
            context = browser.new_context(locale='pt-BR', ignore_https_errors=True)
            _set_job_phase(job_dict, 'context_created')
            if os.environ.get('SCRAPER_BLOCK_HEAVY_RESOURCES', 'false').lower() == 'true':
                context.route('**/*', route_fast_resources)
            _set_job_phase(job_dict, 'search_page_creating')
            detail_page = context.new_page(); detail_page.set_default_timeout(15000)
            search_page = context.new_page(); search_page.set_default_timeout(30000)
            _set_job_phase(job_dict, 'search_page_created')
            _set_job_phase(job_dict, 'query_loop_entered')
            current_batch_size, batch_number = limits['warmup_batch_size'], 0
            for q_idx, query in enumerate(queries, 1):
                if len(results) >= max_leads: break
                if time.perf_counter() - started >= runtime_budget_seconds:
                    if job_dict is not None: job_dict['stop_reason'] = 'runtime_budget'
                    break
                _set_job_phase(job_dict, 'query_started', f'Query {q_idx}/{len(queries)}: {query}')
                local['queries_started'] += 1; query_started = time.perf_counter(); unique_in_query = 0; qualified_before = len(results)
                try:
                    search_page.goto(f'https://www.google.com.br/maps/search/{urllib.parse.quote(query)}', wait_until='domcontentloaded', timeout=navigation_timeout_ms)
                    if time.perf_counter() - query_started >= query_budget_seconds:
                        if job_dict is not None: job_dict['stop_reason'] = 'query_timeout'
                        continue
                    feed = search_page.wait_for_selector('div[role="feed"]', timeout=feed_timeout_ms)
                    if not feed:
                        if job_dict is not None: job_dict['feed_missing'] = int(job_dict.get('feed_missing', 0)) + 1
                        continue
                    limit, no_new, previous_fingerprint, query_seen_hrefs = adaptive_query_limit(max_leads - len(results), limits['query_limit']), 0, '', set()
                    candidate_buffer = []
                    for _ in range(limits['max_scrolls']):
                        local['discovery_scrolls'] += 1
                        if len(results) >= max_leads or len(seen_candidates) >= limits['hard_cap']: break
                        observation = scroll_observation(feed)
                        fingerprint = observation.get('fingerprint', '')
                        no_new = no_new + 1 if fingerprint and fingerprint == previous_fingerprint else 0
                        previous_fingerprint = fingerprint
                        if job_dict is not None:
                            job_dict['dynamic_cards_loaded'] = max(int(job_dict.get('dynamic_cards_loaded', 0)), int(observation.get('identity_count', 0)))
                            job_dict['candidate_identity_count'] = len(seen_candidates)
                            job_dict['source_end_marker_seen'] = bool(observation.get('end_marker'))
                            fps = list(job_dict.get('scroll_fingerprints') or [])
                            if fingerprint: fps.append(fingerprint)
                            job_dict['scroll_fingerprints'] = fps[-20:]
                            job_dict['scroll_no_progress'] = no_new
                        snap_started = time.perf_counter()
                        try:
                            cards = extract_candidate_cards_snapshot(feed) if limits['card_snapshot'] else []
                        except Exception:
                            cards = []
                        if not cards:
                            links = feed.query_selector_all('a.hfpxzc[href*="/maps/place/"], a[href*="/maps/place/"]')
                            cards = [{'href': link.get_attribute('href') or '', 'title': link.get_attribute('aria-label') or '', 'card_text': '', 'card_aria': ''} for link in links]
                        local['candidate_snapshot_count'] += 1; local['candidate_snapshot_ms'].append((time.perf_counter() - snap_started) * 1000)
                        new_count = 0
                        for card in cards:
                            href = card.get('href') or ''
                            if not href or href in query_seen_hrefs or len(query_seen_hrefs) >= limit: continue
                            query_seen_hrefs.add(href); local['candidate_cards_seen'] += 1
                            text = f"{card.get('card_text', '')} {card.get('card_aria', '')}"
                            item = {'href': href, 'title': card.get('title', ''), 'card_text': text,
                                'rating': parse_rating(text), 'reviews_count': parse_reviews(text) if re.search(r'avali|reviews?', text, re.I) else None,
                                'google_sponsored': bool(re.search(r'patrocinado', text, re.I))}
                            identity = candidate_identity(item)
                            if not identity or identity in seen_candidates: local['candidates_duplicate'] += 1; continue
                            seen_candidates.add(identity); unique_in_query += 1; new_count += 1; local['candidates_unique'] += 1
                            reason = _prequalify_card(item, category)
                            if reason: local['candidates_rejected_pre_detail'] += 1; local['details_avoided'] += 1; continue
                            local['candidates_prequalified'] += 1; candidate_buffer.append(item)
                            if len(candidate_buffer) >= current_batch_size:
                                batch_number += 1; process_batch(candidate_buffer, detail_page, q_idx, batch_number); candidate_buffer.clear()
                                if len(results) >= max_leads: break
                        if candidate_buffer and (observation.get('end_marker') or no_new >= limits['max_no_new_scrolls']):
                            batch_number += 1; process_batch(candidate_buffer, detail_page, q_idx, batch_number); candidate_buffer.clear()
                        if len(results) >= max_leads: break
                        if observation.get('end_marker') or no_new >= limits['max_no_new_scrolls']: break
                        feed.evaluate('el => el.scrollTo(0, el.scrollHeight)'); search_page.mouse.wheel(0, 3500)
                        try:
                            search_page.wait_for_function(
                                '''([selector, before]) => {
                                    const feed = document.querySelector(selector);
                                    if (!feed) return false;
                                    const links = [...feed.querySelectorAll('a[href*="/maps/place/"]')];
                                    const ids = links.map(a => a.href || a.getAttribute('href') || '').filter(Boolean);
                                    const text = (feed.innerText || '').toLowerCase();
                                    const end = /(fim dos resultados|não há mais resultados|no more results|end of results|you.?ve reached the end of the list|você chegou ao fim da lista)/i.test(text);
                                    const fingerprint = [feed.scrollTop, feed.clientHeight, feed.scrollHeight, ids.slice(-8).join('|'), end].join('|');
                                    return fingerprint !== before || end;
                                }''',
                                arg=['div[role="feed"]', previous_fingerprint],
                                timeout=limits['scroll_wait_ms'])
                        except Exception:
                            # Timeout is not proof of no progress in a virtualized feed.
                            refreshed = scroll_observation(feed)
                            if refreshed.get('fingerprint') == previous_fingerprint and not refreshed.get('end_marker'):
                                no_new += 1
                            else:
                                no_new = 0
                    if candidate_buffer: batch_number += 1; process_batch(candidate_buffer, detail_page, q_idx, batch_number)
                    conversion = (len(results) - qualified_before) / max(local['details_opened'], 1)
                    if limits['dynamic_batch_size'] and batch_number:
                        current_batch_size = next_detail_batch_size(local.get('last_conversion', conversion), limits['detail_batch_size'], True, limits['max_detail_batch_size'])
                    query_metrics.append({'query': query, 'new_unique_candidates': unique_in_query, 'qualified_leads_generated': len(results) - qualified_before})
                    sync_job_metrics(q_idx, force=True)
                    if unique_in_query < limits['low_yield_threshold'] or len(results) == qualified_before: local.setdefault('low_yield', 0); local['low_yield'] += 1
                    else: local['low_yield'] = 0
                    if local.get('low_yield', 0) >= limits['max_low_yield_queries']: break
                except Exception as exc:
                    if job_dict is not None:
                        job_dict['query_errors'] = int(job_dict.get('query_errors', 0)) + 1
                        job_dict['last_activity'] = time.time()
                    print(f"⚠️ Error collecting query '{query}': {exc}", flush=True)
                finally:
                    local['queries_completed'] += 1
                    if job_dict is not None: job_dict['query_discovery_ms'] = round(job_dict.get('query_discovery_ms', 0.0) + (time.perf_counter() - query_started) * 1000, 2)
            detail_page.close(); search_page.close(); browser.close()
    finally:
        if job_dict is not None:
            elapsed = (time.perf_counter() - started) * 1000
            for key, value in local.items():
                if isinstance(value, (int, float)): job_dict[key] = value
            job_dict.update({'leads': results, 'current_count': len(results), 'candidates_found': len(seen_candidates),
                'qualified': len(results), 'details_skipped': local['details_avoided'], 'target_reached': len(results) >= max_leads,
                'early_stop_triggered': len(results) >= max_leads, 'qualified_leads_per_minute': round(len(results) / max(elapsed / 60000, 0.001), 2),
                'candidate_batch_avg_size': round(sum(local['batch_sizes']) / max(len(local['batch_sizes']), 1), 2),
                'candidate_batch_max_size': max(local['batch_sizes'] or [0]), 'batch_conversion_rate': round(local.get('last_conversion', 0) * 100, 2),
                'candidate_priority_used': bool(local['candidate_priority_used']), 'candidate_snapshot_ms': summarize_samples(local['candidate_snapshot_ms']),
                'basic_detail_snapshot_fallbacks': local['basic_detail_snapshot_fallbacks'], 'manager_sync_count': local['manager_sync_count'],
                'progress_sync_count': local['progress_sync_count'], 'query_metrics': query_metrics, 'scrape_total_ms': round(elapsed, 2)})
            detail_summary = summarize_samples([sample.get('total_ms') for sample in detail_samples])
            job_dict.update({'details_processed': len(detail_samples), 'details_qualified': len(results), 'detail_performance_samples': None,
                'average_detail_ms': detail_summary['avg_ms'], 'p50_detail_ms': detail_summary['p50_ms'], 'p95_detail_ms': detail_summary['p95_ms'], 'max_detail_ms': detail_summary['max_ms'],
                'basic_detail_snapshot_ms': summarize_samples(local['basic_detail_snapshot_ms']),
                'candidate_batches_processed': local['candidate_batches_processed'],
                'performance': {'detail': detail_summary, 'candidate_snapshot': job_dict['candidate_snapshot_ms'],
                                'basic_detail_snapshot': summarize_samples(local['basic_detail_snapshot_ms'])}})
            job_dict.pop('detail_performance_samples', None); sync_job_metrics(len(queries), force=True)
            existing_reason = job_dict.get('stop_reason')
            job_dict['stop_reason'] = existing_reason if existing_reason in STOP_REASONS else discovery_stop_reason(
                captured=len(results), target=max_leads,
                source_exhausted=bool(job_dict.get('source_end_marker_seen') or job_dict.get('scroll_no_progress', 0) >= limits['max_no_new_scrolls']),
                blocked_by_google=bool(job_dict.get('feed_missing') and not job_dict.get('discovery_scrolls')),
                worker_error=bool(job_dict.get('query_errors') and not job_dict.get('feed_missing')),
                queries_exhausted=job_dict.get('queries_completed', 0) >= len(queries),
            )
            job_dict['stop_details'] = {'target': max_leads, 'captured': len(results),
                'limit': 'max_leads' if job_dict['stop_reason'] == 'target_reached' else job_dict['stop_reason'],
                'candidate_identity_count': len(seen_candidates), 'scrolls': job_dict.get('discovery_scrolls', 0)}
            job_dict['status'] = 'running'
    return results


def _scrape_gmaps_incremental(job_id, category, city, state, max_leads, job_dict, mode, query_shard=None):
    limits = discovery_limits(max_leads)
    query_budget_seconds = max(15.0, float(os.environ.get('SCRAPER_QUERY_BUDGET_SECONDS', '75')))
    runtime_budget_seconds = max(query_budget_seconds, float(os.environ.get('SCRAPER_RUNTIME_BUDGET_SECONDS', '900')))
    if limits['pipeline_strategy'] == 'microbatch':
        return _scrape_gmaps_microbatch(job_id, category, city, state, max_leads, job_dict, mode, query_shard)
    initialize_discovery_metrics(job_dict, max_leads)
    results, seen_candidates, seen_places, seen_phones = [], set(), set(), set()
    queries = generate_query_variations(category, city, state)
    if query_shard:
        queries = deterministic_query_shard(queries, *query_shard)
    started = time.perf_counter()
    low_yield = 0
    detail_page = None
    query_metrics = []

    def inc(key, amount=1):
        if job_dict is not None:
            job_dict[key] = int(job_dict.get(key, 0)) + amount

    def record_detail(timings):
        if job_dict is None:
            return
        samples = list(job_dict.get('detail_performance_samples') or [])
        samples.append(dict(timings))
        job_dict['detail_performance_samples'] = samples[-100:]
        total = float(timings.get('total_ms', 0.0))
        job_dict['detail_processing_ms'] = round(job_dict.get('detail_processing_ms', 0.0) + total, 2)
        job_dict['detail_total_ms'] = job_dict['detail_processing_ms']

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
            if os.environ.get('SCRAPER_BLOCK_HEAVY_RESOURCES', 'false').lower() == 'true':
                context.route('**/*', route_fast_resources)
            context.on('page', lambda page: page.on('dialog', lambda dialog: dialog.dismiss()))
            search_page = None
            for q_idx, query in enumerate(queries, 1):
                if len(results) >= max_leads:
                    break
                if time.perf_counter() - started >= runtime_budget_seconds:
                    if job_dict is not None:
                        job_dict['stop_reason'] = 'runtime_budget'
                    break
                query_started = time.perf_counter()
                if job_dict is not None:
                    job_dict['last_activity'] = time.time()
                inc('queries_started')
                page_search = None
                unique_in_query = 0
                cards_before = int(job_dict.get('candidate_cards_seen', 0)) if job_dict else 0
                prequalified_before = int(job_dict.get('candidates_prequalified', 0)) if job_dict else 0
                leads_before = len(results)
                try:
                    if search_page is None or not limits['reuse_search_page']:
                        if search_page is not None:
                            search_page.close()
                        search_page = context.new_page()
                    page_search = search_page
                    page_search.set_default_timeout(30000)
                    page_search.goto(f'https://www.google.com.br/maps/search/{urllib.parse.quote(query)}', wait_until='domcontentloaded', timeout=navigation_timeout_ms)
                    if time.perf_counter() - query_started >= query_budget_seconds:
                        if job_dict is not None:
                            job_dict['stop_reason'] = 'query_timeout'
                        continue
                    feed = page_search.wait_for_selector('div[role="feed"]', timeout=feed_timeout_ms)
                    if not feed:
                        if job_dict is not None: job_dict['feed_missing'] = int(job_dict.get('feed_missing', 0)) + 1
                        continue
                    limit = adaptive_query_limit(max_leads - len(results), limits['query_limit'])
                    no_new = 0
                    previous_fingerprint = ''
                    query_seen_hrefs = set()
                    for _ in range(limits['max_scrolls']):
                        inc('discovery_scrolls')
                        if len(results) >= max_leads or len(seen_candidates) >= limits['hard_cap']:
                            break
                        observation = scroll_observation(feed)
                        fingerprint = observation.get('fingerprint', '')
                        if fingerprint and fingerprint == previous_fingerprint:
                            no_new += 1
                        else:
                            no_new = 0
                        previous_fingerprint = fingerprint
                        if job_dict is not None:
                            job_dict['dynamic_cards_loaded'] = max(int(job_dict.get('dynamic_cards_loaded', 0)), int(observation.get('identity_count', 0)))
                            job_dict['candidate_identity_count'] = len(seen_candidates)
                            job_dict['source_end_marker_seen'] = bool(observation.get('end_marker'))
                            fingerprints = list(job_dict.get('scroll_fingerprints') or [])
                            if fingerprint:
                                fingerprints.append(fingerprint)
                            job_dict['scroll_fingerprints'] = fingerprints[-20:]
                            job_dict['scroll_no_progress'] = no_new
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
                            item = {'href': href, 'title': link.get_attribute('aria-label') or '', 'card_text': card_text, 'rating': parse_rating(card_text), 'reviews_count': parse_reviews(card_text) if re.search(r'avali|reviews?', card_text, re.I) else None, 'google_sponsored': bool(re.search(r'patrocinado', card_text, re.I))}
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
                            timings = {}
                            goto_started = time.perf_counter()
                            detail_page.goto(item['href'], wait_until='commit', timeout=10000)
                            timings['goto_ms'] = (time.perf_counter() - goto_started) * 1000
                            if not validate_detail_identity(detail_page, item):
                                inc('detail_failed')
                                continue
                            detail = extract_basic_place_detail(
                                detail_page, fast=True, item=item,
                                ready_wait_ms=limits['detail_ready_wait_ms'],
                                timings=timings,
                            )
                            if detail is None:
                                detail = _extract_place_detail(
                                    detail_page, fast=True, item=item,
                                    include_optional=False,
                                    ready_wait_ms=limits['detail_ready_wait_ms'],
                                    timings=timings,
                                )
                            if detail is None:
                                local['detail_timeouts'] = local.get('detail_timeouts', 0) + 1
                                continue
                            detail.update({'place_name': detail.get('place_name') or item['title'], 'city': city, 'state': state, 'country_code': 'BR', 'google_sponsored': item['google_sponsored']})
                            if not detail.get('reviews_count') and item.get('reviews_count') is not None:
                                detail['reviews_count'] = item['reviews_count']
                            if not detail.get('total_score') and item.get('rating') is not None:
                                detail['total_score'] = str(item['rating'])
                            qualification_started = time.perf_counter()
                            phone_retry_started = time.perf_counter()
                            wa = detail.get('whatsapp') or ''
                            if not wa:
                                try:
                                    detail_page.wait_for_selector(
                                        'button[data-tooltip*="telefone"], button[data-item-id^="phone:tel:"]',
                                        timeout=limits['phone_retry_wait_ms'],
                                    )
                                except Exception:
                                    pass
                                detail.update(extract_phone_from_place_page(detail_page))
                                wa = detail.get('whatsapp') or ''
                            timings['qualification_ms'] = (time.perf_counter() - qualification_started) * 1000
                            if not wa:
                                inc('rejected_whatsapp')
                                inc('without_whatsapp')
                                inc('rejected_before_web_results')
                                inc('web_results_skipped')
                                timings['total_ms'] = (time.perf_counter() - detail_started) * 1000
                                record_detail(timings)
                                continue
                            reason = detail_prequalification_reason({**item, **detail}, category)
                            if reason:
                                inc('rejected_' + reason)
                                inc('candidates_rejected_pre_detail')
                                inc('details_avoided')
                                inc('rejected_before_web_results')
                                inc('web_results_skipped')
                                timings['total_ms'] = (time.perf_counter() - detail_started) * 1000
                                record_detail(timings)
                                continue
                            inc('web_results_attempted')
                            optional = extract_optional_google_web_results(detail_page, fast=True, timings=timings)
                            if not detail.get('website'):
                                detail['website'] = optional.get('website', '')
                            detail.update({key: optional.get(key, default) for key, default in {
                                'instagram': [], 'facebook': [], 'linkedin': [], 'google_result_cnpj': '', 'web_results': [],
                                'instagram_source': '', 'cnpj_source': '',
                            }.items()})
                            detail['cnpj'] = detail.get('google_result_cnpj') or detail.get('cnpj') or ''
                            detail['cnpj_source'] = 'google_web_results' if detail['cnpj'] else ''
                            _promote_social_website(detail)
                            if optional.get('web_results'):
                                inc('web_results_found')
                            if optional.get('instagram'):
                                inc('web_results_instagram_found')
                            if optional.get('facebook'):
                                inc('facebook_found')
                            if optional.get('linkedin'):
                                inc('linkedin_found')
                            if detail.get('cnpj'):
                                inc('cnpj_found')
                            place_key = f'{detail.get("place_name", "")}|{detail.get("street") or detail.get("address") or ""}'.lower()
                            if (place_key != '|' and place_key in seen_places) or wa in seen_phones:
                                inc('candidates_duplicate')
                                continue
                            seen_places.add(place_key)
                            seen_phones.add(wa)
                            detail['qualification_status'] = 'qualified'
                            detail['with_whatsapp'] = True
                            detail['instagram'] = preserve_google_instagram(detail.get('instagram'))
                            detail['facebook'] = list(dict.fromkeys(detail.get('facebook') or []))
                            detail['linkedin'] = list(dict.fromkeys(detail.get('linkedin') or []))
                            detail['emails'] = list(dict.fromkeys(detail.get('emails') or []))
                            results.append(detail)
                            _emit_qualified_lead(job_dict, detail)
                            inc('qualified_leads')
                            timings['total_ms'] = (time.perf_counter() - detail_started) * 1000
                            record_detail(timings)
                            if job_dict is not None and len(results) == 1:
                                job_dict['time_to_first_qualified_lead_ms'] = round((time.perf_counter() - started) * 1000, 2)
                            progress(q_idx)
                            if discovery_should_stop(len(results), max_leads):
                                if job_dict is not None:
                                    job_dict['target_reached'] = True
                                    job_dict['early_stop_triggered'] = True
                                break
                        if len(results) >= max_leads:
                            break
                        if no_new >= limits['max_no_new_scrolls'] or observation.get('end_marker'):
                            if job_dict is not None and observation.get('end_marker'):
                                job_dict['source_end_marker_seen'] = True
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
                    if job_dict is not None:
                        job_dict['query_errors'] = int(job_dict.get('query_errors', 0)) + 1
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
                    if page_search and not limits['reuse_search_page']:
                        page_search.close()
                        page_search = None
            if detail_page:
                detail_page.close()
            if search_page:
                search_page.close()
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
            samples = list(job_dict.get('detail_performance_samples') or [])
            job_dict['average_detail_ms'] = round(sum(float(x.get('total_ms', 0.0)) for x in samples) / max(len(samples), 1), 2)
            job_dict['p50_detail_ms'] = summarize_samples([x.get('total_ms') for x in samples])['p50_ms']
            job_dict['p95_detail_ms'] = summarize_samples([x.get('total_ms') for x in samples])['p95_ms']
            job_dict['max_detail_ms'] = summarize_samples([x.get('total_ms') for x in samples])['max_ms']
            job_dict['performance'] = {
                'detail': summarize_samples([x.get('total_ms') for x in samples]),
                'goto': summarize_samples([x.get('goto_ms') for x in samples]),
                'ready_wait': summarize_samples([x.get('ready_wait_ms') for x in samples]),
                'basic_extract': summarize_samples([x.get('basic_extract_ms') for x in samples]),
                'qualification': summarize_samples([x.get('qualification_ms') for x in samples]),
                'web_results': {
                    'attempted': job_dict.get('web_results_attempted', 0),
                    'skipped': job_dict.get('web_results_skipped', 0),
                    'found': job_dict.get('web_results_found', 0),
                    'instagram_found': job_dict.get('web_results_instagram_found', 0),
                    'timing': summarize_samples([x.get('web_results_ms') for x in samples]),
                },
            }
            for metric_name, phase in {
                'detail_goto_ms': 'goto',
                'detail_ready_wait_ms': 'ready_wait',
                'basic_extract_ms': 'basic_extract',
                'qualification_ms': 'qualification',
            }.items():
                job_dict[metric_name] = job_dict['performance'][phase]['avg_ms']
            job_dict['web_results_ms'] = job_dict['performance']['web_results']['timing']['avg_ms']
            job_dict.pop('detail_performance_samples', None)
            job_dict['scrape_total_ms'] = round(elapsed, 2)
            job_dict['query_metrics'] = query_metrics
            existing_reason = job_dict.get('stop_reason')
            job_dict['stop_reason'] = existing_reason if existing_reason in STOP_REASONS else discovery_stop_reason(
                captured=len(results), target=max_leads,
                source_exhausted=bool(job_dict.get('source_end_marker_seen') or job_dict.get('scroll_no_progress', 0) >= limits['max_no_new_scrolls']),
                blocked_by_google=bool(job_dict.get('feed_missing') and not job_dict.get('discovery_scrolls')),
                worker_error=bool(job_dict.get('query_errors') and not job_dict.get('feed_missing')),
                queries_exhausted=job_dict.get('queries_completed', 0) >= len(queries),
            )
            job_dict['stop_details'] = {'target': max_leads, 'captured': len(results),
                'limit': 'max_leads' if job_dict['stop_reason'] == 'target_reached' else job_dict['stop_reason'],
                'candidate_identity_count': len(seen_candidates), 'scrolls': job_dict.get('discovery_scrolls', 0)}
            job_dict['status'] = 'running'
    return results


def scrape_gmaps(job_id_or_callback, category, city, state, max_leads=10, webhook_url=None, job_dict=None, mode='full', query_shard=None):
    _set_job_phase(job_dict, 'scraper_entered', 'Scraper iniciado.')
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
            if query_shard:
                queries_to_run = deterministic_query_shard(queries_to_run, *query_shard)
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
                    _emit_qualified_lead(job_dict, detail)

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
