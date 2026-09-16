/* Programação — comportamentos que NÃO são do alternador genérico:
 *   - clicar num chip leva para a LISTA filtrada por aquele título;
 *   - teclado no chip (ele é uma <div role="button">);
 *   - ao trocar de visão (evento `vista-mudou`), recalcula os contadores.
 * A troca Lista/Grade em si fica em static/js/vista_switch.js.
 */
(function () {
    "use strict";

    function recalc() {
        if (window.programacaoFiltros) window.programacaoFiltros.atualizar();
    }

    function abrirNoLista(chip) {
        var termo = chip.getAttribute("data-titulo") || "";
        var grupo = chip.closest("[data-vista-grupo]") || document;
        var botaoLista = grupo.querySelector('[data-vista-btn="lista"]');
        var input = document.querySelector("[data-busca]");
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
    }

    function iniciar() {
        document.addEventListener("click", function (evento) {
            var chip = evento.target.closest("[data-agenda-chip]");
            if (chip) abrirNoLista(chip);
        });

        // O chip é uma <div role="button"> (para caber a estrela dentro): o
        // teclado precisa do Enter/Espaço.
        document.addEventListener("keydown", function (evento) {
            if (evento.key !== "Enter" && evento.key !== " ") return;
            var chip = evento.target.closest("[data-agenda-chip]");
            if (!chip) return;
            evento.preventDefault();
            abrirNoLista(chip);
        });

        document.addEventListener("vista-mudou", recalc);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciar);
    } else {
        iniciar();
    }
})();
