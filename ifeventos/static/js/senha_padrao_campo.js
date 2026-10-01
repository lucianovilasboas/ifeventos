/* Senha padrão do evento: gerar e mostrar/ocultar.
 *
 * Liga qualquer bloco [data-senha-padrao] (modal de criação e página de edição
 * do evento). O gerador monta ~12 caracteres com maiúscula, minúscula, número e
 * símbolo — já no formato que o EventoForm valida (mín. 8, não numérica, não
 * comum). Não usa IDs: resolve os elementos por escopo, então os dois blocos
 * (criação e edição) convivem na mesma página sem colidir.
 */
(function () {
    "use strict";

    var ATTR = "data-senha-init";
    var TAMANHO = 12;

    function aleatorio(max) {
        if (window.crypto && window.crypto.getRandomValues) {
            var valores = new Uint32Array(1);
            window.crypto.getRandomValues(valores);
            return valores[0] % max;
        }
        return Math.floor(Math.random() * max);
    }

    function embaralhar(itens) {
        for (var i = itens.length - 1; i > 0; i--) {
            var j = aleatorio(i + 1);
            var troca = itens[i];
            itens[i] = itens[j];
            itens[j] = troca;
        }
        return itens;
    }

    function gerarSenha() {
        var minusculas = "abcdefghijkmnpqrstuvwxyz";
        var maiusculas = "ABCDEFGHJKLMNPQRSTUVWXYZ";
        var numeros = "23456789";
        var simbolos = "@#%&*!?";
        var todos = minusculas + maiusculas + numeros + simbolos;
        // Garante ao menos um de cada tipo (o validador cobra letra e número).
        var senha = [
            minusculas[aleatorio(minusculas.length)],
            maiusculas[aleatorio(maiusculas.length)],
            numeros[aleatorio(numeros.length)],
            simbolos[aleatorio(simbolos.length)],
        ];
        while (senha.length < TAMANHO) {
            senha.push(todos[aleatorio(todos.length)]);
        }
        return embaralhar(senha).join("");
    }

    function iniciar(raiz) {
        if (raiz.getAttribute(ATTR) === "1") return;
        raiz.setAttribute(ATTR, "1");

        var campo = raiz.querySelector("input");
        if (!campo) return;
        var gerar = raiz.querySelector("[data-senha-gerar]");
        var mostrar = raiz.querySelector("[data-senha-mostrar]");

        if (gerar) {
            gerar.addEventListener("click", function () {
                campo.value = gerarSenha();
                campo.dispatchEvent(new Event("input", { bubbles: true }));
                campo.focus();
            });
        }

        if (mostrar) {
            mostrar.addEventListener("click", function () {
                var visivel = campo.type === "text";
                campo.type = visivel ? "password" : "text";
                var icone = mostrar.querySelector("i");
                if (icone) {
                    icone.className = visivel ? "fa-solid fa-eye" : "fa-solid fa-eye-slash";
                }
                mostrar.setAttribute("aria-pressed", visivel ? "false" : "true");
            });
        }
    }

    function iniciarTudo() {
        Array.prototype.forEach.call(
            document.querySelectorAll("[data-senha-padrao]"), iniciar
        );
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciarTudo);
    } else {
        iniciarTudo();
    }
})();
