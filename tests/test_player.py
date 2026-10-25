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
                  XDG_CONFIG_HOME=CONFIG, XDG_DATA_HOME=CONFIG, LANGUAGE="es", SIMPLEPLAY_ECUALIZADOR="1",
                  HOME=CONFIG)   # la app guarda su estado en Path.home()/.config: sin esto los tests pisarían el real
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QAbstractItemView

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
        self.assertFalse(self.w.motor.reproduciendo)        # para quien mira, ya está parado
        self.assertTrue(espera(1.0, lambda: not self.w.motor.activo))   # y el sonido se apaga tras el fundido
        self.assertEqual(self.w.actual, -1)


class TestContadorYMiniatura(Base):
    def test_el_contador_sigue_a_la_lista(self):
        self.assertEqual(self.w.cuenta.text(), "0 temas")
        self.cargar(A, B)
        espera(0.1)
        self.assertEqual(self.w.cuenta.text(), "2 temas")
        self.w.buscador.setText("mono")
        espera(0.1)
        self.assertEqual(self.w.cuenta.text(), "1 de 2")           # con una búsqueda: cuántos se ven
        self.w.buscador.clear()
        self.w.lista.setCurrentRow(0)
        self.w.lista.item(0).setSelected(True)
        self.w.quitar()
        espera(0.1)
        self.assertEqual(self.w.cuenta.text(), "1 tema")

    def test_la_miniatura_se_funde_al_cambiar_de_tema(self):
        from PySide6.QtGui import QPixmap
        def sol(c):
            pix = QPixmap(28, 28)
            pix.fill(QColor(c))
            return pix
        m = S.Miniatura(28)
        m.show()
        m.setPixmap(sol("#ff0000"))
        espera(0.6)
        self.assertEqual(m.mezcla, 1.0)
        m.setPixmap(sol("#0000ff"))
        espera(0.19)
        self.assertTrue(0.0 < m.mezcla < 1.0)                      # a mitad de camino: mezcla de los dos
        px = m.grab().toImage().pixelColor(14, 14)
        self.assertTrue(px.red() > 20 and px.blue() > 20)
        espera(0.4)
        self.assertEqual(m.mezcla, 1.0)
        self.assertIsNone(m.previa)
        px = m.grab().toImage().pixelColor(14, 14)
        self.assertEqual((px.red(), px.blue()), (0, 255))

    def test_la_miniatura_oculta_aparece_de_a_poco(self):
        from PySide6.QtGui import QPixmap
        pix = QPixmap(28, 28)
        pix.fill(QColor("#00ff00"))
        m = S.Miniatura(28)
        m.setPixmap(pix)                                           # todavía oculta: no hay carátula anterior
        self.assertIsNone(m.previa)
        m.show()
        espera(0.1)
        self.assertLess(m.mezcla, 1.0)
        espera(0.5)
        self.assertEqual(m.mezcla, 1.0)


class TestApoyo(Base):
    def test_apoyar_abre_la_pagina_de_donaciones(self):
        abiertas = []
        original = S.QDesktopServices.openUrl
        S.QDesktopServices.openUrl = staticmethod(lambda url: abiertas.append(url.toString()) or True)
        try:
            self.w.apoyar()
        finally:
            S.QDesktopServices.openUrl = original
        self.assertEqual(abiertas, ["https://buymeacoffee.com/cufadev"])
        self.assertEqual(S.URL_APOYO, abiertas[0])


class TestControlesSolos(Base):
    """Los controles se funden solos si suena un tema y nadie toca nada."""
    def quieto(self):
        self.w._quietud = int(S.Player.SEGUNDOS_QUIETO / 0.2)
        self.w._ult_cursor = S.QCursor.pos()   # el mouse no se mueve entre un tick y el otro
        self.w._vigilar_controles()
        espera(0.7)

    def test_se_esconden_sonando_y_vuelven_al_mover_el_mouse(self):
        self.cargar(A)
        self.w.reproducir(0)
        self.quieto()
        self.assertEqual(self.w.vis_controles, 0.0)
        self.w._ult_cursor = None   # movimiento
        self.w._vigilar_controles()
        espera(0.4)
        self.assertEqual(self.w.vis_controles, 1.0)
        self.assertFalse(self.w.ef_controles.isEnabled())

    def test_en_pausa_siempre_se_ven(self):
        self.cargar(A)
        self.w.reproducir(0)
        self.w.play_pausa()
        self.quieto()
        self.assertEqual(self.w.vis_controles, 1.0)

    def test_con_la_lista_abierta_o_la_opcion_apagada_se_ven(self):
        self.cargar(A)
        self.w.reproducir(0)
        self.w.lista_abierta = True
        self.quieto()
        self.assertEqual(self.w.vis_controles, 1.0)
        self.w.lista_abierta = False
        self.w.poner_ocultar_controles(False)
        self.quieto()
        self.assertEqual(self.w.vis_controles, 1.0)


