/* Bipes do credenciamento do IF Eventos.
 *
 * Três sons, distintos de propósito — em saguão cheio a diferença precisa ser
 * de TOM e de RITMO, não só de frequência:
 *   sucesso -> duas notas ascendentes (registrou / chegou presença nova)
 *   aviso   -> uma nota média curta (já estava confirmada / presença desfeita)
 *   erro    -> zumbido grave, repetido (recusado / falha de rede)
 *
 * O navegador só libera áudio depois de um gesto na página, então o som começa
 * DESLIGADO na primeira visita e é uma chave de duas posições. A preferência
 * fica no navegador (localStorage, mesmo padrão da escolha do modelo de crachá);
 * voltando depois, o som reativa sozinho no primeiro toque em qualquer lugar.
 */
(function (global) {
    'use strict';

    var CHAVE = 'ifeventos.som';
    var VOLUME = 0.25;

    // [frequência em Hz, duração em segundos]
    var SONS = {
        sucesso: [[880, 0.09], [1320, 0.09]],
        aviso: [[660, 0.13]],
        erro: [[220, 0.14], [190, 0.14]]
    };

    var contexto = null;
    var ligado = lerPreferencia();

    function lerPreferencia() {
        try {
            return global.localStorage.getItem(CHAVE) === '1';
        } catch (erro) {
            return false;   // navegação privada pode recusar o armazenamento
        }
    }

    function guardar(valor) {
        try {
            global.localStorage.setItem(CHAVE, valor ? '1' : '0');
        } catch (erro) {
            /* sem armazenamento: vale só nesta página */
        }
    }

    function contextoDeAudio() {
        var Fabrica = global.AudioContext || global.webkitAudioContext;
        if (!Fabrica) return null;
        if (!contexto) {
            try {
                contexto = new Fabrica();
            } catch (erro) {
                return null;
            }
        }
        if (contexto.state === 'suspended' && contexto.resume) contexto.resume();
        return contexto;
    }

    function tocar(notas) {
        if (!ligado) return false;
        var ctx = contextoDeAudio();
        if (!ctx) return false;

        var atraso = 0;
        notas.forEach(function (nota) {
            var frequencia = nota[0];
            var duracao = nota[1];
            var oscilador = ctx.createOscillator();
            var ganho = ctx.createGain();
            oscilador.type = 'sine';
            oscilador.frequency.value = frequencia;
            ganho.gain.value = 0.0001;
            oscilador.connect(ganho);
            ganho.connect(ctx.destination);

            var inicio = ctx.currentTime + atraso;
            ganho.gain.exponentialRampToValueAtTime(VOLUME, inicio + 0.012);
            ganho.gain.exponentialRampToValueAtTime(0.0001, inicio + duracao);
            oscilador.start(inicio);
            oscilador.stop(inicio + duracao + 0.03);
            atraso += duracao + 0.03;
        });
        return true;
    }

    function pintarBotao(botao) {
        if (!botao) return;
        botao.setAttribute('aria-pressed', ligado ? 'true' : 'false');
        botao.innerHTML = ligado
            ? '<i class="fa-solid fa-volume-xmark"></i> Desligar o som'
            : '<i class="fa-solid fa-volume-high"></i> Ligar o som';
        botao.title = ligado
            ? 'O bipe toca a cada confirmação. Clique para silenciar.'
            : 'Clique para ouvir um bipe a cada confirmação.';
    }

    // Um toque em qualquer lugar reativa o áudio já autorizado antes (o navegador
    // só permite criar o contexto a partir de um gesto).
    function reativarNoPrimeiroToque() {
        if (!ligado) return;
        var retomar = function () {
            contextoDeAudio();
            global.removeEventListener('pointerdown', retomar);
            global.removeEventListener('keydown', retomar);
        };
        global.addEventListener('pointerdown', retomar);
        global.addEventListener('keydown', retomar);
    }

    var Bipe = {
        sucesso: function () { return tocar(SONS.sucesso); },
        aviso: function () { return tocar(SONS.aviso); },
        erro: function () { return tocar(SONS.erro); },

        get ligado() { return ligado; },

        ligar: function () {
            ligado = true;
            guardar(true);
            var tocou = tocar(SONS.aviso);   // confirmação sonora de que ligou
            if (!tocou) {
                ligado = false;
                guardar(false);
            }
            return tocou;
        },

        desligar: function () {
            ligado = false;
            guardar(false);
            return true;
        },

        alternar: function () {
            if (ligado) {
                Bipe.desligar();
            } else {
                Bipe.ligar();
            }
            return ligado;
        },

        /** Liga a chave ao botão: rótulo, ícone e estado acessível. */
        montarBotao: function (botao, aoFalhar) {
            if (!botao) return;
            pintarBotao(botao);
            botao.addEventListener('click', function () {
                if (ligado) {
                    Bipe.desligar();
                } else if (!Bipe.ligar()) {
                    if (typeof aoFalhar === 'function') {
                        aoFalhar('Este navegador não permitiu ligar o som.');
                    }
                }
                pintarBotao(botao);
            });
            reativarNoPrimeiroToque();
        }
    };

    global.Bipe = Bipe;
})(window);
