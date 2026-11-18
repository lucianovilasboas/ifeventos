/* Modal "Mais informações" da atividade (painel do participante).
 *
 * A view entrega um mapa `atividades-detalhes` (json_script) com a descrição,
 * os horários completos, o local e os palestrantes — dados que não cabem no
 * cartão. Qualquer elemento com `data-detalhe-atividade="<id>"` abre o modal:
 * o botão do cartão e os chips do cronograma. Só o botão abre no cartão; o
 * resto do cartão continua sem ação para evitar cliques acidentais.
 */
(function () {
    "use strict";

    function iniciar() {
        var modalEl = document.getElementById("atividadeDetalheModal");
        var dadosEl = document.getElementById("atividades-detalhes");
        if (!modalEl || !dadosEl || !window.bootstrap) return;

        var dados;
        try {
            dados = JSON.parse(dadosEl.textContent);
        } catch (e) {
            return;
        }
        var modal = new window.bootstrap.Modal(modalEl);

        function alvo(seletor) {
            return modalEl.querySelector(seletor);
        }

        function preencher(seletor, valor) {
            var el = alvo(seletor);
            if (!el) return;
            el.textContent = valor || "";
            var campo = el.closest("[data-campo]");
            if (campo) {
                campo.hidden = !valor;
            } else {
                el.hidden = !valor;
            }
        }

        function selo(texto, fundo, cor) {
            var el = document.createElement("span");
            el.className = "badge-app";
            el.textContent = texto;
            if (fundo) el.style.background = fundo;
            if (cor) el.style.color = cor;
            alvo("[data-detalhe-selos]").appendChild(el);
        }

        function detalhes(id) {
            return dados[String(id)] || null;
        }

        function abrir(id) {
            var a = detalhes(id);
            if (!a) return;

            preencher("[data-detalhe-titulo]", a.titulo);
            preencher("[data-detalhe-tipo]", a.tipo);
            preencher("[data-detalhe-evento]", a.evento);
            preencher("[data-detalhe-quando]", a.inicio + " — " + a.fim);
            preencher("[data-detalhe-local]", a.local);
            preencher(
                "[data-detalhe-inscritos]",
                a.exige_inscricao ? a.inscritos + "/" + a.vagas + " inscritos" : ""
            );
            preencher(
                "[data-detalhe-palestrantes]",
                (a.palestrantes || []).join(", ")
            );
            preencher("[data-detalhe-descricao]", a.descricao);

            var imagem = alvo("[data-detalhe-imagem]");
            if (imagem) {
                if (a.imagem) {
                    imagem.src = a.imagem;
                    imagem.hidden = false;
                } else {
                    imagem.removeAttribute("src");
                    imagem.hidden = true;
                }
            }

            var selos = alvo("[data-detalhe-selos]");
            if (selos) selos.innerHTML = "";
            if (a.inscricao_aberta === false) {
                selo("Inscrições encerradas", "#f1f0ff", "var(--muted)");
            }
            if (a.hoje) selo("Hoje", "var(--accent-soft)", "var(--accent-ink)");
            if (a.confirmada === true) {
                selo("Presença confirmada", "#dcfce7", "var(--app-green-d)");
            } else if (a.confirmada === false) {
                selo("Não confirmada", "#fee2e2", "#b91c1c");
            }
            if (a.certificado) {
                selo("Emite certificado", "#dcfce7", "var(--app-green-d)");
            }
            if (!a.exige_inscricao) {
                selo("Não precisa de inscrição", "#e0f2fe", "#0369a1");
            } else if (a.inscritos >= a.vagas) {
                selo("Lotado", "#fee2e2", "#b91c1c");
            }

            var ics = alvo("[data-detalhe-ics]");
            if (ics) {
                ics.href = a.ics || "#";
                ics.hidden = !a.ics;
            }

            modal.show();
        }

        // Controles dentro do chip (estrela de favorito, links, botões) têm a
        // própria ação: não abrem o modal. O próprio gatilho é exceção.
        function ehControle(el, gatilho) {
            var controle = el.closest("a, button, [data-fav]");
            return !!controle && controle !== gatilho;
        }

        document.addEventListener("click", function (evento) {
            var gatilho = evento.target.closest("[data-detalhe-atividade]");
            if (!gatilho || ehControle(evento.target, gatilho)) return;
            evento.preventDefault();
            abrir(gatilho.getAttribute("data-detalhe-atividade"));
        });

        // O chip do cronograma é uma <div role="button">: Enter/Espaço abrem.
        document.addEventListener("keydown", function (evento) {
            if (evento.key !== "Enter" && evento.key !== " ") return;
            var gatilho = evento.target.closest("[data-detalhe-atividade]");
            if (!gatilho || ehControle(evento.target, gatilho)) return;
            evento.preventDefault();
            abrir(gatilho.getAttribute("data-detalhe-atividade"));
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciar);
    } else {
        iniciar();
    }
})();
