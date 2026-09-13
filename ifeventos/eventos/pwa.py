"""Views do PWA: manifest, service worker e pagina offline.

Por que views em vez de arquivos estaticos: o service worker precisa ser
servido da RAIZ (`/sw.js`) para ter escopo em todo o site — o WhiteNoise so
serve sob `/static/`, e um SW em `/static/sw.js` controlaria apenas `/static/`.
Manifest e offline tambem ficam na raiz por simetria.

Nenhuma das tres respostas deve ser cacheada com prazo longo: o cache do
navegador guardaria uma versao antiga do manifest/SW depois do deploy.
"""

from django.shortcuts import render
from django.views.decorators.cache import never_cache


@never_cache
def manifest_view(request):
    return render(
        request,
        "pwa/manifest.webmanifest",
        content_type="application/manifest+json",
    )


@never_cache
def service_worker_view(request):
    response = render(
        request,
        "pwa/sw.js",
        content_type="application/javascript",
    )
    # Permite que o SW controle todo o dominio mesmo se servido por um caminho
    # com subpasta (defensivo; hoje ja esta na raiz).
    response["Service-Worker-Allowed"] = "/"
    return response


@never_cache
def offline_view(request):
    return render(request, "pwa/offline.html")
