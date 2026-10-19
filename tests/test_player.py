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
                             capture_output=True, text=True, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}).stdout.split()[-2:]
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
