"""Pruebas de la aplicación completa (Player) con el motor de audio, sin placa de sonido ni pantalla.

    python tests/generar_corpus.py            (una vez)
    python tests/test_player.py

Usa SIMPLEPLAY_AUDIO=null (dispositivo simulado) y la plataforma offscreen de Qt; la sesión guardada va a una
carpeta temporal, así que no toca la del usuario.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

CONFIG = tempfile.mkdtemp()
HOME_REAL = os.environ.get("HOME", "")   # los subprocesos lo necesitan: de él sale el sitio de paquetes del usuario
os.environ.update(QT_QPA_PLATFORM="offscreen", SIMPLEPLAY_AUDIO="null", SIMPLEPLAY_NO_MPRIS="1",
                  XDG_CONFIG_HOME=CONFIG, XDG_DATA_HOME=CONFIG, LANGUAGE="es",
                  HOME=CONFIG)   # la app guarda su estado en Path.home()/.config: sin esto los tests pisarían el real
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import numpy as np
from PySide6.QtWidgets import QApplication

import simpleplay as S

CORPUS = Path(__file__).parent / "corpus"
A, B = str(CORPUS / "tono_44k.mp3"), str(CORPUS / "mono_44k.mp3")     # 10 s cada uno
APP = QApplication.instance() or QApplication([])
M = S.SOMBRA_MARGEN   # margen transparente de la ventana donde se dibuja la sombra


def espera(seg, cond=None):
    fin = time.time() + seg
    while time.time() < fin:
        APP.processEvents()
        if cond and cond():
            return True
        time.sleep(0.01)
    return bool(cond and cond())


class Base(unittest.TestCase):
    def setUp(self):
        for f in list(Path(CONFIG).rglob("estado.json")) + list(Path(CONFIG).rglob("sonoridad.json")):
            f.unlink()
        self.w = S.Player()
        self.w.show()

    def tearDown(self):
        self.w.close()
        self.w.motor.cerrar()

    def cargar(self, *rutas):
        self.w.agregar(list(rutas))


class TestReproduccion(Base):
    def test_reproduce_pausa_y_reanuda(self):
        self.cargar(A, B)
        self.w.reproducir(0)
        espera(1.3)
        self.assertTrue(self.w.motor.reproduciendo)
        self.assertGreater(self.w.posicion(), 0.8)
        self.assertEqual(self.w.btn_play.kind, "pause")
        self.w.play_pausa()
        espera(0.4)
        p1 = self.w.posicion()
        espera(0.5)
        self.assertTrue(self.w.pausado)
        self.assertFalse(self.w.motor.reproduciendo)
        self.assertAlmostEqual(self.w.posicion(), p1, delta=0.002)
        self.assertEqual(self.w.btn_play.kind, "play")
        self.w.play_pausa()
        espera(0.6)
        self.assertTrue(self.w.motor.reproduciendo)
        self.assertGreater(self.w.posicion(), p1 + 0.3)

    def test_la_barra_y_los_tiempos_siguen_la_posicion(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(1.5)
        self.assertGreater(self.w.linea.value(), 50)          # 1 s de 10 s = 10 %
        self.assertTrue(self.w.t_actual.text().startswith("0:0"))

    def test_saltar_y_saltar_en_pausa(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(0.5)
        self.w.saltar(0.5)
        espera(0.6)
        self.assertAlmostEqual(self.w.posicion(), 5.5, delta=0.4)
        self.w.play_pausa()
        espera(0.4)
        self.w.saltar(0.8)
        espera(0.5)
        self.assertAlmostEqual(self.w.posicion(), 8.0, delta=0.1)
        self.assertFalse(self.w.motor.reproduciendo)         # sigue en pausa
        self.assertTrue(self.w.pausado)

    def test_saltar_rel_con_las_flechas(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(0.4)
        self.w.saltar_rel(5)
        espera(0.5)
        self.assertGreater(self.w.posicion(), 5.0)

    def test_el_espectro_responde(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(1.0)
        v = self.w.espectro(S.BANDAS)
        self.assertEqual(len(v), S.BANDAS)
        self.assertTrue(all(0.0 <= x <= 1.0 for x in v))


class TestEspectro(Base):
    """Las barras leen lo que suena desde el motor."""

    def test_la_barra_de_los_440_hz_es_la_mas_alta(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(1.5)
        for _ in range(40):                                   # unos segundos de análisis, como las barras reales
            v = self.w.espectro(S.BANDAS)
        k = int(np.searchsorted(S._BORDES, 440) - 1)
        # 440 Hz está en el borde entre dos bandas: la ventana desparrama energía a la vecina y la compensación de
        # agudos le suma casi 1 dB, así que la barra más alta puede ser cualquiera de las dos (siempre fue así)
        self.assertIn(int(np.argmax(v)), (k, k + 1))
        self.assertGreater(max(v), 0.9)
        self.assertLess(sorted(v)[-4], 0.6)                   # y el resto de las barras queda abajo

    def test_pausa_deja_las_barras_en_cero(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(1.0)
        self.w.play_pausa()
        self.assertEqual(self.w.espectro(S.BANDAS), [0.0] * S.BANDAS)

    def test_un_tema_suave_usa_todo_el_rango(self):
        self.cargar(str(CORPUS / "tono_bajo.mp3"))
        self.w.reproducir(0)
        espera(1.5)
        for _ in range(40):
            v = self.w.espectro(S.BANDAS)
        self.assertGreater(max(v), 0.9)                       # 34 dB más bajo, y la barra igual llega arriba

    def test_sin_audio_barras_planas(self):
        self.assertEqual(self.w.espectro(S.BANDAS), [0.0] * S.BANDAS)   # nada cargado
        self.cargar(A)
        self.w.reproducir(0)
        self.assertEqual(self.w.espectro(S.BANDAS), [0.0] * S.BANDAS)   # recién empieza: todavía no hay audio

    def test_diagnose(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            codigo = S.diagnosticar(A)
        self.assertEqual(codigo, 0, out.getvalue())
        self.assertIn("decodificación:", out.getvalue())
        self.assertIn("dispositivo de audio: abre y avanza", out.getvalue())


class TestFinDePista(Base):
    def test_pasa_al_siguiente_tema(self):
        self.cargar(A, B)
        self.w.reproducir(0)
        espera(0.4)
        self.w.saltar(0.96)
        self.assertTrue(espera(4.0, lambda: self.w.actual == 1), "no pasó al segundo tema")
        espera(0.5)
        self.assertTrue(self.w.motor.reproduciendo)
        self.assertEqual(self.w.motor.ruta, B)

    def test_el_ultimo_sin_repetir_se_detiene(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(0.4)
        self.w.saltar(0.96)
        self.assertTrue(espera(4.0, lambda: self.w.actual == -1), "no se detuvo al final de la lista")
        self.assertFalse(self.w.motor.activo)
        self.assertEqual(self.w.btn_play.kind, "play")

    def test_repetir_un_tema(self):
        self.cargar(A, B)
        self.w.poner_repetir("one")
        self.w.reproducir(0)
        espera(0.4)
        self.w.saltar(0.96)
        espera(2.5)
        self.assertEqual(self.w.actual, 0)
        self.assertTrue(self.w.motor.reproduciendo)
        self.assertLess(self.w.posicion(), 4.0)              # volvió a empezar

    def test_repetir_la_lista_da_la_vuelta(self):
        self.cargar(A, B)
        self.w.poner_repetir("all")
        self.w.reproducir(1)
        espera(0.4)
        self.w.saltar(0.96)
        self.assertTrue(espera(4.0, lambda: self.w.actual == 0))

    def test_un_aviso_viejo_no_mueve_nada(self):
        self.cargar(A, B)
        self.w.reproducir(0)
        espera(0.5)
        self.w._motor_fin()                                   # el motor no terminó: se ignora
        self.assertEqual(self.w.actual, 0)
        self.w.play_pausa()
        self.w._motor_fin()                                   # en pausa tampoco
        self.assertEqual(self.w.actual, 0)


class TestArchivosRotos(Base):
    """Un tema que no se puede reproducir se saltea, y si no hay ninguno bueno la lista se detiene."""

    def meter(self, *rutas):
        """Agrega rutas a la lista aunque no existan (el diálogo solo deja elegir archivos que existen)."""
        for r in rutas:
            self.w.pistas.append(r)
            self.w.orden_original.append(r)
            self.w.datos[r] = S.datos_lista(r)
            self.w.lista.addItem(os.path.basename(r))

    def test_saltea_el_roto_y_toca_el_siguiente(self):
        self.meter(str(CORPUS / "basura.mp3"), A)
        self.w.reproducir(0)
        self.assertTrue(espera(4.0, lambda: self.w.actual == 1), "no pasó al tema bueno")
        espera(0.6)
        self.assertTrue(self.w.motor.reproduciendo)
        self.assertEqual(self.w.motor.ruta, A)

    def test_roto_en_el_medio_de_la_lista(self):
        self.meter(A, str(CORPUS / "vacio.mp3"), B)
        self.w.reproducir(0)
        espera(0.4)
        self.w.saltar(0.96)
        self.assertTrue(espera(6.0, lambda: self.w.actual == 2), "no llegó al tercer tema")
        espera(0.5)
        self.assertTrue(self.w.motor.reproduciendo)

    def test_etiqueta_sin_audio_tambien_se_saltea(self):
        self.meter(str(CORPUS / "solo_etiqueta.mp3"), A)
        self.w.reproducir(0)
        self.assertTrue(espera(5.0, lambda: self.w.actual == 1))

    def test_si_fallan_todos_se_detiene_sin_dar_vueltas(self):
        self.meter(str(CORPUS / "basura.mp3"), str(CORPUS / "vacio.mp3"), "/no/existe.mp3")
        self.w.poner_repetir("all")                        # con "repetir la lista" el bucle sería infinito
        self.w.reproducir(0)
        self.assertTrue(espera(8.0, lambda: self.w.actual == -1), "siguió dando vueltas")
        espera(1.0)
        self.assertEqual(self.w.actual, -1)
        self.assertFalse(self.w.motor.activo)
        self.assertEqual(self.w._fallos, 0)

    def test_tema_borrado_despues_de_agregarlo(self):
        import shutil
        import tempfile
        ruta = os.path.join(tempfile.mkdtemp(), "borrado.mp3")
        shutil.copy(A, ruta)
        self.cargar(ruta, B)
        os.remove(ruta)
        self.w.reproducir(0)
        self.assertTrue(espera(4.0, lambda: self.w.actual == 1))
        self.assertEqual(self.w.motor.ruta, B)


class TestUsoRapido(Base):
    def test_cambiar_de_tema_a_toda_velocidad(self):
        self.cargar(A, B, str(CORPUS / "tono_48k.mp3"), str(CORPUS / "tono_bajo.mp3"))   # distintos: no se repiten
        self.assertEqual(len(self.w.pistas), 4)
        self.w.poner_repetir("all")
        self.w.reproducir(0)
        for _ in range(30):
            self.w.siguiente()
            APP.processEvents()
        espera(1.0)
        self.assertEqual(self.w.actual, 30 % 4)
        self.assertTrue(self.w.motor.reproduciendo)
        self.assertEqual(self.w.motor.ruta, self.w.pistas[self.w.actual])

    def test_saltos_y_pausas_en_rafaga(self):
        self.cargar(A)
        self.w.reproducir(0)
        for i in range(40):
            self.w.saltar((i % 9) / 10)
            if i % 7 == 0:
                self.w.play_pausa()
            APP.processEvents()
        if self.w.pausado:
            self.w.play_pausa()
        espera(0.8)
        self.assertTrue(self.w.motor.reproduciendo)


class TestTransicion(Base):
    """El paso entre la tarjeta y la barra compacta se anima y siempre termina bien."""

    def test_ida_y_vuelta_terminan_en_el_tamano_justo(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(0.4)
        self.w.poner_compacto(True)
        self.assertIsNotNone(self.w._trans)                     # hay una animación en curso
        self.assertTrue(espera(2.0, lambda: self.w._trans is None))
        self.assertTrue(self.w.mini.isVisible())
        self.assertFalse(self.w.card.isVisible())
        self.assertEqual((self.w.width(), self.w.height()), (380 + 2 * M, 56 + 2 * M))
        self.w.poner_compacto(False)
        self.assertTrue(espera(2.0, lambda: self.w._trans is None))
        self.assertTrue(self.w.card.isVisible())
        self.assertFalse(self.w.mini.isVisible())
        self.assertEqual((self.w.width(), self.w.height()), (320 + 2 * M, 320 + 2 * M))

    def test_la_musica_no_se_corta_durante_la_transicion(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(0.6)
        p0 = self.w.posicion()
        self.w.poner_compacto(True)
        espera(0.2)                                             # a mitad de la animación
        self.assertTrue(self.w.motor.reproduciendo)
        espera(0.8)
        self.assertGreater(self.w.posicion(), p0 + 0.5)

    def test_a_mitad_de_camino_la_ventana_mide_lo_mismo_y_se_puede_dibujar(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(0.3)
        self.w.poner_compacto(True)
        espera(0.15)
        self.assertEqual((self.w.width(), self.w.height()), (380 + 2 * M, 320 + 2 * M))   # el mayor de los dos tamaños
        self.assertFalse(self.w.grab().isNull())                           # y dibuja sin errores
        espera(1.0)

    def test_sin_animar_no_hay_capa(self):
        self.cargar(A)
        self.w.poner_compacto(True, animar=False)
        self.assertIsNone(self.w._trans)
        self.assertEqual((self.w.width(), self.w.height()), (380 + 2 * M, 56 + 2 * M))

    def test_apretar_muchas_veces_seguidas(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(0.3)
        for i in range(11):                                     # termina en compacto (11 cambios: impar)
            self.w.poner_compacto(not self.w.compacto)
            espera(0.03 * (i % 4))
        self.assertTrue(espera(2.5, lambda: self.w._trans is None))
        self.assertTrue(self.w.compacto)
        self.assertEqual((self.w.width(), self.w.height()), (380 + 2 * M, 56 + 2 * M))
        self.assertTrue(self.w.mini.isVisible())
        self.assertFalse(self.w.card.isVisible())
        self.w.poner_compacto(False)
        self.assertTrue(espera(2.5, lambda: self.w._trans is None))
        self.assertEqual((self.w.width(), self.w.height()), (320 + 2 * M, 320 + 2 * M))
        self.assertTrue(self.w.motor.reproduciendo)

    def test_con_la_lista_abierta(self):
        self.cargar(A, B)
        self.w.alternar_lista(True)
        espera(0.6)
        self.assertGreater(self.w.height(), 320)
        self.w.poner_compacto(True)
        self.assertTrue(espera(2.0, lambda: self.w._trans is None))
        self.assertEqual((self.w.width(), self.w.height()), (380 + 2 * M, 56 + 2 * M))
        self.assertFalse(self.w.caja.isVisible())
        self.w.poner_compacto(False)
        self.assertTrue(espera(2.0, lambda: self.w._trans is None))
        self.assertEqual((self.w.width(), self.w.height()), (320 + 2 * M, 320 + 2 * M))   # la lista queda cerrada


class TestSombra(Base):
    def test_el_margen_tiene_sombra_y_las_esquinas_lejanas_no(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(0.3)
        img = self.w.grab().toImage()
        w, h = img.width(), img.height()
        self.assertEqual((w, h), (320 + 2 * M, 320 + 2 * M))
        abajo, arriba = img.pixelColor(w // 2, h - M + 4).alpha(), img.pixelColor(w // 2, M - 4).alpha()   # a 4 px del borde
        self.assertGreater(abajo, 20)                                      # debajo de la tarjeta: sombra
        self.assertGreater(abajo, arriba)                                  # y más fuerte abajo que arriba (cae hacia abajo)
        self.assertEqual(img.pixelColor(0, 0).alpha(), 0)                  # la esquina de la ventana, nada
        self.assertEqual(img.pixelColor(w // 2, h // 2).alpha(), 255)      # la tarjeta es opaca

    def test_las_formas_que_proyectan_sombra(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(0.3)
        self.assertEqual([r for _, r, _ in self.w._formas()], [30])        # la tarjeta
        self.w.alternar_lista(True)
        espera(0.6)
        self.assertEqual([r for _, r, _ in self.w._formas()], [30, 18])    # y el panel de la lista
        self.w.poner_compacto(True, animar=False)
        self.assertEqual([r for _, r, _ in self.w._formas()], [28])        # o solo la barra

    def test_apagada_no_hay_margen(self):
        import subprocess
        out = subprocess.run([sys.executable, "-c",
                              "import os,sys; os.environ['SIMPLEPLAY_SOMBRA']='0'; sys.path.insert(0, %r); import simpleplay as S; print(S.SOMBRA, S.SOMBRA_MARGEN)" % str(RAIZ)],
                             capture_output=True, text=True, env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "HOME": HOME_REAL}).stdout.split()[-2:]
        self.assertEqual(out, ["False", "0"])


class TestLista(Base):
    def test_quitar_el_que_suena_pasa_al_vecino(self):
        self.cargar(A, B)
        self.w.reproducir(0)
        espera(0.5)
        self.w.lista.setCurrentRow(0)
        self.w.quitar()
        espera(0.6)
        self.assertEqual(self.w.pistas, [B])
        self.assertTrue(self.w.motor.reproduciendo)
        self.assertEqual(self.w.motor.ruta, B)

    def test_vaciar_la_lista_para_el_audio(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(0.5)
        self.w.lista.selectAll()
        self.w.quitar()
        espera(0.5)
        self.assertFalse(self.w.motor.activo)
        self.assertEqual(self.w.actual, -1)

    def test_parar(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(0.5)
        self.w.parar()
        espera(0.3)
        self.assertFalse(self.w.motor.activo)
        self.assertEqual(self.w.actual, -1)


class TestListas(Base):
    def _lista(self, nombre, texto, carpeta=None):
        d = Path(carpeta or tempfile.mkdtemp())
        f = d / nombre
        f.write_text(texto, encoding="utf-8")
        return f

    def test_guardar_y_abrir_con_rutas_relativas(self):
        self.cargar(A, B)
        destino = Path(tempfile.mkdtemp()) / "mia.m3u8"
        self.w.guardar_lista(str(destino))
        lineas = destino.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lineas[0], "#EXTM3U")
        rutas = [l for l in lineas if not l.startswith("#")]
        self.assertEqual(len(rutas), 2)
        self.assertFalse(any(Path(r).is_absolute() for r in rutas))
        self.w.lista.selectAll()
        self.w.quitar()
        self.w.abrir_lista(str(destino))
        self.assertEqual([Path(p).resolve() for p in self.w.pistas], [Path(A).resolve(), Path(B).resolve()])

    def test_abrir_reemplaza_la_lista_y_respeta_el_orden(self):
        self.cargar(A, B)
        f = self._lista("o.m3u", f"{B}\n{A}\n")
        self.w.abrir_lista(str(f))
        self.assertEqual([Path(p).name for p in self.w.pistas], [Path(B).name, Path(A).name])
        self.assertEqual(self.w.lista.count(), 2)

    def test_entradas_que_faltan_se_saltean(self):
        f = self._lista("f.m3u", f"#EXTM3U\n#EXTINF:-1,x\n{A}\nno_existe.mp3\nC:\\musica\\otro.mp3\n")
        temas, faltan = S.leer_lista(f)
        self.assertEqual(len(temas), 1)
        self.assertEqual(faltan, 2)

    def test_sobrevive_a_mover_lista_y_musica_juntas(self):
        origen = Path(tempfile.mkdtemp())
        (origen / "musica").mkdir()
        import shutil
        shutil.copy(A, origen / "musica" / "a.mp3")
        S.escribir_lista(origen / "l.m3u8", [str(origen / "musica" / "a.mp3")])
        destino = Path(tempfile.mkdtemp()) / "nuevo"
        shutil.move(str(origen), destino)
        temas, faltan = S.leer_lista(destino / "l.m3u8")
        self.assertEqual((len(temas), faltan), (1, 0))
        self.assertTrue(temas[0].startswith(str(destino.resolve())))

    def test_lista_en_latin1_y_url_file(self):
        d = Path(tempfile.mkdtemp())
        import shutil
        shutil.copy(A, d / "canción ñ.mp3")
        f = d / "v.m3u"
        f.write_bytes("canción ñ.mp3\n".encode("latin-1"))
        self.assertEqual(len(S.leer_lista(f)[0]), 1)
        g = d / "u.m3u"
        g.write_text((d / "canción ñ.mp3").resolve().as_uri() + "\n", encoding="utf-8")
        self.assertEqual(len(S.leer_lista(g)[0]), 1)

    def test_arrastrar_o_pasar_una_lista_agrega_sus_temas(self):
        f = self._lista("d.m3u8", f"{A}\n{B}\n")
        self.assertEqual(len(S.buscar_audio([str(f)])), 2)
        self.w.agregar([str(f)])
        self.assertEqual(len(self.w.pistas), 2)

    def test_lista_vacia_o_ilegible_no_toca_la_actual(self):
        self.cargar(A)
        f = self._lista("v.m3u8", "#EXTM3U\nnada.mp3\n")
        self.w.abrir_lista(str(f))
        self.assertEqual(len(self.w.pistas), 1)
        self.w.abrir_lista(str(f) + ".no_existe")
        self.assertEqual(len(self.w.pistas), 1)


class TestCrearListas(Base):
    def setUp(self):
        super().setUp()
        self.d = Path(tempfile.mkdtemp())

    def test_agregar_crea_la_lista_y_no_repite(self):
        self.cargar(A, B)
        f = self.d / "nueva.m3u8"
        self.w.lista.setCurrentRow(1)
        self.w.agregar_a_lista(str(f))
        self.assertEqual([Path(x).name for x in S.leer_lista(f)[0]], [Path(B).name])
        self.w.lista.selectAll()
        self.w.agregar_a_lista(str(f))
        self.assertEqual([Path(x).name for x in S.leer_lista(f)[0]], [Path(B).name, Path(A).name])
        self.w.agregar_a_lista(str(f))
        self.assertEqual(len(S.leer_lista(f)[0]), 2)
        self.assertEqual(len(self.w.pistas), 2)            # la lista que suena no cambia

    def test_agregar_conserva_las_entradas_que_hoy_faltan(self):
        f = self.d / "x.m3u8"
        f.write_text("#EXTM3U\nmusica_en_disco_ausente/zzz.mp3\n", encoding="utf-8")
        self.cargar(A)
        self.w.lista.setCurrentRow(0)
        self.w.agregar_a_lista(str(f))
        texto = f.read_text(encoding="utf-8")
        self.assertIn("zzz.mp3", texto)
        self.assertEqual(len(S.leer_lista(f)[0]), 1)

    def test_guardar_sobre_la_lista_abierta(self):
        f = self.d / "o.m3u8"
        S.escribir_lista(f, [A, B])
        self.w.abrir_lista(str(f))
        self.assertEqual(self.w.lista_actual, str(f.resolve()))
        self.w.lista.setCurrentRow(0)
        self.w.quitar()
        self.w.guardar_lista(self.w.lista_actual)
        self.assertEqual(len(S.leer_lista(f)[0]), 1)

    def test_la_lista_abierta_se_recuerda_en_la_sesion(self):
        f = self.d / "r.m3u8"
        S.escribir_lista(f, [A])
        self.w.abrir_lista(str(f))
        self.w.guardar_estado()
        w2 = S.Player()
        w2.restaurar()
        self.assertEqual(w2.lista_actual, str(f.resolve()))
        w2.close()


class TestNormalizadorSuave(Base):
    def test_una_medida_tardia_se_acomoda_con_rampa_y_no_de_golpe(self):
        c = S.Cadena()          # propia: la del motor la usa también el hilo de audio
        c.poner_ganancia(-8.0, suave=True)
        x = np.full((4410, 2), 0.1, np.float32)              # 100 ms de señal constante
        y = c.procesar(x)[:, 0]
        self.assertGreater(y[0], 0.099)                       # empieza donde estaba (sin salto)
        pendiente = np.abs(np.diff(20 * np.log10(y / 0.1))).max()
        self.assertLess(pendiente, 0.01)                      # ningún paso brusco entre muestras
        bajada = 20 * np.log10(y[-1] / 0.1)
        self.assertAlmostEqual(bajada, -S.RAMPA_DB_S * 0.1, delta=0.1)    # a RAMPA_DB_S dB por segundo
        for _ in range(20):
            y = c.procesar(x)[:, 0]
        self.assertAlmostEqual(20 * np.log10(y[-1] / 0.1), -8.0, delta=0.01)   # y llega a la meta

    def test_al_cambiar_de_tema_la_ganancia_sigue_siendo_inmediata(self):
        c = S.Cadena()          # propia: la del motor la usa también el hilo de audio
        c.poner_ganancia(-8.0)                                # sin suave: un fundido de un bloque
        y = c.procesar(np.full((4410, 2), 0.1, np.float32))[:, 0]
        self.assertAlmostEqual(20 * np.log10(y[-1] / 0.1), -8.0, delta=0.01)

    def test_mientras_suena_un_tema_se_mide_el_que_sigue(self):
        self.cargar(A, B)
        self.w.reproducir(0)
        self.assertTrue(espera(5.0, lambda: len(self.w._cache_sonoridad()) == 2))
        self.w.reproducir(1)
        # el segundo ya estaba medido: su ganancia es la de la caché desde el primer instante
        v = [v for k, v in self.w._cache_sonoridad().items() if k.startswith(B)][0]
        esperado = 10 ** (S.ganancia_para(v["lufs"], v["pico"]) / 20)
        self.assertAlmostEqual(self.w.motor.cadena._gan_obj, esperado, places=5)


class TestSesion(Base):
    def test_restaura_el_tema_y_la_posicion(self):
        self.cargar(A, B)
        self.w.reproducir(1)
        espera(0.4)
        self.w.saltar(0.3)
        espera(0.6)
        self.w.guardar_estado()
        self.w.close()
        self.w.motor.cerrar()
        w2 = S.Player()
        w2.show()
        self.w = w2
        w2.restaurar()
        self.assertEqual(w2.pendiente[0], 1)
        self.assertAlmostEqual(w2.pendiente[1], 3.5, delta=1.0)
        self.assertFalse(w2.motor.activo)                     # restaurar no suena hasta el play
        w2.play_pausa()
        espera(1.0)
        self.assertEqual(w2.actual, 1)
        self.assertTrue(w2.motor.reproduciendo)
        self.assertAlmostEqual(w2.posicion(), 4.0, delta=1.5)

    def test_cerrar_libera_el_dispositivo(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(0.5)
        self.w.close()
        self.assertIsNone(self.w.motor._dev)


class TestSonido(Base):
    def test_el_tema_se_normaliza_con_su_sonoridad_medida(self):
        self.cargar(A)
        self.w.reproducir(0)
        espera(4.0, lambda: self.w._cache_sonoridad())           # el hilo de medición guarda la medida
        cache = self.w._cache_sonoridad()
        self.assertEqual(len(cache), 1)
        v = next(iter(cache.values()))
        esperado = 10 ** (S.ganancia_para(v["lufs"], v["pico"]) / 20)
        espera(1.0, lambda: abs(self.w.motor.cadena._gan_obj - esperado) < 1e-6)
        self.assertAlmostEqual(self.w.motor.cadena._gan_obj, esperado, places=5)

    def test_sin_normalizar_la_ganancia_queda_en_cero(self):
        self.cargar(A)
        self.w.poner_normalizar(False)
        self.w.reproducir(0)
        espera(1.0)
        self.assertEqual(self.w.motor.cadena._gan_obj, 1.0)
        self.assertEqual(len(self.w._cache_sonoridad()), 0)       # ni siquiera se mide

    def test_el_preset_y_la_normalizacion_se_recuerdan(self):
        self.w.poner_preset("voces")
        self.w.poner_normalizar(False)
        self.cargar(A)
        self.w.guardar_estado()
        self.w.close()
        self.w.motor.cerrar()
        w2 = S.Player()
        w2.show()
        self.w = w2
        w2.restaurar()
        self.assertEqual(w2.preset, "voces")
        self.assertFalse(w2.normalizar)
        self.assertTrue(w2.motor.cadena.activa)                   # el preset ya está aplicado al motor

    def test_un_preset_desconocido_cae_en_plano(self):
        self.w.poner_preset("no-existe")
        self.assertEqual(self.w.preset, "plano")


class TestTransicionBarras(Base):
    """El paso entre el nombre del tema y las barras del espectro (clic en la píldora)."""

    def test_cada_barra_empieza_un_poco_despues_y_todas_terminan_arriba(self):
        n = S.BANDAS
        self.assertEqual([S.Barras.factor(i, n, 0.0) for i in range(n)], [0.0] * n)
        self.assertEqual([S.Barras.factor(i, n, 1.0) for i in range(n)], [1.0] * n)
        for e in (0.2, 0.5, 0.8):
            f = [S.Barras.factor(i, n, e) for i in range(n)]
            self.assertEqual(f, sorted(f, reverse=True))            # las de la izquierda van más adelantadas
            self.assertGreater(f[0], f[-1])
        for i in range(n):                                          # y ninguna baja mientras la entrada sube
            valores = [S.Barras.factor(i, n, e / 20) for e in range(21)]
            self.assertEqual(valores, sorted(valores))

    def test_la_transicion_hacia_las_barras_pasa_por_estados_intermedios_y_termina(self):
        w = self.w
        w.alternar_barras()
        espera(0.12)
        self.assertTrue(0.0 < w.mezcla < 1.0)
        self.assertTrue(0.0 < w.ef_texto.opacity() < 1.0)           # el texto se está yendo
        self.assertLess(w.titulo.dy, 0.0)                           # levantándose
        self.assertTrue(0.0 < w.barras.entrada < 1.0)               # y las barras están subiendo
        self.assertTrue(espera(1.5, lambda: w.mezcla == 1.0 and not w.fundido.state() == w.fundido.State.Running))
        self.assertEqual(w.ef_texto.opacity(), 0.0)
        self.assertEqual(w.ef_barras.opacity(), 1.0)
        self.assertEqual(w.barras.entrada, 1.0)
        self.assertTrue(w.barras.timer.isActive())

    def test_la_vuelta_al_texto_lo_deja_todo_en_su_lugar_y_apaga_las_barras(self):
        w = self.w
        w.alternar_barras()
        self.assertTrue(espera(1.5, lambda: w.mezcla == 1.0))
        w.alternar_barras()
        self.assertTrue(espera(1.5, lambda: w.mezcla == 0.0))
        espera(0.1)
        self.assertEqual(w.ef_texto.opacity(), 1.0)
        self.assertEqual(w.titulo.dy, 0.0)
        self.assertEqual(w.artista.dy, 0.0)
        self.assertEqual(w.barras.entrada, 0.0)
        self.assertFalse(w.barras.timer.isActive())                 # sin barras a la vista no se las dibuja ni se las calcula

    def test_apretar_dos_veces_seguidas_no_deja_nada_a_medias(self):
        w = self.w
        w.alternar_barras()
        espera(0.1)
        w.alternar_barras()                                         # cambia de idea a la mitad: vuelve desde donde estaba
        self.assertTrue(espera(1.5, lambda: w.mezcla == 0.0))
        espera(0.1)
        self.assertEqual(w.ef_texto.opacity(), 1.0)
        self.assertEqual(w.titulo.dy, 0.0)
        self.assertFalse(w.modo_barras)

    def test_se_dibujan_las_barras_a_medio_subir(self):
        from PySide6.QtGui import QColor
        b = self.w.barras
        self.w.ef_barras.setOpacity(1.0)                            # en modo texto están a opacidad 0: se las vería transparentes
        b.resize(200, 24)
        b.vals = [1.0] * b.N
        b.picos = [1.0] * b.N
        b.entrada = 0.0
        vacio = b.grab().toImage()
        b.entrada = 1.0
        lleno = b.grab().toImage()
        b.entrada = 0.45
        medio = b.grab().toImage()

        def distintos(img):                                         # píxeles que cambian respecto del fondo (la imagen vacía)
            return sum(1 for x in range(img.width()) for y in range(img.height()) if img.pixel(x, y) != vacio.pixel(x, y))
        self.assertEqual(distintos(vacio), 0)
        self.assertGreater(distintos(lleno), 0)
        self.assertTrue(0 < distintos(medio) < distintos(lleno))


class TestConsumo(Base):
    """Cosas que no se ven pero que hacen que el reproductor gaste poco."""

    def pixeles_de_referencia(self, b, fondo):
        """Las barras dibujadas como se hacía antes (un rectángulo por segmento), sobre el mismo fondo."""
        from PySide6.QtGui import QImage, QPainter
        img = QImage(b.width(), b.height(), QImage.Format_ARGB32)
        img.fill(fondo)
        p = QPainter(img)
        h = b.height()
        paso = b.SEG + b.HUECO_SEG
        filas = h // paso
        bw = (b.width() - b.HUECO * (b.N - 1)) / b.N
        for i in range(b.N):
            x = i * (bw + b.HUECO)
            f = S.Barras.factor(i, b.N, b.entrada)
            for r in range(round(b.vals[i] * f * filas)):
                y = h - (r + 1) * paso + b.HUECO_SEG
                p.fillRect(S.QRectF(x, y, bw, b.SEG), b._color(r / filas))
            if b.picos[i] * f > 0.02:
                r = min(round(b.picos[i] * f * filas), filas) - 1
                y = h - (r + 1) * paso + b.HUECO_SEG
                p.fillRect(S.QRectF(x, y, bw, b.SEG), S.QColor(255, 255, 255, 220))
        p.end()
        return img

    def test_las_barras_por_lotes_se_ven_igual_que_dibujadas_una_por_una(self):
        import random
        b = self.w.barras
        self.w.ef_barras.setOpacity(1.0)
        random.seed(5)
        for ancho in (200, 241, 333):
            b.resize(ancho, 24)
            b.vals, b.picos, b.entrada = [0.0] * b.N, [0.0] * b.N, 1.0
            vacio = b.grab().toImage()
            fondo = vacio.pixelColor(0, 0)
            for entrada in (1.0, 0.5):
                b.entrada = entrada
                b.vals = [random.random() for _ in range(b.N)]
                b.picos = [min(1.0, v + random.random() * 0.3) for v in b.vals]
                real = b.grab().toImage()
                ref = self.pixeles_de_referencia(b, fondo)
                distintos = sum(1 for x in range(real.width()) for y in range(real.height()) if real.pixel(x, y) != ref.pixel(x, y))
                self.assertEqual(distintos, 0, f"ancho {ancho}, entrada {entrada}")

    def test_los_efectos_de_opacidad_solo_existen_durante_la_transicion(self):
        w = self.w
        self.assertFalse(w.ef_texto.isEnabled())
        self.assertFalse(w.ef_barras.isEnabled())
        self.assertTrue(w.barras.isHidden())                       # en modo texto las barras ni se pintan
        w.alternar_barras()
        espera(0.1)
        self.assertTrue(w.ef_texto.isEnabled() and w.ef_barras.isEnabled())
        self.assertTrue(espera(1.5, lambda: w.mezcla == 1.0 and w.fundido.state() != w.fundido.State.Running))
        self.assertFalse(w.ef_texto.isEnabled() or w.ef_barras.isEnabled())
        self.assertTrue(w.textos_w.isHidden())                     # y en modo barras, el texto no se pinta
        self.assertFalse(w.barras.isHidden())
        w.alternar_barras()
        self.assertTrue(espera(1.5, lambda: w.mezcla == 0.0 and w.fundido.state() != w.fundido.State.Running))
        self.assertTrue(w.barras.isHidden())
        self.assertFalse(w.textos_w.isHidden())

    def test_un_texto_que_entra_no_gasta_un_temporizador_y_uno_largo_si(self):
        w = self.w
        w.titulo.set_text("Corto")
        espera(0.1)
        self.assertFalse(w.titulo.timer.isActive())
        w.titulo.set_text("Un título larguísimo que no entra en la píldora de ninguna manera, ni a palos, nunca")
        self.assertTrue(w.titulo.timer.isActive())
        w.titulo.set_text("Otra vez corto")
        self.assertFalse(w.titulo.timer.isActive())
        self.assertEqual(w.titulo.pos, 0)

    def test_el_titulo_largo_sigue_desplazandose(self):
        w = self.w
        w.titulo.set_text("Un título larguísimo que no entra en la píldora de ninguna manera, ni a palos, nunca")
        w.titulo.espera = 0
        antes = w.titulo.pos
        espera(0.4)
        self.assertGreater(w.titulo.pos, antes)

    def test_la_sombra_no_se_repinta_por_un_cambio_dentro_de_la_tarjeta(self):
        from PySide6.QtCore import QRectF
        w = self.w
        g = QRectF(w.card.geometry())
        self.assertFalse(w._sombra_necesaria(g.adjusted(20, 20, -20, -20)))        # las barras, el tiempo...
        self.assertTrue(w._sombra_necesaria(QRectF(w.rect())))                     # la ventana entera sí
        self.assertTrue(w._sombra_necesaria(g.adjusted(-8, -8, 8, 8)))             # el borde de la tarjeta, donde se ve la sombra
        self.assertTrue(w._sombra_necesaria(g.adjusted(0, 0, -g.width() + 10, -g.height() + 10)))   # la esquina redondeada


class TestPerfilesAuriculares(Base):
    def test_parametrico_con_coma_decimal(self):
        coma = "Preamp: -4,7 dB\nFilter 1: ON LS Fc 55 Hz Gain 2,2 dB Q 0,71\nFilter 2: ON PK Fc 210 Hz Gain -3,9 dB Q 0,5\n"
        punto = coma.replace(",", ".")
        self.assertEqual(S.leer_parametrico(coma), S.leer_parametrico(punto))
        self.assertNotEqual(min(S.leer_parametrico(coma)[1]), max(S.leer_parametrico(coma)[1]))

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(Path(__file__).parent))
        import datos_autoeq
        self.D = datos_autoeq
        for f in (S.ESTADO.parent / "perfiles").glob("*"):
            f.unlink()
        self._http = S._http

    def tearDown(self):
        S._http = self._http
        super().tearDown()

    def instalar_m20x(self):
        f, g = S.leer_perfil(self.D.M20X_GRAFICO)
        return self.w.instalar_perfil("Audio-Technica ATH-M20x", "oratory1990", f, g)

    def archivo(self, nombre, texto):
        p = Path(tempfile.mkdtemp()) / nombre
        p.write_text(texto)
        return str(p)

    def acciones(self, menu):
        out = []
        for a in menu.actions():
            out.append(a.text())
            if a.menu():
                out += self.acciones(a.menu())
        return out

    def test_un_perfil_se_guarda_y_se_lee_igual(self):
        ident = self.instalar_m20x()
        self.assertEqual(self.w.perfiles_instalados(), [(ident, "Audio-Technica ATH-M20x")])
        f, g, nombre = self.w._cargar_perfil(ident)
        f0, g0 = S.leer_perfil(self.D.M20X_GRAFICO)
        self.assertEqual(len(f), len(f0))
        self.assertAlmostEqual(g[40], g0[40], places=1)
        self.assertEqual(nombre, "Audio-Technica ATH-M20x")

    def test_activar_un_perfil_enciende_el_filtro_con_su_compensacion(self):
        ident = self.instalar_m20x()
        self.w.poner_preset("perfil:" + ident)
        c = self.w.motor.cadena
        self.assertEqual(self.w.preset, "perfil:" + ident)
        c.procesar(np.zeros((4410, 2), np.float32))                    # el bloque que aplica el cambio pendiente
        self.assertTrue(c.activa)
        f, g, _ = self.w._cargar_perfil(ident)
        comp = min(max(-S.nivel_relativo_db(f, g), 0.0), S.COMPENSACION_MAX_DB)
        self.assertAlmostEqual(c._pre, 10 ** ((comp - max(0.0, max(g))) / 20), places=4)
        self.assertGreater(comp, 0.0)
        self.assertLessEqual(comp, S.COMPENSACION_MAX_DB)

    def test_el_perfil_elegido_se_recuerda(self):
        ident = self.instalar_m20x()
        self.w.poner_preset("perfil:" + ident)
        self.cargar(A)
        self.w.guardar_estado()
        self.w.close()
        self.w.motor.cerrar()
        w2 = S.Player()
        w2.show()
        self.w = w2
        w2.restaurar()
        self.assertEqual(w2.preset, "perfil:" + ident)
        w2.motor.cadena.procesar(np.zeros((4410, 2), np.float32))
        self.assertTrue(w2.motor.cadena.activa)

    def test_si_el_perfil_ya_no_esta_se_vuelve_a_plano_sin_romper_nada(self):
        self.w.poner_preset("perfil:no-existe")
        self.assertEqual(self.w.preset, "plano")
        ident = self.instalar_m20x()
        self.w.poner_preset("perfil:" + ident)
        (S.ESTADO.parent / "perfiles" / f"{ident}.json").unlink()
        self.w._aplicar_eq()
        self.assertEqual(self.w.preset, "plano")

    def test_importar_un_archivo_grafico_o_parametrico(self):
        a = self.w.importar_perfil_de(self.archivo("Audio-Technica ATH-M20x GraphicEQ.txt", self.D.M20X_GRAFICO))
        self.assertEqual(self.w.preset, "perfil:" + a)
        self.assertEqual(dict(self.w.perfiles_instalados())[a], "Audio-Technica ATH-M20x")      # sin el " GraphicEQ"
        b = self.w.importar_perfil_de(self.archivo("otro ParametricEQ.txt", self.D.M20X_PARAMETRICO))
        self.assertEqual(self.w.preset, "perfil:" + b)
        self.assertEqual(len(self.w.perfiles_instalados()), 2)

    def test_importar_algo_que_no_es_un_perfil_no_cambia_nada(self):
        antes = self.w.preset
        self.assertIsNone(self.w.importar_perfil_de(self.archivo("basura.txt", "esto no es un perfil")))
        self.assertIsNone(self.w.importar_perfil_de("/no/existe.txt"))
        self.assertEqual(self.w.preset, antes)
        self.assertEqual(self.w.perfiles_instalados(), [])

    def test_el_menu_de_sonido_lista_los_perfiles_y_las_dos_formas_de_agregar(self):
        from PySide6.QtWidgets import QMenu
        ident = self.instalar_m20x()
        self.w.poner_preset("perfil:" + ident)
        m = QMenu()
        self.w._menu_sonido(m)
        textos = self.acciones(m)
        self.assertIn("Audio-Technica ATH-M20x", textos)
        self.assertTrue(any("Buscar auriculares" in t for t in textos))
        self.assertTrue(any("Importar un perfil" in t for t in textos))
        marcada = [a for sub in m.actions() if sub.menu() for a in sub.menu().actions() if a.menu()
                   for b in a.menu().actions() if b.text() == "Audio-Technica ATH-M20x" and b.isChecked()]
        self.assertEqual(len(marcada), 1)

    def test_el_dialogo_busca_en_el_indice_y_baja_el_elegido(self):
        from PySide6.QtWidgets import QApplication
        d = S.DialogoAuriculares(self.w, descargar=False)
        d._llenar(self.D.INDICE)
        self.assertEqual(d.lista.count(), 0)                           # sin escribir nada no se vuelcan los ~800 modelos
        self.assertIn("6 perfiles", d.estado.text())
        d.busca.setText("m20x")
        self.assertEqual(d.lista.count(), 2)
        self.assertIn("oratory1990", d.lista.item(0).text())
        self.assertFalse(d.usar.isEnabled())
        d.lista.setCurrentRow(0)
        self.assertTrue(d.usar.isEnabled())
        pedido = []
        self.w.descargar_perfil = lambda *a: pedido.append(a)
        d._usar()
        self.assertEqual(pedido, [("Audio-Technica ATH-M20x", "oratory1990", "oratory1990/over-ear/Audio-Technica ATH-M20x")])
        d.deleteLater()

    def test_bajar_un_perfil_lo_instala_y_lo_activa(self):
        pedidas = []
        S._http = lambda url, binario=False, reintentos=4: (pedidas.append(url), self.D.M20X_GRAFICO.encode())[1]
        self.w.descargar_perfil("Audio-Technica ATH-M20x", "oratory1990", "oratory1990/over-ear/Audio-Technica ATH-M20x")
        self.assertTrue(espera(3.0, lambda: self.w.preset.startswith("perfil:")))
        self.assertTrue(pedidas[0].endswith("Audio-Technica%20ATH-M20x%20GraphicEQ.txt"))
        self.assertEqual([n for _, n in self.w.perfiles_instalados()], ["Audio-Technica ATH-M20x"])

    def test_si_falla_la_descarga_avisa_y_no_cambia_nada(self):
        def sin_red(*a, **k):
            raise OSError("sin conexión")
        S._http = sin_red
        avisos = []
        self.w._aviso = lambda texto, ms=0: avisos.append(texto)
        self.w.descargar_perfil("X", "y", "a/b/X")
        self.assertTrue(espera(3.0, lambda: any("No se pudo bajar" in a for a in avisos)))
        self.assertEqual(self.w.perfiles_instalados(), [])
        self.assertFalse(self.w.preset.startswith("perfil:"))

    def test_los_tests_no_tocan_la_configuracion_real(self):
        self.assertTrue(str(S.ESTADO).startswith(CONFIG))


class TestFlacEnElReproductor(Base):
    F = str(CORPUS / "con_etiquetas.flac")
    F2 = str(CORPUS / "tono_16.flac")
    CORTO = str(CORPUS / "corto_2s.flac")

    def test_un_flac_se_agrega_con_sus_etiquetas_y_se_reproduce(self):
        self.cargar(self.F)
        self.assertEqual(self.w.pistas, [self.F])
        self.assertEqual(self.w.lista.item(0).text(), "Artista de prueba - Tema de prueba")
        self.w.reproducir(0)
        espera(1.0)
        self.assertTrue(self.w.motor.reproduciendo)
        self.assertAlmostEqual(self.w.duracion, 10.0, delta=0.1)
        self.assertGreater(self.w.posicion(), 0.5)
        self.assertEqual(self.w.titulo.texto, "Tema de prueba")
        self.assertEqual(self.w.artista.texto, "Artista de prueba")

    def test_la_tapa_del_flac_llega_a_la_tarjeta_y_a_todas_las_vistas(self):
        self.cargar(self.F)
        self.w.reproducir(0)
        espera(0.5)
        self.assertIsNotNone(self.w.card.escalada)                     # la tarjeta clásica muestra la carátula
        self.cargar(self.F2)
        self.w.reproducir(1)
        espera(0.5)
        self.assertIsNone(self.w.card.escalada)                        # un flac sin carátula: vuelve el degradé

    def test_una_lista_con_mp3_y_flac_pasa_de_uno_al_otro(self):
        self.cargar(self.CORTO, A)
        self.w.reproducir(0)
        self.assertTrue(espera(5.0, lambda: self.w.actual == 1))       # el flac de 2 s termina y sigue el mp3
        espera(0.5)
        self.assertTrue(self.w.motor.reproduciendo)
        self.assertEqual(self.w.pistas[self.w.actual], A)

    def test_agregar_una_carpeta_toma_los_flac_y_los_mp3(self):
        import shutil
        d = Path(tempfile.mkdtemp())
        shutil.copy(CORPUS / "tono_16.flac", d / "uno.flac")
        shutil.copy(CORPUS / "tono_44k.mp3", d / "dos.mp3")
        (d / "tres.ogg").write_bytes(b"OggS")
        self.cargar(str(d))
        self.assertEqual([Path(p).name for p in self.w.pistas], ["dos.mp3", "uno.flac"])

    def test_el_volumen_de_un_flac_se_normaliza_igual_que_el_de_un_mp3(self):
        self.cargar(self.F2)
        self.w.reproducir(0)
        self.assertTrue(espera(5.0, lambda: bool(self.w._cache_sonoridad())))
        v = next(iter(self.w._cache_sonoridad().values()))
        self.assertIsNotNone(v)
        self.assertAlmostEqual(v["pico"], 0.5, delta=0.05)

    def test_las_barras_del_espectro_siguen_a_un_flac(self):
        self.cargar(self.F2)
        self.w.reproducir(0)
        espera(1.2)
        barras = self.w.espectro(S.BANDAS)
        self.assertGreater(max(barras), 0.5)
        self.assertEqual(barras.index(max(barras)), int(np.argmax(S.bandas_db(self.w.motor.muestras(S.VENTANA)))))

    def test_la_sesion_con_un_flac_se_guarda_y_se_restaura(self):
        self.cargar(self.F, A)
        self.w.reproducir(0)
        espera(0.6)
        self.w.guardar_estado()
        self.w.close()
        self.w.motor.cerrar()
        w2 = S.Player()
        w2.show()
        self.w = w2
        w2.restaurar()
        self.assertEqual(w2.pistas, [self.F, A])
        self.assertEqual(w2.titulo.texto, "Tema de prueba")

    def test_saltar_dentro_de_un_flac_desde_el_reproductor(self):
        self.cargar(self.F2)
        self.w.reproducir(0)
        espera(0.5)
        self.w.saltar(0.6)
        espera(0.6)
        self.assertAlmostEqual(self.w.posicion(), 6.6, delta=0.8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
