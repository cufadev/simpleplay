#!/usr/bin/env python3
# simpleplay - quitar_duplicados.py
# Copyright (C) 2026 Facundo González <facundonic.gonzalez@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""Quita los temas repetidos de una carpeta y se queda siempre con la versión de mejor calidad de audio.

Es la línea de comandos del motor `limpieza.py` (ahí está explicado cómo se decide que dos archivos son el mismo tema:
por nombre y por la huella acústica, y por qué un remix o un en vivo no cuenta como repetido).

    python tools/quitar_duplicados.py CARPETA                muestra qué quitaría; NO toca nada
    python tools/quitar_duplicados.py CARPETA --aplicar      manda las copias peores a la papelera
    python tools/quitar_duplicados.py CARPETA --aplicar --definitivo   las borra para siempre (sin papelera)
    python tools/quitar_duplicados.py CARPETA --solo-nombre  sin huella acústica (más rápido, no hace falta fpcalc)
    python tools/quitar_duplicados.py CARPETA --solo-sonido  ignora los nombres: útil si las etiquetas son un desastre
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import limpieza  # noqa: E402
from limpieza import archivos_de, mejor_primero, quitar, revisar  # noqa: E402,F401  (los usa limpiar_biblioteca.py)


def mostrar(grupos):
    for g in grupos:
        print(f"\n  {g[0]['art'] or '?'} - {g[0]['tit'] or g[0]['ruta'].stem}")
        for k, d in enumerate(g):
            motivo = "" if k == 0 else f"  ({d.get('motivo', '')})"
            print(f"    {'SE QUEDA' if k == 0 else 'se quita':8s} {d['desc']:22s} {d['tam'] / 1048576:6.1f} MB  {d['ruta']}{motivo}")


def main():
    ap = argparse.ArgumentParser(description="Quita los temas repetidos de una carpeta y deja el de mejor calidad.")
    ap.add_argument("carpeta")
    ap.add_argument("--aplicar", action="store_true", help="quitar las copias peores (por defecto solo se muestran)")
    ap.add_argument("--definitivo", action="store_true", help="borrar para siempre en vez de mandar a la papelera")
    ap.add_argument("--si", action="store_true", help="no pedir confirmación")
    ap.add_argument("--solo-nombre", action="store_true", help="no usar la huella acústica")
    ap.add_argument("--solo-sonido", action="store_true", help="no mirar los nombres, solo la huella acústica")
    ap.add_argument("--sin-espectro", action="store_true", help="juzgar la calidad solo por la tasa de bits, sin medir el corte de frecuencias")
    ap.add_argument("--umbral", type=float, help=f"parecido mínimo de la huella, de 0 a 1 (por defecto {limpieza.UMBRAL_SONIDO})")
    a = ap.parse_args()
    carpeta = Path(a.carpeta).expanduser()
    if not carpeta.is_dir():
        print(f"No existe la carpeta: {carpeta}")
        return 2
    if a.umbral:
        limpieza.UMBRAL_SONIDO = a.umbral
    sonido = not a.solo_nombre
    if sonido and not limpieza.hay_fpcalc():
        print("Aviso: falta fpcalc (paquete libchromaprint-tools): se compara solo por nombre.")
    def progreso(hecho, total):
        print(f"\r  leyendo {hecho}/{total}  ", end="" if hecho < total else "\n", file=sys.stderr, flush=True)
    total, grupos, quitar_rutas = revisar(carpeta, sonido=sonido, nombre=not a.solo_sonido, calidad_real=not a.sin_espectro, progreso=progreso)
    print(f"{total} archivos de audio en {carpeta}")
    mostrar(grupos)
    print(f"\n{len(grupos)} tema(s) repetido(s): se quitarían {len(quitar_rutas)} archivo(s).")
    if not a.aplicar:
        if quitar_rutas:
            print("No se tocó nada. Para quitarlos, agregá --aplicar.")
        return 0
    if quitar_rutas and not a.si and sys.stdin.isatty():
        destino = "BORRAR PARA SIEMPRE" if a.definitivo else "mandar a la papelera"
        if input(f"¿{destino} {len(quitar_rutas)} archivo(s)? [s/N] ").strip().lower() not in ("s", "si", "sí", "y", "yes"):
            print("Cancelado, no se tocó nada.")
            return 0
    print(f"Listo: {quitar(quitar_rutas, a.definitivo)} archivo(s) " + ("borrados." if a.definitivo else "en la papelera."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
