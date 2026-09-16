/* Pré-preenche o cadastro com os dados da planilha de alunos (roster).
 *
 * Enquanto a pessoa digita o e-mail (ou o CPF) em /accounts/signup/, consulta o
 * endpoint informado no <form data-roster-url="..."> e, se achar a pessoa na
 * pré-carga, preenche os campos de metadados — SOMENTE os que estiverem VAZIOS
 * — para ela conferir e corrigir. Sem JS, nada muda: o cadastro segue normal.
 */
(function () {
    "use strict";

    var ESPERA = 400;

    function iniciar() {
        var form = document.querySelector("form[data-roster-url]");
        if (!form) return;
        var email = document.getElementById("id_email");
        var cpf = document.getElementById("id_cpf");
        var rota = form.getAttribute("data-roster-url");
        if (!email || !rota || !form.querySelector("[data-meta-campo]")) return;

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
            definir("vinculo", dados.vinculo);
            definir("matricula", dados.matricula);
            // `curso` antes de `ano`: o script de dependentes repovoa as opções
            // de `ano` quando `curso` muda.
            definir("curso", dados.curso);
            definir("ano", dados.ano);
            definir("turma", dados.turma);
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