class TestAcento(Base):
    def tearDown(self):
        self.w.poner_acento("naranja", guardar=False)
        super().tearDown()

    def test_hay_seis_acentos_y_el_naranja_es_el_primero(self):
        self.assertEqual(len(S.ACENTOS), 6)
        self.assertEqual(next(iter(S.ACENTOS)), "naranja")
        self.assertEqual(S.ACENTOS["naranja"][2], S.NARANJA)
        self.assertEqual(len({v[2] for v in S.ACENTOS.values()}), 6)

    def test_tinte_cambia_el_naranja_en_las_hojas_de_estilo(self):
        self.w.poner_acento("azul", guardar=False)
        css = S.tinte(S.ESTILO)
        self.assertNotIn("#ff4e01", css)
        self.assertNotIn("255,78,1", css)
        self.assertIn(S.ACENTOS["azul"][2], css)
        self.assertIn("rgba(47,123,255,190)", css)

    def test_con_el_naranja_no_se_toca_nada(self):
        self.w.poner_acento("naranja", guardar=False)
        self.assertEqual(S.tinte(S.ESTILO), S.ESTILO)

    def test_elegir_aplica_a_la_ventana_y_se_guarda(self):
        viejo = S.ARCHIVO_ACENTO
        S.ARCHIVO_ACENTO = Path(tempfile.mkdtemp()) / "cfg" / "acento"
        try:
            self.w.poner_acento("verde")
            self.assertEqual(self.w.acento, "verde")
            self.assertIn(S.ACENTOS["verde"][2], self.w.styleSheet())
            self.assertEqual(S.ARCHIVO_ACENTO.read_text(), "verde")
            self.w.poner_acento("violeta", guardar=False)
            self.w._cargar_acento()                                   # lo guardado manda al arrancar
            self.assertEqual(self.w.acento, "verde")
        finally:
            S.ARCHIVO_ACENTO = viejo

    def test_un_acento_desconocido_se_ignora(self):
        self.w.poner_acento("azul", guardar=False)
        self.w.poner_acento("fucsia-que-no-existe", guardar=False)
        self.assertEqual(self.w.acento, "azul")


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


class TestEspacial(Base):
    def _senal(self, hz, canales=(1, 1), seg=1.0, amp=0.3):
        t = np.arange(int(44100 * seg)) / 44100
        x = np.zeros((len(t), 2), np.float32)
        for c, k in enumerate(canales):
            x[:, c] = k * amp * np.sin(2 * np.pi * hz * t)
        return x

    def _correr(self, c, x, veces=3):
        for _ in range(veces):
            y = c.procesar(x)
        return y

    def test_el_balance_baja_solo_el_canal_opuesto(self):
        c = S.Cadena()
        c.poner_balance(100)                                   # todo a la derecha
        y = self._correr(c, self._senal(440))
        self.assertLess(np.abs(y[:, 0]).max(), 1e-6)
        self.assertAlmostEqual(float(np.abs(y[:, 1]).max()), 0.3, delta=0.01)
        c.poner_balance(-50)
        y = self._correr(c, self._senal(440))
        self.assertAlmostEqual(float(np.abs(y[:, 0]).max()), 0.3, delta=0.01)
        self.assertAlmostEqual(float(np.abs(y[:, 1]).max()), 0.15, delta=0.01)

    def test_el_balance_centrado_no_toca_el_audio(self):
        c = S.Cadena()
        self.assertFalse(c.activa)
        c.poner_balance(0)
        self.assertFalse(c.activa)

    def test_el_crossfeed_deja_igual_lo_que_es_mono(self):
        c = S.Cadena()
        c.poner_crossfeed(S.CROSSFEED_NIVELES[3])
        for hz in (100, 1000, 6000):
            y = self._correr(c, self._senal(hz))
            self.assertAlmostEqual(float(np.abs(y).max()), 0.3, delta=0.01, msg=f"{hz} Hz")

    def test_el_crossfeed_pasa_graves_al_otro_oido_y_no_agudos(self):
        grave, agudo = S.Cadena(), S.Cadena()
        grave.poner_crossfeed(0.4)
        agudo.poner_crossfeed(0.4)
        yg = self._correr(grave, self._senal(150, (1, 0)))
        ya = self._correr(agudo, self._senal(6000, (1, 0)))
        self.assertGreater(float(np.abs(yg[:, 1]).max()), 0.08)      # un grave de la izquierda llega a la derecha
        self.assertLess(float(np.abs(ya[:, 1]).max()), 0.02)         # un agudo no

    def test_apagar_el_crossfeed_vuelve_al_audio_original_sin_saltos(self):
        c = S.Cadena()
        c.poner_crossfeed(0.6)
        x = self._senal(200, (1, 0))
        self._correr(c, x)
        c.poner_crossfeed(0)
        y = self._correr(c, x, veces=3)
        self.assertFalse(c._espacial_activo())
        self.assertAlmostEqual(float(np.abs(y[:, 0]).max()), 0.3, delta=0.01)
        self.assertLess(float(np.abs(y[:, 1]).max()), 1e-4)

    def test_el_parametrico_sube_donde_se_le_pide(self):
        curva = S.curva_parametrica([(1000.0, 6.0, 1.0)], [100, 1000, 10000])
        self.assertAlmostEqual(float(curva[1]), 6.0, delta=0.05)
        self.assertLess(abs(float(curva[0])), 0.6)
        self.assertLess(abs(float(curva[2])), 0.6)

    def test_un_q_mas_alto_hace_la_banda_mas_angosta(self):
        ancha = S.curva_parametrica([(1000.0, 6.0, 0.5)], [2000])[0]
        angosta = S.curva_parametrica([(1000.0, 6.0, 4.0)], [2000])[0]
        self.assertGreater(float(ancha), float(angosta) + 1.0)

    def test_el_parametrico_se_aplica_se_guarda_y_se_restaura(self):
        self.cargar(A)
        self.w.poner_parametrico([[100, 3, 1.0], [300, -2, 2.0], [1000, 4, 1.0], [4000, 0, 1.0], [12000, -3, 0.7]])
        self.w.poner_balance(-30)
        self.w.poner_crossfeed(2)
        self.assertEqual(self.w.preset, "parametrico")
        self.assertTrue(self.w.motor.cadena.activa)
        self.w.guardar_estado()
        self.w.close()
        self.w.motor.cerrar()
        w2 = S.Player()
        w2.show()
        self.w = w2
        w2.restaurar()
        self.assertEqual(w2.preset, "parametrico")
        self.assertEqual(w2.balance, -30)
        self.assertEqual(w2.crossfeed, 2)
        self.assertEqual([round(b[1], 1) for b in w2.eq_param], [3, -2, 4, 0, -3])
        self.assertEqual(w2.motor.cadena._cf_obj, S.CROSSFEED_NIVELES[2])

    def test_valores_raros_en_la_sesion_se_corrigen(self):
        self.w.poner_balance(500)
        self.assertEqual(self.w.balance, 100)
        self.w.poner_crossfeed(99)
        self.assertEqual(self.w.crossfeed, len(S.CROSSFEED_NIVELES) - 1)
        self.w.poner_parametrico([[5, 99, 99]] * 5)
        self.assertEqual(self.w.eq_param[0], [S.PARAM_HZ[0], S.LIM_BANDA_DB, S.PARAM_Q[1]])


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
        x = np.full((4410, 2), 0.1, np.float32)
        y = c.procesar(x)[:, 0]
        self.assertAlmostEqual(20 * np.log10(y[0] / 0.1), 0.0, delta=0.5)      # arranca desde donde estaba
        y = c.procesar(x)[:, 0]                               # el bloque siguiente ya está en la meta (la salida va 5 ms atrás)
        self.assertAlmostEqual(20 * np.log10(y[-1] / 0.1), -8.0, delta=0.01)
        self.assertAlmostEqual(20 * np.log10(y[S.LIM_ANTICIPO] / 0.1), -8.0, delta=0.01)    # (pasado el retraso)

    def test_con_shuffle_tambien_se_mide_el_que_sigue_y_ese_es_el_que_suena(self):
        self.cargar(A, B)
        self.w.btn_shuffle.setChecked(True)
        self.w.reproducir(0)
        self.assertTrue(espera(5.0, lambda: len(self.w._cache_sonoridad()) == 2))     # midió el otro antes de que suene
        self.assertEqual(self.w._sig_azar[0], B)
        self.w.siguiente()
        self.assertEqual(self.w.actual, 1)                                              # el sorteado de antemano
        v = [v for k, v in self.w._cache_sonoridad().items() if k.startswith(B)][0]
        esperado = 10 ** (S.ganancia_para(v["lufs"], v["pico"]) / 20)
        self.assertAlmostEqual(self.w.motor.cadena._gan_obj, esperado, places=5)      # arranca ya normalizado

    def test_prender_el_shuffle_mide_el_que_va_a_seguir(self):
        self.cargar(A, B)
        self.w.reproducir(0)
        espera(3.0, lambda: len(self.w._cache_sonoridad()) == 2)
        for f in Path(CONFIG).rglob("sonoridad.json"):
            f.unlink()
        self.w._sonoridades = None
        self.assertEqual(len(self.w._cache_sonoridad()), 0)
        self.w.btn_shuffle.setChecked(True)
        self.assertTrue(espera(5.0, lambda: any(k.startswith(B) for k in self.w._cache_sonoridad())))

    def test_el_sorteo_anticipado_se_descarta_si_ya_no_vale(self):
        self.cargar(A, B)
        self.w.btn_shuffle.setChecked(True)
        self.w.reproducir(0)
        self.w._sig_azar = (A, False)                          # el actual no puede ser el que sigue
        self.assertEqual(self.w._sortear_siguiente(), 1)
        self.w._sig_azar = ("/no/esta.mp3", False)             # ya no está en la lista
        self.assertEqual(self.w._sortear_siguiente(), 1)

    def test_mientras_suena_un_tema_se_mide_el_que_sigue(self):
        self.cargar(A, B)
        self.w.reproducir(0)
        self.assertTrue(espera(5.0, lambda: len(self.w._cache_sonoridad()) == 2))
        self.w.reproducir(1)
        # el segundo ya estaba medido: su ganancia es la de la caché desde el primer instante
        v = [v for k, v in self.w._cache_sonoridad().items() if k.startswith(B)][0]
        esperado = 10 ** (S.ganancia_para(v["lufs"], v["pico"]) / 20)
        self.assertAlmostEqual(self.w.motor.cadena._gan_obj, esperado, places=5)


