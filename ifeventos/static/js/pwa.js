/* PWA — Nossos Eventos
 * ---------------------------------------------------------------------------
 * 1) Registra o service worker (/sw.js), que dá instalabilidade e a tela
 *    offline.
 * 2) Cuida do botão "Instalar app":
 *    - Android/Chrome/Edge usam o `beforeinstallprompt` (só existe em HTTPS);
 *    - iPhone/iPad (Safari), que nunca emitem o evento, recebem um passo a
 *      passo de "Adicionar à Tela de Início";
 *    - Android sem prompt (HTTP, webview, Firefox) recebe o caminho pelo menu.
 *
 * Sem dependência de Bootstrap: a landing também usa este arquivo.
 */
(function () {
    "use strict";

    var script = document.currentScript || document.querySelector("script[data-pwa-sw]");
    var swUrl = script && script.getAttribute("data-pwa-sw") ? script.getAttribute("data-pwa-sw") : "/sw.js";

    var standalone =
        (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
        window.navigator.standalone === true;

    var deferredPrompt = null;
    var botoes = [];

    var ua = window.navigator.userAgent;

    function ehIOS() {
        return /iphone|ipad|ipod/i.test(ua);
    }

    // Safari de verdade no iOS (exclui Chrome/Firefox/Edge e apps embutidos,
    // que não têm o menu de "Adicionar à Tela de Início").
    function ehSafariIOS() {
        return ehIOS() && /safari/i.test(ua) && !/(crios|fxios|edgios|gsa)/i.test(ua);
    }

    function ehAndroid() {
        return /android/i.test(ua);
    }

    function mostrarBotoes() {
        if (standalone) return;
        botoes.forEach(function (botao) { botao.hidden = false; });
    }

    function esconderBotoes() {
        botoes.forEach(function (botao) { botao.hidden = true; });
    }

    function abrirPainel(id) {
        var painel = document.getElementById(id);
        if (!painel) return;

        // No Android, sem HTTPS a instalação é impossível: avisa no próprio
        // painel em vez de deixar o usuário procurando um menu que não aparece.
        if (id === "pwa-android-help" && !window.isSecureContext) {
            var aviso = document.getElementById("pwa-https-aviso");
            if (aviso) aviso.hidden = false;
        }
        painel.hidden = false;
    }

    function fecharPaineis() {
        ["pwa-ios-help", "pwa-android-help"].forEach(function (id) {
            var painel = document.getElementById(id);
            if (painel) painel.hidden = true;
        });
    }

    function iniciarBotoes() {
        botoes = Array.prototype.slice.call(document.querySelectorAll("[data-pwa-install]"));
        if (!botoes.length) return;

        botoes.forEach(function (botao) {
            botao.addEventListener("click", function () {
                if (deferredPrompt) {
                    deferredPrompt.prompt();
                    deferredPrompt.userChoice.then(function () {
                        deferredPrompt = null;
                        esconderBotoes();
                    });
                    return;
                }
                abrirPainel(ehIOS() ? "pwa-ios-help" : "pwa-android-help");
            });
        });

        // iOS sempre precisa de instruções. No Android mostramos o botão mesmo
        // sem prompt (HTTP, webview), para o usuário ao menos ter o caminho.
        if (!standalone && (ehSafariIOS() || ehAndroid())) mostrarBotoes();

        document.addEventListener("click", function (evento) {
            var alvo = evento.target;
            if (alvo && alvo.hasAttribute && alvo.hasAttribute("data-pwa-close")) {
                fecharPaineis();
            }
        });

        document.addEventListener("keydown", function (evento) {
            if (evento.key === "Escape") fecharPaineis();
        });
    }

    window.addEventListener("beforeinstallprompt", function (evento) {
        evento.preventDefault();
        deferredPrompt = evento;
        mostrarBotoes();
    });

    window.addEventListener("appinstalled", function () {
        deferredPrompt = null;
        esconderBotoes();
    });

    if ("serviceWorker" in navigator) {
        window.addEventListener("load", function () {
            navigator.serviceWorker
                .register(swUrl)
                .then(function (registro) {
                    // Ao voltar para a aba, procura uma versão nova do SW; assim
                    // um deploy é incorporado sem precisar fechar o app.
                    document.addEventListener("visibilitychange", function () {
                        if (document.visibilityState === "visible") registro.update();
                    });
                })
                .catch(function (erro) {
                    console.warn("[PWA] Falha ao registrar o service worker:", erro);
                });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciarBotoes);
    } else {
        iniciarBotoes();
    }
})();
