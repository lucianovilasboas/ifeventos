/* Filtros da programação: busca (título/local/palestrante), local, tipo e
 * favoritos ("Minha agenda").
 *
 * Marcação esperada:
 *   [data-filtravel]           -> itens da lista e chips da grade
 *     data-id="<id>"           -> id da atividade (favoritos)
 *     data-local="A|B"         -> lugares (separados por |)
 *     data-tipo="<id>"
 *     data-busca-texto="..."   -> texto pesquisável
 *   [data-fav][data-id]        -> estrela de favoritar
 *   [data-filtro-local="Nome"] / [data-filtro-tipo="<id>"]
 *   [data-filtro-favoritos]    -> liga/desliga "só favoritos"
 *   [data-fav-total]           -> contador de favoritos
 *   [data-ics-favoritos][data-base] -> link .ics dos favoritos
 *   [data-filtro-limpar], [data-secao], [data-total-visivel], [data-filtro-vazio]
 *
 * Seleção múltipla. Filtros e favoritos ficam em localStorage.
 */
(function () {
    "use strict";

    var CHAVE = "ifeventos:programacao-filtros";
    var CHAVE_FAV = "ifeventos:programacao-favoritos";

    function semAcento(texto) {
        return String(texto == null ? "" : texto)
            .toLocaleLowerCase("pt-BR")
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "");
    }

    function ler(chave, padrao) {
        try {
            var cru = localStorage.getItem(chave);
            return cru ? JSON.parse(cru) : padrao;
        } catch (e) {
            return padrao;
        }
    }

    function gravar(chave, valor) {
        try { localStorage.setItem(chave, JSON.stringify(valor)); } catch (e) { /* privado */ }
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
        var chipFav = raiz.querySelector("[data-filtro-favoritos]");
        var favTotal = document.querySelector("[data-fav-total]");
        var linkFav = document.querySelector("[data-ics-favoritos]");

        var locais = new Set();
        var tipos = new Set();
        var favoritos = new Set();
        var somenteFavoritos = false;

        var salvo = ler(CHAVE, null);
        if (salvo) {
            (salvo.locais || []).forEach(function (l) { locais.add(l); });
            (salvo.tipos || []).forEach(function (t) { tipos.add(t); });
            somenteFavoritos = !!salvo.favoritos;
            if (input && salvo.termo) input.value = salvo.termo;
        }
        (ler(CHAVE_FAV, []) || []).forEach(function (id) { favoritos.add(String(id)); });

        function termo() {
            return input ? semAcento(input.value.trim()) : "";
        }

        function combina(item) {
            if (locais.size) {
                var doItem = (item.getAttribute("data-local") || "").split("|");
                if (!doItem.some(function (l) { return locais.has(l); })) return false;
            }
            if (tipos.size && !tipos.has(item.getAttribute("data-tipo") || "")) return false;
            if (somenteFavoritos && !favoritos.has(item.getAttribute("data-id") || "")) return false;
            var busca = termo();
            if (busca) {
                var texto = semAcento(item.getAttribute("data-busca-texto") || item.textContent);
                if (texto.indexOf(busca) === -1) return false;
            }
            return true;
        }

        function painelAtivo() {
            return document.querySelector("[data-vista-painel]:not([hidden])");
        }

        function pintarFavoritos() {
            Array.prototype.forEach.call(document.querySelectorAll("[data-fav]"), function (estrela) {
                var marcado = favoritos.has(estrela.getAttribute("data-id") || "");
                estrela.classList.toggle("is-fav", marcado);
                estrela.setAttribute("aria-pressed", marcado ? "true" : "false");
                var icone = estrela.querySelector("i");
                if (icone) {
                    icone.classList.toggle("fa-solid", marcado);
                    icone.classList.toggle("fa-regular", !marcado);
                }
            });
            if (favTotal) favTotal.textContent = favoritos.size;
            if (chipFav) chipFav.setAttribute("aria-pressed", somenteFavoritos ? "true" : "false");
            if (linkFav) {
                var ids = Array.from(favoritos);
                linkFav.hidden = ids.length === 0;
                if (ids.length) {
                    linkFav.setAttribute(
                        "href",
                        linkFav.getAttribute("data-base") + "?favoritos=" + ids.join(",")
                    );
                }
            }
        }

        function salvar() {
            gravar(CHAVE, {
                locais: Array.from(locais),
                tipos: Array.from(tipos),
                favoritos: somenteFavoritos,
                termo: input ? input.value : "",
            });
        }

        function aplicar() {
            itens.forEach(function (item) { item.hidden = !combina(item); });

            var painel = painelAtivo();
            var visiveis = painel
                ? Array.prototype.filter.call(
                    painel.querySelectorAll("[data-filtravel]"),
                    function (el) { return !el.hidden; }
                ).length
                : 0;
            Array.prototype.forEach.call(document.querySelectorAll("[data-secao]"), function (secao) {
                secao.hidden = !secao.querySelector("[data-filtravel]:not([hidden])");
            });

            var semFiltro = !locais.size && !tipos.size && !somenteFavoritos && !termo();
            if (limpar) limpar.hidden = semFiltro;
            if (vazio) vazio.hidden = visiveis !== 0 || semFiltro;
            if (contador) contador.textContent = visiveis;

            chipsLocal.concat(chipsTipo).forEach(function (chip) {
                var ligado = chip.hasAttribute("data-filtro-local")
                    ? locais.has(chip.getAttribute("data-filtro-local"))
                    : tipos.has(chip.getAttribute("data-filtro-tipo"));
                chip.setAttribute("aria-pressed", ligado ? "true" : "false");
            });
            pintarFavoritos();
            // O "+N no mesmo horário" só pode prometer cartas que o filtro não
            // escondeu — então o bloco de paralelas se recontá depois do filtro.
            if (window.programacaoParalelas) window.programacaoParalelas.atualizar();
            salvar();
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
        if (chipFav) {
            chipFav.addEventListener("click", function () {
                somenteFavoritos = !somenteFavoritos;
                aplicar();
            });
        }
        if (limpar) {
            limpar.addEventListener("click", function () {
                locais.clear();
                tipos.clear();
                somenteFavoritos = false;
                if (input) input.value = "";
                aplicar();
            });
        }
        if (input) input.addEventListener("input", aplicar);

        // Estrela de favoritar (lista e grade). Fica ANTES do handler do chip
        // (este arquivo carrega primeiro) e corta a propagação, senão clicar na
        // estrela da grade também levaria para a lista.
        document.addEventListener("click", function (evento) {
            var estrela = evento.target.closest("[data-fav]");
            if (!estrela) return;
            evento.preventDefault();
            evento.stopImmediatePropagation();
            var id = estrela.getAttribute("data-id") || "";
            if (!id) return;
            favoritos.has(id) ? favoritos.delete(id) : favoritos.add(id);
            gravar(CHAVE_FAV, Array.from(favoritos));
            aplicar();
        });

        // "Acontecendo agora": marca a atividade cuja janela cobre o horário.
        function marcarAgora() {
            var agora = Date.now();
            itens.forEach(function (item) {
                var ini = Date.parse(item.getAttribute("data-inicio") || "");
                var fim = Date.parse(item.getAttribute("data-fim") || "");
                var atual = ini && fim && agora >= ini && agora < fim;
                item.classList.toggle("is-agora", !!atual);
                var selo = item.querySelector(".agora-selo");
                if (selo) selo.hidden = !atual;
            });
        }

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
