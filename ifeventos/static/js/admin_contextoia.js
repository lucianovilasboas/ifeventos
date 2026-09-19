/* Admin — Contextos de IA: datalist com os modelos de chat da OpenAI.
 *
 * Busca a lista (cacheada no servidor) no endpoint do admin e a injeta num
 * <datalist> ligado aos inputs "Modelo de LLM" — tanto na edição inline da
 * lista quanto no formulário. Sem chave/rede, o endpoint devolve lista vazia e
 * o campo continua sendo texto livre.
 */
(function () {
    "use strict";

    var URL_MODELOS = "/admin/eventos/contextoia/modelos-openai/";
    var ID_LISTA = "openai-modelos";
    var SELETOR = 'input[name="modelo"], input[name$="-modelo"]';

    function ligar() {
        document.querySelectorAll(SELETOR).forEach(function (input) {
            input.setAttribute("list", ID_LISTA);
        });
    }

    function criarDatalist(modelos) {
        if (document.getElementById(ID_LISTA)) return;
        var lista = document.createElement("datalist");
        lista.id = ID_LISTA;
        (modelos || []).forEach(function (modelo) {
            var opcao = document.createElement("option");
            opcao.value = modelo.id;
            lista.appendChild(opcao);
        });
        document.body.appendChild(lista);
        ligar();
    }

    document.addEventListener("DOMContentLoaded", function () {
        if (!document.querySelector(SELETOR)) return;
        fetch(URL_MODELOS, { headers: { "X-Requested-With": "XMLHttpRequest" } })
            .then(function (resposta) { return resposta.ok ? resposta.json() : { modelos: [] }; })
            .then(function (dados) { criarDatalist(dados.modelos || []); })
            .catch(function () { /* datalist é acessório */ });
    });
})();
