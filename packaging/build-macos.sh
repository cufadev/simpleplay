#!/bin/bash
# simpleplay - arma la versión de macOS en una Mac (o en un runner de GitHub Actions con macOS).
# Resultado: dist/simpleplay.app  y  dist/simpleplay-<versión>-macos-<intel|apple-silicon>.dmg
#
# Hace falta Python 3.13 (python.org o `brew install python@3.13`) y las herramientas de línea de comandos de Xcode
# (`xcode-select --install`). Se corre desde cualquier carpeta:   bash packaging/build-macos.sh
#
# El .dmg queda sin firmar por Apple (solo firma "ad-hoc", que hace falta para que corra en Apple Silicon): macOS
# avisa la primera vez y hay que abrirlo desde Ajustes > Privacidad y seguridad > "Abrir igualmente".
set -euo pipefail
cd "$(dirname "$0")/.."

VER=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' simpleplay.py)
case "$(uname -m)" in
    arm64)  ARQ=apple-silicon ;;
    x86_64) ARQ=intel ;;
    *) echo "arquitectura desconocida: $(uname -m)"; exit 1 ;;
esac
PY=${PYTHON:-python3.13}
command -v "$PY" >/dev/null || PY=python3
echo "simpleplay $VER para macOS ($ARQ) con $($PY --version)"

if [ ! -d .venv-build ]; then
    "$PY" -m venv .venv-build
fi
.venv-build/bin/python -m pip install --quiet --upgrade pip
.venv-build/bin/pip install --quiet -r requirements.txt pyinstaller

rm -rf dist/simpleplay.app dist/simpleplay build/simpleplay
.venv-build/bin/pyinstaller --noconfirm --clean --onedir --windowed --name simpleplay \
    --icon icon/simpleplay.icns --add-data "icon/simpleplay-256.png:icon" \
    --osx-bundle-identifier xyz.cufadev.simpleplay \
    --hidden-import miniaudio --hidden-import _cffi_backend --collect-data certifi \
    --exclude-module tkinter --exclude-module PIL \
    --exclude-module PySide6.QtNetwork --exclude-module PySide6.QtSvg \
    simpleplay.py

APP=dist/simpleplay.app
PLIST=$APP/Contents/Info.plist
set_plist() {   # clave tipo valor: la cambia si existe y la agrega si no
    /usr/libexec/PlistBuddy -c "Set :$1 $3" "$PLIST" 2>/dev/null || /usr/libexec/PlistBuddy -c "Add :$1 $2 $3" "$PLIST"
}
set_plist CFBundleShortVersionString string "$VER"
set_plist CFBundleVersion string "$VER"
set_plist CFBundleDisplayName string simpleplay
set_plist NSHumanReadableCopyright string "© 2026 Facundo González. GPL-3.0-or-later."
set_plist NSHighResolutionCapable bool true
set_plist LSApplicationCategoryType string public.app-category.music

# firma "ad-hoc" (sin cuenta de Apple): obligatoria en Apple Silicon y se rehace después de tocar el Info.plist
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

# el instalador: la app y un acceso directo a Aplicaciones para arrastrarla
DMG=dist/simpleplay-$VER-macos-$ARQ.dmg
rm -rf dist/dmg "$DMG"
mkdir -p dist/dmg
cp -R "$APP" dist/dmg/
ln -s /Applications dist/dmg/Applications
hdiutil create -volname "simpleplay $VER" -srcfolder dist/dmg -ov -format UDZO "$DMG" >/dev/null
rm -rf dist/dmg

echo
echo "Listo: $APP"
echo "       $DMG ($(du -h "$DMG" | cut -f1))"
