/* Painel analítico do organizador — desenha os gráficos do evento.
 *
 * Os dados vêm prontos do servidor em `#dados-graficos` (relatorios/graficos.py);
 * aqui só pintamos, para o template não carregar lógica de agregação.
 * Chart.js é local (static/vendor/chart.min.js), sem depender de CDN.
 */
(function () {
    "use strict";

    var PALETA = ["#2f9e41", "#6366f1", "#8b5cf6", "#f59e0b", "#0ea5e9", "#ec4899", "#10b981", "#ef4444"];
    var CORES = {
        verde: "#2f9e41",
        indigo: "#6366f1",
        cinza: "#d1d5db",
        vermelho: "#ef4444",
        ambar: "#f59e0b",
    };

    function cor(nome, indice) {
        if (!nome || nome === "paleta") return PALETA[indice % PALETA.length];
        return CORES[nome] || PALETA[indice % PALETA.length];
    }

    function tipoChart(tipo) {
        if (tipo === "barh") return "bar";
        if (tipo === "donut") return "doughnut";
        return tipo;
    }

    var LIMITE_ROTULO = 26;

    function montar(dados, canvas) {
        var tipo = tipoChart(dados.tipo);
        // Rótulos completos para o tooltip; no eixo, versão curta (os títulos
        // de atividade são longos e atropelam o gráfico no celular).
        var completos = (dados.labels || []).map(String);
        var curtos = completos.map(function (texto) {
            return texto.length > LIMITE_ROTULO
                ? texto.slice(0, LIMITE_ROTULO - 1).trim() + "…"
                : texto;
        });
        var ehBarra = tipo === "bar";
        var donut = tipo === "doughnut";

        var opcoes = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: donut || dados.series.length > 1,
                    position: "bottom",
                    labels: { boxWidth: 12, font: { size: 11 } },
                },
                tooltip: {
                    intersect: false,
                    callbacks: {
                        title: function (itens) {
                            return completos[itens[0].dataIndex] || itens[0].label;
                        },
                    },
                },
            },
        };

        if (ehBarra || tipo === "line") {
            opcoes.scales = {
                x: {
                    beginAtZero: true,
                    grid: { display: false },
                    ticks: { font: { size: 11 } },
                },
                y: {
                    beginAtZero: true,
                    grid: { color: "#e5e5e5" },
                    ticks: { font: { size: 11 }, precision: 0 },
                },
            };
            if (dados.tipo === "barh") {
                opcoes.indexAxis = "y";
                opcoes.scales.y.grid = { display: false };
                opcoes.scales.x.grid = { color: "#e5e5e5" };
            }
        }

        var series = dados.series.map(function (s, indice) {
            return {
                label: s.nome,
                data: s.data,
                backgroundColor: donut ? PALETA : cor(s.cor, indice),
                borderColor: donut ? "#ffffff" : cor(s.cor, indice),
                borderWidth: donut ? 0 : 1.5,
                borderRadius: ehBarra ? 4 : 0,
                tension: 0.3,
                fill: false,
                pointRadius: 3,
            };
        });

        return new window.Chart(canvas.getContext("2d"), {
            type: tipo,
            data: { labels: curtos, datasets: series },
            options: opcoes,
        });
    }

    function pintarHeatmap() {
        var maior = 0;
        document.querySelectorAll(".heat-cel").forEach(function (celula) {
            maior = Math.max(maior, Number(celula.getAttribute("data-valor") || 0));
        });
        if (!maior) return;
        document.querySelectorAll(".heat-cel").forEach(function (celula) {
            var valor = Number(celula.getAttribute("data-valor") || 0);
            if (!valor) return;
            var intensidade = 0.12 + 0.75 * (valor / maior);
            celula.style.background = "rgba(47, 158, 65, " + intensidade.toFixed(2) + ")";
        });
    }

    function iniciar() {
        var script = document.getElementById("dados-graficos");
        if (!script || typeof window.Chart === "undefined") return;

        var graficos = [];
        try {
            graficos = JSON.parse(script.textContent || "[]");
        } catch (e) {
            return;
        }
        var porId = {};
        graficos.forEach(function (g) { porId[g.id] = g; });

        document.querySelectorAll("[data-grafico]").forEach(function (canvas) {
            var dados = porId[canvas.getAttribute("data-grafico")];
            if (dados) montar(dados, canvas);
        });

        pintarHeatmap();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciar);
    } else {
        iniciar();
    }
})();
