from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus

from .actions import ActionExecutionError, WindowsActions
from .config import Settings, load_apps_registry, load_settings
from .gemini_client import GeminiError, GeminiPlanner
from .memory import ConversationMemory


class FridayAssistant:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self.registry = load_apps_registry(self.settings.apps_path)
        self.actions = WindowsActions(self.registry, self.settings)
        self.memory = ConversationMemory(
            self.settings.memory_path,
            ttl_minutes=self.settings.memory_ttl_minutes,
            max_messages=self.settings.memory_max_messages,
        )
        self.planner = GeminiPlanner(
            api_key=self.settings.gemini_api_key,
            model=self.settings.gemini_model,
        )

    def handle(self, user_request: str) -> dict[str, Any]:
        request = user_request.strip()
        if not request:
            return {
                "reply": "Nenhum comando recebido.",
                "actions": [],
                "results": [],
            }

        context = self.memory.build_context()
        plan = self._build_plan(request, context)
        results = []
        for action in plan.get("actions", []):
            try:
                result = self.actions.execute(action)
                results.append({"ok": True, "action": action, "result": result})
            except ActionExecutionError as error:
                results.append({"ok": False, "action": action, "result": str(error)})

        reply = plan.get("reply", "Certo.")
        self.memory.remember_turn(
            user_request=request,
            assistant_reply=reply,
            slots=self._extract_memory_slots(request, plan),
        )

        return {
            "reply": reply,
            "actions": plan.get("actions", []),
            "results": results,
        }

    def _build_plan(
        self,
        user_request: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            plan = self.planner.plan(user_request, self.registry, context)

            # Se o modelo não gerar ações, mas o texto parece comando de mídia,
            # aplica fallback local para garantir play/pause/next/etc.
            if not plan.get("actions") and _looks_like_media_command(user_request):
                return self._fallback_plan(user_request, context)

            if not plan.get("actions") and _looks_like_music_request(user_request):
                return self._fallback_plan(user_request, context)

            reply = str(plan.get("reply", "")).lower()
            if (
                not plan.get("actions")
                and ("nao consegui" in reply or "não consegui" in reply)
                and (_looks_like_media_command(user_request) or _looks_like_music_request(user_request))
            ):
                return self._fallback_plan(user_request, context)

            return plan
        except GeminiError:
            return self._fallback_plan(user_request, context)

    def _fallback_plan(
        self,
        user_request: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = user_request.strip().lower()
        remembered_playlist = _resolve_playlist_reference(request, context)
        remembered_music = _resolve_music_reference(request, context)

        if remembered_playlist and _looks_like_playlist_request(request):
            return {
                "reply": f"Tocando a playlist {remembered_playlist} no Spotify.",
                "actions": [
                    {
                        "type": "spotify_api_play",
                        "params": {"query": remembered_playlist, "target": "playlist"},
                    },
                ],
            }

        playlist_query = _extract_playlist_query(request)
        if playlist_query:
            return {
                "reply": f"Tocando a playlist {playlist_query} no Spotify.",
                "actions": [
                    {
                        "type": "spotify_api_play",
                        "params": {"query": playlist_query, "target": "playlist"},
                    },
                ],
            }

        if remembered_music and _looks_like_music_request(request):
            platform = _get_context_slot(context, "last_media_platform")
            if platform == "youtube":
                return {
                    "reply": f"Tocando {remembered_music} no YouTube.",
                    "actions": [
                        {
                            "type": "youtube_search_play",
                            "params": {
                                "query": remembered_music,
                                "browser": "chrome",
                            },
                        }
                    ],
                }

            use_api = bool(
                (self.settings.spotify_client_id or "").strip()
                and (self.settings.spotify_client_secret or "").strip()
            )
            return {
                "reply": f"Retomando a musica {remembered_music}.",
                "actions": [
                    {
                        "type": "spotify_api_play" if use_api else "spotify_search_play",
                        "params": {"query": remembered_music},
                    },
                ],
            }

        # Pedido de música (Spotify)
        # Exemplos: "pesquisa música Monster da banda Skillet", "toque a música Monster do Skillet"
        music_query = _extract_music_query(request)
        if music_query:
            if "youtube" in request:
                return {
                    "reply": f"Tocando {music_query} no YouTube.",
                    "actions": [
                        {
                            "type": "youtube_search_play",
                            "params": {
                                "query": music_query,
                                "browser": "chrome",
                            },
                        }
                    ],
                }

            use_api = bool(
                (self.settings.spotify_client_id or "").strip()
                and (self.settings.spotify_client_secret or "").strip()
            )
            return {
                "reply": f"Buscando no Spotify: {music_query}.",
                "actions": [
                    {
                        "type": "spotify_api_play" if use_api else "spotify_search_play",
                        "params": {"query": music_query},
                    },
                ],
            }

        media_keywords = {
            "pause": "play_pause",
            "pausa": "play_pause",
            "pausar": "play_pause",
            "parar": "play_pause",
            "play": "play_pause",
            "dar play": "play_pause",
            "de play": "play_pause",
            "dê play": "play_pause",
            "tocar": "play_pause",
            "toca": "play_pause",
            "toque": "play_pause",
            "continuar": "play_pause",
            "retomar": "play_pause",
            "retome": "play_pause",
            "proxima": "next",
            "próxima": "next",
            "pular": "next",
            "anterior": "previous",
            "voltar musica": "previous",
            "mutar": "mute",
        }
        for keyword, action in media_keywords.items():
            if keyword in request:
                return {
                    "reply": "Executando controle de mídia.",
                    "actions": [{"type": "media_control", "params": {"action": action}}],
                }

        search_patterns = [
            r"pesquise (?:sobre )?(?P<query>.+?) no chrome$",
            r"procure (?:sobre )?(?P<query>.+?) no chrome$",
            r"pesquise (?:sobre )?(?P<query>.+)$",
        ]
        for pattern in search_patterns:
            match = re.search(pattern, request)
            if match:
                return {
                    "reply": "Abrindo a pesquisa.",
                    "actions": [
                        {
                            "type": "search_web",
                            "params": {
                                "query": match.group("query").strip(),
                                "browser": "chrome",
                            },
                        }
                    ],
                }

        open_match = re.search(r"(?:abra|abrir|abre) (?:o |a )?(?P<app>.+)$", request)
        if open_match:
            return {
                "reply": "Tentando abrir o aplicativo solicitado.",
                "actions": [
                    {
                        "type": "open_app",
                        "params": {"name": open_match.group("app").strip()},
                    }
                ],
            }

        return {
            "reply": "Nao consegui montar uma automacao com seguranca para esse pedido.",
            "actions": [],
        }

    def _extract_memory_slots(
        self,
        user_request: str,
        plan: dict[str, Any],
    ) -> dict[str, str]:
        slots: dict[str, str] = {}
        request = user_request.strip()
        lowered = request.lower()
        direct_music_query = _extract_music_query(lowered)
        direct_playlist_query = _extract_playlist_query(lowered)

        if direct_playlist_query:
            slots["last_playlist_query"] = direct_playlist_query
            slots["last_media_query"] = direct_playlist_query
            slots["last_spotify_target"] = "playlist"

        if direct_music_query:
            slots["last_music_query"] = direct_music_query
            slots["last_media_query"] = direct_music_query
            slots["last_spotify_target"] = "track"

        if "youtube" in lowered:
            slots["last_media_platform"] = "youtube"
        elif direct_music_query or direct_playlist_query:
            slots["last_media_platform"] = "spotify"

        for action in plan.get("actions", []):
            if not isinstance(action, dict):
                continue
            action_type = str(action.get("type", "")).strip()
            params = action.get("params", {})
            if not isinstance(params, dict):
                continue

            if action_type in {"spotify_search_play", "spotify_api_play"}:
                query = str(params.get("query", "")).strip()
                target = str(params.get("target", "track")).strip().lower()
                if query:
                    slots["last_media_query"] = query
                    slots["last_media_platform"] = "spotify"
                    slots["last_spotify_target"] = target
                    if target == "playlist":
                        slots["last_playlist_query"] = query
                    else:
                        slots["last_music_query"] = query
            elif action_type == "search_web":
                query = str(params.get("query", "")).strip()
                if query:
                    slots["last_search_query"] = query
            elif action_type == "open_url":
                url = str(params.get("url", "")).strip()
                youtube_query = _extract_youtube_query_from_url(url)
                if youtube_query:
                    slots["last_music_query"] = youtube_query
                    slots["last_media_query"] = youtube_query
                    slots["last_media_platform"] = "youtube"
            elif action_type == "youtube_search_play":
                query = str(params.get("query", "")).strip()
                if query:
                    slots["last_music_query"] = query
                    slots["last_media_query"] = query
                    slots["last_media_platform"] = "youtube"

        return slots


def _looks_like_media_command(text: str) -> bool:
    t = text.strip().lower()
    triggers = [
        "pause",
        "pausa",
        "pausar",
        "play",
        "tocar",
        "toque",
        "continuar",
        "retomar",
        "proxima",
        "próxima",
        "pular",
        "anterior",
        "voltar",
        "mute",
        "mutar",
        "volume",
        "spotify",
        "música",
        "musica",
    ]
    return any(k in t for k in triggers)


def _looks_like_music_request(text: str) -> bool:
    t = text.strip().lower()
    return (("musica" in t or "música" in t) and (
        "spotify" in t
        or "banda" in t
        or "toque" in t
        or "toca" in t
        or "tocar" in t
        or "pesquisa" in t
        or "pesquise" in t
        or "procure" in t
    )) or any(
        marker in t
        for marker in [
            "essa musica",
            "essa música",
            "essa canção",
            "essa cancao",
            "essa faixa",
        ]
    )


def _looks_like_playlist_request(text: str) -> bool:
    t = text.strip().lower()
    return any(
        marker in t
        for marker in [
            "playlist",
            "essa playlist",
            "minha playlist",
        ]
    ) and any(
        marker in t
        for marker in [
            "spotify",
            "toque",
            "toca",
            "tocar",
            "abra",
            "abrir",
            "abre",
        ]
    )


def _extract_music_query(request_lower: str) -> str | None:
    # Normaliza alguns prefixos comuns
    text = request_lower.strip()
    text = re.sub(r"^sexta[- ]feira\s+", "", text)
    text = re.sub(r"^friday\s+", "", text)

    patterns = [
        r"(?:pesquisa|pesquise|procure)\s+(?:musica|música)\s+(?P<song>.+?)\s+da\s+banda\s+(?P<artist>.+)$",
        r"(?:pesquisa|pesquise|procure)\s+no\s+youtube\s+a?\s*(?:musica|música)\s+(?P<song>.+?)\s+da\s+banda\s+(?P<artist>.+)$",
        r"(?:pesquisa|pesquise|procure)\s+no\s+youtube\s+a?\s*(?:musica|música)\s+(?P<song>.+?)\s+do\s+(?P<artist>.+)$",
        r"(?:toque|toca|tocar)\s+a?\s*(?:musica|música)\s+(?P<song>.+?)\s+da\s+banda\s+(?P<artist>.+)$",
        r"(?:toque|toca|tocar)\s+a?\s*(?:musica|música)\s+(?P<song>.+?)\s+do\s+(?P<artist>.+)$",
        r"(?:toque|toca|tocar)\s+(?P<song>.+?)\s+no\s+spotify$",
        r"(?:pesquisa|pesquise|procure)\s+(?P<song>.+?)\s+no\s+spotify$",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        song = (m.groupdict().get("song") or "").strip(" ,")
        artist = (m.groupdict().get("artist") or "").strip(" ,")

        # remove sufixos comuns que grudam na captura
        song = re.sub(r"\s+no\s+spotify$", "", song).strip(" ,")
        artist = re.sub(r"\s+no\s+spotify$", "", artist).strip(" ,")
        if song and artist:
            return f"{song} {artist}".strip()
        if song:
            return song

    # fallback super simples: se a frase tem 'musica', tenta pegar tudo depois
    if "musica" in text or "música" in text:
        m2 = re.search(r"(?:musica|música)\s+(?P<q>.+)$", text)
        if m2:
            q = m2.group("q").strip(" ,")
            # remove "no spotify" se existir
            q = re.sub(r"\s+no\s+spotify$", "", q).strip()
            q = re.sub(r"\s+no\s+youtube$", "", q).strip()
            return q if q else None
    return None


def _extract_playlist_query(request_lower: str) -> str | None:
    text = request_lower.strip()
    text = re.sub(r"^sexta[- ]feira\s+", "", text)
    text = re.sub(r"^friday\s+", "", text)

    patterns = [
        r"(?:toque|toca|tocar|abra|abre|abrir)\s+a?\s*(?:minha\s+)?playlist\s+(?P<playlist>.+?)(?:\s+no\s+spotify)?$",
        r"(?:toque|toca|tocar)\s+a\s+playlist\s+(?P<playlist>.+?)(?:\s+do\s+spotify)?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        playlist = (match.group("playlist") or "").strip(" ,")
        playlist = re.sub(r"\s+por\s+gentileza$", "", playlist).strip(" ,")
        return playlist or None
    return None


def _resolve_music_reference(
    request_lower: str,
    context: dict[str, Any] | None,
) -> str | None:
    if not any(
        marker in request_lower
        for marker in [
            "essa musica",
            "essa música",
            "essa canção",
            "essa cancao",
            "essa faixa",
            "ela",
        ]
    ):
        return None
    return _get_context_slot(context, "last_music_query") or _get_context_slot(
        context, "last_media_query"
    )


def _resolve_playlist_reference(
    request_lower: str,
    context: dict[str, Any] | None,
) -> str | None:
    if "essa playlist" not in request_lower:
        return None
    return _get_context_slot(context, "last_playlist_query")


def _get_context_slot(context: dict[str, Any] | None, key: str) -> str | None:
    slots = context.get("slots", {}) if isinstance(context, dict) else {}
    if not isinstance(slots, dict):
        return None
    value = str(slots.get(key, "")).strip()
    return value or None


def _extract_youtube_query_from_url(url: str) -> str | None:
    match = re.search(r"[?&]search_query=([^&]+)", url)
    if not match:
        return None
    return match.group(1).replace("+", " ").strip()
