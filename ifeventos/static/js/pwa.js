/* PWA — Nossos Eventos
 * ---------------------------------------------------------------------------
 * 1) Registra o service worker (/sw.js), que dá instalabilidade e a tela
 *    offline.
 * 2) Cuida do botão "Instalar app":
 *    - Android/Chrome/Edge usam o `beforeinstallprompt`;
 *    - iPhone/iPad (Safari) não emitem esse evento, então o botão abre um
 *      passo a passo de "Adicionar à Tela de Início".
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

    function mostrarBotoes() {
        if (standalone) return;
        botoes.forEach(function (botao) { botao.hidden = false; });
    }

    function esconderBotoes() {
        botoes.forEach(function (botao) { botao.hidden = true; });
    }

    function ehIOS() {
        return /iphone|ipad|ipod/i.test(window.navigator.userAgent);
    }

    // Safari de verdade no iOS (exclui Chrome/Firefox/Edge e apps embutidos,
    // que não têm o menu de "Adicionar à Tela de Início").
    function ehSafariIOS() {
        var ua = window.navigator.userAgent;
        return ehIOS() && /safari/i.test(ua) && !/(crios|fxios|edgios|gsa)/i.test(ua);
    }

    function abrirSheetIOS() {
        var sheet = document.getElementById("pwa-ios-help");
        if (sheet) sheet.hidden = false;
    }

    function fecharSheetIOS() {
        var sheet = document.getElementById("pwa-ios-help");
        if (sheet) sheet.hidden = true;
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
                abrirSheetIOS();
            });
        });

        // No iOS o botão abre as instruções; nos demais ele só aparece quando
        // o navegador de fato oferecer a instalação.
        if (ehSafariIOS() && !standalone) mostrarBotoes();

        document.addEventListener("click", function (evento) {
            var alvo = evento.target;
            if (alvo && alvo.hasAttribute && alvo.hasAttribute("data-pwa-close")) {
                fecharSheetIOS();
            }
        });

        document.addEventListener("keydown", function (evento) {
            if (evento.key === "Escape") fecharSheetIOS();
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
