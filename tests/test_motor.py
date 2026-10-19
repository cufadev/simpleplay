"""Pruebas del motor de audio (clase Motor de simpleplay.py), con el dispositivo NULL de miniaudio.

    python tests/generar_corpus.py            (una vez)
    python tests/test_motor.py

Cada bloque que el motor manda al dispositivo se captura con `Motor.espia`, así se mira el audio real que saldría:
silencios, clicks (saltos entre muestras vecinas), la frecuencia que suena y la posición.
"""
import glob
import os
import sys
import time
import unittest
from pathlib import Path

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import miniaudio
import numpy as np
from PySide6.QtCore import QCoreApplication

import simpleplay as S

CORPUS = Path(__file__).parent / "corpus"
APP = QCoreApplication.instance() or QCoreApplication([])


def espera(seg, cond=None):
    """Deja correr el tiempo (y los eventos de Qt); si hay `cond`, sale en cuanto se cumple."""
    fin = time.time() + seg
    while time.time() < fin:
        APP.processEvents()
        if cond and cond():
            return True
        time.sleep(0.01)
    return bool(cond and cond())


def frecuencia(x, fs=S.FS):
    esp = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.argmax(esp) * fs / len(x))


class Base(unittest.TestCase):
    def setUp(self):
        self.bloques = []
        self.m = S.Motor(buffer_ms=120, backend=miniaudio.Backend.NULL)
        self.m.espia = self.bloques.append
        self.fines = []
        self.m.fin_de_pista.connect(lambda: self.fines.append(time.time()))

    def tearDown(self):
        self.m.cerrar()

    def audio(self, desde=0, canal=0):
        b = self.bloques[desde:]
        return np.concatenate([x[:, canal] for x in b]) if b else np.zeros(0, np.float32)

    def salto_maximo(self, x):
        return float(np.abs(np.diff(x)).max()) if len(x) > 1 else 0.0


