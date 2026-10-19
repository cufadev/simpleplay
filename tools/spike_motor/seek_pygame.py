import os, sys, time
os.environ["SDL_AUDIODRIVER"] = "dummy"
import pygame
pygame.mixer.init()
f = sys.argv[1] + "/largo_60min.mp3"
for seg in (0, 600, 1800, 2700, 3500):
    t0 = time.perf_counter()
    pygame.mixer.music.load(f)
    pygame.mixer.music.play(start=seg)
    dt = time.perf_counter() - t0
    time.sleep(0.3)
    print(f"  pygame: saltar a {seg:5d} s -> {dt*1000:7.0f} ms | get_pos tras 0.3 s: {pygame.mixer.music.get_pos()} ms (offset aparente {pygame.mixer.music.get_pos()/1000:.1f} s)")
