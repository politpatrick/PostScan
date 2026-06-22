import json
import os
import sys

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

if sys.platform == "darwin":
    OLLAMA_MODELS = ["gemma4:e2b-mlx"]
    _DEFAULT_MODEL = "gemma4:e2b-mlx"
elif sys.platform == "win32":
    OLLAMA_MODELS = ["gemma4:e2b"]
    _DEFAULT_MODEL = "gemma4:e2b"
else:
    OLLAMA_MODELS = ["gemma4:e2b"]
    _DEFAULT_MODEL = "gemma4:e2b"

_DEFAULTS: dict = {"llm_provider": "ollama", "ollama_model": _DEFAULT_MODEL, "google_api_key": ""}


def load() -> dict:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {**_DEFAULTS, **data}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_DEFAULTS)


def save(data: dict) -> None:
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_provider() -> str:
    return load().get("llm_provider", "ollama")


def get_ollama_model() -> str:
    return load().get("ollama_model", _DEFAULT_MODEL)


def get_google_api_key() -> str:
    return load().get("google_api_key", "")
