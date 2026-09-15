/* Busca numa lista (cliente, sem paginação — listas pequenas).
 *
 * Usa: envolva a lista num [data-busca-lista], ponha um input [data-busca] e
 * marque cada item com data-titulo="..." — ou, quando o texto visível já serve
 * (listas que mudam em tempo real), só com data-busca-item, que faz a busca
 * pelo textContent do item. Os itens que não casam com o termo são escondidos;
 * quando nada casa, aparece o aviso [data-busca-vazio].
 *
 * A comparação ignora caixa e acento (NFD + remoção dos diacríticos), para
 * "programacao" achar "Programação".
 *
 * Para listas que ganham/perdem itens depois do load (AJAX/socket), chame
 * window.listaBusca.atualizar() depois de mexer no DOM.
 */
(function () {
    "use strict";

    var SELETOR_ITEM = "[data-titulo], [data-busca-item]";
    var filtros = [];

    function semAcento(texto) {
        return String(texto == null ? "" : texto)
            .toLocaleLowerCase("pt-BR")
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "");
    }

    // Texto pesquisável: o data-titulo quando existe; senão o que está à vista.
    function alvo(item) {
        var atributo = item.getAttribute("data-titulo");
        return atributo != null ? atributo : item.textContent;
    }

    function preparar(raiz) {
        var input = raiz.querySelector("[data-busca]");
        var vazio = raiz.querySelector("[data-busca-vazio]");
        if (!input || !raiz.querySelector(SELETOR_ITEM)) return;

        function filtrar() {
            var termo = semAcento(input.value.trim());
            var achou = 0;
            // Reconsulta os itens a cada filtro: a lista pode ter mudado.
            Array.prototype.forEach.call(
                raiz.querySelectorAll(SELETOR_ITEM),
                function (item) {
                    var casa = !termo || semAcento(alvo(item)).indexOf(termo) !== -1;
                    item.style.display = casa ? "" : "none";
                    if (casa) achou += 1;
                }
            );
            if (vazio) vazio.style.display = achou === 0 ? "" : "none";
        }

        filtros.push(filtrar);
        input.addEventListener("input", filtrar);
        filtrar();
    }

    function iniciar() {
        Array.prototype.forEach.call(
            document.querySelectorAll("[data-busca-lista]"),
            preparar
        );
    }

    window.listaBusca = {
        atualizar: function () {
            filtros.forEach(function (filtrar) { filtrar(); });
        },
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciar);
    } else {
        iniciar();
    }
})();
