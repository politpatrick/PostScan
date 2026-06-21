import os
import re
import json
import subprocess
import tempfile
from typing import Optional

import requests
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import database

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "phi3:mini"
TFIDF_THRESHOLD = 0.85

DATE_PATTERNS = [
    (r"\b(\d{2})\.(\d{2})\.(\d{4})\b", "de_long"),   # DD.MM.YYYY
    (r"\b(\d{2})\.(\d{2})\.(\d{2})\b", "de_short"),   # DD.MM.YY
    (r"\b(\d{4})-(\d{2})-(\d{2})\b", "iso"),           # YYYY-MM-DD
    (r"\b(\d{1,2})\.\s*([A-Za-zä-ü]+)\s*(\d{4})\b", "de_text"),  # D. Monat YYYY
]

MONTH_MAP = {
    "januar": "01", "februar": "02", "märz": "03", "april": "04",
    "mai": "05", "juni": "06", "juli": "07", "august": "08",
    "september": "09", "oktober": "10", "november": "11", "dezember": "12",
    "jan": "01", "feb": "02", "mär": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09",
    "okt": "10", "nov": "11", "dez": "12",
}


def _to_v_date(day: str, month: str, year: str) -> str:
    y2 = year[-2:] if len(year) == 4 else year
    return f"v{int(day):02d}.{int(month):02d}.{y2}"


def extract_dates(text: str) -> list[str]:
    dates = []
    seen = set()

    for m in re.finditer(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", text):
        d, mo, y = m.group(1), m.group(2), m.group(3)
        v = _to_v_date(d, mo, y)
        if v not in seen:
            seen.add(v)
            dates.append(v)

    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        y, mo, d = m.group(1), m.group(2), m.group(3)
        v = _to_v_date(d, mo, y)
        if v not in seen:
            seen.add(v)
            dates.append(v)

    for m in re.finditer(r"\b(\d{2})\.(\d{2})\.(\d{2})\b", text):
        d, mo, y = m.group(1), m.group(2), m.group(3)
        v = f"v{d}.{mo}.{y}"
        if v not in seen:
            seen.add(v)
            dates.append(v)

    for m in re.finditer(r"\b(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\s*(\d{4})\b", text):
        d, mo_name, y = m.group(1), m.group(2).lower(), m.group(3)
        mo = MONTH_MAP.get(mo_name)
        if mo:
            v = _to_v_date(d, mo, y)
            if v not in seen:
                seen.add(v)
                dates.append(v)

    return dates


def run_ocr(pdf_path: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            [
                "ocrmypdf",
                "--skip-text",
                "--pages", "1-2",
                "--output-type", "pdf",
                "--sidecar", "-",
                pdf_path,
                tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        text = result.stdout or ""
        if not text.strip():
            text = _extract_text_pdftotext(pdf_path)
        return text
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return _extract_text_pdftotext(pdf_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _extract_text_pdftotext(pdf_path: str) -> str:
    try:
        result = subprocess.run(
            ["pdftotext", "-l", "2", pdf_path, "-"],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout or ""
    except Exception:
        return ""


def _tfidf_classify(text: str) -> tuple[Optional[str], Optional[str], float]:
    entries = database.load()
    if len(entries) < 2:
        return None, None, 0.0

    corpus = [f"{e.get('dokumenttyp','')} {e.get('absender','')}".strip() for e in entries]
    try:
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
        matrix = vec.fit_transform(corpus + [text])
        sims = cosine_similarity(matrix[-1], matrix[:-1])[0]
        best_idx = int(sims.argmax())
        best_score = float(sims[best_idx])
        if best_score > 0:
            e = entries[best_idx]
            return e.get("dokumenttyp"), e.get("absender"), best_score
    except Exception:
        pass
    return None, None, 0.0


def _llm_classify(text: str, rag_context: str) -> dict:
    truncated = text[:3000]
    prompt = f"""{rag_context}

Analysiere den folgenden Dokumenttext und extrahiere genau diese vier Felder als JSON:
- "dokumenttyp": Typ des Dokuments (z.B. Rechnung, Bescheid, Vertrag, Brief, Kontoauszug)
- "absender": Absender / Unternehmen / Behörde
- "dokumentdatum": Datum im Format vDD.MM.YY (z.B. v21.06.26), oder "" wenn nicht erkennbar
- "personenbezug": Name der Person (nur Nachname), oder "" wenn nicht erkennbar

Antworte NUR mit einem JSON-Objekt, keine weiteren Erklärungen.

Dokumenttext:
{truncated}

JSON:"""

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 256, "temperature": 0.1},
            },
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        match = re.search(r"\{.*?\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return {}


def analyze(pdf_path: str) -> dict:
    text = run_ocr(pdf_path)
    dates = extract_dates(text)
    primary_date = dates[0] if dates else ""

    dokumenttyp, absender, score = _tfidf_classify(text)

    if score >= TFIDF_THRESHOLD and primary_date:
        personenbezug = ""
        entries = database.load()
        for e in entries:
            if e.get("dokumenttyp") == dokumenttyp and e.get("absender") == absender:
                personenbezug = e.get("personenbezug", "")
                break
        return {
            "dokumenttyp": dokumenttyp or "",
            "absender": absender or "",
            "dokumentdatum": primary_date,
            "dokumentdatum_candidates": dates,
            "personenbezug": personenbezug,
            "confidence": score,
            "source": "tfidf",
        }

    rag = database.get_rag_context()
    llm_result = _llm_classify(text, rag)

    dt = llm_result.get("dokumenttyp") or dokumenttyp or ""
    ab = llm_result.get("absender") or absender or ""
    dat = llm_result.get("dokumentdatum") or primary_date
    pb = llm_result.get("personenbezug", "")

    return {
        "dokumenttyp": dt,
        "absender": ab,
        "dokumentdatum": dat,
        "dokumentdatum_candidates": dates,
        "personenbezug": pb,
        "confidence": score,
        "source": "llm",
    }