class TestShuffle(Base):
    def test_cada_tema_suena_una_vez_por_ronda_con_300_temas(self):
        pistas = [f"/m/{n:03d}.mp3" for n in range(300)]
        ya, actual, vistos = set(), None, []
        for _ in range(900):                                    # tres rondas completas
            i, nueva = S.elegir_al_azar(pistas, ya, actual)
            if nueva:
                ya.clear()
            actual = pistas[i]
            ya.add(actual)
            vistos.append(actual)
        for ronda in (vistos[0:300], vistos[300:600], vistos[600:900]):
            self.assertEqual(len(set(ronda)), 300)              # ninguno repetido, ninguno faltante
        for corte in (300, 600):                                # el último de una ronda no abre la siguiente
            self.assertNotEqual(vistos[corte - 1], vistos[corte])

    def test_la_ronda_se_adapta_si_cambia_la_lista(self):
        pistas = [f"/m/{n}.mp3" for n in range(10)]
        ya = {pistas[0], pistas[1], pistas[2]}
        pistas.remove("/m/5.mp3")                                # se quita uno
        pistas.append("/m/nuevo.mp3")                            # y se agrega otro: entra a la ronda
        restantes = set(pistas) - ya
        sale = set()
        actual = pistas[2]
        for _ in range(len(restantes)):
            i, nueva = S.elegir_al_azar(pistas, ya, actual)
            self.assertFalse(nueva)
            actual = pistas[i]
            ya.add(actual)
            sale.add(actual)
        self.assertEqual(sale, restantes)

    def test_con_dos_temas_alterna(self):
        pistas = ["/m/a.mp3", "/m/b.mp3"]
        ya, actual, seq = set(), None, []
        for _ in range(8):
            i, nueva = S.elegir_al_azar(pistas, ya, actual)
            if nueva:
                ya.clear()
            actual = pistas[i]
            ya.add(actual)
            seq.append(actual)
        self.assertTrue(all(seq[k] != seq[k + 1] for k in range(7)))

    def test_en_el_reproductor_no_repite_hasta_agotar(self):
        self.cargar(A, B)
        self.w.btn_shuffle.setChecked(True)
        self.w.reproducir(0)
        otros = []
        for _ in range(4):
            self.w.siguiente()
            otros.append(self.w.actual)
        self.assertEqual(otros, [1, 0, 1, 0])                   # con dos temas, siempre el otro

    def test_anterior_en_shuffle_salta_a_otro_al_azar(self):
        pistas = [A, B, str(CORPUS / "tono_16.flac"), str(CORPUS / "corto_2s.flac")]
        self.cargar(*[p for p in pistas if Path(p).exists()])
        self.w.btn_shuffle.setChecked(True)
        self.w.reproducir(0)
        for _ in range(6):
            antes = self.w.actual
            self.w.anterior()                                   # atrás o adelante: siempre otro tema
            self.assertNotEqual(self.w.actual, antes)

    def test_la_ronda_se_recuerda_en_la_sesion(self):
        self.cargar(A, B)
        self.w.btn_shuffle.setChecked(True)
        self.w.reproducir(0)
        self.w.guardar_estado()
        w2 = S.Player()
        w2.restaurar()
        self.assertTrue(w2.btn_shuffle.isChecked())
        self.assertIn(A, w2._ya_sonaron)
        w2.close()


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


