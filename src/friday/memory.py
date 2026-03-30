from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class ConversationMemory:
    def __init__(
        self,
        path: Path,
        *,
        ttl_minutes: int = 180,
        max_messages: int = 24,
    ) -> None:
        self.path = path
        self.ttl_seconds = max(60, int(ttl_minutes)) * 60
        self.max_messages = max(2, int(max_messages))
        self._history: list[dict[str, Any]] = []
        self._slots: dict[str, dict[str, Any]] = {}
        self._load()

    def build_context(self) -> dict[str, Any]:
        self._prune()
        return {
            "recent_history": [
                {
                    "role": item.get("role", "user"),
                    "content": item.get("content", ""),
                }
                for item in self._history
            ],
            "slots": {
                key: str(value.get("value", ""))
                for key, value in self._slots.items()
                if str(value.get("value", "")).strip()
            },
        }

    def remember_turn(
        self,
        *,
        user_request: str,
        assistant_reply: str,
        slots: dict[str, str] | None = None,
    ) -> None:
        now = time.time()
        if user_request.strip():
            self._history.append(
                {"role": "user", "content": user_request.strip(), "timestamp": now}
            )
        if assistant_reply.strip():
            self._history.append(
                {"role": "assistant", "content": assistant_reply.strip(), "timestamp": now}
            )

        for key, value in (slots or {}).items():
            normalized = str(value or "").strip()
            if not normalized:
                continue
            self._slots[key] = {"value": normalized, "updated_at": now}

        self._prune()
        self._save()

    def _load(self) -> None:
        if not self.path.exists():
            return

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        history = data.get("history", [])
        slots = data.get("slots", {})
        if isinstance(history, list):
            self._history = [item for item in history if isinstance(item, dict)]
        if isinstance(slots, dict):
            self._slots = {
                str(key): value
                for key, value in slots.items()
                if isinstance(value, dict)
            }
        self._prune()

    def _save(self) -> None:
        payload = {
            "history": self._history,
            "slots": self._slots,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _prune(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        self._history = [
            item
            for item in self._history
            if float(item.get("timestamp", 0)) >= cutoff and str(item.get("content", "")).strip()
        ]
        if len(self._history) > self.max_messages:
            self._history = self._history[-self.max_messages :]

        self._slots = {
            key: value
            for key, value in self._slots.items()
            if float(value.get("updated_at", 0)) >= cutoff and str(value.get("value", "")).strip()
        }