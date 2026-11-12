#!/usr/bin/env python3
"""Avisa en Discord (por webhook) que salió una versión nueva.

Lee la versión de simpleplay.py y los títulos de las novedades del CHANGELOG.md, y arma un mensaje con
un embed. Por defecto SOLO MUESTRA una vista previa; para publicar de verdad hay que pasar --enviar.

La URL del webhook es un secreto (quien la tenga puede escribir en el canal): se lee de la variable
DISCORD_WEBHOOK_URL o del archivo ~/.config/tarab/discord-webhook, nunca va en el repo.

Uso:
    python3 tools/anunciar_discord.py                 # vista previa de la versión actual
    python3 tools/anunciar_discord.py --enviar        # publica en el canal
    python3 tools/anunciar_discord.py --enviar --mencion everyone --texto "Ya se puede bajar."
    python3 tools/anunciar_discord.py --version 1.5 --nombre "tarab player"
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "tarab"
ARCHIVO_URL = CONFIG / "discord-webhook"
ARCHIVO_ULTIMO = CONFIG / "ultimo-aviso"      # última versión anunciada: evita avisar dos veces
REPO = "https://github.com/cufadev/simpleplay"
COLOR = 0xFF4E01                              # el naranja de la marca
SECCIONES = {"Added": "Novedades", "Fixed": "Correcciones", "Changed": "Cambios"}
URL_VALIDA = re.compile(r"^https://(?:\w+\.)?discord(?:app)?\.com/api/(?:v\d+/)?webhooks/\d+/[\w-]+$")
LIMITE_CAMPO = 1024                           # tope de Discord por campo de un embed


def version_actual():
    m = re.search(r'^VERSION = "(.+?)"', (RAIZ / "simpleplay.py").read_text(encoding="utf-8"), re.M)
    if not m:
        sys.exit("no encuentro VERSION en simpleplay.py")
    return m.group(1)


def novedades(version):
    """{'Added': [títulos], 'Fixed': [...]} de la sección `## [version]` del CHANGELOG."""
    texto = (RAIZ / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", texto, re.M | re.S)
    if not m:
        sys.exit(f"no hay una sección [{version}] en CHANGELOG.md")
    secciones, actual = {}, None
    for linea in m.group(1).splitlines():
        if linea.startswith("### "):
            actual = linea[4:].strip()
        elif linea.startswith("- ") and actual:
            t = re.match(r"- \*\*(.+?)\*\*", linea)
            titulo = t.group(1) if t else re.split(r"(?<=[.!?])\s", linea[2:], maxsplit=1)[0]
            secciones.setdefault(actual, []).append(titulo.strip().rstrip(".:"))
    return secciones


def armar_campos(secciones):
    campos = []
    for clave, nombre in SECCIONES.items():
        items = secciones.get(clave)
        if not items:
            continue
        lineas, largo = [], 0
        for i, t in enumerate(items):
            linea = f"• {t}"
            if largo + len(linea) + 1 > LIMITE_CAMPO - 24:          # deja lugar para el "y N más"
                lineas.append(f"…y {len(items) - i} más (están en el changelog)")
                break
            lineas.append(linea)
            largo += len(linea) + 1
        campos.append({"name": nombre, "value": "\n".join(lineas), "inline": False})
    return campos


def armar_payload(nombre, version, secciones, texto, mencion):
    descripcion = texto or f"Ya está disponible la versión **{version}**."
    embed = {
        "title": f"{nombre} {version}",
        "url": f"{REPO}/releases/tag/v{version}",
        "description": descripcion,
        "color": COLOR,
        "fields": armar_campos(secciones),
        "footer": {"text": "Descargas en la página de releases"},
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    payload = {"embeds": [embed], "allowed_mentions": {"parse": []}}   # por defecto no menciona a nadie
    if mencion:
        payload["content"] = f"@{mencion}"
        payload["allowed_mentions"] = {"parse": [mencion]}
    return payload


def leer_url():
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url and ARCHIVO_URL.exists():
        modo = ARCHIVO_URL.stat().st_mode & 0o077
        if modo:
            print(f"aviso: {ARCHIVO_URL} lo pueden leer otros usuarios; conviene `chmod 600`", file=sys.stderr)
        url = ARCHIVO_URL.read_text(encoding="utf-8").strip()
    return url


def enviar(url, payload):
    """POST al webhook; reintenta una vez si Discord pide esperar (429). Devuelve el JSON de la respuesta."""
    req = urllib.request.Request(url + ("&" if "?" in url else "?") + "wait=true",
                                 data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "tarab-anuncios/1.0"})
    for intento in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and intento == 1:
                time.sleep(min(float(e.headers.get("Retry-After", 2)), 30))
                continue
            sys.exit(f"Discord respondió {e.code}: {e.read()[:200].decode(errors='replace')}")
        except urllib.error.URLError as e:
            sys.exit(f"no pude conectar: {e.reason}")


def main():
    ap = argparse.ArgumentParser(description="Avisa en Discord que salió una versión nueva.")
    ap.add_argument("--enviar", action="store_true", help="publicar de verdad (sin esto solo muestra la vista previa)")
    ap.add_argument("--version", help="versión a anunciar (por defecto la de simpleplay.py)")
    ap.add_argument("--nombre", default="simpleplay", help='nombre en el título (p. ej. "tarab player")')
    ap.add_argument("--texto", help="frase de apertura en lugar de la estándar")
    ap.add_argument("--mencion", choices=["everyone", "here"], help="menciona a todos / a los conectados")
    ap.add_argument("--forzar", action="store_true", help="anunciar aunque esa versión ya se haya anunciado")
    a = ap.parse_args()

    version = a.version or version_actual()
    payload = armar_payload(a.nombre, version, novedades(version), a.texto, a.mencion)

    if not a.enviar:
        print(f"VISTA PREVIA (no se envió nada). Para publicar: --enviar\n")
        e = payload["embeds"][0]
        print(f"  {e['title']}   {e['url']}\n  {e['description']}")
        for c in e["fields"]:
            print(f"\n  {c['name']} ({len(c['value'])}/{LIMITE_CAMPO} caracteres)\n" + "\n".join("    " + l for l in c["value"].splitlines()))
        if payload.get("content"):
            print(f"\n  menciona: {payload['content']}")
        print(f"\n  webhook: {'configurado' if leer_url() else 'FALTA (variable DISCORD_WEBHOOK_URL o ' + str(ARCHIVO_URL) + ')'}")
        return

    url = leer_url()
    if not url:
        sys.exit(f"falta la URL del webhook: variable DISCORD_WEBHOOK_URL o archivo {ARCHIVO_URL}")
    if not URL_VALIDA.match(url):
        sys.exit("esa URL no parece un webhook de Discord (https://discord.com/api/webhooks/ID/TOKEN)")
    if not a.forzar and ARCHIVO_ULTIMO.exists() and ARCHIVO_ULTIMO.read_text().strip() == version:
        sys.exit(f"la versión {version} ya se anunció; usá --forzar si querés repetirlo")

    r = enviar(url, payload)
    CONFIG.mkdir(parents=True, exist_ok=True)
    ARCHIVO_ULTIMO.write_text(version)
    print(f"publicado: mensaje {r.get('id')} en el canal {r.get('channel_id')}")


if __name__ == "__main__":
    main()