def _distancia(a, b):
    return float(np.sqrt(np.mean((np.array(a) - np.array(b)) ** 2)))


def _eligir_mas_cerca(b, objetivo):
    """Elige, de las cuatro versiones de la ronda, la que queda más cerca de un gusto oculto (la distancia a `objetivo`)."""
    return min(range(4), key=lambda i: _distancia(b.opciones()[i]["curva"], objetivo))


def _gusto(azar):
    ejes = {k: azar.uniform(-6, 6) for k in S.EJES_AFINADOR}
    return sum((v * np.array(S.EJES_AFINADOR[k]) for k, v in ejes.items()), np.zeros(len(S.BANDAS_HZ)))


class TestBuscadorSonido(unittest.TestCase):
    """La búsqueda por rondas (sin Qt)."""

    def test_son_tres_rondas_de_cuatro_versiones_y_la_primera_es_la_de_ahora(self):
        b = S.BuscadorSonido()
        for _ in range(3):
            ops = b.opciones()
            self.assertEqual(len(ops), 4)
            self.assertEqual(ops[0]["clave"], "actual")
            self.assertEqual(ops[0]["curva"], b.curva())
            b.elegir(0)
        self.assertTrue(b.terminado)
        self.assertEqual(b.opciones(), [])

    def test_la_primera_ronda_se_nota_unos_6_dB_y_las_otras_menos(self):
        b = S.BuscadorSonido()
        picos = []
        for _ in range(3):
            picos.append(max(abs(max(o["curva"]) - max(b.curva())) for o in b.opciones()[1:]))
            b.elegir(0)
        self.assertGreaterEqual(picos[0], 5.5)
        self.assertLess(picos[1], picos[0])
        self.assertLess(picos[2], picos[1])

    def test_un_grupo_que_ya_viene_empujado_se_prueba_hacia_atras(self):
        b = S.BuscadorSonido()
        b.elegir(1)                                                    # se queda con la cálida: graves arriba
        graves = next(o for o in b.opciones() if o["clave"] == "graves")
        self.assertEqual(graves["signo"], -1)
        brillo = next(o for o in b.opciones() if o["clave"] == "brillo")
        self.assertEqual(brillo["signo"], 1)
        self.assertLess(graves["ejes"]["graves"], b.ejes["graves"])

    def test_se_acerca_al_gusto_de_quien_escucha(self):
        import random
        azar = random.Random(5)
        antes, despues = [], []
        for _ in range(60):
            objetivo = _gusto(azar)
            b = S.BuscadorSonido()
            antes.append(_distancia(b.curva(), objetivo))
            while not b.terminado:
                b.elegir(_eligir_mas_cerca(b, objetivo))
            despues.append(_distancia(b.curva(), objetivo))
        self.assertLess(np.mean(despues), 0.8 * np.mean(antes))
        self.assertGreater(np.mean(np.array(despues) <= np.array(antes) + 1e-9), 0.9)   # casi nunca empeora

    def test_las_curvas_no_se_pasan_de_los_limites(self):
        b = S.BuscadorSonido()
        while not b.terminado:
            for o in b.opciones():
                self.assertTrue(all(abs(g) <= S.LIM_BANDA_DB for g in o["curva"]))
            b.elegir(1)                                                # siempre empujando: tope
        self.assertTrue(all(abs(v) <= S.EJE_MAX_DB + 1e-6 for v in b.ejes.values()))

    def test_parte_de_la_curva_que_ya_tenias(self):
        b = S.BuscadorSonido(S.PRESETS["voces"])
        self.assertEqual(b.curva(), [float(x) for x in S.PRESETS["voces"]])

    def test_el_ajuste_fino_se_recorta_y_va_de_a_medio_dB(self):
        b = S.BuscadorSonido()
        b.poner_eje("brillo", 99)
        self.assertEqual(b.ejes["brillo"], S.EJE_MAX_DB)
        b.poner_eje("graves", 2.26)
        self.assertEqual(b.ejes["graves"], 2.5)

    def test_los_nombres_dicen_como_suena_y_despues_que_cambio(self):
        b = S.BuscadorSonido()
        n1 = [S.nombre_opcion(o, 0) for o in b.opciones()]
        self.assertEqual(n1, ["Como está", "Cálido", "Voces al frente", "Brillante"])
        b.elegir(0)
        n2 = [S.nombre_opcion(o, 1) for o in b.opciones()]
        self.assertEqual(n2, ["Como ahora", "Más graves", "Más voces", "Más brillo"])


