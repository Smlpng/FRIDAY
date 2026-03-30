from __future__ import annotations

import argparse
import json
import sys
import threading
import traceback
from typing import Iterable

from .assistant import FridayAssistant
from .gui import ParticleSphereGUI
from .voice import VoiceLoop


def _pick_microphone_index(
    *,
    preferred_index: int | None,
    names: list[str],
    avoid_substrings: Iterable[str],
    prefer_substrings: Iterable[str],
) -> int | None:
    if preferred_index is not None and 0 <= preferred_index < len(names):
        name = names[preferred_index].lower()
        if not any(bad in name for bad in avoid_substrings):
            return preferred_index

    def find_matching(all_substrings: list[str]) -> int | None:
        for idx, name in enumerate(names):
            lowered = name.lower()
            if any(bad in lowered for bad in avoid_substrings):
                continue
            if all(sub in lowered for sub in all_substrings):
                return idx
        return None

    prefer_list = [s.lower() for s in prefer_substrings]
    # tenta (microfone + realtek)
    idx = find_matching(["microfone", *prefer_list])
    if idx is not None:
        return idx

    # fallback: qualquer "microfone" válido
    idx = find_matching(["microfone"])
    if idx is not None:
        return idx

    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S com Gemini para Windows")
    parser.add_argument("--once", help="Executa um unico comando")
    parser.add_argument("--voice", action="store_true", help="Ativa o modo de voz")
    parser.add_argument(
        "--voice-debug",
        action="store_true",
        help="Mostra logs detalhados do modo de voz",
    )
    parser.add_argument(
        "--no-wake",
        action="store_true",
        help="Modo diagnostico: nao exige falar 'friday' antes do comando",
    )
    parser.add_argument("--gui", action="store_true", help="Abre a interface grafica")
    parser.add_argument(
        "--list-mics",
        action="store_true",
        help="Lista microfones disponiveis e seus indices",
    )
    parser.add_argument(
        "--mic-test",
        action="store_true",
        help="Testa o microfone configurado e imprime o que foi ouvido",
    )
    parser.add_argument(
        "--mic-index",
        type=int,
        default=None,
        help="Sobrescreve o microphone_device_index apenas para esta execucao",
    )
    parser.add_argument(
        "--energy-threshold",
        type=int,
        default=None,
        help="Define energy_threshold fixo (tenta melhorar quando nao entende o audio)",
    )
    parser.add_argument(
        "--ambient-adjust",
        type=int,
        default=None,
        help="Sobrescreve ambient_noise_adjust_seconds (use 0 para desativar)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Exibe a resposta completa em JSON",
    )
    return parser


def run_once(assistant: FridayAssistant, command: str, output_json: bool) -> int:
    response = assistant.handle(command)
    if output_json:
        print(json.dumps(response, ensure_ascii=False, indent=2))
    else:
        print(response["reply"])
        for result in response["results"]:
            status = "OK" if result["ok"] else "ERRO"
            print(f"[{status}] {result['result']}")
    return 0


