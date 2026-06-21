import json
import os

STAMMDATEN_PATH = os.path.join(os.path.dirname(__file__), "stammdaten.json")

_DEFAULTS = {
    "dokumenttypen": ["Bescheid", "Brief", "Kontoauszug", "Rechnung", "Vertrag"],
    "absender": ["AOK Bayern", "Finanzamt", "HUK-COBURG", "Sparkasse", "Telekom", "Unbekannt"],
    "personen": ["Kunze"],
    "kombinationen": [
        {"dokumenttyp": "Rechnung",    "absender": "HUK-COBURG"},
        {"dokumenttyp": "Rechnung",    "absender": "AOK Bayern"},
        {"dokumenttyp": "Bescheid",    "absender": "Finanzamt"},
        {"dokumenttyp": "Vertrag",     "absender": "Telekom"},
        {"dokumenttyp": "Kontoauszug", "absender": "Sparkasse"},
        {"dokumenttyp": "Brief",       "absender": "Unbekannt"},
    ],
}


# ---------------------------------------------------------------------------
# Internal I/O
# ---------------------------------------------------------------------------

def _load_all() -> dict:
    if not os.path.exists(STAMMDATEN_PATH):
        return {k: list(v) for k, v in _DEFAULTS.items()}
    with open(STAMMDATEN_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return {k: list(v) for k, v in _DEFAULTS.items()}

    # Current 4-section format
    if isinstance(data, dict) and "dokumenttypen" in data:
        return {
            "dokumenttypen":  data.get("dokumenttypen", []),
            "absender":       data.get("absender", []),
            "personen":       data.get("personen", []),
            "kombinationen":  data.get("kombinationen", []),
        }

    # Migrate: old 2-section format {kombinationen, personen}
    if isinstance(data, dict) and "kombinationen" in data:
        kombi = data.get("kombinationen", [])
        result = {
            "dokumenttypen": sorted({e.get("dokumenttyp", "") for e in kombi if e.get("dokumenttyp")}),
            "absender":      sorted({e.get("absender", "")    for e in kombi if e.get("absender")}),
            "personen":      sorted(data.get("personen", [])),
            "kombinationen": kombi,
        }
        _save_all(result)
        return result

    # Migrate: legacy triplet list [{dokumenttyp, absender, personenbezug}]
    if isinstance(data, list):
        kombi, typen, abs_set, pers = [], set(), set(), set()
        seen: set[tuple] = set()
        for e in data:
            t, a = e.get("dokumenttyp", ""), e.get("absender", "")
            typen.add(t); abs_set.add(a)
            if (t, a) not in seen:
                seen.add((t, a))
                kombi.append({"dokumenttyp": t, "absender": a})
            pb = e.get("personenbezug", "")
            if pb:
                pers.add(pb)
        result = {
            "dokumenttypen": sorted(typen - {""}),
            "absender":      sorted(abs_set - {""}),
            "personen":      sorted(pers),
            "kombinationen": kombi,
        }
        _save_all(result)
        return result

    return {k: list(v) for k, v in _DEFAULTS.items()}


def _save_all(data: dict) -> None:
    with open(STAMMDATEN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Dokumenttypen
# ---------------------------------------------------------------------------

def load_dokumenttypen() -> list[str]:
    return _load_all()["dokumenttypen"]

def save_dokumenttypen(items: list[str]) -> None:
    d = _load_all(); d["dokumenttypen"] = items; _save_all(d)

def add_dokumenttyp(name: str) -> None:
    if not name:
        return
    d = _load_all()
    if name not in d["dokumenttypen"]:
        d["dokumenttypen"] = sorted(d["dokumenttypen"] + [name])
        _save_all(d)


# ---------------------------------------------------------------------------
# Absender
# ---------------------------------------------------------------------------

def load_absender() -> list[str]:
    return _load_all()["absender"]

def save_absender(items: list[str]) -> None:
    d = _load_all(); d["absender"] = items; _save_all(d)

def add_absender(name: str) -> None:
    if not name:
        return
    d = _load_all()
    if name not in d["absender"]:
        d["absender"] = sorted(d["absender"] + [name])
        _save_all(d)


# ---------------------------------------------------------------------------
# Personen
# ---------------------------------------------------------------------------

def load_persons() -> list[str]:
    return _load_all()["personen"]

def save_persons(items: list[str]) -> None:
    d = _load_all(); d["personen"] = items; _save_all(d)

def add_person(name: str) -> None:
    if not name:
        return
    d = _load_all()
    if name not in d["personen"]:
        d["personen"] = sorted(d["personen"] + [name])
        _save_all(d)

def get_persons() -> list[str]:
    return sorted(load_persons())


# ---------------------------------------------------------------------------
# Kombinationen (KI-Kontext)
# ---------------------------------------------------------------------------

def load() -> list[dict]:
    """Returns kombinationen — used as TF-IDF corpus and LLM RAG context."""
    return _load_all()["kombinationen"]

def save(kombinationen: list[dict]) -> None:
    d = _load_all(); d["kombinationen"] = kombinationen; _save_all(d)

def add_kombination(typ: str, absender: str) -> None:
    if not typ or not absender:
        return
    d = _load_all()
    for e in d["kombinationen"]:
        if e.get("dokumenttyp") == typ and e.get("absender") == absender:
            return
    d["kombinationen"].append({"dokumenttyp": typ, "absender": absender})
    _save_all(d)


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_unique_values(field: str) -> list[str]:
    if field == "dokumenttyp":
        return sorted(load_dokumenttypen())
    if field == "absender":
        return sorted(load_absender())
    if field == "personenbezug":
        return get_persons()
    return []


def get_rag_context() -> str:
    d = _load_all()
    lines: list[str] = []

    if d["dokumenttypen"]:
        lines.append("Bekannte Dokumenttypen: " + ", ".join(d["dokumenttypen"]))

    if d["absender"]:
        lines.append("Bekannte Absender: " + ", ".join(d["absender"]))

    if d["personen"]:
        lines.append("Bekannte Personen: " + ", ".join(d["personen"]))

    if d["kombinationen"]:
        lines.append("Historische Kombinationen (Dokumenttyp → Absender):")
        for e in d["kombinationen"]:
            lines.append(f"  - {e.get('dokumenttyp', '')} → {e.get('absender', '')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def ensure_defaults() -> None:
    if not os.path.exists(STAMMDATEN_PATH):
        _save_all({k: list(v) for k, v in _DEFAULTS.items()})
