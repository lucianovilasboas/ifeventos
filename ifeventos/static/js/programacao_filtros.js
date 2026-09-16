/* Filtros da programação: busca (título/local/palestrante), local e tipo.
 *
 * Marcação esperada:
 *   [data-filtravel]           -> itens da lista e chips da grade
 *     data-local="A|B"         -> lugares (separados por |)
 *     data-tipo="<id>"
 *     data-busca-texto="..."   -> texto pesquisável
 *   [data-filtro-local="Nome"] -> chip que liga/desliga um local
 *   [data-filtro-tipo="<id>"]  -> chip que liga/desliga um tipo
 *   [data-filtro-limpar]       -> limpa tudo
 *   [data-secao]               -> grupo da lista (some quando fica sem itens)
 *   [data-total-visivel]       -> contador do cabeçalho
 *   [data-filtro-vazio]        -> aviso de "nada encontrado"
 *
 * Seleção múltipla (dá para marcar vários locais/tipos). A escolha fica salva em
 * localStorage. Complementa `programacao_vistas.js`, que só troca lista/grade.
 */
(function () {
    "use strict";

    var CHAVE = "ifeventos:programacao-filtros";

    function semAcento(texto) {
        return String(texto == null ? "" : texto)
            .toLocaleLowerCase("pt-BR")
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "");
    }

    function iniciar() {
        var raiz = document.querySelector("[data-filtros]");
        if (!raiz) return;
        var itens = Array.prototype.slice.call(document.querySelectorAll("[data-filtravel]"));
        if (!itens.length) return;

        var input = raiz.querySelector("[data-busca]");
        var limpar = raiz.querySelector("[data-filtro-limpar]");
        var vazio = document.querySelector("[data-filtro-vazio]");
        var contador = document.querySelector("[data-total-visivel]");
        var chipsLocal = Array.prototype.slice.call(raiz.querySelectorAll("[data-filtro-local]"));
        var chipsTipo = Array.prototype.slice.call(raiz.querySelectorAll("[data-filtro-tipo]"));

        var locais = new Set();
        var tipos = new Set();

        function normais() {
            if (!input) return "";
            return semAcento(input.value.trim());
        }

        function combina(item, termo) {
            if (locais.size) {
                var doItem = (item.getAttribute("data-local") || "").split("|");
                var achou = doItem.some(function (l) { return locais.has(l); });
                if (!achou) return false;
            }
            if (tipos.size) {
                if (!tipos.has(item.getAttribute("data-tipo") || "")) return false;
            }
            if (termo) {
                var texto = semAcento(item.getAttribute("data-busca-texto") || item.textContent);
                if (texto.indexOf(termo) === -1) return false;
            }
            return true;
        }

        function painelAtivo() {
            return document.querySelector("[data-vista-painel]:not([hidden])");
        }

        function aplicar() {
            var termo = normais();
            var visiveis = 0;
            itens.forEach(function (item) {
                var ok = combina(item, termo);
                item.hidden = !ok;
            });
            // Cada atividade aparece na lista E na grade; o contador olha só o
            // painel visível para não contar duas vezes.
            var painel = painelAtivo();
            if (painel) {
                visiveis = Array.prototype.filter.call(
                    painel.querySelectorAll("[data-filtravel]"),
                    function (el) { return !el.hidden; }
                ).length;
            }
            // Seções da lista somem quando ficam sem itens visíveis.
            Array.prototype.forEach.call(document.querySelectorAll("[data-secao]"), function (secao) {
                var algum = secao.querySelector("[data-filtravel]:not([hidden])");
                secao.hidden = !algum;
            });

            var semFiltro = !locais.size && !tipos.size && !termo;
            if (limpar) limpar.hidden = semFiltro;
            if (vazio) vazio.hidden = visiveis !== 0 || semFiltro;
            if (contador) contador.textContent = visiveis;

            chipsLocal.concat(chipsTipo).forEach(function (chip) {
                var ligado = chip.hasAttribute("data-filtro-local")
                    ? locais.has(chip.getAttribute("data-filtro-local"))
                    : tipos.has(chip.getAttribute("data-filtro-tipo"));
                chip.setAttribute("aria-pressed", ligado ? "true" : "false");
            });
            salvar();
        }

        function salvar() {
            try {
                localStorage.setItem(CHAVE, JSON.stringify({
                    locais: Array.from(locais),
                    tipos: Array.from(tipos),
                    termo: input ? input.value : "",
                }));
            } catch (e) { /* modo privado: ignora */ }
        }

        function restaurar() {
            var salvo = null;
            try { salvo = JSON.parse(localStorage.getItem(CHAVE) || "null"); } catch (e) { salvo = null; }
            if (!salvo) return;
            (salvo.locais || []).forEach(function (l) { locais.add(l); });
            (salvo.tipos || []).forEach(function (t) { tipos.add(t); });
            if (input && salvo.termo) input.value = salvo.termo;
        }

        chipsLocal.forEach(function (chip) {
            chip.addEventListener("click", function () {
                var valor = chip.getAttribute("data-filtro-local");
                locais.has(valor) ? locais.delete(valor) : locais.add(valor);
                aplicar();
            });
        });
        chipsTipo.forEach(function (chip) {
            chip.addEventListener("click", function () {
                var valor = chip.getAttribute("data-filtro-tipo");
                tipos.has(valor) ? tipos.delete(valor) : tipos.add(valor);
                aplicar();
            });
        });
        if (limpar) {
            limpar.addEventListener("click", function () {
                locais.clear();
                tipos.clear();
                if (input) input.value = "";
                aplicar();
            });
        }
        if (input) {
            input.addEventListener("input", aplicar);
        }

        // "Acontecendo agora": marca a atividade cuja janela cobre o horário.
        function marcarAgora() {
            var agora = Date.now();
            itens.forEach(function (item) {
                var ini = Date.parse(item.getAttribute("data-inicio") || "");
                var fim = Date.parse(item.getAttribute("data-fim") || "");
                var agoraAgora = ini && fim && agora >= ini && agora < fim;
                item.classList.toggle("is-agora", !!agoraAgora);
                var selo = item.querySelector(".agora-selo");
                if (selo) selo.hidden = !agoraAgora;
            });
        }

        restaurar();
        aplicar();
        marcarAgora();
        setInterval(marcarAgora, 60000);

        window.programacaoFiltros = { atualizar: function () { aplicar(); marcarAgora(); } };
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciar);
    } else {
        iniciar();
    }
})();
