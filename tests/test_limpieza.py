"""Pruebas del motor de limpieza (limpieza.py). No hace falta Qt ni fpcalc.

    .venv/bin/python tests/test_limpieza.py
"""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import limpieza as L  # noqa: E402


def dato(ruta, calidad, tit="", art="", dur=200.0, tags=(False, False), tam=1000):
    return {"ruta": Path(ruta), "calidad": calidad, "tit": tit, "art": art, "duracion": dur, "tags": tags, "tam": tam}


class Huellas(unittest.TestCase):
    def setUp(self):
        r = random.Random(1)
        self.a = [r.getrandbits(32) for _ in range(900)]
        self.otro = [r.getrandbits(32) for _ in range(900)]

    def ruido(self, h, fraccion, semilla=2):
        r = random.Random(semilla)
        return [x ^ sum(1 << b for b in range(32) if r.random() < fraccion) for x in h]

    def test_la_misma_huella_da_uno(self):
        self.assertEqual(L.parecido_huellas(self.a, self.a), 1.0)

    def test_dos_temas_distintos_quedan_lejos_del_umbral(self):
        self.assertLess(L.parecido_huellas(self.a, self.otro), 0.6)

    def test_otra_codificacion_con_ruido_sigue_pareciendo_el_mismo(self):
        self.assertGreater(L.parecido_huellas(self.a, self.ruido(self.a, 0.1)), L.UMBRAL_SONIDO)

    def test_un_desfase_por_silencio_inicial_no_importa(self):
        self.assertGreater(L.parecido_huellas(self.a, [0] * 3 + self.a[:-3]), 0.95)
        self.assertGreater(L.parecido_huellas([0] * 5 + self.a[:-5], self.a), 0.95)

    def test_sin_huella_no_hay_parecido(self):
        self.assertEqual(L.parecido_huellas(None, self.a), 0.0)
        self.assertEqual(L.parecido_huellas([], self.a), 0.0)


class Calidad(unittest.TestCase):
    def test_sin_perdida_antes_que_con_perdida(self):
        mp3 = dato("a.mp3", (0, 320, 0))
        flac = dato("a.flac", (1, 16 * 44100, 0))
        self.assertEqual(L.mejor_primero([mp3, flac])[0]["ruta"].name, "a.flac")

    def test_entre_flac_gana_la_de_mas_profundidad_y_frecuencia(self):
        a, b = dato("16.flac", (1, 16 * 44100, 0)), dato("24.flac", (1, 24 * 96000, 0))
        self.assertEqual(L.mejor_primero([a, b])[0]["ruta"].name, "24.flac")

    def test_a_igual_calidad_gana_la_que_tiene_etiquetas(self):
        a, b = dato("sin.mp3", (0, 192, 0)), dato("con.mp3", (0, 192, 0), tags=(True, True))
        self.assertEqual(L.mejor_primero([a, b])[0]["ruta"].name, "con.mp3")


class Corte(unittest.TestCase):
    def test_el_corte_se_traduce_a_una_tasa_creciente(self):
        k = [L.kbps_por_corte(h) for h in (10000, 16000, 19000, 20500, 22050)]
        self.assertEqual(k, sorted(k))
        self.assertAlmostEqual(L.kbps_por_corte(16500), 128)

    def test_un_flac_cortado_a_16k_vale_como_un_mp3_de_128(self):
        class FalsoCache:
            def corte(self, d):
                return 16000
        flac = dato("a.flac", (1, 16 * 44100, 0))
        flac["desc"] = "FLAC"
        mp3 = dato("b.mp3", (0, 192, 0))
        mp3["desc"] = "MP3"
        L.refinar_calidad([flac, mp3], FalsoCache())
        self.assertEqual(flac["calidad"][0], 0)
        self.assertLessEqual(flac["calidad"][1], 130)
        self.assertLessEqual(mp3["calidad"][1], 130)       # un mp3 "de 192" que se corta a 16 kHz vale 128


class Nombres(unittest.TestCase):
    def test_un_remix_o_un_en_vivo_no_es_la_misma_version(self):
        orig = dato("Artista - Tema.mp3", (0, 1, 0), "Tema", "Artista")
        vivo = dato("Artista - Tema (Live).mp3", (0, 1, 0), "Tema (Live)", "Artista")
        self.assertNotEqual(L._variantes(orig), L._variantes(vivo))

    def test_el_ruido_de_youtube_no_cuenta_como_version(self):
        a = dato("Artista - Tema [abc123].mp3", (0, 1, 0), "Tema", "Artista")
        b = dato("Artista - Tema (Official Video).mp3", (0, 1, 0), "Tema", "Artista")
        self.assertEqual(L._variantes(a), L._variantes(b))

    def test_las_llaves_ignoran_acentos_y_feat(self):
        a = dato("x.mp3", (0, 1, 0), "Canción (feat. Otro)", "Ana Pérez")
        b = dato("y.mp3", (0, 1, 0), "cancion", "ana perez")
        self.assertTrue(L._mismo_nombre(a, b, L._llaves(a), L._llaves(b)))


if __name__ == "__main__":
    unittest.main()
