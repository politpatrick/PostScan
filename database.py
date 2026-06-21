import json
import os
from typing import Optional

STAMMDATEN_PATH = os.path.join(os.path.dirname(__file__), "stammdaten.json")

_DEFAULT_ENTRIES = [
    {"dokumenttyp": "Rechnung", "absender": "HUK-COBURG", "personenbezug": "Kunze"},
    {"dokumenttyp": "Rechnung", "absender": "AOK Bayern", "personenbezug": "Kunze"},
    {"dokumenttyp": "Bescheid", "absender": "Finanzamt", "personenbezug": "Kunze"},
    {"dokumenttyp": "Vertrag", "absender": "Telekom", "personenbezug": "Kunze"},
    {"dokumenttyp": "Kontoauszug", "absender": "Sparkasse", "personenbezug": "Kunze"},
    {"dokumenttyp": "Brief", "absender": "Unbekannt", "personenbezug": ""},
]


def load() -> list[dict]:
    if not os.path.exists(STAMMDATEN_PATH):
        return []
    with open(STAMMDATEN_PATH, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []


def save(entries: list[dict]) -> None:
    with open(STAMMDATEN_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def add_or_update(entry: dict) -> None:
    entries = load()
    key = (entry.get("dokumenttyp", ""), entry.get("absender", ""))
    for i, e in enumerate(entries):
        if (e.get("dokumenttyp", ""), e.get("absender", "")) == key:
            entries[i] = entry
            save(entries)
            return
    entries.append(entry)
    save(entries)


def delete(index: int) -> None:
    entries = load()
    if 0 <= index < len(entries):
        entries.pop(index)
        save(entries)


def get_rag_context() -> str:
    entries = load()
    if not entries:
        return ""
    lines = ["Bekannte Kombinationen (Dokumenttyp | Absender | Personenbezug):"]
    for e in entries:
        dt = e.get("dokumenttyp", "")
        ab = e.get("absender", "")
        pb = e.get("personenbezug", "")
        lines.append(f"  - {dt} | {ab} | {pb}")
    return "\n".join(lines)


def get_unique_values(field: str) -> list[str]:
    entries = load()
    seen = set()
    result = []
    for e in entries:
        v = e.get(field, "")
        if v and v not in seen:
            seen.add(v)
            result.append(v)
    return sorted(result)


def ensure_defaults() -> None:
    if not os.path.exists(STAMMDATEN_PATH):
        save(_DEFAULT_ENTRIES)