class TestEcualizadorGrafico(Base):
    def test_el_motor_iguala_el_volumen_de_una_curva(self):
        curva = [6, 5, 3, 1, 0, 0, 0, 0, 0, 0]
        self.w.escuchar_curva(curva)
        pre = self.w.motor.cadena._pend[2]
        self.assertAlmostEqual(20 * np.log10(pre), -S.nivel_relativo_db(S.BANDAS_HZ, curva), places=3)
        self.assertLess(pre, 1.0)                                      # una curva que sube se baja de volumen

    def test_mi_sonido_se_guarda_y_se_restaura(self):
        curva = [2, 1, 0, -1, 0, 1.5, 2.5, 0, -1, 3]
        self.w.poner_curva_personal(curva)
        self.assertEqual(self.w.preset, "personal")
        self.cargar(A)
        self.w.guardar_estado()
        self.w.close()
        self.w.motor.cerrar()
        w2 = S.Player()
        w2.show()
        self.w = w2
        w2.restaurar()
        self.assertEqual(w2.preset, "personal")
        self.assertEqual(w2.eq_personal, curva)
        self.assertTrue(w2.motor.cadena.activa)

    def test_sin_mi_sonido_guardado_el_preset_personal_cae_en_plano(self):
        self.w.poner_preset("personal")
        self.assertEqual(self.w.preset, "plano")

    def test_valores_fuera_de_rango_se_recortan(self):
        self.w.poner_curva_personal([99, -99] + [0] * 8)
        self.assertEqual(self.w.eq_personal[:2], [S.LIM_BANDA_DB, -S.LIM_BANDA_DB])

    def test_curva_actual_de_un_preset_y_de_un_perfil(self):
        self.w.poner_preset("graves")
        self.assertEqual(self.w.curva_actual(), [float(x) for x in S.PRESETS["graves"]])
        ident = self.w.instalar_perfil("Prueba", "test", [20, 1000, 20000], [4, 0, -4])
        self.w.poner_preset("perfil:" + ident)
        c = self.w.curva_actual()
        self.assertEqual(len(c), 10)
        self.assertGreater(c[0], 0)                                    # el perfil sube los graves
        self.assertLess(c[-1], 0)

    def test_las_barras_mueven_el_sonido(self):
        d = S.DialogoEcualizador(self.w)
        self.assertEqual(d.curva(), [float(x) for x in S.PRESETS[S.PRESET_INICIAL]])   # arranca desde lo que suena
        d.sliders[0].setValue(10)                                      # +5 dB en 31 Hz (el preset tenía +4)
        espera(0.3, lambda: self.w.preset == "personal")
        self.assertEqual(self.w.preset, "personal")
        self.assertEqual(self.w.eq_personal[0], 5.0)
        self.assertEqual(self.w.eq_personal[1:], [float(x) for x in S.PRESETS[S.PRESET_INICIAL][1:]])
        self.assertEqual(d.valores[0].text(), "+5")

    def test_partir_de_un_preset_carga_sus_valores(self):
        d = S.DialogoEcualizador(self.w)
        d.poner_curva(S.curva_de_preset("voces"))
        self.assertEqual(d.curva(), [float(x) for x in S.PRESETS["voces"]])
        self.assertEqual(self.w.eq_personal, [float(x) for x in S.PRESETS["voces"]])

    def test_al_elegir_un_preset_las_barras_se_deslizan_hasta_su_lugar(self):
        d = S.DialogoEcualizador(self.w)
        d.show()
        antes = [sl.value() for sl in d.sliders]
        destino = [round(g * 2) for g in S.curva_de_preset("graves")]
        d.poner_curva(S.curva_de_preset("graves"), animar=True)
        self.assertEqual(self.w.preset, "personal")                       # el sonido cambia enseguida
        self.assertEqual(self.w.eq_personal, [x / 2 for x in destino])
        self.assertEqual([sl.value() for sl in d.sliders], antes)         # las barras todavía no se movieron
        vistos = []
        espera(0.8, lambda: vistos.append([sl.value() for sl in d.sliders]) and d.anim_barras.state() != d.anim_barras.State.Running and len(vistos) > 3)
        final = [sl.value() for sl in d.sliders]
        self.assertEqual(final, destino)
        medios = [v for v in vistos if v != antes and v != destino]
        self.assertTrue(medios)                                           # pasaron por posiciones intermedias
        i = max(range(10), key=lambda k: abs(destino[k] - antes[k]))     # y la que más recorre lo hace sin saltos hacia atrás
        serie = [v[i] for v in vistos]
        sentido = 1 if destino[i] > antes[i] else -1
        self.assertTrue(all((b - a) * sentido >= 0 for a, b in zip(serie, serie[1:])))
        self.assertEqual(d.valores[i].text(), S.fmt_db(destino[i] / 2))   # y el número va acompañando
        d.reject()

    def test_tocar_una_barra_a_mitad_de_la_animacion_la_asienta(self):
        d = S.DialogoEcualizador(self.w)
        d.poner_curva(S.curva_de_preset("brillante"), animar=True)
        d.anim_barras.setCurrentTime(100)
        d._asentar()
        self.assertEqual([sl.value() / 2 for sl in d.sliders], [float(x) for x in S.PRESETS["brillante"]])
        self.assertNotEqual(d.anim_barras.state(), d.anim_barras.State.Running)

    def test_buscar_sin_musica_avisa_y_no_deja_elegir(self):
        d = S.DialogoBuscarSonido(self.w)
        self.assertFalse(d.elegir.isEnabled())

    def test_buscar_de_punta_a_punta_guarda_un_preset(self):
        self.cargar(A)
        inicio = np.array(self.w.curva_actual())
        objetivo = inicio + 5 * np.array(S.EJES_AFINADOR["graves"]) + 3 * np.array(S.EJES_AFINADOR["presencia"])
        d = S.DialogoBuscarSonido(self.w)
        self.assertTrue(espera(1.0, lambda: self.w.actual >= 0))      # arrancó un tema para poder comparar
        antes = _distancia(inicio, objetivo)
        n = 0
        while d.paginas.currentIndex() == 0 and n < 10:
            n += 1
            i = _eligir_mas_cerca(d.buscador, objetivo)
            d.fichas[i].click()                                       # tocar una ficha la hace sonar
            self.assertEqual(d._sel, i)
            d.elegir.click()
        self.assertEqual(n, 3)
        self.assertEqual(d.paginas.currentIndex(), 1)                 # ahora el ajuste fino
        self.assertLess(_distancia(d.resultado, objetivo), antes)
        elegido = d.resultado
        d.sliders["brillo"].setValue(4)                               # +2 dB a mano: el resultado y la etiqueta lo siguen
        self.assertEqual(d.buscador.ejes["brillo"], 2.0)
        self.assertNotEqual(d.resultado, elegido)
        self.assertIn("2", d.valores["brillo"].text())
        self.w.pedir_nombre_preset = lambda sugerido: "Mi gusto"       # sin esto abriría el cuadro de nombre y esperaría
        d.elegir.click()                                              # en el ajuste fino es «Guardar preset…»
        self.assertEqual(self.w.preset, "mio:Mi gusto")
        self.assertEqual(self.w.eq_personal, [round(x * 2) / 2 for x in d.resultado])
        self.assertEqual(self.w.mis_presets["Mi gusto"], [round(x * 2) / 2 for x in d.resultado])

    def test_si_no_se_pone_nombre_la_busqueda_no_se_guarda(self):
        self.cargar(A)
        d = S.DialogoBuscarSonido(self.w)
        for _ in range(3):
            d.elegir.click()
        self.w.pedir_nombre_preset = lambda sugerido: None             # canceló el cuadro del nombre
        d.elegir.click()
        self.assertEqual(self.w.mis_presets, {})
        self.assertEqual(d.result(), 0)                                # el panel no se cerró dando por bueno el guardado
        d.reject()

    def test_el_ajuste_fino_compara_con_como_estaba(self):
        self.cargar(A)
        self.w.poner_preset("voces")
        d = S.DialogoBuscarSonido(self.w)
        for _ in range(3):
            d.elegir.click()
        d.b_antes.click()
        pre = self.w.motor.cadena._pend[2]
        self.assertAlmostEqual(20 * np.log10(pre), -S.nivel_relativo_db(S.BANDAS_HZ, d.inicial), places=3)
        d.reject()

    def test_el_slider_centrado_llena_desde_el_cero_y_doble_clic_lo_resetea(self):
        sl = S.SliderCentrado()
        sl.resize(200, 24)
        sl.setRange(-16, 16)
        self.assertEqual(sl._valor_en(sl.M), -16)
        self.assertEqual(sl._valor_en(sl.width() - sl.M), 16)
        self.assertEqual(sl._valor_en(sl.width() / 2), 0)
        sl.setValue(7)
        sl.mouseDoubleClickEvent(None)
        self.assertEqual(sl.value(), 0)

    def test_presets_con_nombre_se_guardan_eligen_y_borran(self):
        a, b = [3, 2, 1, 0, 0, 0, 0, 1, 2, 3], [-2, -1, 0, 0, 1, 2, 3, 2, 0, -1]
        self.w.guardar_mi_preset("Fiesta", a)
        self.w.guardar_mi_preset("Voces", b)
        self.assertEqual(self.w.preset, "mio:Voces")
        self.assertEqual(self.w.curva_actual(), [float(x) for x in b])
        self.w.poner_preset("mio:Fiesta")
        self.assertEqual(self.w.curva_actual(), [float(x) for x in a])
        menu = S.Menu()
        self.w._menu_sonido(menu, anidado=False)
        textos = [x.text() for x in menu.actions()]
        self.assertIn("Fiesta", textos)
        self.assertIn("Voces", textos)
        self.w.borrar_mi_preset("Fiesta")                              # estaba puesto: vuelve a plano
        self.assertEqual(self.w.preset, "plano")
        self.assertNotIn("Fiesta", self.w.mis_presets)

    def test_presets_con_nombre_sobreviven_al_reinicio(self):
        curva = [1, 2, 3, 0, 0, 0, -1, -2, 0, 4]
        self.w.guardar_mi_preset("Para el auto", curva)
        self.cargar(A)
        self.w.guardar_estado()
        self.w.close()
        self.w.motor.cerrar()
        w2 = S.Player()
        w2.show()
        self.w = w2
        w2.restaurar()
        self.assertEqual(w2.preset, "mio:Para el auto")
        self.assertEqual(w2.mis_presets["Para el auto"], [float(x) for x in curva])
        self.assertTrue(w2.motor.cadena.activa)

    def test_un_preset_con_nombre_roto_en_el_archivo_se_ignora(self):
        S.ESTADO.parent.mkdir(parents=True, exist_ok=True)
        S.ESTADO.write_text('{"mis_presets": {"Malo": [1, 2], "Bueno": [0,0,0,0,0,0,0,0,0,1], "Raro": "x"}, "preset": "mio:Malo"}')
        self.w.restaurar()
        self.assertEqual(list(self.w.mis_presets), ["Bueno"])
        self.assertEqual(self.w.preset, S.PRESET_INICIAL)

    def test_cancelar_la_busqueda_deja_el_sonido_como_estaba(self):
        self.cargar(A)
        self.w.poner_preset("voces")
        d = S.DialogoBuscarSonido(self.w)
        d.fichas[1].click()
        d.reject()
        self.assertEqual(self.w.preset, "voces")
        self.assertIsNone(d.resultado)
        self.assertIsNone(self.w.eq_personal)

    def test_sin_la_variable_el_menu_no_ofrece_ni_el_ecualizador_ni_el_afinado(self):
        S.EQ_GRAFICO = False
        try:
            self.w.eq_personal = [1.0] * 10
            menu = S.Menu()
            self.w._menu_sonido(menu, anidado=False)
            textos = [a.text() for a in menu.actions()]
            for no in ("Ecualizador gráfico…", "Buscar mi sonido…", "Mi sonido"):
                self.assertNotIn(no, textos)
        finally:
            S.EQ_GRAFICO = True

    def test_el_menu_de_sonido_ofrece_el_ecualizador_y_el_afinado(self):
        menu = S.Menu()
        self.w._menu_sonido(menu, anidado=False)
        textos = [a.text() for a in menu.actions()]
        self.assertIn("Ecualizador gráfico…", textos)
        self.assertIn("Buscar mi sonido…", textos)
        self.assertNotIn("Mi sonido", textos)                          # todavía no hay
        self.w.poner_curva_personal([1] * 10)
        menu = S.Menu()
        self.w._menu_sonido(menu, anidado=False)
        self.assertIn("Mi sonido", [a.text() for a in menu.actions()])


