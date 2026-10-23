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


class TestRemuestreo(unittest.TestCase):
    """El remuestreador propio (lo que no es de 44,1 kHz): respuesta plana, sin alias y con el largo justo."""
    class Gen:
        def __init__(self, x):
            self.x, self.i = x, 0

        def send(self, n):
            a = self.x[self.i:self.i + n]
            self.i += n
            if len(a) == 0:
                raise StopIteration
            return np.ascontiguousarray(a, np.float32).tobytes()

    def pasar(self, x, f_ent):
        return S._leer(S.Remuestreador(self.Gen(x), f_ent), len(x) * 2)

    def tono(self, f, f_ent, seg=2):
        s = np.sin(2 * np.pi * f / f_ent * np.arange(f_ent * seg)).astype(np.float32)
        return np.stack([s, s], 1)

    def test_respuesta_plana_hasta_20k_y_sin_alias(self):
        for f in (1000, 10000, 18000, 20000):
            y = self.pasar(self.tono(f, 48000), 48000)[4410:-4410, 0].astype(np.float64)
            F = np.abs(np.fft.rfft(y * np.hanning(len(y))))
            fr = np.fft.rfftfreq(len(y), 1 / S.FS)
            k = np.argmin(np.abs(fr - f))
            pico = F[k - 3:k + 4].max()
            ref = np.abs(np.fft.rfft(np.sin(2 * np.pi * f / S.FS * np.arange(len(y))) * np.hanning(len(y))))[k - 3:k + 4].max()
            self.assertAlmostEqual(20 * np.log10(pico / ref), 0.0, delta=0.05, msg=f"{f} Hz")
            self.assertLess(20 * np.log10(F[np.abs(fr - f) > 300].max() / pico), -90, f"alias con {f} Hz")

    def test_lo_que_pasa_de_nyquist_se_rechaza(self):
        y = self.pasar(self.tono(23000, 48000), 48000)
        self.assertLess(float(np.abs(y[3000:-3000]).max()), 1e-4)

    def test_largo_exacto_en_las_frecuencias_comunes(self):
        for f_ent in (22050, 32000, 48000, 88200, 96000, 192000):
            x = np.zeros((f_ent + 37, 2), np.float32)
            self.assertAlmostEqual(len(self.pasar(x, f_ent)), round(len(x) * S.FS / f_ent), delta=1, msg=str(f_ent))

    def test_da_lo_mismo_pidiendo_en_trozos_de_cualquier_tamano(self):
        x = (np.random.default_rng(3).standard_normal((48000, 2)) * 0.1).astype(np.float32)
        entero = self.pasar(x, 48000)
        r, partes, tam, k = S.Remuestreador(self.Gen(x), 48000), [], [1, 7, 1024, 333, 4096, 2], 0
        while True:
            try:
                partes.append(np.frombuffer(r.send(tam[k % len(tam)]), np.float32).reshape(-1, 2))
            except StopIteration:
                break
            k += 1
        self.assertTrue(np.array_equal(np.concatenate(partes), entero))

    def test_entradas_cortas_y_vacia(self):
        for n in (0, 1, 5, 100):
            self.assertAlmostEqual(len(self.pasar(np.zeros((n, 2), np.float32), 48000)), round(n * S.FS / 48000), delta=1)

    def test_44k_no_se_toca(self):
        self.assertIsInstance(S.abrir_fuente(str(CORPUS / "tono_44k.mp3")), type(miniaudio.stream_file(str(CORPUS / "tono_44k.mp3"))))
        self.assertIsInstance(S.abrir_fuente(str(CORPUS / "tono_48k.mp3")), S.Remuestreador)


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


