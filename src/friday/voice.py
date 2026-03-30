from __future__ import annotations

from collections.abc import Callable
import difflib
import queue
import re
import sys
import threading
import unicodedata
from typing import Any

import pyttsx3
import speech_recognition as sr


# SpeechRecognition depende do módulo "pyaudio".
# No Windows, é comum usar "PyAudioWPatch", que expõe o módulo "pyaudiowpatch".
# Para evitar erro "No module named 'pyaudio'", fazemos um alias em runtime.
try:  # pragma: no cover
    import pyaudio as _pyaudio  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    try:
        import pyaudiowpatch as _pyaudio  # type: ignore

        sys.modules.setdefault("pyaudio", _pyaudio)
    except ModuleNotFoundError:
        _pyaudio = None  # type: ignore


class VoiceLoop:
    def __init__(
        self,
        wake_word: str | list[str],
        language: str,
        *,
        microphone_device_index: int | None = None,
        phrase_time_limit: int = 6,
        ambient_noise_adjust_seconds: int = 1,
        energy_threshold: int | None = None,
        on_speaking: Callable[[bool], Any] | None = None,
        debug: bool = False,
        require_wake_word: bool = True,
        speak_replies: bool = True,
    ) -> None:
        self.wake_words = _coerce_wake_words(wake_word)
        self.language = language
        self.microphone_device_index = microphone_device_index
        self.phrase_time_limit = phrase_time_limit
        self.ambient_noise_adjust_seconds = ambient_noise_adjust_seconds
        self.energy_threshold = energy_threshold
        self.on_speaking = on_speaking
        self.debug = debug
        self.require_wake_word = require_wake_word
        self.speak_replies = speak_replies
        self.recognizer = sr.Recognizer()
        if self.energy_threshold is not None:
            self.recognizer.dynamic_energy_threshold = False
            self.recognizer.energy_threshold = int(self.energy_threshold)

        self._tts_queue: queue.Queue[str] = queue.Queue()
        self._tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self._tts_thread.start()

    def _tts_worker(self) -> None:
        engine = None
        try:
            engine = pyttsx3.init()
        except Exception as exc:  # pragma: no cover
            if self.debug:
                print(f"[tts] falha ao inicializar engine: {exc}")
            return

        while True:
            text = self._tts_queue.get()
            try:
                if self.on_speaking:
                    self.on_speaking(True)
                if self.debug:
                    print(f"[tts] falando: {text}")
                engine.say(text)
                engine.runAndWait()
            except Exception as exc:  # pragma: no cover
                if self.debug:
                    print(f"[tts] falha ao falar: {exc}")
                try:
                    engine.stop()
                except Exception:
                    pass
            finally:
                if self.on_speaking:
                    self.on_speaking(False)

    def speak(self, text: str) -> None:
        if not text:
            return
        self._tts_queue.put(text)

    def run(self, handler: Callable[[str], str]) -> None:
        mic_index = self.microphone_device_index
        try:
            mic_names = sr.Microphone.list_microphone_names()
            if mic_index is None:
                print("Microfone: padrao do Windows")
            elif 0 <= mic_index < len(mic_names):
                print(f"Microfone: {mic_index}: {mic_names[mic_index]}")
            else:
                print(f"Microfone: indice {mic_index} (fora da lista)")
        except Exception:
            pass

        try:
            mic = sr.Microphone(device_index=mic_index)
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "Falha ao inicializar o microfone. Se aparecer erro de PyAudio, instale 'PyAudioWPatch'."
            ) from exc

        try:
            with mic as source:
                adjust_seconds = max(0, int(self.ambient_noise_adjust_seconds))
                if adjust_seconds > 0:
                    self.recognizer.adjust_for_ambient_noise(source, duration=adjust_seconds)
                self.speak("Modo de voz iniciado.")

                while True:
                    print("Aguardando wake word...")
                    try:
                        if self.debug:
                            print("Ouvindo microfone...")
                        audio = self.recognizer.listen(
                            source,
                            timeout=None,
                            phrase_time_limit=max(1, int(self.phrase_time_limit)),
                        )
                        if self.debug:
                            print("Audio capturado, transcrevendo...")
                        transcript = self.recognizer.recognize_google(
                            audio,
                            language=self.language,
                        )
                    except sr.UnknownValueError:
                        if self.debug:
                            print("Nao entendi o audio.")
                        continue
                    except sr.RequestError:
                        self.speak(
                            "Nao consegui usar o servico de reconhecimento agora. Verifique sua internet."
                        )
                        continue
                    except KeyboardInterrupt:
                        self.speak("Encerrando modo de voz.")
                        return

                    phrase = transcript.strip()
                    print(f"Ouvido: {phrase}")
                    lowered = phrase.lower()

                    if self.require_wake_word:
                        if not _contains_any_wake_word(lowered, self.wake_words):
                            if self.debug:
                                print(f"Wake word(s) {self.wake_words} not detected")
                            continue
                        command = _strip_wake_prefix_any(lowered, self.wake_words)
                    else:
                        command = lowered.strip(" ,")
                    if not command:
                        self.speak("Pode falar.")
                        continue

                    reply = handler(command)
                    if self.speak_replies and reply:
                        self.speak(reply)
        except AttributeError as exc:  # pragma: no cover
            raise RuntimeError(
                "Nao consegui abrir o stream do microfone. Tente outro indice de microfone ou instale 'PyAudioWPatch'."
            ) from exc


