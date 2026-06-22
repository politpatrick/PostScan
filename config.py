import json
import os
import sys

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

if sys.platform == "darwin":
    OLLAMA_MODELS = ["gemma2:9b", "gemma4:e2b-mlx"]
else:
    OLLAMA_MODELS = ["gemma2:9b"]

_DEFAULTS: dict = {"llm_provider": "ollama", "ollama_model": "gemma2:9b", "google_api_key": ""}


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
    return load().get("ollama_model", "gemma2:9b")


def get_google_api_key() -> str:
    return load().get("google_api_key", "")
