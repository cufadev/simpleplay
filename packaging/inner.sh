#!/bin/bash
# Corre DENTRO del contenedor (Ubuntu 22.04, glibc 2.35). Genera /out/simpleplay (carpeta PyInstaller).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# libs de Qt/xcb que PyInstaller copia al paquete, para no depender de lo que traiga la distro destino
apt-get install -y -qq --no-install-recommends \
    python3 python3-venv python3-pip libpython3.10 binutils file \
    libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
    libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 libxkbcommon-x11-0 \
    libxkbcommon0 libegl1 libgl1 libfontconfig1 libdbus-1-3 libglib2.0-0 >/dev/null
# Python 3.13 (el mismo del desarrollo) vía uv: con el 3.10 de Ubuntu 22.04 la app se
# cerraba a los segundos ("deallocating None"); desde 3.12 None es inmortal.
# Se sigue compilando sobre glibc 2.35, que es lo que fija la compatibilidad.
python3 -m venv /tmp/uvenv
/tmp/uvenv/bin/pip install -q uv
/tmp/uvenv/bin/uv venv -q --python 3.13 /tmp/venv
/tmp/uvenv/bin/uv pip install -q --python /tmp/venv/bin/python \
    pyinstaller PySide6 pygame mutagen numpy miniaudio
/tmp/venv/bin/python --version
cd /src
/tmp/venv/bin/pyinstaller --noconfirm --clean --onedir --name simpleplay \
    --distpath /out --workpath /tmp/work --specpath /tmp/work \
    --add-data "/src/icon/simpleplay-256.png:icon" \
    --exclude-module tkinter --exclude-module PIL \
    --exclude-module PySide6.QtNetwork --exclude-module PySide6.QtSvg \
    simpleplay.py
echo "paquete listo: $(du -sh /out/simpleplay | cut -f1)"
# el contenedor corre como root: devolver lo generado al usuario del host
chown -R "$HOST_UID:$HOST_GID" /out
