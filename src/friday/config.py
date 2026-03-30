from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
DEFAULT_APPS_PATH = CONFIG_DIR / "apps.json"
EXAMPLE_APPS_PATH = CONFIG_DIR / "apps.example.json"
DEFAULT_SETTINGS_PATH = CONFIG_DIR / "settings.json"
EXAMPLE_SETTINGS_PATH = CONFIG_DIR / "settings.example.json"
DEFAULT_SPOTIFY_TOKEN_PATH = CONFIG_DIR / "spotify_token.json"
DEFAULT_MEMORY_PATH = CONFIG_DIR / "conversation_memory.json"


@dataclass(slots=True)
class Settings:
    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"
    friday_name: str = "friday"
    wake_words: list[str] | None = None
    language: str = "pt-BR"
    apps_path: Path = DEFAULT_APPS_PATH
    microphone_device_index: int | None = None
    phrase_time_limit: int = 6
    ambient_noise_adjust_seconds: int = 1
    energy_threshold: int | None = None
    gui_particle_count: int = 850
    memory_path: Path = DEFAULT_MEMORY_PATH
    memory_ttl_minutes: int = 180
    memory_max_messages: int = 24

    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = "http://127.0.0.1:8765/callback"
    spotify_token_path: Path = DEFAULT_SPOTIFY_TOKEN_PATH
    spotify_scopes: list[str] | None = None


def load_settings() -> Settings:
    settings_path = DEFAULT_SETTINGS_PATH if DEFAULT_SETTINGS_PATH.exists() else EXAMPLE_SETTINGS_PATH
    if settings_path.exists():
        with settings_path.open("r", encoding="utf-8") as file:
            raw_settings = json.load(file)

        voice = (
            raw_settings.get("voice", {})
            if isinstance(raw_settings.get("voice", {}), dict)
            else {}
        )
        gui = (
            raw_settings.get("gui", {})
            if isinstance(raw_settings.get("gui", {}), dict)
            else {}
        )
        memory = (
            raw_settings.get("memory", {})
            if isinstance(raw_settings.get("memory", {}), dict)
            else {}
        )

        spotify = (
            raw_settings.get("spotify", {})
            if isinstance(raw_settings.get("spotify", {}), dict)
            else {}
        )

        mic_index = voice.get("microphone_device_index", None)
        if mic_index is not None:
            try:
                mic_index = int(mic_index)
            except (TypeError, ValueError):
                mic_index = None

        energy_threshold = voice.get("energy_threshold", None)
        if energy_threshold is not None:
            try:
                energy_threshold = int(energy_threshold)
            except (TypeError, ValueError):
                energy_threshold = None

        return Settings(
            gemini_api_key=str(raw_settings.get("gemini_api_key", "")).strip(),
            gemini_model=str(raw_settings.get("gemini_model", "gemini-2.5-flash")).strip(),
            friday_name=str(raw_settings.get("friday_name", "friday")).strip().lower(),
            wake_words=_parse_wake_words(raw_settings),
            language=str(raw_settings.get("friday_language", "pt-BR")).strip(),
            microphone_device_index=mic_index,
            phrase_time_limit=int(voice.get("phrase_time_limit", 6)),
            ambient_noise_adjust_seconds=int(voice.get("ambient_noise_adjust_seconds", 1)),
            energy_threshold=energy_threshold,
            gui_particle_count=int(gui.get("particle_count", 850)),
            memory_path=Path(
                str(memory.get("path", DEFAULT_MEMORY_PATH))
            ).expanduser(),
            memory_ttl_minutes=int(memory.get("ttl_minutes", 180)),
            memory_max_messages=int(memory.get("max_messages", 24)),

            spotify_client_id=str(spotify.get("client_id", "")).strip(),
            spotify_client_secret=str(spotify.get("client_secret", "")).strip(),
            spotify_redirect_uri=str(spotify.get("redirect_uri", "http://127.0.0.1:8765/callback")).strip(),
            spotify_token_path=Path(str(spotify.get("token_path", DEFAULT_SPOTIFY_TOKEN_PATH))).expanduser(),
            spotify_scopes=([
                str(s).strip()
                for s in spotify.get("scopes", [])
                if str(s).strip()
            ] if isinstance(spotify.get("scopes"), list) else None),
        )

    load_dotenv(ROOT_DIR / ".env")
    return Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        friday_name=os.getenv("FRIDAY_NAME", "friday").strip().lower(),
        language=os.getenv("FRIDAY_LANGUAGE", "pt-BR").strip(),
        memory_path=Path(os.getenv("FRIDAY_MEMORY_PATH", str(DEFAULT_MEMORY_PATH))).expanduser(),
        memory_ttl_minutes=int(os.getenv("FRIDAY_MEMORY_TTL_MINUTES", "180")),
        memory_max_messages=int(os.getenv("FRIDAY_MEMORY_MAX_MESSAGES", "24")),

        spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID", "").strip(),
        spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET", "").strip(),
        spotify_redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8765/callback").strip(),
        spotify_token_path=Path(os.getenv("SPOTIFY_TOKEN_PATH", str(DEFAULT_SPOTIFY_TOKEN_PATH))).expanduser(),
        spotify_scopes=None,
    )


def _parse_wake_words(raw_settings: dict[str, Any]) -> list[str] | None:
    candidates: list[str] = []

    top = raw_settings.get("wake_words")
    if isinstance(top, list):
        for item in top:
            if isinstance(item, str) and item.strip():
                candidates.append(item.strip().lower())

    voice = raw_settings.get("voice")
    if isinstance(voice, dict):
        voice_list = voice.get("wake_words")
        if isinstance(voice_list, list):
            for item in voice_list:
                if isinstance(item, str) and item.strip():
                    candidates.append(item.strip().lower())

    if candidates:
        # remove duplicados preservando ordem
        seen = set()
        unique: list[str] = []
        for w in candidates:
            if w not in seen:
                unique.append(w)
                seen.add(w)
        return unique

    return None


def load_apps_registry(apps_path: Path | None = None) -> dict[str, Any]:
    target_path = apps_path or DEFAULT_APPS_PATH
    if target_path.exists():
        with target_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    with EXAMPLE_APPS_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)
