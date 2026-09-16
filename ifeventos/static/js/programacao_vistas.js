/* Alterna a programação entre LISTA e GRADE (cronograma), sem recarregar.
 *
 * Marcação esperada em programacao.html:
 *   [data-vista-btn="lista|grade"]  -> os botões
 *   [data-vista-painel="lista|grade"] -> os painéis (um ganha `hidden`)
 *
 * A preferência fica em localStorage; `?vista=grade` (link direto) tem
 * prioridade e é o que o servidor já renderiza. Sem JavaScript a lista
 * continua sendo a visão padrão.
 */
(function () {
    "use strict";

    var CHAVE = "ifeventos:programacao-vista";

    function iniciar() {
        var botoes = Array.prototype.slice.call(
            document.querySelectorAll("[data-vista-btn]")
        );
        var paineis = Array.prototype.slice.call(
            document.querySelectorAll("[data-vista-painel]")
        );
        if (!botoes.length || !paineis.length) return;

        function recalc() {
            if (window.programacaoFiltros) window.programacaoFiltros.atualizar();
        }

        function aplicar(vista) {
            paineis.forEach(function (painel) {
                painel.hidden = painel.getAttribute("data-vista-painel") !== vista;
            });
            botoes.forEach(function (botao) {
                var ativo = botao.getAttribute("data-vista-btn") === vista;
                botao.setAttribute("aria-pressed", ativo ? "true" : "false");
                botao.classList.toggle("is-active", ativo);
            });
            recalc();
            try {
                localStorage.setItem(CHAVE, vista);
            } catch (e) {
                /* armazenamento indisponível (modo privado): só ignora */
            }
        }

        botoes.forEach(function (botao) {
            botao.addEventListener("click", function () {
                aplicar(botao.getAttribute("data-vista-btn"));
            });
        });

        // Clicar num chip leva para a LISTA já filtrada por aquele título —
        // reaproveita a busca existente em vez de duplicar o cartão na grade.
        document.addEventListener("click", function (evento) {
            var chip = evento.target.closest("[data-agenda-chip]");
            if (!chip) return;
            var termo = chip.getAttribute("data-titulo") || "";
            var input = document.querySelector("[data-busca]");
            var botaoLista = document.querySelector('[data-vista-btn="lista"]');
            if (botaoLista) {
                botaoLista.click();
            } else {
                recalc();
            }
            if (input) {
                input.value = termo;
                input.dispatchEvent(new Event("input", { bubbles: true }));
                input.focus();
            }
        });

        // Deep link (?vista=...) manda; senão, aplica a preferência salva.
        if (new URLSearchParams(window.location.search).has("vista")) return;
        var salvo = null;
        try {
            salvo = localStorage.getItem(CHAVE);
        } catch (e) {
            salvo = null;
        }
        if (salvo === "grade" || salvo === "lista") aplicar(salvo);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciar);
    } else {
        iniciar();
    }
})();