class TestPanelMusica(Base):
    def _carpeta_con_dos(self):
        d = Path(CONFIG) / "biblio"
        d.mkdir(exist_ok=True)
        for f in (A, B):
            (d / Path(f).name).write_bytes(Path(f).read_bytes())
        return d

    def test_elegir_una_carpeta_reemplaza_o_suma(self):
        d = self._carpeta_con_dos()
        self.cargar(A)
        self.w.abrir_musica()
        espera(0.3)
        self.w._panel._carpeta(d)                       # reemplazar: lo anterior se va
        espera(0.4)
        self.assertEqual(sorted(Path(r).parent.name for r in self.w.pistas), ["biblio", "biblio"])
        self.assertEqual(self.w.carpetas_musica[0], str(d))
        self.w.abrir_musica()
        espera(0.3)
        self.w._panel._modo(1)                          # sumar: lo que hay se queda
        self.w._panel._carpeta(Path(A).parent)
        espera(0.4)
        self.assertGreater(len(self.w.pistas), 2)

    def test_vaciar_pide_confirmar_y_no_depende_de_la_seleccion(self):
        self.cargar(A, B)
        self.w.abrir_musica()
        espera(0.3)
        pn = self.w._panel
        pn._vaciar()
        self.assertEqual(len(self.w.pistas), 2)         # el primer toque solo pide confirmar
        pn._vaciar()
        espera(0.3)
        self.assertEqual(self.w.pistas, [])
        self.assertEqual(self.w.lista.count(), 0)

    def test_abrir_lista_reemplaza_aunque_haya_seleccion_simple(self):
        self.cargar(A, B)
        self.w.lista.setSelectionMode(QAbstractItemView.SingleSelection)    # como la kiosk
        f = Path(CONFIG) / "una.m3u8"
        f.write_text(f"{B}\n")
        self.w.abrir_lista(str(f))
        espera(0.3)
        self.assertEqual([Path(r).name for r in self.w.pistas], [Path(B).name])

    def test_la_biblioteca_sobrevive_al_reinicio(self):
        d = self._carpeta_con_dos()
        self.cargar(A)
        self.w.recordar_carpeta(d)
        self.w.guardar_estado()
        w2 = S.Player()
        w2.restaurar()
        self.assertEqual(w2.carpetas_musica[0], str(d))
        w2.close()


