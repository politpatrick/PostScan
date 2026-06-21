import json
import os

STAMMDATEN_PATH = os.path.join(os.path.dirname(__file__), "stammdaten.json")

_DEFAULT_KOMBINATIONEN = [
    {"dokumenttyp": "Rechnung", "absender": "HUK-COBURG"},
    {"dokumenttyp": "Rechnung", "absender": "AOK Bayern"},
    {"dokumenttyp": "Bescheid", "absender": "Finanzamt"},
    {"dokumenttyp": "Vertrag", "absender": "Telekom"},
    {"dokumenttyp": "Kontoauszug", "absender": "Sparkasse"},
    {"dokumenttyp": "Brief", "absender": "Unbekannt"},
]
_DEFAULT_PERSONEN = ["Kunze"]


# ---------------------------------------------------------------------------
# Internal I/O
# ---------------------------------------------------------------------------

def _load_all() -> dict:
    if not os.path.exists(STAMMDATEN_PATH):
        return {"kombinationen": [], "personen": []}
    with open(STAMMDATEN_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return {"kombinationen": [], "personen": []}

    # New format
    if isinstance(data, dict):
        return {
            "kombinationen": data.get("kombinationen", []),
            "personen": data.get("personen", []),
        }

    # Migrate old format (list of triplets)
    if isinstance(data, list):
        seen: set[tuple] = set()
        kombinationen = []
        personen_set: set[str] = set()
        for e in data:
            key = (e.get("dokumenttyp", ""), e.get("absender", ""))
            if key not in seen:
                seen.add(key)
                kombinationen.append({"dokumenttyp": key[0], "absender": key[1]})
            pb = e.get("personenbezug", "")
            if pb:
                personen_set.add(pb)
        migrated = {"kombinationen": kombinationen, "personen": sorted(personen_set)}
        _save_all(migrated)
        return migrated

    return {"kombinationen": [], "personen": []}


def _save_all(data: dict) -> None:
    with open(STAMMDATEN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Public API – Kombinationen
# ---------------------------------------------------------------------------

def load() -> list[dict]:
    return _load_all()["kombinationen"]


def save(kombinationen: list[dict]) -> None:
    data = _load_all()
    data["kombinationen"] = kombinationen
    _save_all(data)


def add_or_update(entry: dict) -> None:
    """Upsert by (dokumenttyp, absender) key."""
    data = _load_all()
    key = (entry.get("dokumenttyp", ""), entry.get("absender", ""))
    for i, e in enumerate(data["kombinationen"]):
        if (e.get("dokumenttyp", ""), e.get("absender", "")) == key:
            data["kombinationen"][i] = {"dokumenttyp": key[0], "absender": key[1]}
            _save_all(data)
            return
    data["kombinationen"].append({"dokumenttyp": key[0], "absender": key[1]})
    _save_all(data)


def delete_kombination(index: int) -> None:
    data = _load_all()
    if 0 <= index < len(data["kombinationen"]):
        data["kombinationen"].pop(index)
        _save_all(data)


# ---------------------------------------------------------------------------
# Public API – Personen
# ---------------------------------------------------------------------------

def load_persons() -> list[str]:
    return _load_all()["personen"]


def save_persons(persons: list[str]) -> None:
    data = _load_all()
    data["personen"] = persons
    _save_all(data)


def add_person(name: str) -> None:
    if not name:
        return
    data = _load_all()
    if name not in data["personen"]:
        data["personen"].append(name)
        data["personen"].sort()
        _save_all(data)


def get_persons() -> list[str]:
    return sorted(load_persons())


# ---------------------------------------------------------------------------
# Public API – Query helpers
# ---------------------------------------------------------------------------

def get_unique_values(field: str) -> list[str]:
    if field == "personenbezug":
        return get_persons()
    seen: set[str] = set()
    result: list[str] = []
    for e in load():
        v = e.get(field, "")
        if v and v not in seen:
            seen.add(v)
            result.append(v)
    return sorted(result)


def get_rag_context() -> str:
    data = _load_all()
    lines: list[str] = []
    if data["kombinationen"]:
        lines.append("Bekannte Dokumenttyp/Absender-Kombinationen:")
        for e in data["kombinationen"]:
            lines.append(f"  - {e.get('dokumenttyp', '')} | {e.get('absender', '')}")
    if data["personen"]:
        lines.append("Bekannte Personen (Nachname):")
        for p in data["personen"]:
            lines.append(f"  - {p}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def ensure_defaults() -> None:
    if not os.path.exists(STAMMDATEN_PATH):
        _save_all({"kombinationen": _DEFAULT_KOMBINATIONEN, "personen": _DEFAULT_PERSONEN})
