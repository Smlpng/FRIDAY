from __future__ import annotations

import json
from typing import Any

import requests


SYSTEM_INSTRUCTION = """
Voce e o cerebro de um assistente para Windows chamado FRIDAY.
Seu trabalho e transformar pedidos do usuario em um JSON com a estrutura:
{
  "reply": "resposta curta em portugues",
  "actions": [
    {
                                                "type": "open_app|search_web|media_control|open_url|type_text|hotkey|wait|spotify_search_play|spotify_api_play|youtube_search_play",
      "params": {}
    }
  ]
}

Regras:
- Responda somente JSON valido.
- Nao use markdown.
- Use apenas os tipos de acao permitidos.
- O input pode conter recent_history e memory_slots com contexto recente; use esse contexto para resolver referencias como "essa musica", "isso", "aquilo" e "de novo" quando o antecedente estiver claro.
- Para pesquisas web, prefira o tipo search_web com campos query e browser.
- Para abrir apps ou jogos, use open_app com o nome do app em params.name.
- Para musica, use media_control com params.action sendo play_pause, next, previous, mute, volume_up ou volume_down.
- Para tocar uma musica no Spotify (ex: "toque a musica X no spotify"), use spotify_api_play com params.query e params.target="track".
- Para tocar uma playlist do usuario no Spotify (ex: "toque minha playlist treino"), use spotify_api_play com params.query e params.target="playlist".
- Para buscar/abrir no Spotify sem garantir playback, use spotify_search_play com params.query.
- Para buscar e tentar tocar no YouTube, use youtube_search_play com params.query.
- Para abrir uma busca do YouTube, use open_url com uma URL completa do YouTube em params.url.
- Para atalhos de teclado, use hotkey com params.keys como lista.
- Se nenhuma acao for necessaria, retorne actions vazia.
- A resposta em reply deve ser curta e objetiva.
""".strip()


class GeminiError(RuntimeError):
    pass


class GeminiPlanner:
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def plan(
        self,
        user_request: str,
        apps_catalog: dict[str, Any],
        conversation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise GeminiError("GEMINI_API_KEY nao configurada.")

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )

        payload = {
            "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "contents": [
                {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "request": user_request,
                                    "recent_history": (conversation_context or {}).get("recent_history", []),
                                    "memory_slots": (conversation_context or {}).get("slots", {}),
                                    "known_apps": sorted(apps_catalog.get("apps", {}).keys()),
                                    "aliases": apps_catalog.get("aliases", {}),
                                },
                                ensure_ascii=False,
                            )
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }

        response = requests.post(url, json=payload, timeout=30)
        if response.status_code >= 400:
            raise GeminiError(
                f"Falha ao chamar Gemini ({response.status_code}): {response.text}"
            )

        data = response.json()
        text = self._extract_text(data)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as error:
            raise GeminiError(f"Gemini retornou JSON invalido: {text}") from error

        if not isinstance(parsed, dict):
            raise GeminiError("Gemini nao retornou um objeto JSON.")

        parsed.setdefault("reply", "Certo.")
        parsed.setdefault("actions", [])
        return parsed

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        candidates = data.get("candidates", [])
        if not candidates:
            raise GeminiError("Gemini nao retornou candidates.")

        parts = candidates[0].get("content", {}).get("parts", [])
        text_parts = [part.get("text", "") for part in parts if "text" in part]
        text = "".join(text_parts).strip()
        if not text:
            raise GeminiError("Gemini retornou resposta vazia.")
        return text
