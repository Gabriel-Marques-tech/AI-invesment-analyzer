"""Helper para rodar módulos do src/ sem precisar de `pip install -e .`.

Uso:
    python run.py graph.diagnosticar_banco
    python run.py collectors.cvm_collector
    python run.py graph.limpar_dados --apenas-fake
"""
import runpy
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(_SRC))

if len(sys.argv) < 2:
    print("Uso: python run.py <modulo> [args...]", file=sys.stderr)
    print("Ex.:  python run.py graph.diagnosticar_banco", file=sys.stderr)
    sys.exit(2)

modulo = sys.argv[1]
# Repassa o restante dos args como se fosse `python -m modulo ...`
sys.argv = [modulo] + sys.argv[2:]
runpy.run_module(modulo, run_name="__main__")
