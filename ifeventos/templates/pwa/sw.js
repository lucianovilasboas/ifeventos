{% load static %}/* Service worker — Nossos Eventos (PWA)
 * ---------------------------------------------------------------------------
 * Escopo: instalabilidade + tela offline. NAO cacheia dados nem HTML
 * autenticado (evita vazar pagina de uma conta para outra no mesmo aparelho).
 *
 * - /static/            -> cache-first (a URL inclui ?v=, entao muda quando o
 *                          ASSET_VERSION muda e o cache se renova sozinho).
 * - navegacao (paginas) -> network-first, com /offline/ como fallback.
 * - o resto             -> rede pura.
 *
 * O nome do cache carrega o ASSET_VERSION: a cada deploy o cache antigo e
 * descartado no activate.
 */

const VERSION = "{{ ASSET_VERSION }}";
const CACHE = "ne-" + VERSION;
const OFFLINE_URL = "{% url 'pwa_offline' %}";
const ESTATICOS = "{% get_static_prefix %}";

// Prefixos que NUNCA sao interceptados: tempo real (Socket.IO), midia de
// usuario, admin, API e fluxo de autenticacao.
const IGNORAR = ["/socket.io", "/media/", "/admin/", "/api/", "/accounts/"];

const PRECACHE = [
  OFFLINE_URL,
  "{% static 'css/base/tokens.css' %}?v={{ ASSET_VERSION }}",
  "{% static 'img/pwa/icon-192.png' %}",
  "{% static 'img/pwa/icon-512.png' %}",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE);
      // Item a item: um asset ausente nao invalida o precache inteiro.
      await Promise.all(
        PRECACHE.map((url) => cache.add(url).catch(() => null))
      );
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const chaves = await caches.keys();
      await Promise.all(
        chaves
          .filter((k) => k.startsWith("ne-") && k !== CACHE)
          .map((k) => caches.delete(k))
      );
      await self.clients.claim();
    })()
  );
});

async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const guardado = await cache.match(request);
  if (guardado) return guardado;
  const resposta = await fetch(request);
  if (resposta && resposta.ok) cache.put(request, resposta.clone());
  return resposta;
}

async function networkFirst(request) {
  try {
    return await fetch(request);
  } catch (erro) {
    const cache = await caches.open(CACHE);
    const offline = await cache.match(OFFLINE_URL);
    if (offline) return offline;
    throw erro;
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (IGNORAR.some((prefixo) => url.pathname.startsWith(prefixo))) return;

  if (request.mode === "navigate") {
    event.respondWith(networkFirst(request));
    return;
  }

  if (url.pathname.startsWith(ESTATICOS)) {
    event.respondWith(cacheFirst(request));
  }
});
