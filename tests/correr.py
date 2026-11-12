#!/usr/bin/env python3
"""Corre todas las pruebas con un solo comando.

    python tests/generar_corpus.py            (una vez; necesita ffmpeg)
    python tests/correr.py                    (todas)
    python tests/correr.py motor limpieza     (solo esas)

Cada archivo test_*.py va en su propio proceso: cada uno prepara su entorno (carpeta de configuración temporal,
audio simulado, plataforma offscreen de Qt) antes de importar la aplicación, y juntos en un mismo proceso
(`unittest discover`) se pisan y Qt termina abortando.
"""
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).parent


def main(pedidos):
    archivos = sorted(AQUI.glob("test_*.py"))
    if pedidos:
        archivos = [a for a in archivos if any(p in a.stem for p in pedidos)]
    if not archivos:
        sys.exit("no hay pruebas con ese nombre")
    if not (AQUI / "corpus").is_dir():
        print("aviso: falta tests/corpus (python tests/generar_corpus.py); varias pruebas van a fallar\n", flush=True)
    fallaron = []
    for a in archivos:
        print(f"== {a.name}", flush=True)
        t = time.monotonic()
        r = subprocess.run([sys.executable, str(a)], cwd=AQUI.parent)
        print(f"   {'bien' if r.returncode == 0 else 'FALLÓ'} ({time.monotonic() - t:.0f} s)\n", flush=True)
        if r.returncode != 0:
            fallaron.append(a.name)
    if fallaron:
        sys.exit("fallaron: " + ", ".join(fallaron))
    print(f"todo bien ({len(archivos)} archivos)")


if __name__ == "__main__":
    main(sys.argv[1:])
