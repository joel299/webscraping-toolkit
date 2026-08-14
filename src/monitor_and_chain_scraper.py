#!/usr/bin/env python3
import json
import os
import subprocess
import time

LOG_FILE = "/root/scraper_chain.log"
CITY = os.environ.get("SCRAPER_CITY", "Campo Grande")
STATE = os.environ.get("SCRAPER_STATE", "Mato Grosso do Sul")
MAX_LEADS = int(os.environ.get("SCRAPER_MAX_LEADS", "150"))
WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")

def log(msg):
    text = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(text, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass

def get_container_id():
    try:
        cid = subprocess.check_output(["docker", "ps", "--filter", "name=scraper-ui", "--format", "{{.ID}}"]).decode().strip()
        return cid.split('\n')[0] if cid else None
    except Exception:
        return None

def get_job_status(job_id):
    cid = get_container_id()
    if not cid:
        return None
    py_code = f"import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8990/api/job/{job_id}').read().decode())"
    try:
        out = subprocess.check_output(["docker", "exec", cid, "python3", "-c", py_code], timeout=15).decode("utf-8")
        return json.loads(out.strip())
    except Exception:
        return None

def start_job(category, city, state, max_leads, webhook):
    cid = get_container_id()
    if not cid:
        return None
    py_code = (
        "import urllib.request, json; "
        f"payload = {{'category': {json.dumps(category)}, 'city': {json.dumps(city)}, 'state': {json.dumps(state)}, 'max_leads': {max_leads}, 'webhook': {json.dumps(webhook)}}}; "
        "req = urllib.request.Request('http://127.0.0.1:8990/api/scrape', data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'}); "
        "print(urllib.request.urlopen(req).read().decode())"
    )
    try:
        out = subprocess.check_output(["docker", "exec", cid, "python3", "-c", py_code], timeout=20).decode("utf-8")
        data = json.loads(out.strip())
        return data.get("job_id")
    except Exception as e:
        log(f"❌ Error starting scrape job for {category}: {e}")
        return None

def main():
    log("🚀 Iniciando sequência completa dos 2 lotes (150 Dentistas + 150 Clínica Médica)...")

    # Lote 1: Dentistas
    job1_id = start_job("Dentista", CITY, STATE, MAX_LEADS, WEBHOOK_URL)
    if not job1_id:
        log("❌ Erro fatal: Não foi possível disparar o Lote 1 (Dentistas).")
        return

    log(f"📌 Lote 1 (Dentistas) disparado com sucesso! ID: #{job1_id}")

    job1_finished = False
    last_log = 0
    while not job1_finished:
        st_data = get_job_status(job1_id)
        if st_data:
            st = st_data.get("status")
            phase = st_data.get("phase")
            count = st_data.get("current_count", 0)
            enc_count = st_data.get("enriched_count", 0)
            log_msg = st_data.get("log", "")

            if time.time() - last_log >= 30:
                log(f"📊 [Lote 1: Dentistas] Status: {st} | Fase: {phase} | Coletados: {count}/{MAX_LEADS} | Enriquecidos: {enc_count} | {log_msg}")
                last_log = time.time()

            if st in ("enriched", "completed"):
                log(f"✅ Lote 1 (Dentistas) concluído! Total: {count} leads ({enc_count} enriquecidos). Preparando Lote 2...")
                job1_finished = True
                break
            elif st == "error":
                log(f"⚠️ Lote 1 apresentou aviso/erro: {st_data.get('error')}. Prosseguindo...")
                job1_finished = True
                break
        time.sleep(10)

    # Lote 2: Clínica médica, consultório
    next_cat = "Clínica médica, consultório"
    log(f"🚀 Iniciando Lote 2 ('{next_cat}')...")
    job2_id = start_job(next_cat, CITY, STATE, MAX_LEADS, WEBHOOK_URL)

    if not job2_id:
        time.sleep(10)
        job2_id = start_job(next_cat, CITY, STATE, MAX_LEADS, WEBHOOK_URL)

    if not job2_id:
        log("❌ Erro fatal: Não foi possível disparar o Lote 2.")
        return

    log(f"📌 Lote 2 ({next_cat}) disparado com sucesso! ID: #{job2_id}")

    job2_finished = False
    last_log = 0
    while not job2_finished:
        st_data = get_job_status(job2_id)
        if st_data:
            st = st_data.get("status")
            phase = st_data.get("phase")
            count = st_data.get("current_count", 0)
            enc_count = st_data.get("enriched_count", 0)
            log_msg = st_data.get("log", "")

            if time.time() - last_log >= 30:
                log(f"📊 [Lote 2: Clínica Médica] Status: {st} | Fase: {phase} | Coletados: {count}/{MAX_LEADS} | Enriquecidos: {enc_count} | {log_msg}")
                last_log = time.time()

            if st in ("enriched", "completed"):
                log(f"🎉 AMBOS OS LOTES CONCLUÍDOS COM SUCESSO! Lote 2: {count} leads ({enc_count} enriquecidos).")
                job2_finished = True
                break
            elif st == "error":
                log(f"⚠️ Lote 2 encerrou com aviso: {st_data.get('error')}.")
                job2_finished = True
                break
        time.sleep(10)

if __name__ == "__main__":
    main()
