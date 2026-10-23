"""Mosquito: control remoto chiquito para simpleplay, desde el navegador del celular. Solo para desarrollo por ahora.

Se activa con SIMPLEPLAY_MOSQUITO=1 (menú Agregar > «Mosquito…»). Al abrirlo levanta un servidor chico en la red de
casa y muestra un QR; el celular lo escanea y se abre una página con play/pausa, anterior, siguiente, la carátula y la
barra de progreso. No instala nada en el celular, no usa internet ni cuentas.

Seguridad: cada vez que se activa se genera una clave nueva (va en el QR y en el enlace); sin ella el servidor no
contesta, y solo atiende a equipos de la red local (10.x, 172.16-31.x, 192.168.x, enlace local). Al cerrar la ventana
el servidor se apaga.
"""
import hmac
import ipaddress
import json
import math
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PySide6.QtCore import Qt, QObject, QTimer, Signal, QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap

try:
    import qrcode
except ImportError:      # sin la librería se muestra solo el enlace
    qrcode = None

ACCIONES = {"play", "siguiente", "anterior"}
MAX_LISTA = 3000      # temas que se mandan al celular
CARPETA_ICONOS = Path(__file__).resolve().parent / "icon"
CLAVE_VALIDA = re.compile(r"[A-Za-z0-9_-]{8,64}")
ARCHIVO = "mosquito.json"      # clave y puerto guardados cuando se elige «recordar este celular»
MANIFIESTO = json.dumps({
    "name": "Mosquito", "short_name": "Mosquito", "start_url": "./", "scope": "./", "display": "standalone",
    "background_color": "#0a0a0c", "theme_color": "#ff4e01",
    "icons": [{"src": "icono.png", "sizes": "256x256", "type": "image/png"},
              {"src": "icono512.png", "sizes": "512x512", "type": "image/png"}]}).encode()

