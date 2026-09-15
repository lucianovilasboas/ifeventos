/* Botão de rolagem: um só, flutuante e discreto.
 *
 * No topo ele desce até o fim; depois de rolar uma tela, volta ao topo. Só
 * aparece em páginas longas (mais de 1,5 tela de conteúdo), então telas curtas
 * — login, formulários, dashboards com poucos itens — não ganham botão.
 *
 * O botão é criado aqui (não em cada template), então basta carregar este
 * arquivo nas duas bases. Sem JS nada existe e nada quebra.
 */
(function () {
    "use strict";

    var MINIMO_TELAS = 1.5;   // abaixo disso a página não é "longa"
    var SALTO_TELAS = 1;      // rolou uma tela: a seta passa a apontar para cima
    var MARGEM = 4;           // tolerância em px para topo/fim
    var ESPERA_DOM = 250;     // debounce ao recalcular (busca AJAX troca o trecho)

    function iniciar() {
        if (!document.body) return;

        var botao = document.createElement("button");
        botao.type = "button";
        botao.className = "btn-rolagem no-print";
        botao.hidden = true;
        botao.innerHTML = '<i class="fa-solid fa-chevron-down" aria-hidden="true"></i>';
        document.body.appendChild(botao);

        var icone = botao.querySelector("i");

        function rolagem() {
            return document.scrollingElement || document.documentElement;
        }

        function definirModo(paraCima) {
            var modo = paraCima ? "topo" : "fim";
            if (botao.dataset.modo === modo) return;
            botao.dataset.modo = modo;
            var rotulo = paraCima ? "Voltar ao topo" : "Ir para o final";
            botao.setAttribute("aria-label", rotulo);
            botao.title = rotulo;
            icone.className = "fa-solid " + (paraCima ? "fa-chevron-up" : "fa-chevron-down");
        }

        function atualizar() {
            var el = rolagem();
            var altura = el.scrollHeight;
            var tela = window.innerHeight;
            var topo = el.scrollTop;

            if (altura <= tela * MINIMO_TELAS) {
                botao.hidden = true;
                return;
            }

            var noTopo = topo <= MARGEM;
            var noFim = topo >= altura - tela - MARGEM;
            // No topo, desce; no fim (mesmo em página de pouco mais de uma
            // tela) ou depois de rolar uma tela, sobe.
            var paraCima = noFim || (!noTopo && topo >= tela * SALTO_TELAS);
            definirModo(paraCima);
            botao.hidden = false;
        }

        var agendado = false;
        function agendar() {
            if (agendado) return;
            agendado = true;
            window.requestAnimationFrame(function () {
                agendado = false;
                atualizar();
            });
        }

        botao.addEventListener("click", function () {
            var el = rolagem();
            var reduzido = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
            el.scrollTo({
                top: botao.dataset.modo === "topo" ? 0 : el.scrollHeight,
                behavior: reduzido ? "auto" : "smooth",
            });
        });

        window.addEventListener("scroll", agendar, { passive: true });
        window.addEventListener("resize", agendar);

        // A busca do relatório troca o trecho por AJAX: a altura muda sem
        // scroll nem resize, então o estado precisa ser recalculado.
        if (window.MutationObserver) {
            var espera = null;
            new MutationObserver(function () {
                if (espera) clearTimeout(espera);
                espera = setTimeout(atualizar, ESPERA_DOM);
            }).observe(document.body, { childList: true, subtree: true });
        }

        atualizar();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciar);
    } else {
        iniciar();
    }
})();
