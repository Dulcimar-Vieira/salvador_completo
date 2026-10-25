#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import gzip
import hashlib
import io
import json
import os
import random
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import requests

FEED_URL = "https://feeds.whatjobs.com/sinerj/sinerj_pt_BR.xml.gz"
OUTPUT_FOLDER = "json_parts"
STATE_FILE = "daily_jobs_state.json"
MAX_JOBS_PER_DAY = 1000
TIMEZONE = ZoneInfo("America/Sao_Paulo")


# Extração de remuneração inspirada na validação do repositório rio-de-janeiro.
MONEY_NUMBER = (
    r"(?:"
    r"\d{1,3}(?:\.\d{3})+(?:,\d{2})?"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d{2})?"
    r"|\d+(?:,\d{2}|\.\d{2})?"
    r")"
    r"(?:\s*(?:mil|k)\b)?"
)
SALARY_AMOUNT_RE = re.compile(
    rf"\b(?:faixa salarial|piso salarial|sal[aá]rios?|remunera[cç][aã]o|proventos)\b"
    rf"(?:\s+(?:fixo|base|mensal(?:\s+de)?|bruto|inicial|m[ií]nimo garantido|"
    rf"oferecido|oferecida|oferecidos|oferecidas|de at[eé]|a partir de|entre)){{0,3}}"
    rf"\s*(?:[:：=–—-]\s*)?"
    rf"(?:(?:a partir de|de|entre)\s+)?"
    rf"(?P<amount>(?:R\$\s*)?{MONEY_NUMBER})(?![\d.,])",
    re.IGNORECASE,
)

