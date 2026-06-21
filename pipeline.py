import json
import os
import re
import subprocess
import tempfile

import requests
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import database

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "phi3:mini"
TFIDF_THRESHOLD = 0.85
DIGITAL_PDF_MIN_CHARS = 100

MONTH_MAP = {
    "januar": "01", "februar": "02", "märz": "03", "april": "04",
    "mai": "05", "juni": "06", "juli": "07", "august": "08",
    "september": "09", "oktober": "10", "november": "11", "dezember": "12",
    "jan": "01", "feb": "02", "mär": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09",
    "okt": "10", "nov": "11", "dez": "12",
}


def _to_v_date(day: str, month: str, year: str) -> str:
    d, m, y = int(day), int(month), year
    if not (1 <= d <= 31 and 1 <= m <= 12):
        return ""
    y2 = y[-2:] if len(y) == 4 else y
    return f"v{d:02d}.{m:02d}.{y2}"


def extract_dates(text: str) -> list[str]:
    dates: list[str] = []
    seen: set[str] = set()

    def _add(v: str) -> None:
        if v and v not in seen:
            seen.add(v)
            dates.append(v)

    for m in re.finditer(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", text):
        _add(_to_v_date(m.group(1), m.group(2), m.group(3)))

    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        _add(_to_v_date(m.group(3), m.group(2), m.group(1)))

    for m in re.finditer(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2})\b", text):
        d, mo, y = m.group(1), m.group(2), m.group(3)
        if 1 <= int(d) <= 31 and 1 <= int(mo) <= 12:
            v = f"v{int(d):02d}.{int(mo):02d}.{y}"
            _add(v)

    for m in re.finditer(r"\b(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\s*(\d{4})\b", text):
        mo_str = MONTH_MAP.get(m.group(2).lower())
        if mo_str:
            _add(_to_v_date(m.group(1), mo_str, m.group(3)))

    return dates


def _pdftotext(pdf_path: str, max_pages: int = 2) -> str:
    try:
        result = subprocess.run(
            ["pdftotext", "-l", str(max_pages), pdf_path, "-"],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout or ""
    except Exception:
        return ""


def run_ocr(pdf_path: str) -> str:
    # Check if PDF already has embedded text (digital PDF shortcut)
    existing_text = _pdftotext(pdf_path)
    if len(existing_text.strip()) >= DIGITAL_PDF_MIN_CHARS:
        return existing_text

    # Scanned PDF: run ocrmypdf and write sidecar to temp file
    sidecar_file = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    sidecar_path = sidecar_file.name
    sidecar_file.close()
    out_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    out_path = out_file.name
    out_file.close()

    try:
        subprocess.run(
            [
                "ocrmypdf",
                "--skip-text",
                "--pages", "1-2",
                "--output-type", "pdf",
                "--sidecar", sidecar_path,
                pdf_path,
                out_path,
            ],
            capture_output=True,
            timeout=120,
        )
        with open(sidecar_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        if text.strip():
            return text
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    finally:
        for p in (sidecar_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass

    return existing_text


def _tfidf_classify(text: str) -> tuple[str, str, float]:
    entries = database.load()
    if not entries:
        return "", "", 0.0

    corpus = [
        f"{e.get('dokumenttyp', '')} {e.get('absender', '')} {e.get('personenbezug', '')}".strip()
        for e in entries
    ]
    try:
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
        matrix = vec.fit_transform(corpus + [text])
        sims = cosine_similarity(matrix[-1], matrix[:-1])[0]
        best_idx = int(sims.argmax())
        best_score = float(sims[best_idx])
        if best_score > 0:
            e = entries[best_idx]
            return (
                e.get("dokumenttyp", ""),
                e.get("absender", ""),
                best_score,
            )
    except Exception:
        pass
    return "", "", 0.0


def _personenbezug_for(dokumenttyp: str, absender: str) -> str:
    for e in database.load():
        if e.get("dokumenttyp") == dokumenttyp and e.get("absender") == absender:
            return e.get("personenbezug", "")
    return ""


def _parse_llm_json(raw: str) -> dict:
    # Try multiple extraction strategies for robustness
    raw = raw.strip()

    # Strategy 1: greedy match of outermost braces
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    # Strategy 2: locate first { … last }
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass

    return {}


def _llm_classify(text: str, rag_context: str) -> dict:
    truncated = text[:3000]
    prompt = (
        f"{rag_context}\n\n"
        "Analysiere den folgenden Dokumenttext und extrahiere genau diese vier Felder als JSON.\n"
        "Regeln:\n"
        '- "dokumenttyp": Typ des Dokuments (z.B. Rechnung, Bescheid, Vertrag, Brief, Kontoauszug)\n'
        '- "absender": Absender / Unternehmen / Behörde\n'
        '- "dokumentdatum": Datum im Format vDD.MM.YY (z.B. v21.06.26), sonst ""\n'
        '- "personenbezug": Nur Nachname der Person, sonst ""\n'
        "Antworte NUR mit einem JSON-Objekt. Kein Fließtext, keine Markdown-Codeblöcke.\n\n"
        f"Dokumenttext:\n{truncated}\n\nJSON:"
    )

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "keep_alive": 0,
                "options": {"num_predict": 512, "temperature": 0.1},
            },
            timeout=90,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        return _parse_llm_json(raw)
    except Exception:
        return {}


def analyze(pdf_path: str) -> dict:
    text = run_ocr(pdf_path)
    dates = extract_dates(text)
    primary_date = dates[0] if dates else ""

    dokumenttyp, absender, score = _tfidf_classify(text)

    # Fast-Lane: skip LLM if confidence is high enough and date is clear
    if score >= TFIDF_THRESHOLD and primary_date:
        return {
            "dokumenttyp": dokumenttyp,
            "absender": absender,
            "dokumentdatum": primary_date,
            "dokumentdatum_candidates": dates,
            "personenbezug": _personenbezug_for(dokumenttyp, absender),
            "confidence": round(score, 3),
            "source": "tfidf",
        }

    # LLM Fallback with RAG context
    rag = database.get_rag_context()
    llm = _llm_classify(text, rag)

    return {
        "dokumenttyp": llm.get("dokumenttyp") or dokumenttyp,
        "absender": llm.get("absender") or absender,
        "dokumentdatum": llm.get("dokumentdatum") or primary_date,
        "dokumentdatum_candidates": dates,
        "personenbezug": llm.get("personenbezug", ""),
        "confidence": round(score, 3),
        "source": "llm",
    }
