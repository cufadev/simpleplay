#!/bin/bash
# Prueba de MPRIS sobre un bus de sesión aislado (no toca el escritorio): estado, SetPosition, Seek, PlayPause,
# Next y la señal Seeked. Se corre así (la salida a un archivo, porque Qt deja servicios abiertos en el bus):
#
#   TMPCFG=$(mktemp -d) dbus-run-session -- tests/mpris/probar.sh > /tmp/mpris.log 2>&1; cat /tmp/mpris.log
#
# Resultado esperado: Playing, la posición sigue a SetPosition (6 s) y a Seek (-2 s), PlayPause alterna,
# Next cambia el tema y se ven 2 señales Seeked con "int64 6000000" y la posición tras el Seek.
S=$(cd "$(dirname "$0")" && pwd); RAIZ=$(dirname "$(dirname "$S")"); N=org.mpris.MediaPlayer2.simpleplay; R=/org/mpris/MediaPlayer2; P=org.mpris.MediaPlayer2.Player
SEEKED=$(mktemp)
b() { busctl --user "$@" 2>&1 | tr '\n' ' '; }
dbus-monitor --session "type='signal',interface='$P',member='Seeked'" > "$SEEKED" 2>&1 &
MON=$!
"$RAIZ/.venv/bin/python" "$S/app.py" 2>&1 | grep -v "propagate\|textinput\|portal\|Locale\|locale\|UTF-8\|reconfigure\|more information" &
APP=$!
for i in $(seq 1 60); do busctl --user list 2>/dev/null | grep -q $N && break; sleep 0.5; done
sleep 1.5
echo "inicio       : estado=$(b get-property $N $R $P PlaybackStatus) posición=$(b get-property $N $R $P Position)"
echo "  [SetPosition] $(b call $N $R $P SetPosition ox /org/mpris/MediaPlayer2/Track/0 6000000)"; sleep 0.6
echo "SetPosition 6 s -> posición=$(b get-property $N $R $P Position)"
echo "  pos antes de Seek: $(b get-property $N $R $P Position)"; echo "  [Seek] $(b call $N $R $P Seek x -- -2000000)"; sleep 0.6
echo "Seek -2 s       -> posición=$(b get-property $N $R $P Position)"
b call $N $R $P PlayPause > /dev/null; sleep 0.5
echo "PlayPause       -> estado=$(b get-property $N $R $P PlaybackStatus)"
b call $N $R $P PlayPause > /dev/null; sleep 0.4
b call $N $R $P Next > /dev/null; sleep 0.8
echo "Next            -> estado=$(b get-property $N $R $P PlaybackStatus) título=$(b get-property $N $R $P Metadata | cut -c1-90)"
wait $APP
kill $MON 2>/dev/null
echo "señales Seeked vistas: $(grep -c 'member=Seeked' "$SEEKED")"
grep -A1 "member=Seeked" "$SEEKED" | grep -E "int|x" | head -3