def _coerce_wake_words(wake_word: str | list[str]) -> list[str]:
    if isinstance(wake_word, list):
        words = [w.strip().lower() for w in wake_word if isinstance(w, str) and w.strip()]
    else:
        words = [str(wake_word or "friday").strip().lower()]

    seen: set[str] = set()
    unique: list[str] = []
    for w in words:
        if w not in seen:
            unique.append(w)
            seen.add(w)
    return unique


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^0-9a-zA-Z\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _contains_wake_word(phrase: str, wake_word: str) -> bool:
    if not wake_word:
        return True

    p = _norm(phrase)
    w = _norm(wake_word)

    if not w:
        return True

    if w in p:
        return True

    # compara também sem espacos (ex: "f r i d a y" => "friday")
    p_compact = p.replace(" ", "")
    w_compact = w.replace(" ", "")
    if w_compact and w_compact in p_compact:
        return True

    tokens = [t for t in re.split(r"\s+", p) if t]

    # Se veio soletrado ("f r i d a y"), junta e compara
    letter_tokens = [t for t in tokens if len(t) == 1 and t.isalpha()]
    if len(letter_tokens) >= min(3, len(w_compact)):
        spelled = "".join(letter_tokens)
        if _similar(spelled, w_compact) >= 0.85:
            return True

    # tenta encontrar alguma palavra próxima (ex: "javis", "fridai")
    for token in tokens[:5]:
        if _similar(token, w) >= 0.78 or _similar(token, w_compact) >= 0.78:
            return True
    return False


def _contains_any_wake_word(phrase: str, wake_words: list[str]) -> bool:
    return any(_contains_wake_word(phrase, w) for w in wake_words)


def _strip_wake_prefix(original_text: str, wake_word: str) -> str:
    text = original_text.strip()
    if not text:
        return text

    wake_word = (wake_word or "").strip()
    if not wake_word:
        return text

    ww = re.escape(wake_word)

    raw_letters = list(wake_word.replace(" ", "").replace("-", ""))
    patterns = [ww]
    if raw_letters:
        pattern_letters = r"[\s\W_]*".join(map(re.escape, raw_letters))
        patterns.append(pattern_letters)

    pattern = r"^\s*(?:" + r"|".join(patterns) + r")\s*[:,-]?\s*"
    stripped = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return stripped.strip()


def _strip_wake_prefix_any(original_text: str, wake_words: list[str]) -> str:
    text = original_text.strip()
    if not text:
        return text

    best: str | None = None
    best_len = -1
    for w in wake_words:
        candidate = _strip_wake_prefix(text, w)
        if candidate != text and (len(text) - len(candidate)) > best_len:
            best = candidate
            best_len = len(text) - len(candidate)

    if best is not None:
        return best.strip()

    # Fallback: se detectou por fuzzy/compact, mas nao bateu o regex
    parts = text.split(maxsplit=1)
    return (parts[1] if len(parts) == 2 else "").strip()
