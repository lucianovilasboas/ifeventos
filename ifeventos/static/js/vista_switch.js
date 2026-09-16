/* Alternador de visão genérico (Lista / Grade / Cartões / Cronograma).
 *
 * Marcação:
 *   [data-vista-grupo="nome"]     -> agrupa um alternador e seus painéis
 *     [data-vista-btn="valor"]    -> botões (um por visão)
 *     [data-vista-painel="valor"] -> painéis (o inativo ganha `hidden`)
 *
 * A escolha fica em localStorage por grupo; `?vista=<valor>` na URL tem
 * prioridade (link direto) e o botão marcado no HTML (aria-pressed="true") é o
 * padrão sem JavaScript. Ao trocar, dispara `vista-mudou` no documento para
 * quem precisar recalcular algo (ex.: contadores da programação).
 */
(function () {
    "use strict";

    var PREFIXO = "ifeventos:vista:";

    function iniciarGrupo(grupo) {
        var nome = grupo.getAttribute("data-vista-grupo");
        var botoes = Array.prototype.slice.call(grupo.querySelectorAll("[data-vista-btn]"));
        var paineis = Array.prototype.slice.call(grupo.querySelectorAll("[data-vista-painel]"));
        if (!nome || !botoes.length || !paineis.length) return;

        var valores = botoes.map(function (b) { return b.getAttribute("data-vista-btn"); });
        var param = grupo.getAttribute("data-vista-param") || "vista";

        function escolhaInicial() {
            var daUrl = new URLSearchParams(window.location.search).get(param);
            if (daUrl && valores.indexOf(daUrl) !== -1) return daUrl;

            var salvo = null;
            try { salvo = localStorage.getItem(PREFIXO + nome); } catch (e) { salvo = null; }
            if (salvo && valores.indexOf(salvo) !== -1) return salvo;

            var marcado = botoes.filter(function (b) {
                return b.getAttribute("aria-pressed") === "true";
            })[0];
            if (marcado) return marcado.getAttribute("data-vista-btn");

            var visivel = paineis.filter(function (p) { return !p.hidden; })[0];
            return visivel ? visivel.getAttribute("data-vista-painel") : valores[0];
        }

        function aplicar(vista, salvar) {
            paineis.forEach(function (painel) {
                painel.hidden = painel.getAttribute("data-vista-painel") !== vista;
            });
            botoes.forEach(function (botao) {
                var ativo = botao.getAttribute("data-vista-btn") === vista;
                botao.setAttribute("aria-pressed", ativo ? "true" : "false");
                botao.classList.toggle("is-active", ativo);
            });
            if (salvar) {
                try { localStorage.setItem(PREFIXO + nome, vista); } catch (e) { /* privado */ }
            }
            document.dispatchEvent(new CustomEvent("vista-mudou", {
                detail: { grupo: nome, vista: vista },
            }));
        }

        botoes.forEach(function (botao) {
            botao.addEventListener("click", function () {
                aplicar(botao.getAttribute("data-vista-btn"), true);
            });
        });

        aplicar(escolhaInicial(), false);
    }

    function iniciar() {
        Array.prototype.forEach.call(
            document.querySelectorAll("[data-vista-grupo]"),
            iniciarGrupo
        );
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciar);
    } else {
        iniciar();
    }
})();
