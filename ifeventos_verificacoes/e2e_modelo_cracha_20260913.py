#!/usr/bin/env python3
"""Etapa 1 no navegador: o organizador escolhe o modelo e o participante obedece."""
import asyncio
import json
import shutil
import subprocess
import sys
import time
import urllib.request

import websockets

CDP = 9666
SESSAO, EVENTO = sys.argv[1], sys.argv[2]


async def cmd(ws, id_, metodo, params=None):
    await ws.send(json.dumps({"id": id_, "method": metodo, "params": params or {}}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == id_:
            return msg


async def avaliar(ws, id_, expr, gesto=False):
    r = await cmd(ws, id_, "Runtime.evaluate",
                  {"expression": expr, "returnByValue": True, "userGesture": gesto})
    return r.get("result", {}).get("result", {}).get("value")


async def principal():
    alvo = None
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json/list") as r:
                for item in json.load(r):
                    if item.get("type") == "page":
                        alvo = item
                        break
            if alvo:
                break
        except Exception:
            pass
        time.sleep(0.5)
    if not alvo:
        print("sem alvo CDP")
        return 1

    base = "http://127.0.0.1:8501"
    async with websockets.connect(alvo["webSocketDebuggerUrl"], max_size=None) as ws:
        i = 0
        i += 1; await cmd(ws, i, "Network.enable")
        i += 1; await cmd(ws, i, "Network.setCookie",
                          {"name": "sessionid", "value": SESSAO, "url": base + "/"})
        i += 1; await cmd(ws, i, "Page.enable")

        # ---------- organizador: o seletor existe e muda o modelo
        url_org = f"{base}/organizador/atividades_evento/{EVENTO}/"
        i += 1; await cmd(ws, i, "Page.navigate", {"url": url_org})
        await asyncio.sleep(4)
        i += 1; tem_seletor = await avaliar(ws, i, "!!document.getElementById('id_modelo_cracha')")
        i += 1; opcoes = await avaliar(
            ws, i, "[...document.querySelectorAll('#id_modelo_cracha option')].map(o=>o.value).join(',')")
        i += 1; valor_inicial = await avaliar(ws, i, "document.getElementById('id_modelo_cracha').value")
        print(f"ORGANIZADOR: seletor={tem_seletor} | opcoes={opcoes} | valor atual={valor_inicial}")

        i += 1; await avaliar(ws, i, """
            const sel = document.getElementById('id_modelo_cracha');
            sel.value = 'classico';
            sel.form.submit(); 'enviado'
        """, gesto=True)
        await asyncio.sleep(4)
        i += 1; valor_depois = await avaliar(ws, i, "document.getElementById('id_modelo_cracha').value")
        print(f"ORGANIZADOR: depois de escolher Classico o seletor mostra '{valor_depois}'")

        # ---------- participante: só o modelo do evento, sem seletor
        url_part = f"{base}/participante/meus-crachas/"
        i += 1; await cmd(ws, i, "Page.navigate", {"url": url_part})
        await asyncio.sleep(4)
        i += 1; dados = await avaliar(ws, i, """
            JSON.stringify({
                blocos: document.querySelectorAll('.cracha-bloco').length,
                etiquetas: document.querySelectorAll('.cracha--etiqueta').length,
                classicos: document.querySelectorAll('.cracha--classico').length,
                seletor: document.querySelectorAll('.crachas-modelo').length,
                modelo_do_lote: (document.querySelector('.cracha-acoes a') || {}).href || null,
            })
        """)
        print("PARTICIPANTE:", dados)
        return 0


if __name__ == "__main__":
    marca = "/tmp/chrome_e2e_modelo"
    shutil.rmtree(marca, ignore_errors=True)
    chrome = subprocess.Popen([
        "google-chrome", "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
        f"--remote-debugging-port={CDP}", f"--user-data-dir={marca}", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        codigo = asyncio.run(principal())
    finally:
        chrome.terminate()
    sys.exit(codigo)