def interactive_mode(assistant: FridayAssistant, output_json: bool) -> int:
    print("J.A.R.V.I.S pronto. Digite 'sair' para encerrar.")
    while True:
        try:
            command = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if command.lower() in {"sair", "exit", "quit"}:
            return 0

        if not command:
            continue

        run_once(assistant, command, output_json)


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Sem argumentos: abre GUI + voz por padrão.
    if (
        not args.once
        and not args.voice
        and not args.gui
        and not args.list_mics
        and not args.mic_test
    ):
        args.gui = True
        args.voice = True

    if args.list_mics:
        try:
            import speech_recognition as sr

            names = sr.Microphone.list_microphone_names()
            if not names:
                print("Nenhum microfone encontrado.")
                return 1

            for idx, name in enumerate(names):
                print(f"{idx}: {name}")
            return 0
        except Exception:
            print("Falha ao listar microfones:")
            traceback.print_exc()
            return 1

    assistant = FridayAssistant()

    def resolve_mic_index() -> int | None:
        override = int(args.mic_index) if args.mic_index is not None else None
        configured = assistant.settings.microphone_device_index
        try:
            import speech_recognition as sr

            names = sr.Microphone.list_microphone_names()
        except Exception:
            return override if override is not None else configured

        preferred_index = override if override is not None else configured
        avoid = [
            "mapeador",
            "output",
            "alto-falantes",
            "speakers",
            "hdmi",
            "driver",
            "mixagem",
            "stereo",
        ]
        # tenta priorizar realtek quando existir
        picked = _pick_microphone_index(
            preferred_index=preferred_index,
            names=names,
            prefer_substrings=["realtek"],
            avoid_substrings=avoid,
        )
        return picked if picked is not None else preferred_index

    if args.mic_test:
        try:
            import audioop
            import speech_recognition as sr

            mic_index = resolve_mic_index()
            names = sr.Microphone.list_microphone_names()
            mic_name = None
            if mic_index is not None and 0 <= mic_index < len(names):
                mic_name = names[mic_index]

            print(
                "Microfone selecionado:",
                (
                    f"{mic_index}: {mic_name}"
                    if mic_name
                    else (mic_index if mic_index is not None else "padrao")
                ),
            )
            print("Fale algo por alguns segundos...")

            recognizer = sr.Recognizer()

            source = sr.Microphone(device_index=mic_index)
            entered = False
            try:
                source.__enter__()
                entered = True

                if getattr(source, "stream", None) is None:
                    print(
                        "Nao consegui abrir o stream desse dispositivo. Tente outro indice (ex: 1, 9, 21)."
                    )
                    return 1

                recognizer.adjust_for_ambient_noise(
                    source,
                    duration=max(0, int(assistant.settings.ambient_noise_adjust_seconds)),
                )
                audio = recognizer.listen(
                    source,
                    timeout=8,
                    phrase_time_limit=max(1, int(assistant.settings.phrase_time_limit)),
                )
            finally:
                if entered:
                    try:
                        source.__exit__(None, None, None)
                    except Exception:
                        pass

            raw = audio.get_raw_data()
            rms = audioop.rms(raw, audio.sample_width)
            print(f"RMS (volume capturado): {rms}")

            try:
                text = recognizer.recognize_google(audio, language=assistant.settings.language)
                print("Transcricao:", text)
            except sr.UnknownValueError:
                print("Transcricao: (nao entendi o audio)")
            except sr.RequestError as exc:
                print("Transcricao: (falha no servico - verifique internet)")
                print("Detalhe:", exc)

            return 0
        except Exception as exc:
            print("Falha no teste de microfone:", exc)
            print("Dica: rode `python friday.py --list-mics` e teste com `--mic-index <numero>`. ")
            return 1

    speaking_event = threading.Event()

    def on_speaking(is_speaking: bool) -> None:
        if is_speaking:
            speaking_event.set()
        else:
            speaking_event.clear()

    def start_voice_loop() -> None:
        try:
            mic_index = resolve_mic_index()

            wake_words = assistant.settings.wake_words or [assistant.settings.friday_name]

            ambient_adjust = (
                int(args.ambient_adjust)
                if args.ambient_adjust is not None
                else assistant.settings.ambient_noise_adjust_seconds
            )
            energy_threshold = (
                int(args.energy_threshold)
                if args.energy_threshold is not None
                else assistant.settings.energy_threshold
            )
            voice_loop = VoiceLoop(
                wake_word=wake_words,
                language=assistant.settings.language,
                microphone_device_index=mic_index,
                phrase_time_limit=assistant.settings.phrase_time_limit,
                ambient_noise_adjust_seconds=ambient_adjust,
                energy_threshold=energy_threshold,
                on_speaking=on_speaking,
                debug=bool(args.voice_debug),
                require_wake_word=not bool(args.no_wake),
                speak_replies=True,
            )

            def handle_command(command: str) -> str:
                response = assistant.handle(command)
                reply = str(response.get("reply", "")).strip()
                if args.json:
                    print(json.dumps(response, ensure_ascii=False, indent=2))
                else:
                    print(f"FRIDAY: {reply}" if reply else "FRIDAY: (sem resposta)")
                return reply

            voice_loop.run(handle_command)
        except Exception:
            print("Falha no modo de voz:")
            traceback.print_exc()

    if args.gui:
        if args.voice:
            thread = threading.Thread(target=start_voice_loop, daemon=True)
            thread.start()

        gui = ParticleSphereGUI(
            particle_count=assistant.settings.gui_particle_count,
            speaking_event=speaking_event,
        )
        gui.run()
        return 0

    if args.voice:
        start_voice_loop()
        return 0

    if args.once:
        return run_once(assistant, args.once, args.json)

    return interactive_mode(assistant, args.json)


if __name__ == "__main__":
    sys.exit(main())