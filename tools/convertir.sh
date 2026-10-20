#!/usr/bin/env bash
# convertir.sh: pasa a mp3 (o flac) el audio de todos los videos de una carpeta, subcarpetas incluidas.
# Necesita ffmpeg. No toca los originales y no pisa lo que ya está convertido.

uso() {
  cat <<'EOF'
uso: convertir.sh [CARPETA] [opciones]

  Convierte el audio de todos los videos de CARPETA (y sus subcarpetas) y lo guarda en otra carpeta
  con la misma estructura. Sin CARPETA usa la carpeta en la que estás parado. También convierte audios sueltos (m4a, ogg, opus, wma, wav, aac).

opciones:
  -o, --salida DIR     dónde guardar        (por defecto: audio-convertido, dentro de la carpeta)
  -f, --formato F      mp3 | flac           (por defecto: mp3)
  -q, --calidad Q      solo para mp3: vbr (la mejor variable, por defecto) | 320 | 256 | 192 | 128
  -p, --pista N        qué pista de audio usar, empezando en 0 (por defecto: 0, la primera)
  -h, --ayuda          muestra esto

ejemplos:
  convertir.sh                                  # la carpeta actual
  convertir.sh -q 320                           # la carpeta actual, mp3 a 320 kbps
  convertir.sh ~/Videos/recitales
  convertir.sh ~/Videos/recitales -q 320
  convertir.sh ~/Videos/recitales -f flac -o ~/Música/recitales
  convertir.sh ~/Videos/peliculas -p 1          # la segunda pista de audio (por ejemplo, el idioma original)
EOF
}

formato=mp3; calidad=vbr; pista=0; salida=""; carpeta=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o|--salida)  [ $# -ge 2 ] || { echo "falta el valor de $1" >&2; exit 2; }; salida="$2"; shift 2 ;;
    -f|--formato) [ $# -ge 2 ] || { echo "falta el valor de $1" >&2; exit 2; }; formato="$2"; shift 2 ;;
    -q|--calidad) [ $# -ge 2 ] || { echo "falta el valor de $1" >&2; exit 2; }; calidad="$2"; shift 2 ;;
    -p|--pista)   [ $# -ge 2 ] || { echo "falta el valor de $1" >&2; exit 2; }; pista="$2"; shift 2 ;;
    -h|--ayuda|--help) uso; exit 0 ;;
    -*) echo "opción desconocida: $1 (probá con -h)" >&2; exit 2 ;;
    *)  [ -z "$carpeta" ] || { echo "una sola carpeta por vez (sobra: $1)" >&2; exit 2; }; carpeta="$1"; shift ;;
  esac
done

command -v ffmpeg >/dev/null || { echo "no encuentro ffmpeg: instalalo con  sudo apt install ffmpeg" >&2; exit 1; }
[ -n "$carpeta" ] || carpeta="."                 # sin carpeta: la actual
[ -d "$carpeta" ] || { echo "no existe la carpeta: $carpeta" >&2; exit 1; }
case "$formato" in mp3|flac) ;; *) echo "formato desconocido: $formato (mp3 o flac)" >&2; exit 2 ;; esac
case "$pista" in ''|*[!0-9]*) echo "la pista tiene que ser un número (0, 1, 2...)" >&2; exit 2 ;; esac
case "$calidad" in vbr|320|256|192|128) ;; *) echo "calidad desconocida: $calidad (vbr, 320, 256, 192 o 128)" >&2; exit 2 ;; esac

carpeta="$(realpath "$carpeta")"
salida="$(realpath -m "${salida:-$carpeta/audio-convertido}")"
[ "$salida" != "$carpeta" ] || { echo "la salida no puede ser la misma carpeta" >&2; exit 2; }

if [ "$formato" = flac ]; then
  codec=(-c:a flac)
elif [ "$calidad" = vbr ]; then
  codec=(-c:a libmp3lame -q:a 0)
else
  codec=(-c:a libmp3lame -b:a "${calidad}k")
fi

# los archivos a convertir, sin mirar la carpeta de salida (por si quedó adentro de la de entrada)
mapfile -d '' -t archivos < <(find "$carpeta" -type f \
  \( -iname '*.mkv' -o -iname '*.mp4' -o -iname '*.avi' -o -iname '*.webm' -o -iname '*.mov' -o -iname '*.m4v' \
     -o -iname '*.wmv' -o -iname '*.flv' -o -iname '*.ts' -o -iname '*.mpg' -o -iname '*.mpeg' \
     -o -iname '*.m4a' -o -iname '*.ogg' -o -iname '*.opus' -o -iname '*.wma' -o -iname '*.wav' -o -iname '*.aac' \) \
  -not -path "$salida/*" -print0 | sort -z)

total=${#archivos[@]}
[ "$total" -gt 0 ] || { echo "no hay videos ni audios para convertir en $carpeta"; exit 0; }
echo "Convirtiendo $total archivo(s) a $formato  ->  $salida"

parcial=""
trap '[ -n "$parcial" ] && rm -f "$parcial"; echo; echo "interrumpido: lo ya convertido queda en $salida"; exit 130' INT TERM

hechos=0; saltados=0; fallos=()
i=0
for f in "${archivos[@]}"; do
  i=$((i + 1))
  rel="${f#"$carpeta"/}"
  destino="$salida/${rel%.*}.$formato"
  if [ -e "$destino" ]; then
    saltados=$((saltados + 1))
    echo "[$i/$total] ya estaba:  $rel"
    continue
  fi
  mkdir -p "$(dirname "$destino")"
  parcial="${destino%.*}.parcial.$formato"      # se escribe aparte y se renombra al terminar: no quedan archivos a medias
  if ffmpeg -nostdin -y -loglevel error -i "$f" -vn -map "0:a:$pista" -map_metadata 0 -ar 44100 "${codec[@]}" "$parcial" 2>/dev/null; then
    mv -f "$parcial" "$destino"
    hechos=$((hechos + 1))
    echo "[$i/$total] listo:      $rel"
  else
    rm -f "$parcial"
    fallos+=("$rel")
    echo "[$i/$total] NO SE PUDO: $rel  (¿no tiene esa pista de audio?)"
  fi
  parcial=""
done

echo
echo "Resumen: $hechos convertido(s), $saltados que ya estaban, ${#fallos[@]} con error."
if [ "${#fallos[@]}" -gt 0 ]; then
  echo "Con error:"; printf '  - %s\n' "${fallos[@]}"
fi
echo "Carpeta de salida: $salida"
[ "${#fallos[@]}" -eq 0 ]