class TestReproduccion(Base):
    def test_posicion_avanza_con_el_reloj(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(1.5)
        p = self.m.posicion()
        self.assertTrue(self.m.reproduciendo)
        self.assertGreater(p, 0.9)   # 1,5 s menos el primer bloque y la latencia
        self.assertLess(p, 1.5)
        self.assertAlmostEqual(self.m.duracion, 10.0, delta=0.1)

    def test_suena_el_tono_correcto(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(1.0)
        self.assertAlmostEqual(frecuencia(self.audio()[-8192:]), 440, delta=6)

    def test_el_archivo_de_48k_suena_igual_de_afinado(self):
        self.m.cargar(str(CORPUS / "tono_48k.mp3"))
        espera(1.0)
        self.assertAlmostEqual(frecuencia(self.audio()[-8192:]), 440, delta=6)
        self.assertAlmostEqual(self.m.duracion, 10.0, delta=0.1)

    def test_espectro_lee_lo_que_suena(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(1.2)
        m = self.m.muestras(4096)
        self.assertEqual(len(m), 4096)
        self.assertGreater(float(np.abs(m).max()), 0.3)
        self.assertAlmostEqual(frecuencia(m), 440, delta=15)

    def test_cambio_de_tema_sigue_sonando(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(0.8)
        n = len(self.bloques)
        self.m.cargar(str(CORPUS / "mono_44k.mp3"))
        espera(0.8)
        self.assertGreater(float(np.abs(self.audio(n)).max()), 0.3)
        self.assertEqual(self.fines, [])


class TestPausa(Base):
    def test_pausa_silencia_congela_y_reanuda_sin_clicks(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(1.0)
        self.m.pausar()
        espera(0.4)
        n = len(self.bloques)
        p1 = self.m.posicion()
        espera(0.6)
        p2 = self.m.posicion()
        self.assertFalse(self.m.reproduciendo)
        self.assertAlmostEqual(p1, p2, delta=0.002)                 # la posición no se mueve
        self.assertLess(float(np.abs(self.audio(n)).max()), 1e-6)   # y no sale nada
        self.m.reanudar()
        espera(0.8)
        self.assertGreater(float(np.abs(self.audio(n)).max()), 0.3)
        self.assertGreater(self.m.posicion(), p2)
        self.assertLess(self.salto_maximo(self.audio()), 0.06)      # una senoide limpia no pasa de 0,031

    def test_pausa_no_pierde_audio(self):
        """El tiempo en pausa no consume el archivo: al reanudar sigue donde se dejó."""
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(1.0)
        self.m.pausar()
        espera(0.5)
        p1 = self.m.posicion()
        espera(1.5)
        self.m.reanudar()
        espera(0.5)
        self.assertLess(self.m.posicion() - p1, 1.0)               # avanzó ~0,5 s, no los 2 s de la pausa


class TestFinDePista(Base):
    def test_se_avisa_una_sola_vez(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"), inicio=9.0)
        self.assertTrue(espera(3.0, lambda: self.fines))
        espera(0.6)
        self.assertEqual(len(self.fines), 1)
        self.assertFalse(self.m.reproduciendo)
        self.assertAlmostEqual(self.m.posicion(), self.m.duracion, delta=0.2)

    def test_se_puede_volver_a_empezar_despues_del_fin(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"), inicio=9.2)
        self.assertTrue(espera(3.0, lambda: self.fines))
        n = len(self.bloques)
        self.m.saltar(1.0)
        self.m.reanudar()
        espera(0.8)
        self.assertGreater(float(np.abs(self.audio(n)).max()), 0.3)
        self.assertTrue(self.m.reproduciendo)


class TestSaltos(Base):
    def test_salto_largo_es_instantaneo_y_exacto(self):
        largo = str(CORPUS / "largo_60min.mp3")
        self.m.cargar(largo)
        self.assertTrue(espera(5.0, lambda: self.m._idx is not None), "el índice de frames no llegó a armarse")
        for destino in (600.0, 1800.0, 3500.0):
            t0 = time.perf_counter()
            self.m.saltar(destino)
            dt = time.perf_counter() - t0
            self.assertLess(dt, 0.05, f"saltar({destino}) tardó {dt*1000:.0f} ms")
            n = len(self.bloques)
            espera(0.7)
            pos = self.m.posicion()
            self.assertAlmostEqual(pos, destino + 0.6, delta=0.5)
            # el barrido vale 200 + t Hz: la frecuencia que sale dice en qué segundo está sonando
            x = self.audio(n)[-8192:]
            self.assertAlmostEqual(frecuencia(x) - 200, pos, delta=8)

    def test_salto_sin_indice_sigue_funcionando(self):
        """Antes de que el índice esté listo (o en otros formatos) se usa el salto lineal de miniaudio."""
        self.m.cargar(str(CORPUS / "vbr_4min.mp3"))
        self.m._idx = None
        self.m.saltar(100.0)
        espera(0.7)
        self.assertAlmostEqual(self.m.posicion(), 100.6, delta=0.5)

    def test_saltos_y_cambios_sin_clicks(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(0.6)
        for s in (2.0, 5.5, 0.3, 8.0, 3.3):
            self.m.saltar(s)
            espera(0.35)
        self.m.cargar(str(CORPUS / "tono_48k.mp3"))
        espera(0.5)
        x = self.audio()
        self.assertGreater(float(np.abs(x).max()), 0.3)
        self.assertLess(self.salto_maximo(x), 0.08)

    def test_saltar_en_pausa_cambia_la_posicion_sin_sonar(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(0.6)
        self.m.pausar()
        espera(0.4)
        n = len(self.bloques)
        self.m.saltar(7.0)
        espera(0.5)
        self.assertAlmostEqual(self.m.posicion(), 7.0, delta=0.05)
        self.assertLess(float(np.abs(self.audio(n)).max()), 1e-6)


class TestParar(Base):
    def test_parar_deja_todo_en_cero(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(0.8)
        self.m.parar()
        espera(0.5)
        n = len(self.bloques)
        espera(0.4)
        self.assertFalse(self.m.activo)
        self.assertEqual(self.m.posicion(), 0.0)
        self.assertLess(float(np.abs(self.audio(n)).max()), 1e-6)

    def test_volumen(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(0.6)
        self.m.volumen = 0.0
        espera(0.5)
        # lo que se entrega al dispositivo (espia es previo al volumen): hay audio pero el volumen lo anula
        self.assertGreater(float(np.abs(self.audio()[-4096:]).max()), 0.3)


class TestRobustez(Base):
    """Archivos que no se pueden abrir, dispositivo que se cae y recursos que no se pierden."""

    def setUp(self):
        super().setUp()
        self.errores = []
        self.m.error_archivo.connect(lambda ruta, msg: self.errores.append((os.path.basename(ruta), msg)))

    def test_archivo_inexistente_no_rompe_nada(self):
        self.assertFalse(self.m.cargar("/no/existe/nada.mp3"))
        self.assertEqual(len(self.errores), 1)
        self.assertFalse(self.m.activo)
        self.assertTrue(self.m.cargar(str(CORPUS / "tono_44k.mp3")))   # y se puede seguir usando
        espera(0.8)
        self.assertTrue(self.m.reproduciendo)

    def test_basura_y_vacio_se_rechazan(self):
        for nombre in ("basura.mp3", "vacio.mp3"):
            self.assertFalse(self.m.cargar(str(CORPUS / nombre)), nombre)
        self.assertEqual([e[0] for e in self.errores], ["basura.mp3", "vacio.mp3"])
        self.assertFalse(self.m.activo)

    def test_etiqueta_sin_audio_avisa_y_no_termina_como_si_nada(self):
        self.m.cargar(str(CORPUS / "solo_etiqueta.mp3"))
        espera(1.5, lambda: self.errores)
        self.assertEqual(len(self.errores), 1)
        self.assertEqual(self.fines, [])                                # no es un fin de pista normal
        self.assertFalse(self.m.reproduciendo)

    def test_truncado_suena_hasta_donde_hay_y_termina_una_vez(self):
        self.m.cargar(str(CORPUS / "roto_truncado.mp3"))
        self.assertTrue(espera(8.0, lambda: self.fines))
        espera(0.5)
        self.assertEqual(len(self.fines), 1)
        self.assertEqual(self.errores, [])

    def test_un_archivo_malo_corta_el_que_suena_pero_no_el_motor(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(0.8)
        self.assertFalse(self.m.cargar(str(CORPUS / "basura.mp3")))
        espera(0.5)
        n = len(self.bloques)
        espera(0.4)
        self.assertLess(float(np.abs(self.audio(n)).max()), 1e-6)       # quedó en silencio
        self.assertTrue(self.m.cargar(str(CORPUS / "tono_44k.mp3")))
        espera(0.8)
        self.assertTrue(self.m.reproduciendo)

    def test_borrar_el_archivo_mientras_suena(self):
        import shutil
        import tempfile
        carpeta = tempfile.mkdtemp()
        ruta = os.path.join(carpeta, "efimero.mp3")
        shutil.copy(CORPUS / "tono_44k.mp3", ruta)
        self.m.cargar(ruta)
        self.assertTrue(espera(3.0, lambda: self.m._idx is not None))
        espera(0.3)
        os.remove(ruta)
        espera(0.4)
        self.assertTrue(self.m.reproduciendo)                           # sigue: el archivo está abierto
        self.assertTrue(self.m.saltar(5.0))                             # y con el índice mapeado hasta se puede saltar
        espera(0.6)
        self.assertAlmostEqual(self.m.posicion(), 5.5, delta=0.5)
        self.assertEqual(self.errores, [])
        self.assertFalse(self.m.cargar(ruta))                           # pero volver a abrirlo ya no se puede
        self.assertEqual(len(self.errores), 1)

    def test_borrar_el_archivo_sin_indice_hace_fallar_el_salto_sin_cortar_el_audio(self):
        import shutil
        import tempfile
        carpeta = tempfile.mkdtemp()
        ruta = os.path.join(carpeta, "efimero.mp3")
        shutil.copy(CORPUS / "tono_44k.mp3", ruta)
        self.m.cargar(ruta)
        espera(0.3)
        self.m._idx = None                                              # (otro formato, o el índice aún no estaba)
        os.remove(ruta)
        self.assertFalse(self.m.saltar(5.0))
        self.assertEqual(len(self.errores), 1)
        espera(0.5)
        self.assertTrue(self.m.reproduciendo)                           # el audio no se cortó por eso

    def test_nunca_cae_al_dispositivo_nulo_sin_pedirlo(self):
        """Sin placa de sonido tiene que avisar, no reproducir en silencio: el dispositivo nulo no figura en la lista."""
        m = S.Motor()
        try:
            self.assertNotIn(miniaudio.Backend.NULL, m.backends)
            self.assertTrue(m.backends)
        finally:
            m.cerrar()
        self.assertEqual(S.Motor(backend=miniaudio.Backend.NULL).backends, [miniaudio.Backend.NULL])   # salvo que se pida

    def test_dispositivo_caido_se_reabre_y_el_tema_sigue(self):
        m = S.Motor(buffer_ms=120, backend=miniaudio.Backend.NULL, vigilancia_s=0.2, umbral_s=0.7)
        bloques = []
        m.espia = bloques.append
        try:
            m.cargar(str(CORPUS / "tono_44k.mp3"))
            espera(1.0)
            antes = m.posicion()
            m._dev.stop()                                               # el dispositivo muere sin avisar
            espera(0.5)
            n = len(bloques)
            self.assertTrue(espera(4.0, lambda: len(bloques) > n + 3), "el audio no volvió")
            espera(0.5)
            self.assertTrue(m.reproduciendo)
            self.assertGreater(m.posicion(), antes)                    # sigue donde estaba, no desde cero
            self.assertLess(m.posicion(), antes + 4.0)
            self.assertGreater(float(np.abs(bloques[-1]).max()), 0.1)
        finally:
            m.cerrar()

    def test_placa_ausente_avisa_una_vez_y_reintenta(self):
        reales = S.miniaudio.PlaybackDevice
        intentos = []

        class Falsa(reales):
            def __init__(self, *a, **k):
                intentos.append(1)
                if len(intentos) <= 3:
                    self.running, self._device, self.callback_generator, self.stop_callback = False, None, None, None
                    raise miniaudio.MiniaudioError("no hay placa")
                super().__init__(*a, **k)

        S.miniaudio.PlaybackDevice = Falsa
        m = S.Motor(buffer_ms=120, backend=miniaudio.Backend.NULL, vigilancia_s=0.1, reintento_s=0.3)
        avisos = []
        m.error_dispositivo.connect(avisos.append)
        try:
            m.cargar(str(CORPUS / "tono_44k.mp3"))
            self.assertEqual(len(avisos), 1)
            self.assertTrue(espera(5.0, lambda: m._dev is not None), "nunca reabrió")
            espera(1.0)
            self.assertEqual(len(avisos), 1)                            # no se repite el aviso en cada intento
            self.assertTrue(m.reproduciendo)
        finally:
            S.miniaudio.PlaybackDevice = reales
            m.cerrar()

    @unittest.skipUnless(os.path.isdir("/proc/self/fd"), "solo en Linux")
    def test_no_se_pierden_archivos_abiertos(self):
        ruta = str(CORPUS / "tono_44k.mp3")
        self.m.cargar(ruta)
        espera(0.5)
        base = len(os.listdir("/proc/self/fd"))
        for i in range(60):
            self.m.cargar(ruta)
            self.m.saltar(1.0 + (i % 7))
            espera(0.01)
        espera(2.5)                                                     # los archivos mapeados se cierran al segundo
        self.assertLessEqual(len(os.listdir("/proc/self/fd")) - base, 6)


@unittest.skipUnless(glob.glob(os.path.expanduser("~/Música/*.mp3")), "no hay mp3 reales en ~/Música")
class TestArchivosReales(Base):
    """El salto por índice contra el salto exacto (lento) de miniaudio, con mp3 de verdad. Solo lectura."""

    def test_indice_coincide_con_el_salto_exacto(self):
        F32 = miniaudio.SampleFormat.FLOAT32
        archivos = sorted(glob.glob(os.path.expanduser("~/Música/*.mp3")), key=os.path.getsize)[-4:]
        peor = 0
        for ruta in archivos:
            self.m.cargar(ruta)
            self.assertTrue(espera(5.0, lambda: self.m._idx is not None), ruta)
            dur = self.m.duracion
            for frac in (0.0005, 0.02, 0.05, 0.3, 0.6, 0.95, 0.999):
                frame = int(frac * (dur - 3) * S.FS)
                a = S._leer(self.m._fuente_en(ruta, frame), 4096)[:, 0]
                b = S._leer(miniaudio.stream_file(ruta, output_format=F32, nchannels=2, sample_rate=S.FS,
                                                  frames_to_read=1024, seek_frame=frame), 4096)[:, 0]
                n = min(len(a), len(b))
                c = np.fft.irfft(np.fft.rfft(a[:n] - a[:n].mean(), 2 * n) * np.conj(np.fft.rfft(b[:n] - b[:n].mean(), 2 * n)))
                k = int(np.argmax(c))
                lag = k if k < n else k - 2 * n
                peor = max(peor, abs(lag))
                print(f"   {os.path.basename(ruta)[:40]:40s} {frac*100:3.0f}%: desfase {lag:+d} muestras")
        self.assertLessEqual(peor, 64, "el salto por índice se desvía del salto exacto de miniaudio (más de 1,5 ms)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