class TestFundidos(Base):
    """Pausa, parar y cerrar bajan el volumen de a poco (~250 ms) y reanudar lo sube (~150 ms): antes cortaban en 5 ms."""

    @staticmethod
    def envolvente(x, ventana=441):
        """Pico de cada 10 ms."""
        n = len(x) // ventana
        return np.abs(x[:n * ventana]).reshape(n, ventana).max(axis=1)

    def test_pausa_baja_de_a_poco(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(1.0)
        n = len(self.bloques)
        self.m.pausar()
        espera(0.9)
        env = self.envolvente(self.audio(n))
        sonando_ms = int((env > 0.02).sum()) * 10
        self.assertGreater(sonando_ms, 180)            # la bajada dura ~250 ms (más lo que ya estaba en el bloque)
        self.assertLess(sonando_ms, 600)
        self.assertLess(float(np.abs(np.diff(env)).max()), 0.15)   # y no hay un escalón: cada 10 ms cae poco
        self.assertLess(float(env[-10:].max()), 1e-6)

    def test_reanudar_sube_de_a_poco(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(0.8)
        self.m.pausar()
        espera(0.8)
        n = len(self.bloques)
        self.m.reanudar()
        espera(0.8)
        env = self.envolvente(self.audio(n))
        tope = float(env.max())
        i0 = int(np.argmax(env > 0.02))                # dónde empieza a oírse
        i90 = int(np.argmax(env > 0.9 * tope))
        self.assertGreater((i90 - i0) * 10, 80)        # tarda en llegar al volumen (~150 ms), no es un golpe
        self.assertLess(float(np.abs(np.diff(env)).max()), 0.15)

    def test_parar_baja_de_a_poco_y_despues_deja_todo_en_cero(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(1.0)
        n = len(self.bloques)
        self.m.parar()
        self.assertFalse(self.m.reproduciendo)         # para quien mira, ya está parado
        self.assertTrue(espera(1.5, lambda: not self.m.activo))
        espera(0.3)
        env = self.envolvente(self.audio(n))
        self.assertGreater(int((env > 0.02).sum()) * 10, 180)
        self.assertLess(float(np.abs(np.diff(env)).max()), 0.15)
        self.assertEqual(self.m.posicion(), 0.0)

    def test_cargar_cancela_un_parar_que_esperaba(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(0.8)
        self.m.parar()
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(1.0)
        self.assertTrue(self.m.reproduciendo)
        self.assertTrue(self.m.activo)

    def test_cerrar_baja_el_volumen_antes_de_cortar(self):
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(1.0)
        n = len(self.bloques)
        t = time.time()
        self.m.cerrar()
        dt = time.time() - t
        self.assertGreater(dt, 0.2)                    # esperó el fundido
        self.assertLess(dt, 1.0)
        fin = self.audio(n)
        self.assertLess(float(np.abs(fin[-2000:]).max()), 0.02)    # lo último que salió ya es casi silencio


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


MUSICA_REAL = os.path.expanduser(os.environ.get("SIMPLEPLAY_MUSICA", "~/Música"))   # donde están tus mp3 de verdad


@unittest.skipUnless(glob.glob(os.path.join(MUSICA_REAL, "*.mp3")), "no hay mp3 reales (SIMPLEPLAY_MUSICA=carpeta)")
class TestArchivosReales(Base):
    """El salto por índice contra el salto exacto (lento) de miniaudio, con mp3 de verdad. Solo lectura."""

    def test_indice_coincide_con_el_salto_exacto(self):
        F32 = miniaudio.SampleFormat.FLOAT32
        archivos = sorted(glob.glob(os.path.join(MUSICA_REAL, "*.mp3")), key=os.path.getsize)[-4:]
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


class TestCadena(unittest.TestCase):
    """Normalización, ecualizador y limitador (S.Cadena y las funciones de medición)."""

    @staticmethod
    def tono(f, a, seg=2.0):
        t = np.arange(int(S.FS * seg)) / S.FS
        x = (a * np.sin(2 * np.pi * f * t)).astype(np.float32)
        return np.stack([x, x], 1)

    @staticmethod
    def pasar(c, x, bloque=4410):
        return np.concatenate([c.procesar(x[i:i + bloque]) for i in range(0, len(x), bloque)])

    @staticmethod
    def db(y):
        y = y[S.FS // 2:]
        return 20 * np.log10(float(np.sqrt(np.mean(y ** 2))) + 1e-12)

    def respuesta(self, preset, f):
        c = S.Cadena()
        c.poner_eq(S.PRESETS[preset])
        x = self.tono(f, 0.1)
        return self.db(self.pasar(c, x)) - self.db(x)

    def test_plano_no_toca_el_audio(self):
        c = S.Cadena()
        self.assertFalse(c.activa)
        c.poner_eq(S.PRESETS["plano"])
        self.assertFalse(c.activa)
        x = self.tono(1000, 0.1)
        self.assertTrue(np.array_equal(self.pasar(c, x), x))

    def test_el_ecualizador_aplica_las_ganancias_del_preset(self):
        # "graves": +6 dB en 31 Hz y +5 en 62 Hz, y todo baja 0,5 de lo que sube (preamp) para no saturar
        sube = max(S.PRESETS["graves"])
        pre = -0.5 * sube
        for f, esperado in ((62, 5.0 + pre), (125, 3.5 + pre), (1000, 0.0 + pre), (8000, 0.0 + pre)):
            self.assertAlmostEqual(self.respuesta("graves", f), esperado, delta=0.6, msg=f"{f} Hz")

    def test_los_agudos_del_preset_brillante_suben(self):
        self.assertGreater(self.respuesta("brillante", 8000), self.respuesta("brillante", 250) + 4.0)

    def test_ganancia_de_pista(self):
        c = S.Cadena()
        c.poner_ganancia(6.0)
        x = self.tono(1000, 0.1)
        self.assertAlmostEqual(self.db(self.pasar(c, x)) - self.db(x), 6.0, delta=0.1)

    def test_el_limitador_nunca_pasa_de_uno(self):
        c = S.Cadena()
        c.poner_ganancia(9.0)
        y = self.pasar(c, self.tono(1000, 0.9))
        self.assertLessEqual(float(np.abs(y).max()), S.LIM_TECHO + 1e-6)
        self.assertGreater(float(np.abs(y).max()), S.LIM_TECHO - 0.01)   # y sí sube: comprime hasta el techo, no aplasta

    def test_cambiar_de_preset_en_marcha_no_hace_clicks(self):
        c = S.Cadena()
        x = self.tono(440, 0.3, 3.0)
        salida = []
        for i in range(0, len(x), 4410):
            if i == 4410 * 10:
                c.poner_eq(S.PRESETS["vivo"])
            if i == 4410 * 20:
                c.poner_eq(S.PRESETS["graves"])
            if i == 4410 * 30:
                c.poner_eq(S.PRESETS["plano"])
            salida.append(c.procesar(x[i:i + 4410]))
        y = np.concatenate(salida)
        natural = 2 * np.pi * 440 / S.FS * 0.3                 # el salto más grande entre dos muestras de la señal
        self.assertLess(float(np.abs(np.diff(y[:, 0])).max()), natural * 1.5)

    def test_la_sonoridad_distingue_un_tema_fuerte_de_uno_suave(self):
        import tempfile, wave
        d = tempfile.mkdtemp()

        def wav(nombre, a):
            p = os.path.join(d, nombre)
            x = (self.tono(1000, a, 10.0) * 32767).astype("<i2")
            with wave.open(p, "wb") as w:
                w.setnchannels(2); w.setsampwidth(2); w.setframerate(S.FS)
                w.writeframes(x.tobytes())
            return p
        suave, fuerte = S.medir_tema(wav("s.wav", 0.05), 10), S.medir_tema(wav("f.wav", 0.2), 10)
        self.assertAlmostEqual(fuerte[0] - suave[0], 12.04, delta=0.3)       # 4 veces la amplitud = 12 dB
        # y con la ganancia que se les calcula, los dos terminan en la misma sonoridad
        self.assertAlmostEqual(fuerte[0] + S.ganancia_para(*fuerte), S.OBJETIVO_LUFS, delta=0.3)
        self.assertLessEqual(S.ganancia_para(*suave), S.GANANCIA_MAX_DB)

    def test_el_silencio_no_se_mide(self):
        self.assertIsNone(S._sonoridad([np.zeros((S.FS * 2, 2), np.float32)]))

    def test_replaygain_de_las_etiquetas(self):
        import shutil, tempfile
        from mutagen.id3 import ID3, TXXX
        ruta = os.path.join(tempfile.mkdtemp(), "rg.mp3")
        shutil.copy(CORPUS / "tono_44k.mp3", ruta)
        self.assertIsNone(S.leer_replaygain(ruta))
        t = ID3(ruta)
        t.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_GAIN", text="-6.50 dB"))
        t.save(ruta)
        self.assertAlmostEqual(S.leer_replaygain(ruta), -6.5 + (S.OBJETIVO_LUFS + 18.0), delta=0.01)


class TestCandidatosEscoba(unittest.TestCase):
    """Cómo se separan artista y título del nombre del archivo antes de buscarlos en MusicBrainz."""

    def test_el_numero_de_lista_no_es_el_artista(self):
        for nombre in ("391 - Boom Boom Kid - I Do.mp3", "391. Boom Boom Kid - I Do.mp3", "07) Boom Boom Kid - I Do.mp3"):
            c = S.candidatos("/x/" + nombre, None, None)
            self.assertEqual(c[0], ("Boom Boom Kid", "I Do"), nombre)
            self.assertNotIn("391", [a for a, _ in c] + [t for _, t in c])

    def test_bandas_que_empiezan_con_numero_siguen_andando(self):
        self.assertEqual(S.candidatos("/x/3 Doors Down - Kryptonite (Official Video) [xPU8OAjjS4k].mp3", None, None)[0],
                         ("3 Doors Down", "Kryptonite"))
        # "311 - Amber": sin el número queda solo "Amber" (sin artista), así que se prueba también la banda 311
        self.assertIn(("311", "Amber"), S.candidatos("/x/311 - Amber.mp3", None, None))

    def test_con_etiquetas_y_numero_en_el_nombre_usa_el_artista_de_la_etiqueta(self):
        self.assertIn(("Los Redondos", "Morena"), S.candidatos("/x/185 - Morena.mp3", None, "Los Redondos"))

    def test_nombre_limpio_sigue_igual(self):
        self.assertEqual(S.candidatos("/x/Ram Jam - Black Betty (Official Video) [I_2D8Eo15wE].mp3", None, None)[0],
                         ("Ram Jam", "Black Betty"))


class TestRendimiento(unittest.TestCase):
    """Que lo que se hizo para gastar menos siga dando lo mismo."""

    @staticmethod
    def bandas_db_de_antes(v):
        mag = np.abs(np.fft.rfft(v * S._HANN)) / (S.VENTANA / 4)
        res = S.FS / S.VENTANA
        out = np.empty(S.BANDAS)
        for k in range(S.BANDAS):
            a, b = S._BORDES[k], S._BORDES[k + 1]
            lo = int(a / res)
            hi = max(int(b / res), lo + 1)
            out[k] = 20 * np.log10(mag[lo:hi].max() + 1e-9) + 3 * np.log2(np.sqrt(a * b) / 100)
        return out

    def test_el_espectro_vectorizado_da_lo_mismo_que_el_bucle(self):
        rng = np.random.default_rng(7)
        t = np.arange(S.VENTANA) / S.FS
        casos = [rng.standard_normal(S.VENTANA).astype(np.float32) * 0.1,
                 (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32),
                 (0.3 * np.sin(2 * np.pi * 60 * t) + 0.2 * np.sin(2 * np.pi * 5000 * t)).astype(np.float32),
                 np.zeros(S.VENTANA, np.float32)]
        for v in casos:
            self.assertTrue(np.allclose(S.bandas_db(v), self.bandas_db_de_antes(v), atol=1e-9, rtol=0))

    def test_volver_a_plano_apaga_el_filtro_sin_clicks_y_deja_el_audio_intacto(self):
        c = S.Cadena()
        t = np.arange(S.FS * 3) / S.FS
        x = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        x = np.stack([x, x], 1)
        salida = []
        for i in range(0, len(x), 4410):
            if i == 4410 * 5:
                c.poner_eq(S.PRESETS["vivo"])
            if i == 4410 * 15:
                c.poner_eq(S.PRESETS["plano"])
            salida.append(c.procesar(x[i:i + 4410]))
            if i == 4410 * 14:
                self.assertTrue(c.activa)
        y = np.concatenate(salida)
        self.assertFalse(c.activa)                                   # el filtro dejó de correr
        self.assertIsNone(c._h)
        self.assertTrue(np.array_equal(y[-4410 * 5:], x[-4410 * 5:]))   # y el audio pasa tal cual otra vez
        natural = 2 * np.pi * 440 / S.FS * 0.3
        self.assertLess(float(np.abs(np.diff(y[:, 0])).max()), natural * 1.5)


class TestLimitador(unittest.TestCase):
    """El limitador con anticipación de la cadena: techo firme, sin distorsión, igual en cualquier tamaño de bloque."""
    @staticmethod
    def tono(f, a, seg=2.0):
        x = (a * np.sin(2 * np.pi * f * np.arange(int(S.FS * seg)) / S.FS)).astype(np.float32)
        return np.stack([x, x], 1)

    @staticmethod
    def pasar(c, x, bloque=1024):
        return np.concatenate([c.procesar(x[i:i + bloque]) for i in range(0, len(x), bloque)])

    def cadena(self, db):
        c = S.Cadena()
        c.poner_ganancia(db)
        return c

    def test_el_techo_vale_siempre_hasta_con_ruido_muy_fuerte(self):
        x = (np.random.default_rng(5).standard_normal((S.FS * 2, 2)) * 0.5).astype(np.float32)
        y = self.pasar(self.cadena(9.0), x)
        self.assertLessEqual(float(np.abs(y).max()), S.LIM_TECHO + 1e-6)

    def test_un_tono_limitado_no_se_distorsiona(self):
        y = self.pasar(self.cadena(6.0), self.tono(1000, 0.5, 3.0))[S.FS:, 0].astype(np.float64)
        F = np.abs(np.fft.rfft(y * np.hanning(len(y))))
        fr = np.fft.rfftfreq(len(y), 1 / S.FS)
        f1 = F[np.argmin(np.abs(fr - 1000)) - 3:np.argmin(np.abs(fr - 1000)) + 4].max()
        for h in (2, 3, 5):
            k = np.argmin(np.abs(fr - 1000 * h))
            self.assertLess(20 * np.log10(F[k - 3:k + 4].max() / f1), -90, f"armónico {h}")

    def test_da_lo_mismo_con_bloques_de_cualquier_tamano(self):
        t = np.arange(S.FS * 3) / S.FS
        x = (self.tono(100, 0.5, 3.0) * (1 + 0.8 * np.sin(2 * np.pi * 3 * t))[:, None]).astype(np.float32)
        ref = self.pasar(self.cadena(6.0), x, 4410)[S.FS:]   # pasada la rampa inicial y la memoria de la suelta
        for b in (64, 333, 1024, 8192):
            self.assertEqual(float(np.abs(self.pasar(self.cadena(6.0), x, b)[S.FS:] - ref).max()), 0.0, f"bloque {b}")

    def test_los_dos_canales_bajan_juntos(self):
        x = np.zeros((S.FS, 2), np.float32)
        x[:, 1] = 0.2 * np.sin(2 * np.pi * 500 * np.arange(S.FS) / S.FS)
        x[20000:20100, 0] = 1.4
        y = self.pasar(self.cadena(0.1), x)
        D = S.LIM_ANTICIPO - 1
        gan = 10 ** (0.1 / 20)
        g_quieto = np.abs(y[D + 40000:D + 42000, 1]).max() / (np.abs(x[40000:42000, 1]).max() * gan)   # lejos del golpe: sin reducción
        g_golpe = np.abs(y[D + 20000:D + 20400, 1]).max() / (np.abs(x[20000:20400, 1]).max() * gan)
        self.assertAlmostEqual(g_quieto, 1.0, delta=0.01)
        self.assertLess(g_golpe, 0.75)                                          # el canal tranquilo también bajó con el golpe

    def test_la_ganancia_vuelve_a_uno_despues_de_un_pico(self):
        x = self.tono(440, 0.3, 3.0)
        x[20000:20050] = 1.5
        y = self.pasar(self.cadena(0.1), x)
        D = S.LIM_ANTICIPO - 1
        i = S.FS * 2
        self.assertTrue(np.allclose(y[i + D:i + D + 4000], x[i:i + 4000] * 10 ** (0.1 / 20), atol=1e-4))

    def test_prender_y_apagar_la_cadena_no_hace_clicks(self):
        x = self.tono(440, 0.3, 3.0)
        c, sal = S.Cadena(), []
        for i in range(0, len(x), 1024):
            if i == 1024 * 40:
                c.poner_ganancia(3.0)
            if i == 1024 * 80:
                c.poner_ganancia(0.0)
            sal.append(c.procesar(x[i:i + 1024]))
        y = np.concatenate(sal)
        self.assertLess(float(np.abs(np.diff(y[:, 0])).max()), 2 * np.pi * 440 / S.FS * 0.3 * 1.5)
        self.assertFalse(c.activa)
        self.assertTrue(np.array_equal(y[-4410:], x[-4410:]))                  # apagada: el audio vuelve tal cual, sin retraso

    def test_sin_nada_que_hacer_el_audio_pasa_intacto(self):
        c, x = S.Cadena(), self.tono(440, 0.95, 1.0)
        self.assertTrue(np.array_equal(c.procesar(x), x))


class TestPrecisionDeGraves(unittest.TestCase):
    """El filtro del ecualizador cumple la curva pedida también en los graves, sin retraso."""
    def respuesta(self, h, f0):
        f = np.fft.rfftfreq(65536, 1 / S.FS)
        return 20 * np.log10(np.abs(np.fft.rfft(h, 65536))[np.argmin(np.abs(f - f0))] + 1e-12)

    def test_una_banda_de_graves_llega_casi_a_lo_pedido(self):
        if S.FASE_EQ != "minima":
            self.skipTest("solo con la fase mínima (la lineal tiene menos resolución en graves)")
        for k, f0 in ((0, 31), (1, 62), (2, 125)):
            g = [0.0] * 10
            g[k] = 6.0
            self.assertGreater(self.respuesta(S._taps_ecualizador(g), f0), 5.7, f"+6 dB en {f0} Hz")   # antes: 4,8 / 4,2 / 5,1
            g[k] = -6.0
            self.assertLess(self.respuesta(S._taps_ecualizador(g), f0), -5.7, f"-6 dB en {f0} Hz")

    def test_los_presets_salen_clavados(self):
        f = np.fft.rfftfreq(65536, 1 / S.FS)
        marca = (f >= 25) & (f <= 20000)
        for nombre, g in S.PRESETS.items():
            if not any(g):
                continue
            H = 20 * np.log10(np.abs(np.fft.rfft(S._taps_ecualizador(g), 65536)) + 1e-12)
            pedido = np.interp(np.log10(f[marca]), np.log10(S.BANDAS_HZ), g)
            self.assertLess(float(np.abs(H[marca] - pedido).max()), 0.15 if S.FASE_EQ == "minima" else 0.5, nombre)

    def test_sin_retraso_con_fase_minima(self):
        if S.FASE_EQ != "minima":
            self.skipTest("solo con la fase mínima")
        h = S._taps_ecualizador(S.PRESETS["graves"])
        self.assertLess(int(np.argmax(np.abs(h))), 50)               # la respuesta empieza al principio, no en el medio
        c = S.Cadena()
        c.poner_eq(S.PRESETS["graves"])
        x = np.zeros((4410, 2), np.float32)
        x[1000] = 1.0                                                  # un impulso
        y = np.concatenate([c.procesar(x), c.procesar(np.zeros_like(x))])
        self.assertLess(abs(int(np.argmax(np.abs(y[:, 0]))) - (1000 + S.LIM_ANTICIPO - 1)), 5)   # el EQ no agrega nada: solo el retraso del limitador


class TestPerfilesDeAuriculares(unittest.TestCase):
    """Los perfiles de AutoEq: lectura, filtro, nivel, índice."""

    def setUp(self):
        sys.path.insert(0, str(Path(__file__).parent))
        import datos_autoeq
        self.D = datos_autoeq

    def respuesta_del_filtro(self, freqs, gan):
        h = S._taps_ecualizador(gan, freqs)
        H = 20 * np.log10(np.abs(np.fft.rfft(h, 65536)) + 1e-12)
        return np.interp(freqs, np.fft.rfftfreq(65536, 1 / S.FS), H)

    def test_se_lee_el_perfil_grafico_del_m20x(self):
        f, g = S.leer_perfil(self.D.M20X_GRAFICO)
        self.assertGreater(len(f), 100)
        self.assertEqual(f, sorted(f))
        self.assertLessEqual(f[0], 21)
        self.assertGreaterEqual(f[-1], 19000)
        self.assertLessEqual(max(g), 0.0)                              # el preamp ya viene metido: nada pasa de 0 dB
        self.assertLess(min(g), -8.0)

    def test_el_filtro_reproduce_la_correccion_del_m20x(self):
        f, g = S.leer_perfil(self.D.M20X_GRAFICO)
        err = np.abs(self.respuesta_del_filtro(f, g) - np.array(g))[np.array(f) >= 25]
        self.assertLess(float(err.mean()), 0.3)                         # en promedio, imperceptible
        self.assertLess(float(err.max()), 1.5)                          # y en lo peor (el sub-grave), poco

    def test_el_formato_parametrico_da_la_misma_curva_que_el_grafico(self):
        fg, gg = S.leer_perfil(self.D.M20X_GRAFICO)
        fp, gp = S.leer_perfil(self.D.M20X_PARAMETRICO)
        self.assertEqual(len(fp), 127)
        diff = np.array(gp) - np.interp(np.log10(fp), np.log10(fg), gg)
        self.assertLess(float(np.abs(diff).mean()), 1.0)
        self.assertLess(float(np.abs(diff).max()), 2.5)

    def test_los_filtros_parametricos_hacen_lo_que_dicen(self):
        fr = np.array([20.0, 100.0, 1000.0, 10000.0])
        pk = S._respuesta_biquad("PK", 1000, 6.0, 1.0, fr)
        self.assertAlmostEqual(float(pk[2]), 6.0, delta=0.05)           # +6 dB justo en su frecuencia
        self.assertLess(abs(float(pk[0])), 0.3)
        bajo = S._respuesta_biquad("LSC", 100, 6.0, 0.7, fr)
        self.assertGreater(float(bajo[0]), 5.5)                         # el estante de graves sube lo grave...
        self.assertLess(abs(float(bajo[3])), 0.3)                       # ...y no toca lo agudo
        alto = S._respuesta_biquad("HSC", 5000, -4.0, 0.7, fr)
        self.assertLess(float(alto[3]), -3.5)
        self.assertLess(abs(float(alto[0])), 0.3)

    def test_un_archivo_que_no_es_un_perfil_da_error(self):
        for basura in ("", "hola mundo", "GraphicEQ: ", "Preamp: -3 dB"):
            with self.assertRaises(ValueError):
                S.leer_perfil(basura)

    def test_nivel_relativo_de_una_curva(self):
        f = [20, 20000]
        self.assertAlmostEqual(S.nivel_relativo_db(f, [0, 0]), 0.0, places=6)
        self.assertAlmostEqual(S.nivel_relativo_db(f, [-6, -6]), -6.0, places=6)
        fm, gm = S.leer_perfil(self.D.M20X_GRAFICO)
        self.assertTrue(-9 < S.nivel_relativo_db(fm, gm) < -3)          # el M20x baja el nivel general

    def test_el_indice_se_lee_y_se_busca_sin_mayusculas_ni_acentos(self):
        e = S.indice_autoeq(self.D.INDICE)
        self.assertEqual(len(e), 6)
        self.assertIn(("1MORE Aero (ANC Off)", "HypetheSonics on GRAS RA0045",
                       "HypetheSonics/GRAS RA0045 in-ear/1MORE Aero (ANC Off)"), e)    # los paréntesis del nombre no rompen
        r = S.buscar_en_indice(e, "m20X")
        self.assertEqual([x[1] for x in r], ["oratory1990", "Rtings on HMS II.3"])    # oratory1990 primero
        self.assertEqual([x[0] for x in S.buscar_en_indice(e, "audio technica m50")], ["Audio-Technica ATH-M50x"])
        self.assertEqual(S.buscar_en_indice(e, "no existe este modelo"), [])
        self.assertEqual(S.buscar_en_indice(e, "   "), [])

    def test_la_direccion_del_perfil(self):
        e = S.indice_autoeq(self.D.INDICE)
        ruta = next(x[2] for x in e if x[1] == "oratory1990" and "M20x" in x[0])
        self.assertEqual(S.url_perfil(ruta), "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results/"
                         "oratory1990/over-ear/Audio-Technica%20ATH-M20x/Audio-Technica%20ATH-M20x%20GraphicEQ.txt")

    def test_el_motor_aplica_un_perfil_con_su_compensacion_de_nivel(self):
        t = np.arange(S.FS * 2) / S.FS
        x = np.stack([(0.1 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)] * 2, 1)
        f, g = S.leer_perfil(self.D.M20X_GRAFICO)
        c = S.Cadena()
        c.poner_eq(g, freqs=f, makeup_db=3.0)
        y = np.concatenate([c.procesar(x[i:i + 4410]) for i in range(0, len(x), 4410)])
        medido = 20 * np.log10(np.sqrt(np.mean(y[S.FS // 2:] ** 2)) / np.sqrt(np.mean(x[S.FS // 2:] ** 2)))
        esperado = float(np.interp(np.log10(1000), np.log10(f), g)) + 3.0
        self.assertAlmostEqual(medido, esperado, delta=0.5)
        c.poner_eq(None)                                                # y volver a plano lo apaga
        for i in range(0, 8820, 4410):
            c.procesar(x[i:i + 4410])
        self.assertFalse(c.activa)


class TestFlac(Base):
    """El motor y las funciones de apoyo con archivos FLAC (datos de prueba inventados)."""

    def test_un_flac_suena_con_el_tono_y_el_nivel_correctos(self):
        self.m.cargar(str(CORPUS / "tono_16.flac"))
        espera(1.2)
        self.assertTrue(self.m.reproduciendo)
        x = self.audio()[-8192:]
        self.assertAlmostEqual(frecuencia(x), 440, delta=6)
        self.assertAlmostEqual(float(np.abs(x).max()), 0.5, delta=0.03)       # el seno de amplitud 0,5, sin tocar
        self.assertAlmostEqual(self.m.duracion, 10.0, delta=0.1)

    def test_un_flac_de_24_bits_a_96_khz_suena_afinado_y_dura_lo_mismo(self):
        self.m.cargar(str(CORPUS / "tono_24_96k.flac"))
        espera(1.2)
        self.assertAlmostEqual(frecuencia(self.audio()[-8192:]), 440, delta=6)    # se convierte a 44,1 kHz sin desafinar
        self.assertAlmostEqual(self.m.duracion, 10.0, delta=0.1)
        self.assertAlmostEqual(float(np.abs(self.audio()[-8192:]).max()), 0.5, delta=0.03)

    def test_el_flac_suena_igual_que_el_mp3_del_mismo_tono(self):
        self.m.cargar(str(CORPUS / "tono_16.flac"))
        espera(1.0)
        a = float(np.sqrt(np.mean(self.audio()[-16384:] ** 2)))
        n = len(self.bloques)
        self.m.cargar(str(CORPUS / "tono_44k.mp3"))
        espera(1.0)
        b = float(np.sqrt(np.mean(self.audio(n)[-16384:] ** 2)))
        self.assertAlmostEqual(20 * np.log10(a / b), 0.0, delta=0.5)

    def test_se_puede_saltar_dentro_de_un_flac(self):
        self.m.cargar(str(CORPUS / "tono_16.flac"))
        espera(0.5)
        self.assertTrue(self.m.saltar(6.0))
        espera(0.6)
        self.assertAlmostEqual(self.m.posicion(), 6.4, delta=0.5)
        self.assertAlmostEqual(frecuencia(self.audio()[-8192:]), 440, delta=6)

    def test_al_terminar_un_flac_avisa_una_sola_vez(self):
        self.m.cargar(str(CORPUS / "corto_2s.flac"))
        self.assertTrue(espera(4.0, lambda: bool(self.fines)))
        espera(0.5)
        self.assertEqual(len(self.fines), 1)

    def test_las_etiquetas_y_la_tapa_del_flac(self):
        e = S.etiquetas_de(str(CORPUS / "con_etiquetas.flac"), con_portada=True)
        self.assertEqual((e["titulo"], e["artista"], e["album"], e["pista"]),
                         ("Tema de prueba", "Artista de prueba", "Álbum de prueba", 3))
        self.assertTrue(e["portada"] and e["portada"][:4] == b"\x89PNG")           # la carátula es un PNG
        self.assertEqual(S.leer_meta(str(CORPUS / "con_etiquetas.flac"))[:2], ("Tema de prueba", "Artista de prueba"))
        sin = S.etiquetas_de(str(CORPUS / "tono_16.flac"), con_portada=True)
        self.assertEqual((sin["titulo"], sin["artista"], sin["pista"], sin["portada"]), ("", "", 0, None))
        self.assertEqual(S.leer_meta(str(CORPUS / "tono_16.flac"))[0], "tono_16")        # sin título: el nombre del archivo

    def test_los_mp3_siguen_leyendo_sus_etiquetas(self):
        import shutil, tempfile
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, TRCK, APIC
        ruta = os.path.join(tempfile.mkdtemp(), "t.mp3")
        shutil.copy(CORPUS / "tono_44k.mp3", ruta)
        t = ID3()
        t.add(TIT2(encoding=3, text="Otro tema"))
        t.add(TPE1(encoding=3, text="Otro artista"))
        t.add(TALB(encoding=3, text="Otro álbum"))
        t.add(TRCK(encoding=3, text="7/12"))
        t.add(APIC(encoding=3, mime="image/png", type=3, desc="", data=b"\x89PNGfalso"))
        t.save(ruta)
        e = S.etiquetas_de(ruta, con_portada=True)
        self.assertEqual((e["titulo"], e["artista"], e["album"], e["pista"], e["portada"]),
                         ("Otro tema", "Otro artista", "Otro álbum", 7, b"\x89PNGfalso"))
        d = S.datos_lista(ruta)
        self.assertEqual((d["nombre"], d["pista"]), ("Otro artista - Otro tema", 7))

    def test_la_duracion_de_mp3_y_flac(self):
        self.assertAlmostEqual(S.duracion_de(str(CORPUS / "tono_16.flac")), 10.0, delta=0.05)
        self.assertAlmostEqual(S.duracion_de(str(CORPUS / "tono_44k.mp3")), 10.0, delta=0.2)
        self.assertEqual(S.duracion_de(str(CORPUS / "basura.mp3")), 0.0)
        self.assertEqual(S.duracion_de("/no/existe.flac"), 0.0)

    def test_buscar_audio_acepta_mp3_y_flac_y_nada_mas(self):
        import shutil, tempfile
        d = Path(tempfile.mkdtemp())
        (d / "sub").mkdir()
        for origen, destino in (("tono_44k.mp3", "b.mp3"), ("tono_16.flac", "a.flac"), ("tono_16.flac", "sub/C.FLAC")):
            shutil.copy(CORPUS / origen, d / destino)
        (d / "nota.txt").write_text("no es audio")
        (d / "cancion.ogg").write_bytes(b"OggS")
        hallados = [os.path.relpath(r, d) for r in S.buscar_audio([str(d)])]
        self.assertEqual(hallados, ["a.flac", "b.mp3", "sub/C.FLAC"])             # en orden, y sin .txt ni .ogg
        self.assertEqual(S.buscar_audio([str(d / "a.flac"), str(d / "nota.txt"), str(d / "a.flac")]), [str(d / "a.flac")])

    def test_el_replaygain_de_un_flac(self):
        self.assertAlmostEqual(S.leer_replaygain(str(CORPUS / "con_replaygain.flac")), -6.5 + (S.OBJETIVO_LUFS + 18.0), delta=0.01)
        self.assertIsNone(S.leer_replaygain(str(CORPUS / "tono_16.flac")))

    def test_la_sonoridad_de_un_flac_es_igual_a_la_del_mp3(self):
        flac = S.medir_tema(str(CORPUS / "tono_16.flac"), 10.0)
        mp3 = S.medir_tema(str(CORPUS / "tono_44k.mp3"), 10.0)
        self.assertAlmostEqual(flac[0], mp3[0], delta=0.5)
        hires = S.medir_tema(str(CORPUS / "tono_24_96k.flac"), 10.0)
        self.assertAlmostEqual(hires[0], flac[0], delta=0.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
