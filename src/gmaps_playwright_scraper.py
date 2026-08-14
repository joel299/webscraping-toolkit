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

def extract_detail_from_place_page(page):
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

    # 6. Website
    web_btn = page.query_selector('a[data-item-id="authority"], a[aria-label*="site"], a[aria-label*="Website"]')
    if web_btn:
        data['website'] = clean_google_redirect_url(web_btn.get_attribute('href') or '')
    else:
        data['website'] = ''

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
    queries = [f"{cat_clean} {city} {state}"]

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

def scrape_gmaps(job_id_or_callback, category, city, state, max_leads=10, webhook_url=None, job_dict=None):
    print(f"DEBUG: Starting scrape_gmaps with max_leads={max_leads}, webhook_url={webhook_url}", flush=True)
    if job_dict is not None:
        job_dict['status'] = 'running'
        job_dict['started_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        job_dict['last_activity'] = time.time()

    results = []
    seen_urls = set()
    seen_places = set()
    seen_phones = set()

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
                    consecutive_no_new = 0
                    for scroll_step in range(15):
                        if job_dict:
                            job_dict['log'] = f"Buscando candidatos {q_idx+1}/{len(queries_to_run)}: {len(place_items)}/{max_pool} candidatos"
                            job_dict['last_activity'] = time.time()
                        if len(place_items) >= max_pool:
                            break
                        links = feed.query_selector_all('a.hfpxzc')
                        new_found = False
                        for l in links:
                            href = l.get_attribute('href')
                            title = l.get_attribute('aria-label') or ''
                            if href and href not in seen_urls:
                                seen_urls.add(href)
                                place_items.append({'href': href, 'title': title})
                                new_found = True
                                if len(place_items) >= max_pool:
                                    break
                        if not new_found:
                            consecutive_no_new += 1
                        else:
                            consecutive_no_new = 0

                        if consecutive_no_new >= 4:
                            break

                        if links:
                            try:
                                links[-1].scroll_into_view_if_needed()
                            except Exception:
                                pass
                        feed.hover()
                        page_search.mouse.wheel(0, 5000)
                        page_search.keyboard.press('PageDown')
                        time.sleep(1.5)
                except Exception as ex_q:
                    print(f"⚠️ Error collecting from query '{q_str}': {ex_q}", flush=True)
                finally:
                    if page_search:
                        try:
                            page_search.close(timeout=2000)
                        except Exception:
                            pass

            print(f"📌 Collected {len(place_items)} place URLs across {len(queries_to_run)} queries. Extracting details for target {max_leads}...", flush=True)
            if job_dict:
                job_dict['log'] = f"{len(place_items)} candidatos coletados. Extraindo detalhes..."
                job_dict['last_activity'] = time.time()

            # Step 2: Navigate directly to each place page and extract details
            for idx, item in enumerate(place_items):
                if len(results) >= max_leads:
                    break

                target_url = item['href']
                print(f"--> Processing candidate {idx+1}/{len(place_items)}: {item['title']}", flush=True)
                page_place = None
                try:
                    page_place = context.new_page()
                    page_place.set_default_timeout(15000)
                    page_place.on("dialog", lambda d: d.dismiss())

                    page_place.goto(target_url, wait_until="commit", timeout=10000)
                    detail = extract_detail_from_place_page(page_place)

                    name = detail.get('place_name') or item.get('title') or f"Estabelecimento {idx+1}"
                    detail['place_name'] = name
                    detail['city'] = city
                    detail['state'] = state
                    detail['country_code'] = 'BR'

                    wa = detail.get('whatsapp') or ''
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

                    # Step 3: Scrape website for social networks (Instagram, Facebook, LinkedIn, Emails)
                    website_url = detail.get('website') or ''
                    socials = extract_socials_from_website(context, website_url)
                    detail['instagram'] = socials['instagram']
                    detail['facebook'] = socials['facebook']
                    detail['linkedin'] = socials['linkedin']
                    detail['emails'] = socials['emails']

                    detail.setdefault('owner_name', '')
                    detail.setdefault('administrator_name', '')
                    detail.setdefault('legal_name', '')
                    detail.setdefault('cnpj', '')

                    raw_gmaps_url = detail.get('google_maps_url') or target_url
                    m_url = re.search(r'https?://[^\s`"]+', raw_gmaps_url)
                    detail['google_maps_url'] = m_url.group(0) if m_url else raw_gmaps_url

                    results.append(detail)

                    if job_dict:
                        job_dict['leads'] = json.loads(json.dumps(results, ensure_ascii=False))
                        job_dict['current_count'] = len(results)
                        job_dict['log'] = f"Extraído {len(results)}/{max_leads}: {name} (Fone: {wa or 'N/A'})"
                        job_dict['last_activity'] = time.time()

                    print(f"✅ [{len(results)}/{max_leads}] Extracted: {name} | Fone: {wa} | Insta: {len(socials['instagram'])}", flush=True)

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
