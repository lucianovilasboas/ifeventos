/* =====================================================================
 * Ordenação de tabelas por clique no cabeçalho
 * ---------------------------------------------------------------------
 * Sem dependências. Para usar numa tabela:
 *
 *   <table data-ordenavel>
 *     <thead><tr>
 *       <th data-renumerar>#</th>          <- coluna de índice (renumerada)
 *       <th data-sort="text">Atividade</th>
 *       <th data-sort="number">Inscritos</th>
 *       <th>Ações</th>                      <- sem data-sort: não ordena
 *     </tr></thead>
 *     ...
 *
 * Regras:
 *   - `data-sort="text"` compara texto (ignora maiúsculas/acentuação de caixa);
 *   - `data-sort="number"` aceita "1.234", "1.234,5" e "1234";
 *   - se a célula mostrar algo diferente do valor de ordenação, use
 *     `data-valor="..."` nela (ex.: data no formato ISO);
 *   - a primeira ordenação é crescente para texto e DECRESCENTE para número
 *     (para contadores, "maior primeiro" é o que se espera);
 *   - clicar de novo inverte; a seta no cabeçalho mostra o estado atual.
 *
 * Para reordenar depois de o conteúdo mudar (ex.: contagem que chega por
 * WebSocket), chame `window.TabelaOrdenavel.reaplicar()`.
 * ===================================================================== */
(function () {
  "use strict";

  var SELETOR = "table[data-ordenavel]";
  var estado = new WeakMap(); // tabela -> { indice, tipo, direcao }

  function paraNumero(texto) {
    var limpo = String(texto == null ? "" : texto).replace(/[^\d,.-]/g, "");
    if (!limpo) return -Infinity;
    // pt-BR: "1.234,5" -> 1234.5 | "1234" -> 1234
    var normalizado = limpo.indexOf(",") >= 0
      ? limpo.replace(/\./g, "").replace(",", ".")
      : limpo;
    var n = parseFloat(normalizado);
    return isNaN(n) ? -Infinity : n;
  }

  function valorDaCelula(linha, indice, tipo) {
    var celula = linha.children[indice];
    if (!celula) return tipo === "number" ? -Infinity : "";
    var bruto = celula.dataset.valor != null
      ? celula.dataset.valor
      : celula.textContent;
    if (tipo === "number") return paraNumero(bruto);
    return String(bruto || "").trim().toLocaleLowerCase("pt-BR");
  }

  function renumerar(tabela) {
    var th = tabela.querySelector("thead th[data-renumerar]");
    if (!th) return;
    var indice = Array.prototype.indexOf.call(th.parentNode.children, th);
    var corpo = tabela.tBodies[0];
    if (!corpo) return;
    Array.prototype.forEach.call(corpo.rows, function (linha, i) {
      var celula = linha.children[indice];
      if (celula) celula.textContent = String(i + 1);
    });
  }

  function aplicar(tabela, indice, tipo, direcao) {
    var corpo = tabela.tBodies[0];
    if (!corpo) return;

    var linhas = Array.prototype.slice.call(corpo.rows);
    linhas.sort(function (a, b) {
      var va = valorDaCelula(a, indice, tipo);
      var vb = valorDaCelula(b, indice, tipo);
      var cmp = tipo === "number"
        ? va - vb
        : va.localeCompare(vb, "pt-BR");
      return direcao === "asc" ? cmp : -cmp;
    });

    linhas.forEach(function (linha) { corpo.appendChild(linha); });
    renumerar(tabela);
  }

  function marcar(tabela, thAtivo, direcao) {
    Array.prototype.forEach.call(
      tabela.querySelectorAll("thead th[data-sort]"),
      function (th) {
        var ativo = th === thAtivo;
        th.classList.toggle("is-ordenado", ativo);
        th.setAttribute(
          "aria-sort",
          ativo ? (direcao === "asc" ? "ascending" : "descending") : "none"
        );
      }
    );
  }

  function ordenarPor(tabela, th) {
    var indice = Array.prototype.indexOf.call(th.parentNode.children, th);
    var tipo = th.dataset.sort === "number" ? "number" : "text";
    var atual = estado.get(tabela);

    // Mesmo cabeçalho: inverte. Cabeçalho novo: começa pelo mais útil.
    var direcao;
    if (atual && atual.indice === indice) {
      direcao = atual.direcao === "asc" ? "desc" : "asc";
    } else {
      direcao = tipo === "number" ? "desc" : "asc";
    }

    estado.set(tabela, { indice: indice, tipo: tipo, direcao: direcao });
    aplicar(tabela, indice, tipo, direcao);
    marcar(tabela, th, direcao);
  }

  function preparar(tabela) {
    var ths = tabela.querySelectorAll("thead th[data-sort]");
    Array.prototype.forEach.call(ths, function (th) {
      th.classList.add("th-ordenavel");
      th.setAttribute("role", "button");
      th.setAttribute("tabindex", "0");
      th.setAttribute("aria-sort", "none");
      if (!th.title) {
        th.title = "Clique para ordenar por " +
          th.textContent.trim().toLowerCase();
      }

      function acionar() { ordenarPor(tabela, th); }

      th.addEventListener("click", acionar);
      th.addEventListener("keydown", function (evento) {
        if (evento.key === "Enter" || evento.key === " " || evento.key === "Spacebar") {
          evento.preventDefault();
          acionar();
        }
      });
    });

    // Estado inicial: o servidor já entregou a tabela ordenada (ex.: por
    // inscritos). `data-ordenar-inicial="<indice>:<asc|desc>"` só marca a seta
    // e registra o estado — não reordena, para não brigar com o HTML recebido.
    var inicial = tabela.dataset.ordenarInicial;
    if (inicial) {
      var partes = String(inicial).split(":");
      var indice = parseInt(partes[0], 10);
      var direcao = partes[1] === "asc" ? "asc" : "desc";
      var linhaCabecalho = tabela.querySelector("thead tr");
      var thInicial = linhaCabecalho && linhaCabecalho.children[indice];
      if (thInicial && thInicial.dataset.sort) {
        estado.set(tabela, {
          indice: indice,
          tipo: thInicial.dataset.sort === "number" ? "number" : "text",
          direcao: direcao
        });
        marcar(tabela, thInicial, direcao);
      }
    }

    renumerar(tabela);
  }

  // Reaplica a ordenação ativa (usado quando o conteúdo muda por WebSocket).
  function reaplicar(tabela) {
    var atual = estado.get(tabela);
    if (!atual) return;
    aplicar(tabela, atual.indice, atual.tipo, atual.direcao);
  }

  function reaplicarTodas() {
    Array.prototype.forEach.call(document.querySelectorAll(SELETOR), reaplicar);
  }

  function iniciar() {
    Array.prototype.forEach.call(document.querySelectorAll(SELETOR), preparar);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else {
    iniciar();
  }

  window.TabelaOrdenavel = {
    reaplicar: reaplicar,
    reaplicarTodas: reaplicarTodas,
    iniciar: iniciar
  };
})();
