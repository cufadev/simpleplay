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
os.environ.update(QT_QPA_PLATFORM="offscreen", SIMPLEPLAY_AUDIO="null", SIMPLEPLAY_NO_MPRIS="1",
                  XDG_CONFIG_HOME=CONFIG, XDG_DATA_HOME=CONFIG, LANGUAGE="es")
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import numpy as np
from PySide6.QtWidgets import QApplication

import simpleplay as S

CORPUS = Path(__file__).parent / "corpus"
A, B = str(CORPUS / "tono_44k.mp3"), str(CORPUS / "mono_44k.mp3")     # 10 s cada uno
APP = QApplication.instance() or QApplication([])


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
        for f in Path(CONFIG).rglob("estado.json"):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
