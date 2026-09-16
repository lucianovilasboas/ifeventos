/* Atividades no mesmo horário: alterna o leque e conta quantas ficaram ocultas.
 *
 * Marcação (programacao.html):
 *   [data-paralelas]        -> bloco de um horário dentro da célula
 *   [data-paralelo-toggle]  -> cabeçalho e botão "+N" (alternam o bloco)
 *   .agenda-chip.is-extra   -> cartas além das 3 primeiras (ocultas por CSS)
 *   .mais-fechado/.mais-aberto -> rótulos do botão
 *
 * Quando os filtros escondem cartas, o "+N" é recalculado (ver o gancho em
 * programacao_filtros.js). Sem isto, o botão prometeria cartas que o filtro
 * escondeu.
 */
(function () {
    "use strict";

    function iniciar() {
        var grupos = Array.prototype.slice.call(
            document.querySelectorAll("[data-paralelas]")
        );
        if (!grupos.length) return;

        function visiveis(grupo) {
            return Array.prototype.filter.call(
                grupo.querySelectorAll(".agenda-chip.is-extra"),
                function (carta) { return !carta.hidden; }
            );
        }

        function atualizar() {
            grupos.forEach(function (grupo) {
                var abertos = visiveis(grupo);
                var botao = grupo.querySelector(".agenda-mais");
                var fechado = grupo.querySelector(".mais-fechado");
                var aberto = grupo.querySelector(".mais-aberto");

                if (!abertos.length) grupo.classList.remove("is-aberto");
                var estarAberto = grupo.classList.contains("is-aberto");

                if (botao) botao.hidden = abertos.length === 0;
                if (fechado) {
                    fechado.textContent = "+" + abertos.length + " no mesmo horário";
                    fechado.hidden = estarAberto;
                }
                if (aberto) aberto.hidden = !estarAberto;

                Array.prototype.forEach.call(
                    grupo.querySelectorAll("[data-paralelo-toggle]"),
                    function (botaoToggle) {
                        botaoToggle.setAttribute(
                            "aria-expanded", estarAberto ? "true" : "false"
                        );
                    }
                );
            });
        }

        // No celular o bloco abre num modal: a célula é estreita demais para
        // empilhar 15 cartas.
        var modalEl = document.getElementById("agendaParalelaModal");
        var modal = modalEl && window.bootstrap ? new window.bootstrap.Modal(modalEl) : null;
        var estreito = window.matchMedia("(max-width: 700px)");

        function abrirModal(grupo) {
            if (!modal) return;
            var cabecalho = grupo.querySelector(".agenda-paralelo-head");
            var titulo = modalEl.querySelector("[data-modal-titulo]");
            var corpo = modalEl.querySelector("[data-modal-corpo]");
            if (titulo) {
                titulo.textContent = cabecalho
                    ? cabecalho.textContent.trim().replace(/\s+/g, " ")
                    : "Atividades no mesmo horário";
            }
            corpo.innerHTML = "";
            Array.prototype.forEach.call(
                grupo.querySelectorAll(".agenda-chip:not([hidden])"),
                function (carta) {
                    var copia = carta.cloneNode(true);
                    copia.classList.remove("is-extra");
                    copia.style.removeProperty("--i");
                    corpo.appendChild(copia);
                }
            );
            modal.show();
        }

        if (modalEl) {
            // Clicar numa carta do modal leva para a lista (handler delegado) e
            // fecha o modal.
            modalEl.addEventListener("click", function (evento) {
                if (evento.target.closest("[data-agenda-chip]")) modal.hide();
            });
        }

        grupos.forEach(function (grupo) {
            Array.prototype.forEach.call(
                grupo.querySelectorAll("[data-paralelo-toggle]"),
                function (botao) {
                    botao.addEventListener("click", function (evento) {
                        evento.stopPropagation();
                        if (estreito.matches && grupo.classList.contains("is-paralelo")) {
                            abrirModal(grupo);
                            return;
                        }
                        grupo.classList.toggle("is-aberto");
                        atualizar();
                    });
                }
            );
        });

        window.programacaoParalelas = { atualizar: atualizar };
        atualizar();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciar);
    } else {
        iniciar();
    }
})();