def normalize_salary_text(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().lower()

def has_real_salary(salary):
    value = normalize_salary_text(salary)
    if not value:
        return False
    placeholders = (
        "a combinar", "nao informado", "nao informada",
        "nao divulgado", "nao divulgada", "confidencial",
        "negociavel", "sob consulta", "salario nao informado",
        "salario a combinar",
    )
    if any(marker in value for marker in placeholders):
        return False
    if not re.search(r"\d", value):
        return False
    if not re.search(r"(?:R\$|[$€£])", value) and re.fullmatch(r"\d+", value):
        return False
    return True

MAX_SALARY_BRL = 10000.0

# Reconhece valores monetários em formatos brasileiros e internacionais.
SALARY_VALUE_RE = re.compile(
    rf"(?<![\w])(?:R\$\s*|[$€£]\s*)?{MONEY_NUMBER}(?![\d.,])",
    re.IGNORECASE,
)

def parse_salary_amount(raw_amount):
    """Converte um valor salarial para número e reconhece sufixos mil/k."""
    raw_value = str(raw_amount or "").strip()
    multiplier = 1000.0 if re.search(r"\s*(?:mil|k)\b", raw_value, re.IGNORECASE) else 1.0
    value = re.sub(r"\s*(?:mil|k)\b", "", raw_value, flags=re.IGNORECASE)
    value = re.sub(r"^(?:R\$|[$€£])\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"[^\d.,]", "", value)
    if not value:
        return None

    if "." in value and "," in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        left, _, right = value.rpartition(",")
        if len(right) == 3 and left:
            value = value.replace(",", "")
        else:
            value = left.replace(",", "") + "." + right
    elif "." in value:
        parts = value.split(".")
        if len(parts) > 1 and len(parts[0]) <= 3 and all(len(part) == 3 for part in parts[1:]):
            value = "".join(parts)
        else:
            value = "".join(parts[:-1]) + "." + parts[-1]

    try:
        return float(value) * multiplier
    except ValueError:
        return None


def salary_exceeds_limit(salary, description=""):
    """Retorna True quando algum limite salarial informado passa de R$ 10 mil."""
    for match in SALARY_VALUE_RE.finditer(salary or ""):
        amount = parse_salary_amount(match.group(0))
        if amount is not None and amount > MAX_SALARY_BRL:
            return True

    text = re.sub(r"<[^>]+>", " ", description or "")
    text = re.sub(r"\s+", " ", text).strip()
    range_tail_re = re.compile(
        rf"\s*(?:-|–|—|\ba\b|\bat[eé]\b)\s*(?:R\$\s*)?({MONEY_NUMBER})(?![\d.,])",
        re.IGNORECASE,
    )
    for match in SALARY_AMOUNT_RE.finditer(text):
        amount = parse_salary_amount(match.group("amount"))
        if amount is not None and amount > MAX_SALARY_BRL:
            return True
        range_match = range_tail_re.match(text[match.end():match.end() + 100])
        if range_match:
            upper_amount = parse_salary_amount(range_match.group(1))
            if upper_amount is not None and upper_amount > MAX_SALARY_BRL:
                return True
    return False


def extract_salary(structured_salary, description):
    """Prioriza <salary>; no fallback aceita somente valor ligado a rótulo salarial."""
    structured_salary = re.sub(r"\s+", " ", structured_salary or "").strip()
    if has_real_salary(structured_salary):
        return structured_salary

    text = re.sub(r"<[^>]+>", " ", description or "")
    text = re.sub(r"\s+", " ", text).strip()
    for match in SALARY_AMOUNT_RE.finditer(text):
        amount = re.sub(r"\s+", " ", match.group("amount")).strip()
        raw_number = re.sub(r"^R\$\s*", "", amount, flags=re.IGNORECASE).strip()
        has_currency = amount.upper().startswith("R$")
        if not has_currency and re.fullmatch(r"\d{1,2}", raw_number):
            continue
        return amount
    return ""


CIDADES = {"lauro de freitas", "salvador", "simoes filho", "camacari", "feira de santana"}

def normalize(text):
    text = unicodedata.normalize("NFKD", (text or "").strip().lower())
    return "".join(char for char in text if not unicodedata.combining(char))

def clean_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()

def parse_date(value):
    if not value:
        return None
    value = value.strip()
    formats = (
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
    )
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass
    # Suporta datas RSS/RFC 822, comuns em feeds XML.
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None

def job_key(job):
    return job.get("url") or hashlib.md5(
        f"{job.get('title','')}|{job.get('company','')}|{job.get('city','')}".encode("utf-8")
    ).hexdigest()

def load_state(today):
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        if state.get("date") != today:
            return {}
        return state.get("jobs", {})
    except (OSError, json.JSONDecodeError):
        return {}

def save_state(today, selected):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": today, "jobs": selected}, f, ensure_ascii=False, indent=2)

def gerar_intro(titulo, cidade):
    intros = [
        f"Confira a oportunidade para {titulo} em {cidade}. Veja requisitos e como se candidatar.",
        f"Nova vaga disponível para {titulo} em {cidade}. Saiba mais sobre essa oportunidade.",
        f"Empresa está contratando {titulo} em {cidade}. Veja detalhes e envie seu currículo.",
    ]
    return random.choice(intros)

def build_job(elem):
    title = elem.findtext("title", "").strip()
    description = elem.findtext("description", "").strip()
    company = elem.findtext("company/name", "").strip() or "Confidencial"
    url = elem.findtext("urlDeeplink", "").strip() or elem.findtext("link", "").strip()
    job_type = elem.findtext("jobType", "").strip()
    source_salary = elem.findtext("salary", "").strip()
    location_elem = elem.find("locations/location")
    city = location_elem.findtext("city", "").strip() if location_elem is not None else elem.findtext("city", "").strip()
    state = location_elem.findtext("state", "").strip() if location_elem is not None else elem.findtext("state", "").strip()

    pub_raw = elem.findtext("pubdate", "").strip() or elem.findtext("pubDate", "").strip()
    updated_raw = elem.findtext("updated", "").strip()
    pub_dt = parse_date(pub_raw)
    updated_dt = parse_date(updated_raw)

    if not title or not url or not city or not state:
        return None

    today = datetime.now(TIMEZONE).date()

    if not job_matches(city, title, description):
        return None

    salary = extract_salary(source_salary, description)
    if not salary or salary_exceeds_limit(salary, description):
        return None

    description = clean_html(description)
    if True:
        description = gerar_intro(title, city) + "\n\n" + description

    return {
        "id": hashlib.md5(f"{title}-{company}-{city}-{url}".encode("utf-8")).hexdigest(),
        "title": title,
        "description": description,
        "company": company,
        "salary": salary,
        "city": city,
        "state": state,
        "url": url,
        "tipo": job_type,
        "data_publicacao": pub_dt.date().isoformat() if pub_dt else datetime.now(TIMEZONE).date().isoformat(),
        "data_atualizacao": updated_dt.date().isoformat() if updated_dt else "",
        "origem": "WhatJobs",
    }

def job_matches(city, title, description):
    return normalize(city) in CIDADES

def main():
    today = datetime.now(TIMEZONE).date().isoformat()
    print(f"📅 Data de referência: {today}")

    selected = load_state(today)
    # Não reutilizar registros antigos sem remuneração validada.
    selected = {key: job for key, job in selected.items() if has_real_salary(job.get("salary", "")) and not salary_exceeds_limit(job.get("salary", ""), job.get("description", ""))}

    print("📥 Baixando feed do WhatJobs...")
    try:
        response = requests.get(
            FEED_URL,
            headers={"User-Agent": "Mozilla/5.0 (compatible; FeedProcessor/1.0)"},
            timeout=60,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise SystemExit(f"❌ Erro ao baixar o feed: {e}")

    candidates = {}

    with gzip.open(io.BytesIO(response.content), "rb") as f:
        for event, elem in ET.iterparse(f, events=("end",)):
            if elem.tag != "job":
                continue
            job = build_job(elem)
            if job:
                key = job_key(job)
                candidates[key] = job
            elem.clear()

    # Atualiza o conteúdo dos jobs que já foram selecionados hoje.
    for key in list(selected):
        if key in candidates:
            selected[key] = candidates[key]

    # Completa a cota diária com as vagas mais novas do dia.
    novos = [
        job for key, job in candidates.items()
        if key not in selected
    ]
    novos.sort(key=lambda j: (j.get("data_publicacao", ""), j.get("data_atualizacao", "")), reverse=True)

    for job in novos:
        if len(selected) >= MAX_JOBS_PER_DAY:
            break
        selected[job_key(job)] = job

    jobs = list(selected.values())[:MAX_JOBS_PER_DAY]
    if not jobs:
        raise SystemExit("ERRO: nenhuma vaga com remuneração válida; os arquivos anteriores serão preservados.")

    # Um único JSON por execução: no máximo 100 vagas novas por dia,
    # mantendo as mesmas vagas para atualização a cada 6 horas.
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    for filename in os.listdir(OUTPUT_FOLDER):
        if filename.endswith(".json"):
            os.remove(os.path.join(OUTPUT_FOLDER, filename))

    output_path = os.path.join(OUTPUT_FOLDER, "part_1.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

    save_state(today, selected)

    print(f"✅ Vagas encontradas hoje: {len(candidates)}")
    print(f"✅ Vagas selecionadas na cota do dia: {len(jobs)}")
    print(f"📄 Gerado: {output_path}")

if __name__ == "__main__":
    main()
