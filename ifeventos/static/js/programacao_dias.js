/* Abas de dia no celular: mostra uma coluna por vez na grade.
 *
 * Só age quando a tela é estreita (≤ 700px) e há uma data escolhida. No desktop
 * a barra fica escondida e todas as colunas aparecem. As colunas são marcadas
 * com [data-dia="YYYY-MM-DD"] (no <th> do dia e nos <td> daquela coluna).
 */
(function () {
    "use strict";

    var CONSULTA = "(max-width: 700px)";

    function iniciar() {
        var barra = document.querySelector("[data-agenda-dias]");
        if (!barra) return;
        var botoes = Array.prototype.slice.call(barra.querySelectorAll("[data-dia-tab]"));
        if (!botoes.length) return;

        var consulta = window.matchMedia(CONSULTA);
        var atual = "";

        function aplicar() {
            var estreito = consulta.matches;
            var restringir = estreito && atual;

            Array.prototype.forEach.call(document.querySelectorAll("[data-dia]"), function (el) {
                el.hidden = !!(restringir && el.getAttribute("data-dia") !== atual);
            });
            // Semana sem nenhuma coluna visível some inteira (o cabeçalho do
            // horário não conta).
            Array.prototype.forEach.call(
                document.querySelectorAll("#vista-grade .agenda-scroll"),
                function (rolagem) {
                    var colunasVisiveis = rolagem.querySelectorAll(
                        "thead th[data-dia]:not([hidden])"
                    ).length;
                    rolagem.hidden = colunasVisiveis === 0;
                }
            );
            barra.hidden = !estreito;
            botoes.forEach(function (botao) {
                botao.classList.toggle(
                    "is-active", botao.getAttribute("data-dia-tab") === atual
                );
            });
        }

        botoes.forEach(function (botao) {
            botao.addEventListener("click", function () {
                atual = botao.getAttribute("data-dia-tab");
                aplicar();
            });
        });

        if (consulta.addEventListener) consulta.addEventListener("change", aplicar);
        else consulta.addListener(aplicar);

        aplicar();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciar);
    } else {
        iniciar();
    }
})();
