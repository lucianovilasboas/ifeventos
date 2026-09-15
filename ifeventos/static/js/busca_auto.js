/* Busca automática num formulário GET (relatório de inscrições).
 *
 * Usa: no <form> ponha [data-busca-auto] e [data-min="4"]; no input, [data-busca];
 * a dica opcional é [data-busca-dica]. A partir de data-min caracteres o
 * formulário é enviado sozinho (com debounce). Com 1..3 caracteres nada
 * acontece — recarregar a cada letra digitada seria pior. Apagar tudo (0
 * caracteres) envia o formulário, ou seja, limpa a busca.
 *
 * O envio recarrega a página, o que perde o foco; por isso, quando a página
 * volta com ?q=, o input é focado de novo com o cursor no fim.
 */
(function () {
    "use strict";

    var ESPERA = 400;

    function preparar(form) {
        var input = form.querySelector("[data-busca]");
        if (!input) return;

        var minimo = parseInt(form.getAttribute("data-min"), 10) || 4;
        var dica = form.querySelector("[data-busca-dica]");
        var timer = null;

        function mostrarDica(termo) {
            if (dica) dica.hidden = !(termo.length > 0 && termo.length < minimo);
        }

        function enviar() {
            // Sem termo, o campo sai do envio para a URL não ficar com `q=`.
            input.disabled = input.value.trim() === "";
            form.submit();
        }

        input.addEventListener("input", function () {
            var termo = input.value.trim();
            mostrarDica(termo);

            if (timer) clearTimeout(timer);
            // 0 = limpar a busca; >= minimo = filtrar. Entre os dois, aguarda.
            if (termo.length === 0 || termo.length >= minimo) {
                timer = setTimeout(enviar, ESPERA);
            }
        });

        mostrarDica(input.value.trim());
    }

    function refocar() {
        var input = document.querySelector("[data-busca-auto] [data-busca]");
        if (!input || !new URLSearchParams(window.location.search).has("q")) return;

        input.focus();
        var fim = input.value.length;
        try {
            input.setSelectionRange(fim, fim);
        } catch (e) {
            // alguns navegadores não expõem setSelectionRange em type=search
        }
    }

    function iniciar() {
        Array.prototype.forEach.call(
            document.querySelectorAll("[data-busca-auto]"),
            preparar
        );
        refocar();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciar);
    } else {
        iniciar();
    }
})();
