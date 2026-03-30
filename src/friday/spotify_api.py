from __future__ import annotations

import base64
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import requests


SPOTIFY_ACCOUNTS_BASE = "https://accounts.spotify.com"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"


class SpotifyAuthError(RuntimeError):
    pass


class SpotifyApiError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SpotifyConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    token_path: Path
    scopes: list[str]


def _now() -> int:
    return int(time.time())


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _load_token(token_path: Path) -> dict[str, Any] | None:
    if not token_path.exists():
        return None
    try:
        return json.loads(token_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_token(token_path: Path, token: dict[str, Any]) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(json.dumps(token, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_token_valid(token: dict[str, Any]) -> bool:
    expires_at = int(token.get("expires_at", 0) or 0)
    # margem de 60s
    return bool(token.get("access_token")) and expires_at > (_now() + 60)


class _AuthCallbackHandler(BaseHTTPRequestHandler):
    server_version = "FridaySpotifyAuth/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != self.server.callback_path:  # type: ignore[attr-defined]
            self.send_response(404)
            self.end_headers()
            return

        qs = urllib.parse.parse_qs(parsed.query)
        state = (qs.get("state") or [""])[0]
        code = (qs.get("code") or [""])[0]
        error = (qs.get("error") or [""])[0]

        if error:
            self.server.auth_error = error  # type: ignore[attr-defined]
        elif not code:
            self.server.auth_error = "missing_code"  # type: ignore[attr-defined]
        elif state != self.server.expected_state:  # type: ignore[attr-defined]
            self.server.auth_error = "invalid_state"  # type: ignore[attr-defined]
        else:
            self.server.auth_code = code  # type: ignore[attr-defined]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            (
                "<html><body><h2>Autorizacao recebida.</h2>"
                "<p>Voce pode fechar esta janela e voltar para a Friday.</p>"
                "</body></html>"
            ).encode("utf-8")
        )

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # silêncio
        return


def _wait_for_auth_code(
    *,
    redirect_uri: str,
    scopes: list[str],
    client_id: str,
    timeout_seconds: int = 180,
) -> str:
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}:
        raise SpotifyAuthError(
            "redirect_uri precisa usar loopback explicito, como http://127.0.0.1:8765/callback"
        )

    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    callback_path = parsed.path or "/callback"

    state = secrets.token_urlsafe(16)

    server = HTTPServer((host, port), _AuthCallbackHandler)
    server.expected_state = state  # type: ignore[attr-defined]
    server.callback_path = callback_path  # type: ignore[attr-defined]
    server.auth_code = None  # type: ignore[attr-defined]
    server.auth_error = None  # type: ignore[attr-defined]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    scope_str = " ".join(scopes)
    authorize_url = (
        f"{SPOTIFY_ACCOUNTS_BASE}/authorize?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": scope_str,
                "state": state,
                "show_dialog": "true",
            }
        )
    )

    webbrowser.open(authorize_url)

    deadline = time.time() + timeout_seconds
    try:
        while time.time() < deadline:
            if server.auth_error:  # type: ignore[attr-defined]
                raise SpotifyAuthError(f"Falha na autorizacao: {server.auth_error}")  # type: ignore[attr-defined]
            if server.auth_code:  # type: ignore[attr-defined]
                return str(server.auth_code)  # type: ignore[attr-defined]
            time.sleep(0.2)
        raise SpotifyAuthError("Timeout esperando autorizacao do Spotify.")
    finally:
        server.shutdown()
        server.server_close()