PAGINA = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="color-scheme" content="dark light">
<meta name="theme-color" content="#ff4e01"><meta name="mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Mosquito"><link rel="manifest" href="manifest.json"><link rel="apple-touch-icon" href="icono.png"><link rel="icon" href="icono.png">
<title>Mosquito</title><style>
:root{--bg:#0a0a0c;--fg:#f2f2f4;--mut:#8b8b93;--acc:#ff4e01;--card:#17171b;--velo:linear-gradient(rgba(10,10,12,.3),rgba(10,10,12,.62))}
@media(prefers-color-scheme:light){:root{--bg:#f4f3f1;--fg:#16161a;--mut:#6b6b73;--card:#fff;--velo:linear-gradient(rgba(244,243,241,.4),rgba(244,243,241,.7))}}
.fondo{position:fixed;inset:0;z-index:-1;overflow:hidden;background:var(--bg)}
.fondo i{position:absolute;inset:-25%;background:center/cover no-repeat;filter:blur(55px) saturate(1.6);opacity:0;transition:opacity .9s ease;transform:translateZ(0)}.fondo i.on{opacity:.9}
.fondo::after{content:'';position:absolute;inset:0;background:var(--velo)}
*{box-sizing:border-box}body{margin:0;min-height:100svh;background:var(--bg);color:var(--fg);font:16px system-ui,sans-serif;
display:flex;flex-direction:column;align-items:center;justify-content:center;gap:22px;padding:24px 16px calc(24px + env(safe-area-inset-bottom))}
.tapa{position:relative;width:min(78vw,340px);aspect-ratio:1;border-radius:22px;background:var(--card);box-shadow:0 10px 40px rgba(0,0,0,.35);overflow:hidden}
.tapa i{position:absolute;inset:0;background:center/cover no-repeat;opacity:0;transition:opacity .7s ease}.tapa i.on{opacity:1}
.t b,.t span{transition:opacity .35s ease}.t.fade b,.t.fade span{opacity:0}
.t{text-align:center;width:min(88vw,420px);height:84px}.t b{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:20px;line-height:26px;overflow-wrap:anywhere}
.t span{display:block;color:var(--mut);font-size:15px;line-height:20px;margin-top:4px}
.barra{width:min(88vw,420px);padding:12px 0;touch-action:none;cursor:pointer}.riel{position:relative;height:6px;border-radius:3px;background:var(--card);transition:height .15s ease}.barra.ar .riel{height:9px}
.riel b{position:absolute;top:50%;left:0;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;background:var(--acc);box-shadow:0 1px 6px rgba(0,0,0,.45);transition:transform .15s ease}.barra.ar .riel b{transform:scale(1.55)}
.riel i{display:block;height:100%;width:0;border-radius:3px;background:var(--acc)}.tm{display:flex;justify-content:space-between;color:var(--mut);font-size:13px;margin-top:6px}
.bt{display:flex;align-items:center;gap:22px}button{border:0;background:var(--card);color:var(--fg);width:62px;height:62px;border-radius:50%;
display:grid;place-items:center;cursor:pointer;-webkit-tap-highlight-color:transparent}button:active{transform:scale(.94)}
button.p{width:84px;height:84px;background:var(--acc);color:#fff}svg{width:50%;height:50%;fill:currentColor}
.bt{position:relative}
.vf{position:relative;width:min(100vw - 32px,460px);height:58px}
.vw{position:absolute;left:2px;top:0;width:58px;height:58px}.vw[hidden]{display:none}
button.vb{width:58px;height:58px;color:var(--mut);overflow:visible;position:relative;transition:transform .2s cubic-bezier(.2,.8,.2,1)}
button.vb:active{transform:scale(.92)}
button.vb .ci{position:absolute;inset:0;display:grid;place-items:center;transition:opacity .25s ease,transform .35s cubic-bezier(.3,1.5,.5,1)}
button.vb .ci svg{width:58%;height:58%}
button.vb .cm{opacity:0;transform:scale(.3) rotate(45deg);color:var(--acc)}
button.vb.mu .cn{opacity:0;transform:scale(.3) rotate(-45deg)}button.vb.mu .cm{opacity:1;transform:none}
button.vb .cg{position:absolute;inset:0;border-radius:50%;background:var(--acc);opacity:0;transform:scale(0);pointer-events:none}
button.vb.pr .cg{opacity:.4;transform:scale(1);transition:transform .45s linear,opacity .1s}
button.vb .ar{position:absolute;inset:0;border-radius:50%;border:2px solid var(--acc);opacity:0;pointer-events:none}
button.vb .ar.go{animation:aro .52s cubic-bezier(.2,.7,.2,1)}
@keyframes aro{0%{opacity:.7;transform:scale(1)}100%{opacity:0;transform:scale(1.7)}}
.vp{position:absolute;left:5px;bottom:calc(100% + 12px);width:48px;height:196px;border-radius:24px;background:var(--card);box-shadow:0 8px 30px rgba(0,0,0,.4);
opacity:0;transform:translateY(8px) scale(.92);transform-origin:bottom center;pointer-events:none;transition:opacity .2s ease,transform .25s cubic-bezier(.2,.8,.2,1);touch-action:none;z-index:3}
.vp.on{opacity:1;transform:none;pointer-events:auto}
.vt{position:absolute;left:50%;top:34px;bottom:14px;width:6px;margin-left:-3px;border-radius:3px;background:rgba(127,127,135,.35)}
.vt i{position:absolute;left:0;right:0;bottom:0;height:50%;border-radius:3px;background:var(--acc)}
.vt b{position:absolute;left:50%;bottom:50%;width:18px;height:18px;margin:0 0 -9px -9px;border-radius:50%;background:var(--acc);box-shadow:0 1px 6px rgba(0,0,0,.45)}
.vp span{position:absolute;top:9px;left:0;right:0;text-align:center;font-size:13px;color:var(--mut);font-variant-numeric:tabular-nums}
button.p .pi{position:absolute;inset:0;display:grid;place-items:center;transition:opacity .25s ease,transform .4s cubic-bezier(.3,1.5,.5,1)}
button.p{position:relative}button.p .pi svg{width:52%;height:52%}
button.p .pa{opacity:0;transform:scale(.3) rotate(90deg)}button.p.su .pl{opacity:0;transform:scale(.3) rotate(-90deg)}button.p.su .pa{opacity:1;transform:none}
button.sl{overflow:hidden}
button.sl.sg svg{animation:sig .32s ease}button.sl.at svg{animation:ant .32s ease}
@keyframes sig{0%{transform:translateX(0);opacity:1}45%{transform:translateX(18px);opacity:0}46%{transform:translateX(-18px);opacity:0}100%{transform:translateX(0);opacity:1}}
@keyframes ant{0%{transform:translateX(0);opacity:1}45%{transform:translateX(-18px);opacity:0}46%{transform:translateX(18px);opacity:0}100%{transform:translateX(0);opacity:1}}
.cx{position:fixed;top:calc(12px + env(safe-area-inset-top));left:16px;display:flex;align-items:center;gap:6px;font-size:12px;color:var(--mut)}
.cx i{width:8px;height:8px;border-radius:50%;background:#34c759}.cx.cd i{background:#ffb020;animation:lat 1s ease-in-out infinite}
.cx.cc i{background:#ff5a4f;animation:lat 1.8s ease-in-out infinite}.cx.cc{color:#ff5a4f}
@keyframes lat{0%,100%{opacity:1}50%{opacity:.25}}
@media(max-width:340px){.bt{gap:12px}.bt button{width:54px;height:54px}.bt button.p{width:76px;height:76px}}
button.ls{width:auto;height:auto;padding:9px 20px;border-radius:20px;font-size:14px;color:var(--mut)}
.vel{position:fixed;inset:0;background:rgba(0,0,0,.5);opacity:0;pointer-events:none;transition:opacity .35s ease;z-index:4}.vel.on{opacity:1;pointer-events:auto}
.hoja{position:fixed;left:0;right:0;bottom:0;height:78svh;background:var(--card);border-radius:22px 22px 0 0;transform:translateY(102%);
transition:transform .38s cubic-bezier(.2,.8,.2,1);z-index:5;display:flex;flex-direction:column;box-shadow:0 -10px 40px rgba(0,0,0,.4)}.hoja.on{transform:none}
.asa{padding:12px 0 8px;touch-action:none}.asa i{display:block;width:42px;height:5px;border-radius:3px;background:var(--mut);opacity:.5;margin:0 auto}
.bq{margin:0 14px 8px;padding:10px 14px;border:0;border-radius:12px;background:var(--bg);color:var(--fg);font:16px system-ui,sans-serif;outline:0}
.lst{overflow-y:auto;flex:1;padding:0 8px calc(16px + env(safe-area-inset-bottom));overscroll-behavior:contain}
.fila{display:flex;flex-direction:column;padding:11px 14px;border-radius:12px;cursor:pointer}.fila b{font-weight:600;font-size:15px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fila span{color:var(--mut);font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.fila.ac{background:rgba(255,78,1,.16)}.fila.ac b{color:var(--acc)}
</style></head><body>
<div class="fondo"><i id="f0" class="on"></i><i id="f1"></i></div>
<div class="tapa"><i id="c0" class="on"></i><i id="c1"></i></div>
<div class="t" id="tt"><b id="tit">…</b><span id="art"></span></div>
<div class="barra"><div class="riel"><i id="rl"></i><b id="pt"></b></div><div class="tm"><span id="po">0:00</span><span id="du">0:00</span></div></div>
<div class="bt">
<button class="sl" id="a" aria-label="Anterior"><svg viewBox="0 0 16 16"><path d="M4 3.5a.5.5 0 0 0-1 0v9a.5.5 0 0 0 1 0zM13 3.5v9a.5.5 0 0 1-.8.4L6.6 8.4a.5.5 0 0 1 0-.8l5.6-4.5a.5.5 0 0 1 .8.4"/></svg></button>
<button class="p" id="p" aria-label="Play/Pausa"><span class="pi pl"></span><span class="pi pa"></span></button>
<button class="sl" id="s" aria-label="Siguiente"><svg viewBox="0 0 16 16"><path d="M12 3.5a.5.5 0 0 1 1 0v9a.5.5 0 0 1-1 0zM3 3.5v9a.5.5 0 0 0 .8.4l5.6-4.5a.5.5 0 0 0 0-.8L3.8 3.1A.5.5 0 0 0 3 3.5"/></svg></button>
</div>
<div class="vf"><div class="vw" id="vw" hidden><button class="vb" id="vb" aria-label="Volumen (dos toques: silenciar)"><span class="cg" id="cg"></span>
<span class="ci cn"><svg id="ic1" viewBox="0 0 16 16" fill="currentColor"><path d="M9 4a.5.5 0 0 0-.812-.39L5.825 5.5H3.5A.5.5 0 0 0 3 6v4a.5.5 0 0 0 .5.5h2.325l2.363 1.89A.5.5 0 0 0 9 12zM6.312 6.39 8 5.04v5.92L6.312 9.61A.5.5 0 0 0 6 9.5H4v-3h2a.5.5 0 0 0 .312-.11M12.025 8a4.5 4.5 0 0 1-1.318 3.182L10 10.475A3.5 3.5 0 0 0 11.025 8 3.5 3.5 0 0 0 10 5.525l.707-.707A4.5 4.5 0 0 1 12.025 8"/></svg><svg id="ic2" viewBox="0 0 16 16" fill="currentColor" style="display:none"><path d="M11.536 14.01A8.47 8.47 0 0 0 14.026 8a8.47 8.47 0 0 0-2.49-6.01l-.708.707A7.48 7.48 0 0 1 13.025 8c0 2.071-.84 3.946-2.197 5.303z"/><path d="M10.121 12.596A6.48 6.48 0 0 0 12.025 8a6.48 6.48 0 0 0-1.904-4.596l-.707.707A5.48 5.48 0 0 1 11.025 8a5.48 5.48 0 0 1-1.61 3.89z"/><path d="M10.025 8a4.5 4.5 0 0 1-1.318 3.182L8 10.475A3.5 3.5 0 0 0 9.025 8c0-.966-.392-1.841-1.025-2.475l.707-.707A4.5 4.5 0 0 1 10.025 8M7 4a.5.5 0 0 0-.812-.39L3.825 5.5H1.5A.5.5 0 0 0 1 6v4a.5.5 0 0 0 .5.5h2.325l2.363 1.89A.5.5 0 0 0 7 12zM4.312 6.39 6 5.04v5.92L4.312 9.61A.5.5 0 0 0 4 9.5H2v-3h2a.5.5 0 0 0 .312-.11"/></svg></span>
<span class="ci cm"><svg viewBox="0 0 16 16" fill="currentColor"><path d="M6.717 3.55A.5.5 0 0 1 7 4v8a.5.5 0 0 1-.812.39L3.825 10.5H1.5A.5.5 0 0 1 1 10V6a.5.5 0 0 1 .5-.5h2.325l2.363-1.89a.5.5 0 0 1 .529-.06M6 5.04 4.312 6.39A.5.5 0 0 1 4 6.5H2v3h2a.5.5 0 0 1 .312.11L6 10.96zm7.854.606a.5.5 0 0 1 0 .708L12.207 8l1.647 1.646a.5.5 0 0 1-.708.708L11.5 8.707l-1.646 1.647a.5.5 0 0 1-.708-.708L10.793 8 9.146 6.354a.5.5 0 1 1 .708-.708L11.5 7.293l1.646-1.647a.5.5 0 0 1 .708 0"/></svg></span><span class="ar" id="ar"></span></button>
<div class="vp" id="vp"><span id="vn">50</span><div class="vt" id="vt"><i id="vf"></i><b id="vk"></b></div></div></div></div>
<button class="ls" id="ls">Lista</button>
<div class="cx" id="cx"><i></i><span id="cxt">Conectando…</span></div>
<div class="vel" id="vel"></div>
<div class="hoja" id="hoja"><div class="asa" id="asa"><i></i></div><input id="bq" class="bq" type="search" placeholder="Buscar" autocomplete="off"><div class="lst" id="lst"></div></div>
<script>
const K=location.pathname.split('/')[2],$=i=>document.getElementById(i);
const PLAY='<svg viewBox="0 0 16 16"><path d="M10.804 8 5 4.633v6.734zm.792-.696a.802.802 0 0 1 0 1.392l-6.363 3.692C4.713 12.69 4 12.345 4 11.692V4.308c0-.653.713-.998 1.233-.696z"/></svg>';
const PAUSA='<svg viewBox="0 0 16 16"><path d="M5.5 3.5A1.5 1.5 0 0 1 7 5v6a1.5 1.5 0 0 1-3 0V5a1.5 1.5 0 0 1 1.5-1.5m5 0A1.5 1.5 0 0 1 12 5v6a1.5 1.5 0 0 1-3 0V5a1.5 1.5 0 0 1 1.5-1.5"/></svg>';
const f=s=>{s=Math.max(0,Math.floor(s));return Math.floor(s/60)+':'+String(s%60).padStart(2,'0')};
let fallos=0,mudoOpt=null,vtoq=0,vlargo=0,vlargoHecho=false,ptoque=0,vtoca=0,venv=0,tapa='',pos=0,dur=0,sono=false,t0=0,ti=null,viva=0,abierta=false,lv=-1,cargada=-2,idx=-1,filas=[],arrastre=false,fx=0,hasta=0,objetivo=0;
function pintarVol(v){$('vf').style.height=v*100+'%';$('vk').style.bottom=v*100+'%';$('vn').textContent=Math.round(v*100);$('ic1').style.display=v<.5?'':'none';$('ic2').style.display=v<.5?'none':''}
function volver(v){const w=$('vw');if(v===null||v===undefined){w.hidden=true;return}w.hidden=false;if(!vdrag&&Date.now()-vtoca>2500){vv=v;pintarVol(v)}}
const VP=$('vp'),VT=$('vt');let vdrag=false,vv=.5,vcierra=0;
function vabrir(o){VP.classList.toggle('on',o);clearTimeout(vcierra);if(o)vcierra=setTimeout(()=>vabrir(false),3500)}
document.querySelector('#p .pl').innerHTML=PLAY;document.querySelector('#p .pa').innerHTML=PAUSA;
const buzz=n=>{try{navigator.vibrate&&navigator.vibrate(n)}catch(e){}};
function pintarMudo(m){$('vb').classList.toggle('mu',m)}
function silenciar(){const m=!(mudoOpt!==null?mudoOpt:$('vb').classList.contains('mu'));mudoOpt=m;setTimeout(()=>{mudoOpt=null},2500);pintarMudo(m);vabrir(false);buzz(m?[40,30,40]:25);
const a=$('ar');a.classList.remove('go');void a.offsetWidth;a.classList.add('go');cmd('mudo',m?1:0)}
const VB=$('vb');
VB.addEventListener('pointerdown',()=>{vlargoHecho=false;VB.classList.add('pr');clearTimeout(vlargo);vlargo=setTimeout(()=>{vlargoHecho=true;VB.classList.remove('pr');silenciar()},450)});
const finVb=()=>{clearTimeout(vlargo);VB.classList.remove('pr')};
VB.addEventListener('pointerup',finVb);VB.addEventListener('pointercancel',finVb);VB.addEventListener('pointerleave',finVb);
VB.onclick=()=>{if(vlargoHecho){vlargoHecho=false;return}const ahora=Date.now();if(ahora-vtoq<320){vtoq=0;silenciar();return}vtoq=ahora;vabrir(!VP.classList.contains('on'))};
document.addEventListener('pointerdown',e=>{if(!e.target.closest('#vw'))vabrir(false)});
function vmover(e){const r=VT.getBoundingClientRect();vv=Math.min(1,Math.max(0,1-(e.clientY-r.top)/r.height));pintarVol(vv);vtoca=Date.now();clearTimeout(vcierra);
if(Date.now()-venv>150){venv=Date.now();cmd('volumen',null,vv)}}
VP.addEventListener('pointerdown',e=>{vdrag=true;VP.setPointerCapture(e.pointerId);vmover(e)});
VP.addEventListener('pointermove',e=>{if(vdrag)vmover(e)});
VP.addEventListener('pointerup',()=>{if(!vdrag)return;vdrag=false;vtoca=Date.now();cmd('volumen',null,vv);vcierra=setTimeout(()=>vabrir(false),2500)});
VP.addEventListener('pointercancel',()=>{vdrag=false});
function marcar(){filas.forEach((e,i)=>e.classList.toggle('ac',i===idx))}
function centrar(){const e=filas[idx];if(e)e.scrollIntoView({block:'center'})}
async function cargarLista(){try{const r=await fetch('/c/'+K+'/lista',{cache:'no-store'});if(!r.ok)return;const d=await r.json(),L=$('lst');cargada=lv;L.textContent='';
filas=d.map((x,i)=>{const e=document.createElement('div');e.className='fila';const b=document.createElement('b');b.textContent=x.t;const s=document.createElement('span');s.textContent=x.a;
e.append(b,s);e.onclick=()=>{cmd('tocar',i);abrir(false)};L.append(e);return e});marcar();$('bq').oninput();if(abierta)centrar()}catch(e){}}
function abrir(v){abierta=v;$('hoja').classList.toggle('on',v);$('vel').classList.toggle('on',v);if(v){if(cargada!==lv)cargarLista();else centrar()}}
const B=document.querySelector('.barra');
const fr=e=>{const r=$('rl').parentNode.getBoundingClientRect();return Math.min(1,Math.max(0,(e.clientX-r.left)/r.width))};
B.addEventListener('pointerdown',e=>{if(!dur)return;arrastre=true;fx=fr(e);B.setPointerCapture(e.pointerId);B.classList.add('ar');pintar()});
B.addEventListener('pointermove',e=>{if(arrastre){fx=fr(e);pintar()}});
B.addEventListener('pointerup',()=>{if(!arrastre)return;arrastre=false;B.classList.remove('ar');pos=objetivo=fx*dur;t0=Date.now();hasta=Date.now()+2000;cmd('saltar',null,fx)});
B.addEventListener('pointercancel',()=>{arrastre=false;B.classList.remove('ar')});
$('bq').oninput=()=>{const q=$('bq').value.trim().toLowerCase();filas.forEach(e=>{e.style.display=!q||e.textContent.toLowerCase().includes(q)?'':'none'})};
$('ls').onclick=()=>abrir(true);$('vel').onclick=()=>abrir(false);
let y0=null;document.addEventListener('touchstart',e=>{const y=e.touches[0].clientY;y0=(!abierta&&y>innerHeight-110)||(abierta&&e.target.closest('#asa'))?y:null},{passive:true});
document.addEventListener('touchmove',e=>{if(y0===null)return;const d=e.touches[0].clientY-y0;if(!abierta&&d<-40){abrir(true);y0=null}else if(abierta&&d>60){abrir(false);y0=null}},{passive:true});
document.addEventListener('touchend',()=>{y0=null},{passive:true});
function poner(t,a){if(ti===null){$('tit').textContent=t;$('art').textContent=a;ti=t+'|'+a;return}
if(ti===t+'|'+a)return;ti=t+'|'+a;const e=$('tt');e.classList.add('fade');
setTimeout(()=>{$('tit').textContent=t;$('art').textContent=a;e.classList.remove('fade')},350)}
function fundir(id){const sig=1-viva,n=$('c'+sig),v=$('c'+viva),fn=$('f'+sig),fv=$('f'+viva);
const pasar=()=>{n.classList.add('on');v.classList.remove('on');fn.classList.add('on');fv.classList.remove('on');viva=sig};
const apagar=()=>{v.classList.remove('on');fv.classList.remove('on')};
if(!id){apagar();return}
const im=new Image(),u='/c/'+K+'/tapa?'+encodeURIComponent(id);
im.onload=()=>{n.style.backgroundImage=fn.style.backgroundImage='url('+u+')';pasar()};im.onerror=apagar;im.src=u}
function pintar(){const e=sono?pos+(Date.now()-t0)/1000:pos,x=arrastre?fx*dur:Math.min(e,dur||e);$('po').textContent=f(x);$('du').textContent=f(dur);const q=dur?Math.min(100,100*x/dur):0;$('rl').style.width=q+'%';$('pt').style.left=q+'%'}
async function estado(){try{const r=await fetch('/c/'+K+'/estado',{cache:'no-store'});if(!r.ok)throw 0;const d=await r.json();
poner(d.titulo||'Sin pista',d.artista||'');
if(d.tapa!==tapa){tapa=d.tapa;fundir(tapa)}
fallos=0;$('cx').className='cx';$('cxt').textContent='Conectado';if(mudoOpt===null)pintarMudo(!!d.mudo);else if(mudoOpt===!!d.mudo)mudoOpt=null;idx=d.i;lv=d.lv;volver(d.vol);marcar();if(abierta&&cargada!==lv)cargarLista();if(!arrastre&&!(Date.now()<hasta&&Math.abs(d.pos-objetivo)>2)){pos=d.pos;hasta=0}dur=d.dur;sono=d.suena;t0=Date.now();if(Date.now()-ptoque>2500)$('p').classList.toggle('su',sono);pintar()}
catch(e){fallos++;const c=fallos>=3;$('cx').className='cx '+(c?'cc':'cd');$('cxt').textContent=c?'Sin conexión con la PC':'Conectando…'}}
async function cmd(a,i,fr){try{await fetch('/c/'+K+'/cmd',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({a,i,f:fr})});estado()}catch(e){}}
function salto(b,c){b.classList.remove('sg','at');void b.offsetWidth;b.classList.add(c)}
$('p').onclick=()=>{const p=$('p');p.classList.toggle('su');ptoque=Date.now();buzz(12);cmd('play')};
$('a').onclick=()=>{salto($('a'),'at');buzz(12);cmd('anterior')};$('s').onclick=()=>{salto($('s'),'sg');buzz(12);cmd('siguiente')};
setInterval(estado,1500);setInterval(pintar,250);estado();
</script></body></html>"""


def _volumen_leer():
    """Volumen del sistema (0 a 1) o None si no hay forma de leerlo. Usa wpctl (PipeWire) o pactl (PulseAudio)."""
    try:
        if shutil.which("wpctl"):
            t = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], capture_output=True, text=True, timeout=3).stdout
            return min(1.0, float(t.split()[1]))
        if shutil.which("pactl"):
            t = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], capture_output=True, text=True, timeout=3).stdout
            return min(1.0, int(re.search(r"(\d+)%", t).group(1)) / 100)
    except (OSError, ValueError, IndexError, AttributeError, subprocess.SubprocessError):
        pass
    return None


def _volumen_poner(f):
    """Cambia el volumen del sistema (sin pasar del 100 %: nunca amplifica de más)."""
    f = max(0.0, min(1.0, float(f)))
    try:
        if shutil.which("wpctl"):
            subprocess.run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{f:.2f}"], timeout=3, capture_output=True)
        elif shutil.which("pactl"):
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{round(f * 100)}%"], timeout=3, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pass


def _ip_local():
    """La IP de este equipo en la red de casa (la de la interfaz que saldría a internet; no manda nada)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _es_red_local(ip):
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    return a.is_private or a.is_loopback or a.is_link_local


class Mosquito(QObject):
    """Servidor del control remoto. Todo lo de Qt pasa en el hilo principal: el servidor solo lee una foto del estado
    (se renueva cada medio segundo) y pide las acciones por una señal."""
    pedida = Signal(str)
    pedido_tocar = Signal(int)
    pedido_saltar = Signal(float)
    pedido_mudo = Signal(bool)

    def __init__(self, player, leer_meta, carpeta=None):
        super().__init__(player)
        self.player = player
        self.leer_meta = leer_meta
        self.carpeta = Path(carpeta) if carpeta else None
        self.clave = secrets.token_urlsafe(9)
        self.puerto = 0
        self._puerto_guardado = 0
        self.recordado = False
        guardado = self._leer_guardado()
        if guardado:
            self.clave, self._puerto_guardado, self.recordado = guardado[0], guardado[1], True
        self.ip = _ip_local()
        self._lock = threading.Lock()
        self._estado = {"titulo": "", "artista": "", "pos": 0.0, "dur": 0.0, "suena": False, "tapa": ""}
        self._tapa = b""
        self._lista = b"[]"
        self._lv = 0
        self._firma = None
        self._vol = None
        self._parar = threading.Event()
        self._pista_tapa = None
        self._httpd = None
        self.pedida.connect(self._ejecutar, Qt.QueuedConnection)
        self.pedido_tocar.connect(self._tocar, Qt.QueuedConnection)
        self.pedido_saltar.connect(self._saltar, Qt.QueuedConnection)
        self.pedido_mudo.connect(self._silenciar, Qt.QueuedConnection)
        self._rampa = QTimer(self)
        self._rampa.setInterval(15)
        self._rampa.timeout.connect(self._paso_rampa)
        self._meta_vol = 1.0
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._foto)

    # --- «recordar este celular»: la clave y el puerto no cambian, así la página guardada en el celular sigue sirviendo ---
    def _leer_guardado(self):
        if not self.carpeta:
            return None
        try:
            d = json.loads((self.carpeta / ARCHIVO).read_text())
            clave, puerto = d["clave"], int(d["puerto"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if not isinstance(clave, str) or not CLAVE_VALIDA.fullmatch(clave) or not 1024 <= puerto <= 65535:
            return None
        return clave, puerto

    def recordar(self, si):
        """Guarda (o borra) la clave y el puerto actuales. El archivo es solo del usuario (0600)."""
        if not self.carpeta:
            return
        f = self.carpeta / ARCHIVO
        try:
            if si:
                self.carpeta.mkdir(parents=True, exist_ok=True)
                tmp = f.with_suffix(".tmp")
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as fh:
                    json.dump({"clave": self.clave, "puerto": self.puerto}, fh)
                os.replace(tmp, f)
            else:
                f.unlink(missing_ok=True)
            self.recordado = bool(si)
        except OSError:
            pass

    # --- ciclo de vida ---
    @property
    def url(self):
        return f"http://{self.ip}:{self.puerto}/c/{self.clave}/"

    def iniciar(self):
        mosq = self

        class Manejador(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def _responder(self, codigo, tipo, cuerpo, extra=None):
                self.send_response(codigo)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(cuerpo)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(cuerpo)

            def _ruta(self):
                """Devuelve lo que viene después de /c/<clave>/ si la clave es la correcta y el cliente es de la red local."""
                if not _es_red_local(self.client_address[0]):
                    return None
                partes = self.path.split("?")[0].split("/")
                if len(partes) < 4 or partes[1] != "c" or not hmac.compare_digest(partes[2], mosq.clave):
                    return None
                return "/".join(partes[3:])

            def do_GET(self):
                r = self._ruta()
                if r is None:
                    return self._responder(404, "text/plain", b"")
                if r == "":
                    return self._responder(200, "text/html; charset=utf-8", PAGINA.encode())
                if r == "estado":
                    with mosq._lock:
                        d = json.dumps(mosq._estado).encode()
                    return self._responder(200, "application/json", d)
                if r == "manifest.json":
                    return self._responder(200, "application/manifest+json", MANIFIESTO)
                if r in ("icono.png", "icono512.png"):
                    f = CARPETA_ICONOS / ("simpleplay-256.png" if r == "icono.png" else "simpleplay-512.png")
                    try:
                        return self._responder(200, "image/png", f.read_bytes(), {"Cache-Control": "max-age=86400"})
                    except OSError:
                        return self._responder(404, "text/plain", b"")
                if r == "lista":
                    with mosq._lock:
                        d = mosq._lista
                    return self._responder(200, "application/json", d)
                if r == "tapa":
                    with mosq._lock:
                        t = mosq._tapa
                    if not t:
                        return self._responder(404, "text/plain", b"")
                    return self._responder(200, "image/jpeg", t)
                self._responder(404, "text/plain", b"")

            def do_POST(self):
                if self._ruta() != "cmd":
                    return self._responder(404, "text/plain", b"")
                try:
                    n = min(int(self.headers.get("Content-Length", "0")), 256)
                    pedido = json.loads(self.rfile.read(n) or b"{}")
                    accion = pedido.get("a")
                    indice = pedido.get("i")
                    fraccion = pedido.get("f")
                except (ValueError, TypeError, AttributeError):
                    return self._responder(400, "text/plain", b"")
                if accion == "tocar":
                    if type(indice) is not int or not 0 <= indice < MAX_LISTA:
                        return self._responder(400, "text/plain", b"")
                    mosq.pedido_tocar.emit(indice)
                elif accion == "volumen":
                    if type(fraccion) not in (int, float) or not math.isfinite(fraccion) or not 0 <= fraccion <= 1:
                        return self._responder(400, "text/plain", b"")
                    _volumen_poner(fraccion)
                    mosq._vol = float(fraccion)
                elif accion == "mudo":
                    if indice not in (0, 1) or type(indice) is not int:
                        return self._responder(400, "text/plain", b"")
                    if indice == 1:
                        # silenciar es de una: se corta acá mismo, sin esperar al hilo de la interfaz ni a ninguna rampa
                        mosq._meta_vol = 0.0
                        mosq.player.motor.volumen = 0.0
                    else:
                        mosq.pedido_mudo.emit(False)      # devolver el sonido sí lleva una rampa corta, para evitar un golpe
                elif accion == "saltar":
                    if type(fraccion) not in (int, float) or not math.isfinite(fraccion) or not 0 <= fraccion <= 1:
                        return self._responder(400, "text/plain", b"")
                    mosq.pedido_saltar.emit(float(fraccion))
                elif accion in ACCIONES:
                    mosq.pedida.emit(accion)
                else:
                    return self._responder(400, "text/plain", b"")
                self._responder(204, "text/plain", b"")

        try:
            self._httpd = ThreadingHTTPServer(("0.0.0.0", self._puerto_guardado), Manejador)
        except OSError:          # el puerto guardado está ocupado: se usa otro (el enlace guardado en el celular cambia)
            self._httpd = ThreadingHTTPServer(("0.0.0.0", 0), Manejador)
        self._httpd.daemon_threads = True
        self.puerto = self._httpd.server_address[1]
        if self.recordado and self.puerto != self._puerto_guardado:
            self.recordar(True)
        threading.Thread(target=self._httpd.serve_forever, name="mosquito", daemon=True).start()
        threading.Thread(target=self._vigilar_volumen, name="mosquito-vol", daemon=True).start()
        self._foto()
        self._timer.start()

    def _vigilar_volumen(self):
        while not self._parar.is_set():
            self._vol = _volumen_leer()
            self._parar.wait(2.0)

    def detener(self):
        self._rampa.stop()
        try:
            self.player.motor.volumen = 1.0      # no dejar al reproductor mudo si se apaga Mosquito
        except AttributeError:
            pass
        self._parar.set()
        self._timer.stop()
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    # --- hilo principal ---
    def _ejecutar(self, accion):
        p = self.player
        if accion == "play":
            p.play_pausa()
        elif accion == "siguiente":
            p.siguiente()
        elif accion == "anterior":
            p.anterior()

    def _silenciar(self, si):
        """Silencia (o devuelve) SOLO el sonido del reproductor: baja su ganancia interna, no el volumen del sistema. Se hace en
        una rampa corta para que no haya un golpe; el espectro sigue moviéndose."""
        self._meta_vol = 0.0 if si else 1.0
        self._rampa.start()

    def _paso_rampa(self):
        motor = self.player.motor
        v = float(motor.volumen)
        paso = 0.25
        v = min(self._meta_vol, v + paso) if self._meta_vol > v else max(self._meta_vol, v - paso)
        motor.volumen = v
        if v == self._meta_vol:
            self._rampa.stop()

    def _saltar(self, f):
        self.player.saltar(f)

    def _tocar(self, i):
        if 0 <= i < len(self.player.pistas):
            self.player.reproducir(i)

    def _armar_lista(self):
        """La lista de temas para el celular; se rehace solo cuando cambia (agregar, quitar, ordenar)."""
        p = self.player
        firma = (len(p.pistas), hash(tuple(p.pistas)))
        if firma == self._firma:
            return
        self._firma = firma
        filas = []
        for r in p.pistas[:MAX_LISTA]:
            d = p.datos.get(r) or {}
            filas.append({"t": d.get("titulo") or d.get("nombre") or r.rsplit("/", 1)[-1], "a": d.get("artista", "")})
        with self._lock:
            self._lista = json.dumps(filas).encode()
            self._lv += 1

    def _foto(self):
        p = self.player
        self._armar_lista()
        i = p.actual if p.actual >= 0 else -1
        meta = p.meta if i >= 0 else {"titulo": "", "artista": ""}
        if i != self._pista_tapa:
            self._pista_tapa = i
            self._cargar_tapa(i)
        with self._lock:
            self._estado = {"titulo": meta.get("titulo", ""), "artista": meta.get("artista", ""),
                            "pos": round(p.posicion(), 1) if i >= 0 else 0.0, "dur": round(p.duracion, 1),
                            "suena": i >= 0 and not p.pausado, "tapa": str(i) if self._tapa else "",
                            "i": i, "lv": self._lv, "vol": self._vol,
                            "mudo": float(getattr(p.motor, "volumen", 1.0)) < 0.001}

    def _cargar_tapa(self, i):
        datos = b""
        if 0 <= i < len(self.player.pistas):
            try:
                crudo = self.leer_meta(self.player.pistas[i])[2]
                img = QImage()
                if crudo and img.loadFromData(crudo):
                    img = img.scaled(480, 480, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    buf = QBuffer()
                    buf.open(QIODevice.WriteOnly)
                    img.save(buf, "JPEG", 82)
                    datos = bytes(buf.data())
            except Exception:
                datos = b""
        with self._lock:
            self._tapa = datos


def pixmap_qr(texto, lado=240):
    """Dibuja el QR (None si falta la librería) sin necesitar PIL: con la matriz de módulos que da la librería qrcode."""
    if qrcode is None:
        return None
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(texto)
    qr.make(fit=True)
    m = qr.get_matrix()
    n = len(m)
    pix = QPixmap(lado, lado)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setPen(Qt.NoPen)
    redondo = QPainterPath()
    redondo.addRoundedRect(0, 0, lado, lado, 14, 14)      # esquinas redondeadas, como las tarjetas
    p.fillPath(redondo, QColor("white"))
    p.setBrush(QColor("#111"))
    k = lado / n
    for y, fila in enumerate(m):
        for x, v in enumerate(fila):
            if v:
                p.drawRect(int(x * k), int(y * k), int(k) + 1, int(k) + 1)
    p.end()
    return pix
