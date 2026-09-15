/* Busca instantânea no relatório de inscrições (AJAX, sem recarregar a página).
 *
 * Usa: no <form> ponha [data-busca-ajax]; no input, [data-busca]; e envolva o
 * trecho que muda num #resultado-inscricoes. O link [data-busca-limpar] limpa.
 *
 * A cada tecla (com um pequeno debounce) o servidor devolve só o trecho de
 * resultados — a lista pagina (20/página), então filtrar no cliente mentiria.
 * O formulário continua sendo um GET normal: sem JS, Enter ainda busca.
 */
(function () {
    "use strict";

    var ESPERA = 250;
    var CABECALHO = "X-Requested-With";

    function iniciar() {
        var form = document.querySelector("[data-busca-ajax]");
        var input = form && form.querySelector("[data-busca]");
        var destino = document.getElementById("resultado-inscricoes");
        if (!form || !input || !destino) return;

        var timer = null;
        var emVoo = null;

        function urlComTermo() {
            var url = new URL(form.action || window.location.href, window.location.href);
            url.search = "";
            var dados = new FormData(form);
            dados.delete("q");
            var params = new URLSearchParams(dados);
            var termo = input.value.trim();
            if (termo) params.set("q", termo);
            url.search = params.toString();
            return url;
        }

        function buscar() {
            var url = urlComTermo();
            if (emVoo) emVoo.abort();
            emVoo = new AbortController();
            form.setAttribute("aria-busy", "true");

            fetch(url, {
                headers: { "X-Requested-With": "XMLHttpRequest" },
                signal: emVoo.signal,
            })
                .then(function (resposta) {
                    if (!resposta.ok) throw new Error("HTTP " + resposta.status);
                    return resposta.text();
                })
                .then(function (html) {
                    destino.innerHTML = html;
                    window.history.replaceState({}, "", url);
                })
                .catch(function (erro) {
                    if (erro.name !== "AbortError") console.error("Erro na busca:", erro);
                })
                .finally(function () {
                    form.removeAttribute("aria-busy");
                });
        }

        input.addEventListener("input", function () {
            if (timer) clearTimeout(timer);
            timer = setTimeout(buscar, ESPERA);
        });

        // "Limpar busca" (o link é recriado junto com o trecho: delegação).
        document.addEventListener("click", function (e) {
            if (!e.target.closest("[data-busca-limpar]")) return;
            e.preventDefault();
            input.value = "";
            if (timer) clearTimeout(timer);
            buscar();
            input.focus();
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciar);
    } else {
        iniciar();
    }
})();