class TestAtajosQueAlternan(Base):
    def test_ctrl_f_abre_y_al_repetir_cierra_el_buscador(self):
        self.cargar(A, B)
        self.assertFalse(self.w.lista_abierta)
        self.w.show()
        self.w.activateWindow()
        espera(0.3)
        self.w.enfocar_buscador()
        espera(0.3)
        self.assertTrue(self.w.lista_abierta)
        if not self.w.buscador.hasFocus():
            self.skipTest("este entorno no da foco de teclado a la ventana")
        self.w.buscador.setText("mono")
        self.w.enfocar_buscador()                        # segunda vez: se cierra todo
        espera(0.2)
        self.assertEqual(self.w.buscador.text(), "")
        self.assertFalse(self.w.lista_abierta)

    def test_ctrl_shift_m_abre_y_al_repetir_cierra_el_panel(self):
        self.cargar(A)
        self.w.alternar_mosquito()
        espera(0.3)
        self.assertTrue(self.w._panel.isVisible())
        self.w.alternar_mosquito()
        espera(0.3)
        self.assertFalse(self.w._panel.isVisible())
        self.assertIsNotNone(getattr(self.w, "_mosquito", None))     # cerrar el panel no apaga Mosquito


class TestPanelMosquito(Base):
    def test_el_panel_dice_si_hay_un_celular_conectado(self):
        import time
        self.cargar(A)
        self.w.abrir_mosquito()
        espera(0.3)
        m, panel = self.w._mosquito, self.w._panel
        self.assertFalse(m.conectado)
        self.assertFalse(panel.punto.activo)
        m.ultimo_contacto = time.monotonic()          # el celular pregunta por el estado
        panel._estado()
        self.assertTrue(m.conectado)
        self.assertTrue(panel.punto.activo)
        m.ultimo_contacto = time.monotonic() - 10     # hace rato que no pregunta
        self.assertFalse(m.conectado)

    def test_recordar_con_el_interruptor_y_apagar_desde_el_panel(self):
        self.cargar(A)
        self.w.abrir_mosquito()
        espera(0.3)
        m, panel = self.w._mosquito, self.w._panel
        self.assertFalse(panel.recordar.isChecked())
        panel.recordar.click()
        self.assertTrue(m.recordado)
        panel.recordar.click()
        self.assertFalse(m.recordado)
        panel._apagar()
        espera(0.3)
        self.assertIsNone(getattr(self.w, "_mosquito", None))


