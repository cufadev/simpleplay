#!/bin/bash
# Genera dist/simpleplay-<versión>-x86_64.AppImage
# Se compila en Ubuntu 22.04 (glibc 2.35): corre en distros con glibc >= 2.35
# (Ubuntu 22.04+, Debian 12+, Fedora 36+, Mint 21+, Arch...). Más viejas, no.
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' simpleplay.py)
TOOL_DIR=packaging/.cache
TOOL=$TOOL_DIR/appimagetool-x86_64.AppImage
mkdir -p "$TOOL_DIR" build dist

if [ ! -x "$TOOL" ]; then
    curl -fL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi

rm -rf build/out build/AppDir
mkdir -p build/out
docker run --rm -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" -v "$PWD":/src:ro -v "$PWD/build/out":/out ubuntu:22.04 \
    bash /src/packaging/inner.sh

# AppDir: la carpeta de PyInstaller + AppRun + .desktop + ícono
A=build/AppDir
mkdir -p "$A/usr/lib" "$A/usr/share/applications"
cp -r build/out/simpleplay "$A/usr/lib/simpleplay"
cp packaging/simpleplay.desktop "$A/simpleplay.desktop"
cp packaging/simpleplay.desktop "$A/usr/share/applications/"
cp icon/simpleplay-256.png "$A/simpleplay.png"
cp icon/simpleplay-256.png "$A/.DirIcon"
cat > "$A/AppRun" <<'EOS'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/simpleplay/simpleplay" "$@"
EOS
chmod +x "$A/AppRun"

ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$A" "dist/simpleplay-$VERSION-x86_64.AppImage"
ls -lh dist/*.AppImage