class SpotifyClient:
    def __init__(self, config: SpotifyConfig) -> None:
        self.config = config

    def _request_token(self, data: dict[str, str]) -> dict[str, Any]:
        headers = {
            "Authorization": _basic_auth_header(self.config.client_id, self.config.client_secret),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        resp = requests.post(
            f"{SPOTIFY_ACCOUNTS_BASE}/api/token",
            data=data,
            headers=headers,
            timeout=30,
        )
        if resp.status_code >= 400:
            raise SpotifyAuthError(f"Falha ao obter token: {resp.status_code} {resp.text}")
        return resp.json()

    def _ensure_token(self) -> dict[str, Any]:
        token = _load_token(self.config.token_path)
        if token and _is_token_valid(token):
            return token

        if token and token.get("refresh_token"):
            refreshed = self._request_token(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": str(token["refresh_token"]),
                }
            )
            new_token = {
                **token,
                **refreshed,
                "expires_at": _now() + int(refreshed.get("expires_in", 3600)),
            }
            _save_token(self.config.token_path, new_token)
            return new_token

        code = _wait_for_auth_code(
            redirect_uri=self.config.redirect_uri,
            scopes=self.config.scopes,
            client_id=self.config.client_id,
        )
        exchanged = self._request_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.config.redirect_uri,
            }
        )
        new_token = {
            **exchanged,
            "expires_at": _now() + int(exchanged.get("expires_in", 3600)),
        }
        _save_token(self.config.token_path, new_token)
        return new_token

    def _api_headers(self) -> dict[str, str]:
        token = self._ensure_token()
        return {"Authorization": f"Bearer {token['access_token']}"}

    def _request_with_active_device(self, payload: dict[str, Any]) -> None:
        resp = requests.put(
            f"{SPOTIFY_API_BASE}/me/player/play",
            headers={**self._api_headers(), "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=30,
        )
        if resp.status_code == 404:
            devices = self.get_devices()
            if not devices:
                raise SpotifyApiError(
                    "Nenhum dispositivo do Spotify encontrado. Abra o Spotify no PC/celular e tente de novo."
                )
            self.transfer_playback(str(devices[0]["id"]))
            resp = requests.put(
                f"{SPOTIFY_API_BASE}/me/player/play",
                headers={**self._api_headers(), "Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=30,
            )

        if resp.status_code >= 400:
            raise SpotifyApiError(f"Falha ao tocar: {resp.status_code} {resp.text}")

    def search_track(self, query: str, *, market: str = "BR") -> dict[str, Any] | None:
        q = query.strip()
        if not q:
            return None

        resp = requests.get(
            f"{SPOTIFY_API_BASE}/search",
            headers=self._api_headers(),
            params={"q": q, "type": "track", "limit": 1, "market": market},
            timeout=30,
        )
        if resp.status_code >= 400:
            raise SpotifyApiError(f"Falha na busca: {resp.status_code} {resp.text}")
        data = resp.json()
        items = (((data.get("tracks") or {}).get("items")) or [])
        if not items:
            return None
        return items[0]

    def get_user_playlists(self) -> list[dict[str, Any]]:
        playlists: list[dict[str, Any]] = []
        offset = 0
        while True:
            resp = requests.get(
                f"{SPOTIFY_API_BASE}/me/playlists",
                headers=self._api_headers(),
                params={"limit": 50, "offset": offset},
                timeout=30,
            )
            if resp.status_code >= 400:
                raise SpotifyApiError(f"Falha ao listar playlists: {resp.status_code} {resp.text}")

            data = resp.json()
            items = list(data.get("items") or [])
            playlists.extend(item for item in items if isinstance(item, dict))
            if not data.get("next"):
                break
            offset += len(items)
            if not items:
                break
        return playlists

    def find_user_playlist(self, query: str) -> dict[str, Any] | None:
        normalized_query = _normalize_spotify_text(query)
        if not normalized_query:
            return None

        playlists = self.get_user_playlists()
        exact_match = None
        partial_match = None

        for playlist in playlists:
            name = str(playlist.get("name", "")).strip()
            normalized_name = _normalize_spotify_text(name)
            if not normalized_name:
                continue
            if normalized_name == normalized_query:
                exact_match = playlist
                break
            if normalized_query in normalized_name and partial_match is None:
                partial_match = playlist

        return exact_match or partial_match

    def get_devices(self) -> list[dict[str, Any]]:
        resp = requests.get(
            f"{SPOTIFY_API_BASE}/me/player/devices",
            headers=self._api_headers(),
            timeout=30,
        )
        if resp.status_code >= 400:
            raise SpotifyApiError(f"Falha ao listar devices: {resp.status_code} {resp.text}")
        return list((resp.json().get("devices") or []))

    def transfer_playback(self, device_id: str) -> None:
        resp = requests.put(
            f"{SPOTIFY_API_BASE}/me/player",
            headers={**self._api_headers(), "Content-Type": "application/json"},
            data=json.dumps({"device_ids": [device_id], "play": True}),
            timeout=30,
        )
        if resp.status_code >= 400:
            raise SpotifyApiError(f"Falha ao transferir playback: {resp.status_code} {resp.text}")

    def play_track(self, track_uri: str) -> None:
        self._request_with_active_device({"uris": [track_uri]})

    def play_context(self, context_uri: str) -> None:
        self._request_with_active_device({"context_uri": context_uri})


def _normalize_spotify_text(text: str) -> str:
    value = " ".join(str(text or "").strip().lower().split())
    return value