class TestPanelLateral(Base):
    """El ecualizador y el afinado se abren al costado de la ventana, con el mismo vidrio que el reproductor."""

    def test_el_lado_depende_del_lugar_que_hay(self):
        from PySide6.QtCore import QRect
        pant = QRect(0, 0, 1920, 1080)
        self.assertEqual(S.lado_para_panel(pant, QRect(100, 100, 400, 500), 380), "der")
        self.assertEqual(S.lado_para_panel(pant, QRect(1400, 100, 400, 500), 380), "izq")     # a la derecha no entra
        self.assertEqual(S.lado_para_panel(pant, QRect(100, 100, 400, 500), 1700), "der")     # no entra en ningún lado: donde sobra más
        self.assertEqual(S.lado_para_panel(pant, QRect(1000, 100, 400, 500), 1700), "izq")

    def _abrir(self, x):
        pant = self.w.screen().availableGeometry()
        self.w.move(pant.left() + x, pant.top() + 60)
        espera(0.1)
        return self.w.ecualizador()

    def test_se_pega_a_la_derecha_si_hay_lugar_y_a_la_izquierda_si_no(self):
        pant = self.w.screen().availableGeometry()
        d = self._abrir(10)
        visible = self.w.frameGeometry().adjusted(M, M, -M, -M)
        cuerpo_x = d.x() + M
        if pant.width() > visible.width() * 2 + 100:
            self.assertEqual(cuerpo_x, visible.right() + 1 + S.HUECO_PANEL)
        self.assertEqual(d.y() + M, visible.top())                       # alineado arriba
        d.reject()
        d = self._abrir(pant.width() - self.w.width() - 10)               # pegada al borde derecho
        visible = self.w.frameGeometry().adjusted(M, M, -M, -M)
        self.assertLessEqual(d.x() + d.width() - M, pant.right() + 1)    # no se sale de la pantalla
        if visible.left() - pant.left() > d.width():
            self.assertLessEqual(d.x() + d.width() - M, visible.left())  # quedó a la izquierda, sin tapar la ventana
        d.reject()

    def test_sigue_a_la_ventana_y_se_despega_si_se_la_arrastra(self):
        d = self._abrir(10)
        x0 = d.x()
        self.w.move(self.w.x() + 40, self.w.y())
        espera(0.2, lambda: d.x() != x0)
        self.assertNotEqual(d.x(), x0)                                    # fue detrás de la ventana
        d._pegado = False
        x1 = d.x()
        self.w.move(self.w.x() + 40, self.w.y())
        espera(0.2)
        self.assertEqual(d.x(), x1)                                       # despegado: ya no la sigue
        d.reject()

    def test_es_una_ventana_sin_marco_y_translucida_y_no_bloquea(self):
        d = self._abrir(10)
        self.assertTrue(d.windowFlags() & Qt.FramelessWindowHint)
        self.assertTrue(d.testAttribute(Qt.WA_TranslucentBackground))
        self.assertFalse(d.isModal())
        self.assertIs(self.w._panel, d)
        d.reject()

    def test_se_despliega_y_se_pliega_como_el_panel_de_la_lista(self):
        d = self._abrir(10)
        self.assertLess(d._v, 1.0)                                        # recién abierto: todavía saliendo
        self.assertTrue(espera(1.0, lambda: d._v >= 1.0))
        self.assertTrue(d.mask().isEmpty())                               # abierto del todo: sin recorte
        d.reject()
        self.assertTrue(d.isVisible())                                    # se pliega antes de cerrarse
        vistos = []
        espera(0.12, lambda: vistos.append(d._v) and False)
        self.assertTrue(espera(1.0, lambda: not d.isVisible()))
        self.assertTrue(any(0.0 < v < 1.0 for v in vistos))              # y pasó por valores intermedios

    def test_a_medio_desplegar_el_recorte_va_del_lado_pegado_a_la_ventana(self):
        d = self._abrir(10)
        d.despliegue.stop()
        c = d.cuerpo
        d._lado = "der"
        d._desplegar(0.5)
        r = c.mask().boundingRect()
        self.assertEqual(r.left(), 0)
        self.assertAlmostEqual(r.width(), c.width() / 2, delta=2)
        self.assertLess(d.ef.opacity(), 1.0)                              # y a medio fundir
        d._lado = "izq"
        d._desplegar(0.5)
        r = c.mask().boundingRect()
        self.assertEqual(r.right() + 1, c.width())
        d._desplegar(1.0)
        self.assertTrue(c.mask().isEmpty())
        self.assertFalse(d.ef.isEnabled())                                # abierto: se dibuja directo
        d.cerrar_ya()
        self.assertFalse(d.isVisible())

    def test_no_usa_opacidad_ni_mascara_de_ventana(self):
        # Wayland no las soporta: Qt avisaba "does not support setting window opacity" en cada cuadro de la animación
        d = self._abrir(10)
        espera(0.5, lambda: d._v >= 1.0)
        self.assertEqual(d.windowOpacity(), 1.0)
        self.assertTrue(d.mask().isEmpty())
        d.reject()
        espera(0.5, lambda: not d.isVisible())

    def test_abrir_otro_panel_cierra_el_anterior(self):
        a = self.w.ecualizador()
        b = self.w.afinar_al_oido()
        self.assertFalse(a.isVisible())
        self.assertTrue(b.isVisible())
        b.reject()


if __name__ == "__main__":
    unittest.main(verbosity=2)
