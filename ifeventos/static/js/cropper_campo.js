/* Recorte de imagem nos formulários — Nossos Eventos
 * ---------------------------------------------------------------------------
 * Liga qualquer bloco [data-cropper-campo] (ver includes/campo_imagem.html):
 * o usuário escolhe o arquivo, o Cropper recorta na proporção do campo e o
 * resultado (data URL base64) vai para o hidden `cropped_image`, que a view
 * troca pelo arquivo original.
 *
 * Tudo é resolvido por ESCOPO (querySelector dentro de cada bloco), nunca por
 * getElementById: assim vários campos funcionam na mesma página (ex.: o modal
 * de perfil, o de novo evento e o de novo palestrante convivem em /dashboard/).
 *
 * Cuidados com foto GRANDE e PEQUENA:
 *  - a imagem é reduzida antes de cortar quando passa de ~2400 px / 6 MP, para
 *    o Cropper não engasgar no celular;
 *  - `checkOrientation` respeita o EXIF (foto de celular não sai girada);
 *  - o palco tem altura fixa (CSS), então a janela de recorte é a mesma para
 *    os dois extremos;
 *  - a saída nunca é ampliada: vira `min(pedido, pixels reais do recorte)`.
 *
 * Depende de: bootstrap (modal) e Cropper, ambos carregados no dashboard_base.
 */
