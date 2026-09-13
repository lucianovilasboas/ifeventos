#!/usr/bin/env python3
"""Visualizador de crachá em celular simulado: mede e fotografa os dois modos."""
import asyncio
import base64
import json
import shutil
import subprocess
import sys
import time
import urllib.request

import websockets

CDP = 9801
SESSAO = sys.argv[1]
LARGURA, ALTURA = 390, 844          # celular comum
BASE = "http://127.0.0.1:8501"


async def cmd(ws, i, metodo, params=None):
    await ws.send(json.dumps({"id": i, "method": metodo, "params": params or {}}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == i:
            return msg


async def av(ws, i, expr, gesto=False):
    r = await cmd(ws, i, "Runtime.evaluate",
                  {"expression": expr, "returnByValue": True, "userGesture": gesto})
    return r.get("result", {}).get("result", {}).get("value")


async def foto(ws, i, caminho):
    r = await cmd(ws, i, "Page.captureScreenshot", {"format": "png"})
    dados = base64.b64decode(r["result"]["data"])
    open(caminho, "wb").write(dados)
    return len(dados)


async def principal():
    alvo = None
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{CDP}/json/list") as r:
                alvo = next((item for item in json.load(r) if item.get("type") == "page"), None)
            if alvo:
                break
        except Exception:
            pass
        time.sleep(0.5)
    if not alvo:
        print("sem alvo CDP")
        return 1

    async with websockets.connect(alvo["webSocketDebuggerUrl"], max_size=None) as ws:
        i = 0
        i += 1; await cmd(ws, i, "Network.enable")
        i += 1; await cmd(ws, i, "Network.setCookie",
                          {"name": "sessionid", "value": SESSAO, "url": BASE + "/"})
        i += 1; await cmd(ws, i, "Page.enable")
        i += 1; await cmd(ws, i, "Emulation.setDeviceMetricsOverride",
                          {"width": LARGURA, "height": ALTURA, "deviceScaleFactor": 2, "mobile": True})
        i += 1; await cmd(ws, i, "Emulation.setTouchEmulationEnabled", {"enabled": True})

        # espia o pedido de "tela acesa" sem poder quebrar a página
        i += 1; await cmd(ws, i, "Page.addScriptToEvaluateOnNewDocument", {"source": """
            window.__wake = 0;
            try {
                const orig = navigator.wakeLock;
                if (orig && orig.request) {
                    const pedir = orig.request.bind(orig);
                    Object.defineProperty(navigator, 'wakeLock', {
                        configurable: true,
                        value: { request: function (tipo) { window.__wake++; return pedir(tipo); } },
                    });
                }
            } catch (e) { /* se não der para espiar, a página segue normal */ }
        """})

        i += 1; await cmd(ws, i, "Page.navigate", {"url": f"{BASE}/participante/meus-crachas/"})
        await asyncio.sleep(5)

        i += 1; botoes = await av(ws, i, "document.querySelectorAll('[data-visualizar]').length")
        i += 1; visivel_antes = await av(ws, i, "!document.getElementById('crachaViewer').hidden")
        print(f"TELA: botoes={botoes} | visualizador aberto antes do toque={visivel_antes}")

        # abre o primeiro crachá (toque de verdade)
        i += 1; await av(ws, i, "document.querySelector('[data-visualizar]').click(); 'ok'", gesto=True)
        await asyncio.sleep(1)
        i += 1; dados = await av(ws, i, """
            JSON.stringify((() => {
                const v = document.getElementById('crachaViewer');
                const caixa = v.querySelector('.cracha-viewer-caixa');
                const cracha = v.querySelector('.cracha');
                const r = caixa ? caixa.getBoundingClientRect() : null;
                const rc = cracha ? cracha.getBoundingClientRect() : null;
                const palco = document.getElementById('crachaViewerPalco').getBoundingClientRect();
                return {
                    aberto: !v.hidden,
                    fundo: getComputedStyle(v).backgroundColor,
                    caixa: r ? [Math.round(r.width), Math.round(r.height)] : null,
                    cracha: rc ? [Math.round(rc.width), Math.round(rc.height)] : null,
                    palco: [Math.round(palco.width), Math.round(palco.height)],
                    dentro: rc ? (rc.width <= palco.width + 1 && rc.height <= palco.height + 1) : false,
                    modelo: cracha ? cracha.className : null,
                    wake: window.__wake || 0,
                };
            })())
        """)
        print("TELA CHEIA:", dados)
        i += 1; tamanho = await foto(ws, i, "/tmp/viewer_cracha.png")
        print(f"  foto do cracha em tela cheia: {tamanho} bytes")

        # modo "só o QR"
        i += 1; await av(ws, i, "document.getElementById('crachaViewerSoQr').click(); 'ok'", gesto=True)
        await asyncio.sleep(1)
        i += 1; dados_qr = await av(ws, i, """
            JSON.stringify((() => {
                const img = document.querySelector('.cracha-so-qr img');
                const r = img ? img.getBoundingClientRect() : null;
                const cod = document.querySelector('.cracha-so-qr-codigo');
                const nome = document.querySelector('.cracha-so-qr-nome');
                return {
                    qr: r ? [Math.round(r.width), Math.round(r.height)] : null,
                    fracao_da_largura: r ? +(r.width / window.innerWidth).toFixed(2) : null,
                    codigo: cod ? cod.textContent.trim() : null,
                    nome: nome ? nome.textContent.trim().slice(0, 28) : null,
                    nitido: img ? getComputedStyle(img).imageRendering : null,
                };
            })())
        """)
        print("SO O QR:", dados_qr)
        i += 1; tamanho = await foto(ws, i, "/tmp/viewer_so_qr.png")
        print(f"  foto do so-o-QR: {tamanho} bytes")

        # impressão não pode imprimir o visualizador aberto
        i += 1; await cmd(ws, i, "Emulation.setEmulatedMedia", {"media": "print"})
        i += 1; no_papel = await av(ws, i, "getComputedStyle(document.getElementById('crachaViewer')).display")
        i += 1; await cmd(ws, i, "Emulation.setEmulatedMedia", {"media": "screen"})
        print(f"IMPRESSAO: display do visualizador no papel = {no_papel} (tem que ser none)")

        # fecha com ESC
        i += 1; await av(ws, i, """
            document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})); 'ok'
        """, gesto=True)
        await asyncio.sleep(0.6)
        i += 1; fechou = await av(ws, i, "document.getElementById('crachaViewer').hidden")
        i += 1; wake_depois = await av(ws, i, "window.__wake || 0")
        print(f"FECHOU: hidden={fechou} | pedidos de tela acesa={wake_depois}")
        return 0


if __name__ == "__main__":
    perfil = "/tmp/chrome_e2e_viewer"
    shutil.rmtree(perfil, ignore_errors=True)
    chrome = subprocess.Popen(
        ["google-chrome", "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
         f"--remote-debugging-port={CDP}", f"--user-data-dir={perfil}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        codigo = asyncio.run(principal())
    finally:
        chrome.terminate()
    sys.exit(codigo)
