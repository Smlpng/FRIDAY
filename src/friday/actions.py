from __future__ import annotations

import os
import subprocess
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

import pyautogui

from .config import Settings
from .spotify_api import SpotifyApiError, SpotifyAuthError, SpotifyClient, SpotifyConfig


pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.2


class ActionExecutionError(RuntimeError):
    pass


class WindowsActions:
    def __init__(self, registry: dict[str, Any], settings: Settings | None = None) -> None:
        self.registry = registry
        self.settings = settings
        self._spotify: SpotifyClient | None = None

    def execute(self, action: dict[str, Any]) -> str:
        action_type = action.get("type", "")
        params = action.get("params", {})

        handlers = {
            "open_app": lambda: self.open_app(params.get("name", "")),
            "search_web": lambda: self.search_web(
                params.get("query", ""), params.get("browser", "chrome")
            ),
            "media_control": lambda: self.media_control(params.get("action", "")),
            "spotify_search_play": lambda: self.spotify_search_play(params.get("query", "")),
            "spotify_api_play": lambda: self.spotify_api_play(
                params.get("query", ""), params.get("target", "track")
            ),
            "youtube_search_play": lambda: self.youtube_search_play(
                params.get("query", ""), params.get("browser", "chrome")
            ),
            "open_url": lambda: self.open_url(
                params.get("url", ""), params.get("browser", "chrome")
            ),
            "type_text": lambda: self.type_text(params.get("text", "")),
            "hotkey": lambda: self.hotkey(params.get("keys", [])),
            "wait": lambda: self.wait(params.get("seconds", 1)),
        }

        handler = handlers.get(action_type)
        if handler is None:
            raise ActionExecutionError(f"Acao nao suportada: {action_type}")
        return handler()

    def open_app(self, app_name: str) -> str:
        normalized_name = self._resolve_alias(app_name)
        app_entry = self.registry.get("apps", {}).get(normalized_name)

        if app_entry is None:
            raise ActionExecutionError(
                f"App ou jogo '{app_name}' nao cadastrado em config/apps.json."
            )

        uri = app_entry.get("uri")
        if uri:
            os.startfile(uri)
            return f"Abrindo {normalized_name}."

        path = app_entry.get("path", "")
        args = app_entry.get("args", [])
        if not path:
            raise ActionExecutionError(f"App '{normalized_name}' sem path configurado.")

        executable = Path(path)
        if not executable.exists():
            raise ActionExecutionError(
                f"Caminho do app '{normalized_name}' nao encontrado: {path}"
            )

        subprocess.Popen([str(executable), *args])
        return f"Abrindo {normalized_name}."

    def search_web(self, query: str, browser: str = "chrome") -> str:
        if not query.strip():
            raise ActionExecutionError("Consulta de pesquisa vazia.")

        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
        self.open_url(url, browser=browser)
        return f"Pesquisando por {query}."

    def media_control(self, action: str) -> str:
        key_map = {
            "play_pause": "playpause",
            "next": "nexttrack",
            "previous": "prevtrack",
            "mute": "volumemute",
            "volume_up": "volumeup",
            "volume_down": "volumedown",
        }

        key = key_map.get(action)
        if key is None:
            raise ActionExecutionError(f"Controle de midia invalido: {action}")

        pyautogui.press(key)
        return f"Controle de midia executado: {action}."

    def spotify_search_play(self, query: str) -> str:
        q = str(query or "").strip()
        if not q:
            raise ActionExecutionError("Consulta vazia para tocar no Spotify.")

        # 1) Abre/foca o Spotify já na busca (costuma trazer o app para frente)
        encoded = urllib.parse.quote(q)
        try:
            os.startfile(f"spotify:search:{encoded}")
        except Exception:
            # fallback: abre o app e tenta digitar a busca
            try:
                self.open_app("spotify")
            except Exception:
                try:
                    os.startfile("spotify:")
                except Exception as exc:
                    raise ActionExecutionError("Nao consegui abrir o Spotify.") from exc

        time.sleep(1.6)

        # 2) Foca a busca (no Spotify Desktop costuma funcionar)
        try:
            pyautogui.hotkey("ctrl", "l")
            time.sleep(0.1)
            # Em alguns layouts, Ctrl+K também foca a busca
            pyautogui.hotkey("ctrl", "k")
            time.sleep(0.1)
            pyautogui.write(q, interval=0.02)
            pyautogui.press("enter")
        except Exception as exc:
            raise ActionExecutionError("Falha ao digitar a busca no Spotify.") from exc

        # 3) Tenta tocar o primeiro resultado (heurística por teclado)
        time.sleep(1.4)
        try:
            # Às vezes, Enter já seleciona algo; reforça com navegação por Tab
            pyautogui.press("enter")
            time.sleep(0.2)
            pyautogui.press("tab", presses=10, interval=0.03)
            pyautogui.press("down")
            pyautogui.press("enter")
            time.sleep(0.2)

            # Em alguns contextos, Ctrl+Enter/Space inicia a reprodução
            pyautogui.hotkey("ctrl", "enter")
            time.sleep(0.2)
            pyautogui.press("space")
            time.sleep(0.2)
            pyautogui.press("space")
            time.sleep(0.4)

            # fallback extra: tenta play/pause do sistema
            pyautogui.press("playpause")
            time.sleep(0.2)
            pyautogui.press("playpause")
        except Exception:
            # Mesmo se isso falhar, ao menos a busca foi aberta
            pass

        return f"Buscando no Spotify e tentando tocar: {q}."

    def spotify_api_play(self, query: str, target: str = "track") -> str:
        q = str(query or "").strip()
        if not q:
            raise ActionExecutionError("Consulta vazia para tocar no Spotify.")
        if not self.settings:
            raise ActionExecutionError("Spotify API nao configurada.")

        client_id = (self.settings.spotify_client_id or "").strip()
        client_secret = (self.settings.spotify_client_secret or "").strip()
        if not client_id or not client_secret:
            raise ActionExecutionError(
                "Spotify API: informe spotify.client_id e spotify.client_secret em config/settings.json."
            )

        if self._spotify is None:
            scopes = self.settings.spotify_scopes or [
                "user-read-playback-state",
                "user-modify-playback-state",
                "playlist-read-private",
                "playlist-read-collaborative",
            ]
            self._spotify = SpotifyClient(
                SpotifyConfig(
                    client_id=client_id,
                    client_secret=client_secret,
                    redirect_uri=self.settings.spotify_redirect_uri,
                    token_path=self.settings.spotify_token_path,
                    scopes=scopes,
                )
            )

        try:
            normalized_target = str(target or "track").strip().lower()
            if normalized_target == "playlist":
                playlist = self._spotify.find_user_playlist(q)
                if not playlist:
                    return f"Nao encontrei essa playlist nas suas playlists do Spotify: {q}."
                uri = str(playlist.get("uri", "")).strip()
                name = str(playlist.get("name", "")).strip()
                owner_name = str(((playlist.get("owner") or {}).get("display_name") or "")).strip()
                if not uri:
                    return f"Nao consegui obter o URI da playlist: {q}."
                self._spotify.play_context(uri)
                label = f"{name} - {owner_name}".strip(" -")
                return f"Tocando playlist no Spotify: {label}."

            track = self._spotify.search_track(q)
            if not track:
                return f"Nao encontrei essa musica no Spotify: {q}."
            uri = str(track.get("uri", ""))
            name = str(track.get("name", ""))
            artists = ", ".join(a.get("name", "") for a in (track.get("artists") or []) if a.get("name"))
            if not uri:
                return f"Nao consegui obter o URI da musica: {q}."
            self._spotify.play_track(uri)
            label = f"{name} - {artists}".strip(" -")
            return f"Tocando no Spotify: {label}."
        except (SpotifyAuthError, SpotifyApiError) as exc:
            raise ActionExecutionError(str(exc)) from exc

    def youtube_search_play(self, query: str, browser: str = "chrome") -> str:
        q = str(query or "").strip()
        if not q:
            raise ActionExecutionError("Consulta vazia para tocar no YouTube.")

        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(q)}"
        self.open_url(url, browser=browser)
        time.sleep(2.4)

        try:
            pyautogui.press("tab", presses=3, interval=0.08)
            pyautogui.press("enter")
            time.sleep(1.2)
            pyautogui.press("k")
        except Exception:
            pass

        return f"Buscando no YouTube e tentando tocar: {q}."

    def open_url(self, url: str, browser: str = "chrome") -> str:
        if not url.strip():
            raise ActionExecutionError("URL vazia.")

        # URIs de apps (ex: spotify:search:...) devem ser abertos via o handler do Windows.
        lowered = url.strip().lower()
        if lowered.startswith("spotify:"):
            os.startfile(url)
            return f"Abrindo {url}."

        if browser.lower() == "chrome":
            chrome_path = self._find_chrome_path()
            if chrome_path:
                subprocess.Popen([chrome_path, url])
                return f"Abrindo {url} no Chrome."

        webbrowser.open(url)
        return f"Abrindo {url}."

    def type_text(self, text: str) -> str:
        if not text:
            raise ActionExecutionError("Texto vazio para digitacao.")
        pyautogui.write(text, interval=0.03)
        return "Texto digitado."

    def hotkey(self, keys: list[str]) -> str:
        if not keys:
            raise ActionExecutionError("Lista de teclas vazia.")
        pyautogui.hotkey(*keys)
        return f"Atalho executado: {' + '.join(keys)}."

    def wait(self, seconds: int | float) -> str:
        wait_time = max(0, float(seconds))
        time.sleep(wait_time)
        return f"Espera de {wait_time:g}s concluida."

    def _resolve_alias(self, app_name: str) -> str:
        normalized_name = app_name.strip().lower()
        aliases = self.registry.get("aliases", {})
        return aliases.get(normalized_name, normalized_name)

    def _find_chrome_path(self) -> str | None:
        chrome_entry = self.registry.get("apps", {}).get("chrome")
        if chrome_entry:
            chrome_path = chrome_entry.get("path", "")
            if chrome_path and Path(chrome_path).exists():
                return chrome_path

        common_paths = [
            Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
            Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        ]
        for path in common_paths:
            if path.exists():
                return str(path)
        return None
