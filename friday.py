from __future__ import annotations

import sys
from pathlib import Path

import runpy


ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"

# Em alguns modos (ex: VS Code debug), o sys.path pode já conter SRC_DIR,
# mas não necessariamente na primeira posição. Se o diretório do projeto vier
# antes, o arquivo friday.py pode ser resolvido como módulo "friday" e quebrar
# a importação do pacote real em src/friday.
src_str = str(SRC_DIR)
sys.path[:] = [p for p in sys.path if p != src_str]
sys.path.insert(0, src_str)


if __name__ == "__main__":
    runpy.run_module("friday.main", run_name="__main__")