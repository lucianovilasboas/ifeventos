/* Campos de metadados condicionais/dependentes (cadastro e perfil).
 *
 * Lê a configuração de `settings.METADADOS_PARTICIPANTE` no <script
 * id="metadados-config"> e, DENTRO DE CADA FORMULÁRIO:
 *   - mostra/esconde o campo conforme `visivel_quando` (e limpa o valor ao
 *     esconder, para não sobrar dado de um vínculo que não é mais o atual);
 *   - repovoa os <select> com `opcoes_por` conforme o campo pai (`depende_de`).
 *
 * O escopo por formulário importa: na página de perfil convivem o formulário da
 * página e o do modal, cada um com os mesmos campos.
 *
 * A obrigatoriedade condicional é cobrada no servidor (MetadadosFormMixin.clean);
 * aqui não mexemos em `required` — um campo escondido nunca deve travar o envio.
 */
(function () {
    "use strict";

    var dados = document.getElementById("metadados-config");
    if (!dados) return;

    var config;
    try {
        config = JSON.parse(dados.textContent || "[]");
    } catch (e) {
        return;
    }
    if (!config || !config.length) return;

    function aplicarNo(form) {
        function inputsDe(chave) {
            return Array.prototype.slice.call(
                form.querySelectorAll('[data-meta-campo="' + chave + '"]')
            );
        }

        function valorDe(chave) {
            var wrap = inputsDe(chave)[0];
            var campo = wrap && wrap.querySelector("input,select,textarea");
            return campo ? String(campo.value || "").trim() : "";
        }

        function visibilidade() {
            config.forEach(function (c) {
                var visivel = true;
                if (c.visivel_quando) {
                    visivel =
                        c.visivel_quando.valores.indexOf(valorDe(c.visivel_quando.chave)) !== -1;
                }
                inputsDe(c.chave).forEach(function (wrap) {
                    wrap.style.display = visivel ? "" : "none";
                    if (!visivel) {
                        var campo = wrap.querySelector("input,select,textarea");
                        if (campo) campo.value = "";
                    }
                });
            });
        }

        function dependencia() {
            config.forEach(function (c) {
                if (!c.depende_de) return;
                var opcoes =
                    (c.opcoes_por && c.opcoes_por[valorDe(c.depende_de)]) || [];
                inputsDe(c.chave).forEach(function (wrap) {
                    var select = wrap.querySelector("select");
                    if (!select) return;
                    var atual = select.value;
                    select.innerHTML = "";
                    var vazio = document.createElement("option");
                    vazio.value = "";
                    vazio.textContent = "Selecione…";
                    select.appendChild(vazio);
                    opcoes.forEach(function (op) {
                        var opt = document.createElement("option");
                        opt.value = op;
                        opt.textContent = op;
                        select.appendChild(opt);
                    });
                    select.value = opcoes.indexOf(atual) !== -1 ? atual : "";
                });
            });
        }

        dependencia();
        visibilidade();
    }

    function formulariosComMetadados() {
        return Array.prototype.slice
            .call(document.querySelectorAll("form"))
            .filter(function (form) {
                return form.querySelector("[data-meta-campo]");
            });
    }

    function aplicarTudo() {
        formulariosComMetadados().forEach(aplicarNo);
    }

    function aoMudar(evento) {
        var alvo = evento.target;
        if (!alvo || !alvo.closest || !alvo.closest("[data-meta-campo]")) return;
        var form = alvo.closest("form");
        if (form) aplicarNo(form);
    }

    document.addEventListener("change", aoMudar);
    document.addEventListener("input", function (evento) {
        if (evento.target && evento.target.tagName !== "SELECT") aoMudar(evento);
    });

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", aplicarTudo);
    } else {
        aplicarTudo();
    }
})();