(function () {
    "use strict";

    var ATTR_INICIADO = "data-cropper-init";
    var LADO_MAXIMO = 2400;                 // maior lado aceito antes do corte
    var PIXELS_MAXIMOS = 6 * 1024 * 1024;    // ~6 MP

    // Aceita "1", "0.75" ou fração "16/9". parseFloat("16/9") daria 16
    // (para no "/"), então a fração precisa ser dividida na mão.
    function proporcao(valor) {
        if (!valor) return 1;
        if (valor.indexOf("/") !== -1) {
            var partes = valor.split("/");
            var larguraAsp = parseFloat(partes[0]);
            var alturaAsp = parseFloat(partes[1]);
            if (larguraAsp && alturaAsp) return larguraAsp / alturaAsp;
        }
        return parseFloat(valor) || 1;
    }

    // Reduz só quando compensa; devolve um data URL novo ou null se não precisa.
    function reduzirSeGigante(imagem) {
        var w = imagem.naturalWidth;
        var h = imagem.naturalHeight;
        if (!w || !h) return null;
        var maior = Math.max(w, h);
        if (maior <= LADO_MAXIMO && w * h <= PIXELS_MAXIMOS) return null;

        var escala = Math.min(
            LADO_MAXIMO / maior,
            Math.sqrt(PIXELS_MAXIMOS / (w * h))
        );
        var canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(w * escala));
        canvas.height = Math.max(1, Math.round(h * escala));
        canvas.getContext("2d").drawImage(imagem, 0, 0, canvas.width, canvas.height);
        return canvas.toDataURL("image/jpeg", 0.92);
    }

    // Saída com a MAIOR escala que caiba no pedido sem ampliar (preserva a
    // proporção real do recorte e nunca inventa pixel).
    function calcularSaida(recorte, largura, altura) {
        var escala = Math.min(1, largura / recorte.width, altura / recorte.height);
        return {
            largura: Math.max(1, Math.round(recorte.width * escala)),
            altura: Math.max(1, Math.round(recorte.height * escala)),
        };
    }

    // Desenha num canvas branco (JPEG não tem transparência) e devolve o data URL.
    function paraJpeg(recorte, largura, altura) {
        var canvas = document.createElement("canvas");
        canvas.width = largura;
        canvas.height = altura;
        var ctx = canvas.getContext("2d");
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, largura, altura);
        ctx.drawImage(recorte, 0, 0, largura, altura);
        return canvas.toDataURL("image/jpeg", 0.9);
    }

    function ajustarMinimoCaixa(cropper, alvo, largura, altura) {
        var rect = alvo.getBoundingClientRect();
        if (!rect.width || !rect.height || !alvo.naturalWidth) return;
        // Quantos pixels naturais cada pixel exibido representa.
        var densidade = alvo.naturalWidth / rect.width;
        if (!densidade) return;
        cropper.setOptions({
            minCropBoxWidth: Math.min(rect.width, largura / densidade),
            minCropBoxHeight: Math.min(rect.height, altura / densidade),
        });
    }

    function mostrarAviso(raiz, imagem, largura, altura) {
        var aviso = raiz.querySelector("[data-cropper-aviso]");
        if (!aviso) return;
        var w = imagem.naturalWidth;
        var h = imagem.naturalHeight;
        if (w && h && (w < largura || h < altura)) {
            aviso.textContent =
                "Imagem de " + w + "×" + h + " px: o corte vai sair com no " +
                "máximo " + Math.min(w, largura) + "×" + Math.min(h, altura) +
                " px (sem ampliar).";
            aviso.hidden = false;
        } else {
            aviso.hidden = true;
            aviso.textContent = "";
        }
    }

    function iniciarCampo(raiz) {
        if (raiz.getAttribute(ATTR_INICIADO) === "1") return; // já ligado
        raiz.setAttribute(ATTR_INICIADO, "1");

        var input = raiz.querySelector("[data-cropper-input]");
        var saida = raiz.querySelector("[data-cropper-saida]");
        var preview = raiz.querySelector("[data-cropper-preview]");
        var gatilhos = raiz.querySelectorAll("[data-cropper-escolher]");
        var modalEl = raiz.querySelector("[data-cropper-modal]");
        var alvo = raiz.querySelector("[data-cropper-alvo]");
        var confirmar = raiz.querySelector("[data-cropper-confirmar]");

        if (!input || !modalEl || !alvo || !confirmar) return;

        var aspect = proporcao(raiz.getAttribute("data-cropper-aspect"));
        var largura = parseInt(raiz.getAttribute("data-cropper-largura"), 10) || 500;
        var altura = parseInt(raiz.getAttribute("data-cropper-altura"), 10) || 500;

        var modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        var cropper = null;

        // Abrir o seletor de arquivo a partir da pré-visualização (clique/tecla).
        Array.prototype.forEach.call(gatilhos, function (gatilho) {
            gatilho.addEventListener("click", function () { input.click(); });
            gatilho.addEventListener("keydown", function (evento) {
                if (evento.key === "Enter" || evento.key === " ") {
                    evento.preventDefault();
                    input.click();
                }
            });
        });

        input.addEventListener("change", function (evento) {
            var file = evento.target.files && evento.target.files[0];
            if (!file || !/^image\//.test(file.type)) return;
            var leitor = new FileReader();
            leitor.onload = function () {
                var imagem = new Image();
                imagem.onload = function () {
                    var reduzida = reduzirSeGigante(imagem);
                    alvo.src = reduzida || leitor.result;
                    mostrarAviso(raiz, imagem, largura, altura);
                    modal.show();
                };
                imagem.src = leitor.result;
            };
            leitor.readAsDataURL(file);
        });

        // O Cropper só é criado quando o modal já está visível (senão mede 0x0).
        modalEl.addEventListener("shown.bs.modal", function () {
            if (cropper) cropper.destroy();
            cropper = new Cropper(alvo, {
                aspectRatio: aspect,
                viewMode: 1,
                dragMode: "move",
                autoCropArea: 1,
                responsive: true,
                background: false,
                modal: true,
                checkOrientation: true,
            });
            ajustarMinimoCaixa(cropper, alvo, largura, altura);
        });

        modalEl.addEventListener("hidden.bs.modal", function () {
            if (cropper) {
                cropper.destroy();
                cropper = null;
            }
            // Bootstrap não suporta modal aninhado: ao fechar o recorte ele
            // remove `modal-open` mesmo com o modal de baixo aberto, e a
            // rolagem da página atrás volta. Se ainda houver modal aberto,
            // reaplica o travamento (body.modal-open cuida do resto).
            if (document.querySelectorAll(".modal.show").length) {
                document.body.classList.add("modal-open");
            }
        });

        confirmar.addEventListener("click", function () {
            if (!cropper) return;
            // Resolução real do recorte (sem ampliar; considera o zoom do usuário).
            var recorte = cropper.getCroppedCanvas();
            if (!recorte || !recorte.width || !recorte.height) return;
            var saidaTam = calcularSaida(recorte, largura, altura);
            var dataUrl = paraJpeg(recorte, saidaTam.largura, saidaTam.altura);
            if (preview) preview.src = dataUrl;
            if (saida) saida.value = dataUrl;
            // Depois do primeiro corte o botão vira "Trocar imagem" (só na capa;
            // no avatar não existe rótulo).
            var rotulo = raiz.querySelector("[data-cropper-rotulo]");
            if (rotulo) rotulo.textContent = "Trocar imagem";
            modal.hide();
        });
    }

    function iniciarTudo() {
        Array.prototype.forEach.call(
            document.querySelectorAll("[data-cropper-campo]"),
            iniciarCampo
        );
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciarTudo);
    } else {
        iniciarTudo();
    }
})();
