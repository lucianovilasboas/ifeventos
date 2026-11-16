/* Sino de notificações: atualiza por polling e mostra um toast quando chega
   uma nova. O servidor de socket não tem autenticação/salas, então o polling
   é o caminho seguro (e funciona em qualquer página do app). */
(function () {
    "use strict";

    var raiz = document.querySelector("[data-notificacoes]");
    if (!raiz) return;

    var urlListar = raiz.dataset.urlListar;
    var urlTodas = raiz.dataset.urlTodas;
    var urlLidaBase = raiz.dataset.urlLida;
    var csrf = raiz.dataset.csrf;
    var gatilho = raiz.querySelector("[data-notif-gatilho]");
    var painel = raiz.querySelector("[data-notif-painel]");
    var lista = raiz.querySelector("[data-notif-lista]");
    var badge = raiz.querySelector("[data-notif-badge]");
    var btnTodas = raiz.querySelector("[data-notif-todas]");
    var primeiraCarga = true;
    var ultimoId = 0;

    function urlLida(id) {
        return urlLidaBase.replace("/0/", "/" + id + "/");
    }

    function atualizarBadge(total) {
        if (total > 0) {
            badge.textContent = total > 99 ? "99+" : String(total);
            badge.hidden = false;
        } else {
            badge.hidden = true;
        }
    }

    function marcarLida(id) {
        // keepalive: o clique navega para o link e a requisição não pode ser
        // cancelada pelo unload da página.
        fetch(urlLida(id), {
            method: "POST",
            headers: { "X-CSRFToken": csrf },
            keepalive: true
        }).catch(function () { /* acessório */ });
    }

    function itemComoElemento(item) {
        var link = document.createElement("a");
        link.className = "notif-item" + (item.lida ? "" : " nao-lida");
        link.href = item.url || "#";

        var titulo = document.createElement("strong");
        titulo.textContent = item.titulo;
        link.appendChild(titulo);

        if (item.mensagem) {
            var mensagem = document.createElement("span");
            mensagem.textContent = item.mensagem;
            link.appendChild(mensagem);
        }

        var quando = document.createElement("span");
        quando.textContent = item.criada_em || "";
        link.appendChild(quando);

        link.addEventListener("click", function () {
            if (!item.lida) marcarLida(item.id);
        });
        return link;
    }

    function render(itens) {
        lista.innerHTML = "";
        if (!itens.length) {
            var vazio = document.createElement("p");
            vazio.className = "notif-vazio";
            vazio.textContent = "Nenhuma notificação por aqui.";
            lista.appendChild(vazio);
            return;
        }
        itens.forEach(function (item) {
            lista.appendChild(itemComoElemento(item));
        });
    }

    function mostrarToast(item) {
        var container = document.getElementById("notif-toasts");
        if (!container) {
            container = document.createElement("div");
            container.id = "notif-toasts";
            container.className = "toast-container position-fixed bottom-0 end-0 p-3";
            container.style.zIndex = "1085";
            document.body.appendChild(container);
        }

        var el = document.createElement("div");
        el.className = "toast";
        el.setAttribute("role", "alert");
        el.setAttribute("aria-live", "assertive");
        el.setAttribute("aria-atomic", "true");

        var header = document.createElement("div");
        header.className = "toast-header";
        var rotulo = document.createElement("strong");
        rotulo.className = "me-auto";
        rotulo.textContent = "Notificação";
        var fechar = document.createElement("button");
        fechar.type = "button";
        fechar.className = "btn-close";
        fechar.setAttribute("data-bs-dismiss", "toast");
        fechar.setAttribute("aria-label", "Fechar");
        header.appendChild(rotulo);
        header.appendChild(fechar);

        var corpo = document.createElement("div");
        corpo.className = "toast-body";
        var link = document.createElement("a");
        link.href = item.url || "#";
        link.className = "fw-semibold d-block";
        link.textContent = item.titulo;
        var mensagem = document.createElement("div");
        mensagem.textContent = item.mensagem || "";
        corpo.appendChild(link);
        corpo.appendChild(mensagem);

        el.appendChild(header);
        el.appendChild(corpo);
        container.appendChild(el);

        var toast = bootstrap.Toast.getOrCreateInstance(el, { delay: 8000 });
        toast.show();
        el.addEventListener("hidden.bs.toast", function () { el.remove(); });
    }

    function carregar() {
        fetch(urlListar, { headers: { "Accept": "application/json" } })
            .then(function (resposta) {
                if (!resposta.ok) return null;
                return resposta.json();
            })
            .then(function (dados) {
                if (!dados) return;
                var itens = dados.itens || [];
                atualizarBadge(dados.nao_lidas || 0);
                render(itens);

                var maior = itens.reduce(function (max, item) {
                    return Math.max(max, item.id || 0);
                }, 0);
                if (!primeiraCarga) {
                    var novas = itens.filter(function (item) {
                        return item.id > ultimoId && !item.lida;
                    });
                    if (novas.length) mostrarToast(novas[0]);
                }
                primeiraCarga = false;
                ultimoId = Math.max(ultimoId, maior);
            })
            .catch(function () { /* notificação é acessória */ });
    }

    gatilho.addEventListener("click", function () {
        painel.hidden = !painel.hidden;
        gatilho.setAttribute("aria-expanded", painel.hidden ? "false" : "true");
        if (!painel.hidden) carregar();
    });

    document.addEventListener("click", function (evento) {
        if (!raiz.contains(evento.target)) {
            painel.hidden = true;
            gatilho.setAttribute("aria-expanded", "false");
        }
    });

    btnTodas.addEventListener("click", function () {
        fetch(urlTodas, {
            method: "POST",
            headers: { "X-CSRFToken": csrf }
        }).then(carregar).catch(function () { /* acessório */ });
    });

    carregar();
    setInterval(carregar, 30000);
})();
