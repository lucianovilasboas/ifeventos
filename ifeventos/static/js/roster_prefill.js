/* Pré-preenche o cadastro com os dados da planilha de pré-carga (roster).
 *
 * Enquanto a pessoa digita o e-mail (ou o CPF) em /accounts/signup/, consulta o
 * endpoint informado no <form data-roster-url="..."> e, se achar a pessoa na
 * pré-carga, preenche os campos — SOMENTE os que estiverem VAZIOS — para ela
 * conferir e corrigir.
 *
 * É GENÉRICO: percorre as chaves devolvidas em `dados` e preenche o campo
 * correspondente, `[data-meta-campo="<chave>"]`, sem conhecer os campos de
 * nenhum vínculo. A ordem (pai antes do dependente; quem condiciona
 * visibilidade antes de quem é condicionado) sai de `METADADOS_CONFIG`, o mesmo
 * JSON que o script dos campos condicionais já usa. Sem JS, nada muda.
 */
(function () {
    "use strict";

    var ESPERA = 400;

    function ordemDePreenchimento() {
        var dados = document.getElementById("metadados-config");
        var config = [];
        if (dados) {
            try {
                config = JSON.parse(dados.textContent || "[]") || [];
            } catch (e) {
                config = [];
            }
        }
        var pendentes = config.slice();
        var ordem = [];
        var resolvido = {};
        var rodadas = 0;
        while (pendentes.length && rodadas++ < 1000) {
            for (var i = pendentes.length - 1; i >= 0; i--) {
                var campo = pendentes[i];
                var dep =
                    campo.depende_de ||
                    (campo.visivel_quando ? campo.visivel_quando.chave : null);
                if (!dep || resolvido[dep]) {
                    ordem.push(campo.chave);
                    resolvido[campo.chave] = true;
                    pendentes.splice(i, 1);
                }
            }
        }
        // Dependência circular/ausente: completa na ordem da config.
        pendentes.forEach(function (campo) {
            ordem.push(campo.chave);
        });
        return ordem;
    }

    function iniciar() {
        var form = document.querySelector("form[data-roster-url]");
        if (!form) return;
        var email = document.getElementById("id_email");
        var cpf = document.getElementById("id_cpf");
        var rota = form.getAttribute("data-roster-url");
        if (!email || !rota || !form.querySelector("[data-meta-campo]")) return;

        var ordem = ordemDePreenchimento();
        var timer = null;
        var emVoo = null;
        var ultima = "";

        function campoDe(chave) {
            return form.querySelector(
                '[data-meta-campo="' + chave + '"] input,' +
                '[data-meta-campo="' + chave + '"] select,' +
                '[data-meta-campo="' + chave + '"] textarea'
            );
        }

        function definir(chave, valor) {
            var campo = campoDe(chave);
            if (!campo || !valor) return;
            if (String(campo.value || "").trim()) return; // não sobrescreve
            campo.value = valor;
            campo.dispatchEvent(new Event("change", { bubbles: true }));
        }

        function definirId(id, valor) {
            var campo = document.getElementById(id);
            if (!campo || !valor) return;
            if (String(campo.value || "").trim()) return; // não sobrescreve
            campo.value = valor;
            campo.dispatchEvent(new Event("input", { bubbles: true }));
        }

        function preencher(json) {
            var dados = json.dados || {};
            if (json.cpf && cpf && !cpf.value.trim()) {
                cpf.value = json.cpf;
                cpf.dispatchEvent(new Event("input", { bubbles: true }));
            }
            definirId("id_first_name", json.first_name);
            definirId("id_last_name", json.last_name);
            ordem.forEach(function (chave) {
                definir(chave, dados[chave]);
            });
        }

        function consultar() {
            var params = new URLSearchParams();
            if (email.value.trim()) params.set("email", email.value.trim());
            if (cpf && cpf.value.trim()) params.set("cpf", cpf.value.trim());
            var chave = params.toString();
            if (!chave || chave === ultima) return;
            ultima = chave;

            if (emVoo) emVoo.abort();
            emVoo = new AbortController();
            fetch(rota + "?" + chave, {
                headers: { "X-Requested-With": "XMLHttpRequest" },
                signal: emVoo.signal,
            })
                .then(function (resposta) {
                    return resposta.ok ? resposta.json() : null;
                })
                .then(function (json) {
                    if (json && json.encontrado) preencher(json);
                })
                .catch(function (erro) {
                    if (erro.name !== "AbortError") console.error("roster:", erro);
                });
        }

        function agendar() {
            if (timer) clearTimeout(timer);
            timer = setTimeout(consultar, ESPERA);
        }

        email.addEventListener("input", agendar);
        email.addEventListener("blur", consultar);
        if (cpf) {
            cpf.addEventListener("input", agendar);
            cpf.addEventListener("blur", consultar);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciar);
    } else {
        iniciar();
    }
})();
