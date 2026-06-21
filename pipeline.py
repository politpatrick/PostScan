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


def _tfidf_classify(text: str) -> tuple[str, str, float, str, list[dict]]:
    entries = database.load()
    if not entries:
        return "", "", 0.0, "", []

    typ_syn = {t["name"]: t.get("synonyme", []) for t in database.load_dokumenttypen()}
    abs_syn = {a["name"]: a.get("synonyme", []) for a in database.load_absender()}
    corpus = []
    corpus_keys = []
    for e in entries:
        typ = e.get("dokumenttyp", "")
        ab  = e.get("absender", "")
        typ_variants = [typ] + typ_syn.get(typ, [])
        abs_variants = [ab]  + abs_syn.get(ab, [])
        for tv in typ_variants:
            for av in abs_variants:
                corpus.append(f"{tv} {av}".strip())
                corpus_keys.append((typ, ab))

    try:
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
        corpus_matrix = vec.fit_transform(corpus)
        query_matrix = vec.transform([text])
        sims = cosine_similarity(query_matrix, corpus_matrix)[0]
        best_idx = int(sims.argmax())
        best_score = float(sims[best_idx])

        # Top-5 unique (typ, ab) pairs by score
        seen: set[tuple] = set()
        top: list[dict] = []
        for idx in sims.argsort()[::-1]:
            key = corpus_keys[idx]
            if key not in seen:
                seen.add(key)
                top.append({
                    "score": round(float(sims[idx]), 3),
                    "corpus": corpus[idx],
                    "typ": key[0],
                    "ab": key[1],
                })
            if len(top) >= 5:
                break

        if best_score > 0:
            typ, ab = corpus_keys[best_idx]
            return typ, ab, best_score, corpus[best_idx], top
    except Exception:
        pass
    return "", "", 0.0, "", []



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

    # Strategy 3: key-by-key regex extraction for malformed JSON
    result = {}
    for key in ("dokumenttyp", "absender", "dokumentdatum", "personenbezug"):
        m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', raw)
        if m:
            result[key] = m.group(1)
    if result:
        return result

    return {}


def _build_llm_prompt(text: str, rag_context: str) -> str:
    truncated = text[:3000]
    return (
        f"{rag_context}\n\n"
        "Analysiere den folgenden Dokumenttext und extrahiere genau diese vier Felder als JSON.\n"
        "Regeln:\n"
        '- "dokumenttyp": Typ des Dokuments. Nutze einen bekannten Typ wenn passend, '
        "sonst gib den treffendsten deutschen Begriff an (z.B. Steuerbescheinigung, Kündigung, Mahnung).\n"
        '- "absender": Name des Absenders / Unternehmens / Behörde. Nutze einen bekannten Absender '
        "wenn passend, sonst gib den tatsächlichen Namen aus dem Text an.\n"
        '- "dokumentdatum": Datum im Format vDD.MM.YY (z.B. v21.06.26), sonst ""\n'
        '- "personenbezug": Nur Nachname der Person, sonst ""\n'
        "Antworte NUR mit einem JSON-Objekt. Kein Fließtext, keine Markdown-Codeblöcke.\n\n"
        f"Dokumenttext:\n{truncated}\n\nJSON:"
    )


def _llm_classify(text: str, rag_context: str) -> tuple[dict, str, str]:
    prompt = _build_llm_prompt(text, rag_context)
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
        return _parse_llm_json(raw), raw, prompt
    except Exception:
        return {}, "", prompt


def analyze(pdf_path: str) -> dict:
    text = run_ocr(pdf_path)
    dates = extract_dates(text)
    primary_date = dates[0] if dates else ""

    dokumenttyp, absender, score, tfidf_match, tfidf_top = _tfidf_classify(text)

    fast_lane = score >= TFIDF_THRESHOLD and bool(primary_date)

    if fast_lane:
        persons = database.get_persons()
        return {
            "dokumenttyp": dokumenttyp,
            "absender": absender,
            "dokumentdatum": primary_date,
            "dokumentdatum_candidates": dates,
            "personenbezug": persons[0] if len(persons) == 1 else "",
            "confidence": round(score, 3),
            "source": "tfidf",
            "fast_lane": True,
            "tfidf_match": tfidf_match,
            "tfidf_top": tfidf_top,
            "rag_context": "",
            "llm_prompt": "",
            "llm_parsed": {},
            "llm_raw": "",
            "ocr_text": text,
        }

    rag = database.get_rag_context()
    llm, llm_raw, llm_prompt = _llm_classify(text, rag)

    if llm:
        final_typ = (llm.get("dokumenttyp") or "").strip() or dokumenttyp
        final_ab  = (llm.get("absender")    or "").strip() or absender
    else:
        final_typ = dokumenttyp
        final_ab  = absender

    # Detect unknowns: check against names + synonyms (case-insensitive)
    known_typen = {t["name"].lower() for t in database.load_dokumenttypen()}
    for t in database.load_dokumenttypen():
        known_typen.update(s.lower() for s in t.get("synonyme", []))
    known_abs = {a["name"].lower() for a in database.load_absender()}
    for a in database.load_absender():
        known_abs.update(s.lower() for s in a.get("synonyme", []))

    vorschlag_typ = bool(final_typ) and final_typ.lower() not in known_typen
    vorschlag_ab  = bool(final_ab)  and final_ab.lower()  not in known_abs

    if vorschlag_typ:
        database.add_vorschlag_dokumenttyp(final_typ)
    if vorschlag_ab:
        database.add_vorschlag_absender(final_ab)

    return {
        "dokumenttyp": final_typ,
        "absender": final_ab,
        "dokumentdatum": llm.get("dokumentdatum") or primary_date,
        "dokumentdatum_candidates": dates,
        "personenbezug": llm.get("personenbezug", ""),
        "confidence": round(score, 3),
        "source": "llm",
        "fast_lane": False,
        "vorschlag_typ": vorschlag_typ,
        "vorschlag_ab":  vorschlag_ab,
        "tfidf_match": tfidf_match,
        "tfidf_top": tfidf_top,
        "rag_context": rag,
        "llm_prompt": llm_prompt,
        "llm_parsed": llm,
        "llm_raw": llm_raw,
        "ocr_text": text,
    }
