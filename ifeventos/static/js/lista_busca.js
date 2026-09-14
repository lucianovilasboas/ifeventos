/* Busca numa lista de atividades (cliente, sem paginação).
 *
 * Usa: envolva a lista num [data-busca-lista], ponha um input [data-busca] e
 * marque cada item com data-titulo="...". Os itens que não casam com o termo
 * são escondidos; quando nada casa, aparece o aviso [data-busca-vazio].
 *
 * A comparação ignora caixa e acento (NFD + remoção dos diacríticos), para
 * "programacao" achar "Programação".
 */
(function () {
    "use strict";

    function semAcento(texto) {
        return String(texto == null ? "" : texto)
            .toLocaleLowerCase("pt-BR")
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "");
    }

    function preparar(raiz) {
        var input = raiz.querySelector("[data-busca]");
        var itens = Array.prototype.slice.call(raiz.querySelectorAll("[data-titulo]"));
        var vazio = raiz.querySelector("[data-busca-vazio]");
        if (!input || !itens.length) return;

        function filtrar() {
            var termo = semAcento(input.value.trim());
            var achou = 0;
            itens.forEach(function (item) {
                var alvo = semAcento(item.getAttribute("data-titulo"));
                var casa = !termo || alvo.indexOf(termo) !== -1;
                item.style.display = casa ? "" : "none";
                if (casa) achou += 1;
            });
            if (vazio) vazio.style.display = achou === 0 ? "" : "none";
        }

        input.addEventListener("input", filtrar);
        filtrar();
    }

    function iniciar() {
        Array.prototype.forEach.call(
            document.querySelectorAll("[data-busca-lista]"),
            preparar
        );
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciar);
    } else {
        iniciar();
    }
})();
