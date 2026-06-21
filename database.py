import json
import os

STAMMDATEN_PATH = os.path.join(os.path.dirname(__file__), "stammdaten.json")

_DEFAULTS = {
    "dokumenttypen": [
        {"name": "Bescheid",    "abk": "",   "synonyme": []},
        {"name": "Brief",       "abk": "",   "synonyme": []},
        {"name": "Kontoauszug", "abk": "KA", "synonyme": []},
        {"name": "Rechnung",    "abk": "RE", "synonyme": []},
        {"name": "Vertrag",     "abk": "",   "synonyme": []},
    ],
    "absender": [
        {"name": "AOK Bayern",  "abk": "AOK",  "synonyme": []},
        {"name": "Finanzamt",   "abk": "FA",   "synonyme": []},
        {"name": "HUK-COBURG",  "abk": "HUK",  "synonyme": ["HUK COBURG", "HUK Coburg"]},
        {"name": "Sparkasse",   "abk": "SPK",  "synonyme": []},
        {"name": "Telekom",     "abk": "",     "synonyme": ["Deutsche Telekom"]},
        {"name": "Unbekannt",   "abk": "",     "synonyme": []},
    ],
    "personen": ["Kunze"],
    "vorschlaege": {"dokumenttypen": [], "absender": []},
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

def _to_dict(entry) -> dict:
    """Ensure a dokumenttyp or absender entry is a dict; migrate plain strings."""
    if isinstance(entry, str):
        return {"name": entry, "abk": "", "synonyme": []}
    return {
        "name":    entry.get("name", ""),
        "abk":     entry.get("abk", ""),
        "synonyme": entry.get("synonyme", []),
    }


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
        raw_typ = data.get("dokumenttypen", [])
        raw_abs = data.get("absender", [])
        result = {
            "dokumenttypen": [_to_dict(t) for t in raw_typ],
            "absender":      [_to_dict(a) for a in raw_abs],
            "personen":      data.get("personen", []),
            "vorschlaege":   data.get("vorschlaege", {"dokumenttypen": [], "absender": []}),
            "kombinationen": data.get("kombinationen", []),
        }
        # Save back if either list was migrated from strings
        if (raw_typ and isinstance(raw_typ[0], str)) or \
           (raw_abs and isinstance(raw_abs[0], str)):
            _save_all(result)
        return result

    # Migrate: old 2-section format {kombinationen, personen}
    if isinstance(data, dict) and "kombinationen" in data:
        kombi = data.get("kombinationen", [])
        typ_names = sorted({e.get("dokumenttyp", "") for e in kombi if e.get("dokumenttyp")})
        abs_names = sorted({e.get("absender", "")    for e in kombi if e.get("absender")})
        result = {
            "dokumenttypen": [{"name": n, "abk": "", "synonyme": []} for n in typ_names],
            "absender":      [{"name": n, "abk": "", "synonyme": []} for n in abs_names],
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
            "dokumenttypen": [{"name": n, "abk": "", "synonyme": []} for n in sorted(typen - {""})],
            "absender":      [{"name": n, "abk": "", "synonyme": []} for n in sorted(abs_set - {""})],
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
# Dokumenttypen  (list[dict] with name/abk/synonyme)
# ---------------------------------------------------------------------------

def load_dokumenttypen() -> list[dict]:
    return _load_all()["dokumenttypen"]

def load_dokumenttypen_names() -> list[str]:
    return [t["name"] for t in load_dokumenttypen()]

def save_dokumenttypen(items: list[dict]) -> None:
    d = _load_all(); d["dokumenttypen"] = items; _save_all(d)

def add_dokumenttyp(name: str) -> None:
    if not name:
        return
    d = _load_all()
    if not any(t["name"] == name for t in d["dokumenttypen"]):
        d["dokumenttypen"].append({"name": name, "abk": "", "synonyme": []})
        d["dokumenttypen"].sort(key=lambda t: t["name"])
        _save_all(d)

def get_dokumenttyp_display(name: str) -> str:
    for t in load_dokumenttypen():
        if t["name"] == name:
            return t["abk"].strip() if t["abk"].strip() else name
    return name


# ---------------------------------------------------------------------------
# Absender  (now list[dict] with name/abk/synonyme)
# ---------------------------------------------------------------------------

def load_absender() -> list[dict]:
    """Returns list of absender dicts: {name, abk, synonyme}."""
    return _load_all()["absender"]

def load_absender_names() -> list[str]:
    """Returns just the canonical names — for dropdowns."""
    return [a["name"] for a in load_absender()]

def save_absender(items: list[dict]) -> None:
    d = _load_all(); d["absender"] = items; _save_all(d)

def add_absender(name: str) -> None:
    if not name:
        return
    d = _load_all()
    if not any(a["name"] == name for a in d["absender"]):
        d["absender"].append({"name": name, "abk": "", "synonyme": []})
        d["absender"].sort(key=lambda a: a["name"])
        _save_all(d)

def get_absender_display(name: str) -> str:
    """Returns abbreviation if set, otherwise the full name — used in filenames."""
    for a in load_absender():
        if a["name"] == name:
            return a["abk"].strip() if a["abk"].strip() else name
    return name

def get_absender_synonyme(name: str) -> list[str]:
    for a in load_absender():
        if a["name"] == name:
            return a.get("synonyme", [])
    return []


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
        return sorted(load_dokumenttypen_names())
    if field == "absender":
        return sorted(load_absender_names())
    if field == "personenbezug":
        return get_persons()
    return []


def get_rag_context() -> str:
    d = _load_all()
    lines: list[str] = []

    if d["dokumenttypen"]:
        typ_strs = []
        for t in d["dokumenttypen"]:
            s = t["name"]
            if t.get("synonyme"):
                s += " (auch: " + ", ".join(t["synonyme"]) + ")"
            typ_strs.append(s)
        lines.append("Bekannte Dokumenttypen: " + "; ".join(typ_strs))

    if d["absender"]:
        abs_strs = []
        for a in d["absender"]:
            s = a["name"]
            if a.get("synonyme"):
                s += " (auch: " + ", ".join(a["synonyme"]) + ")"
            abs_strs.append(s)
        lines.append("Bekannte Absender: " + "; ".join(abs_strs))

    if d["personen"]:
        lines.append("Bekannte Personen: " + ", ".join(d["personen"]))

    if d["kombinationen"]:
        lines.append("Historische Kombinationen (Dokumenttyp -> Absender):")
        for e in d["kombinationen"]:
            lines.append(f"  - {e.get('dokumenttyp', '')} -> {e.get('absender', '')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Vorschläge (KI-erkannte, noch nicht bestätigte Einträge)
# ---------------------------------------------------------------------------

def load_vorschlaege() -> dict:
    return _load_all().get("vorschlaege", {"dokumenttypen": [], "absender": []})

def _add_vorschlag(field: str, name: str) -> None:
    if not name:
        return
    d = _load_all()
    v = d.setdefault("vorschlaege", {"dokumenttypen": [], "absender": []})
    if name not in v.get(field, []):
        v.setdefault(field, []).append(name)
        _save_all(d)

def add_vorschlag_dokumenttyp(name: str) -> None:
    _add_vorschlag("dokumenttypen", name)

def add_vorschlag_absender(name: str) -> None:
    _add_vorschlag("absender", name)

def remove_vorschlag(field: str, name: str) -> None:
    d = _load_all()
    v = d.get("vorschlaege", {})
    if name in v.get(field, []):
        v[field].remove(name)
        _save_all(d)

def promote_vorschlag_dokumenttyp(name: str) -> None:
    remove_vorschlag("dokumenttypen", name)
    add_dokumenttyp(name)

def promote_vorschlag_absender(name: str) -> None:
    remove_vorschlag("absender", name)
    add_absender(name)


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def ensure_defaults() -> None:
    if not os.path.exists(STAMMDATEN_PATH):
        _save_all({k: list(v) for k, v in _DEFAULTS.items()})
