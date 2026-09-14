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
 * Depende de: bootstrap (modal) e Cropper, ambos carregados no dashboard_base.
 */
(function () {
    "use strict";

    var ATTR_INICIADO = "data-cropper-init";

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
                alvo.src = leitor.result;
                modal.show();
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
            });
        });

        modalEl.addEventListener("hidden.bs.modal", function () {
            if (cropper) {
                cropper.destroy();
                cropper = null;
            }
        });

        confirmar.addEventListener("click", function () {
            if (!cropper) return;
            var canvas = cropper.getCroppedCanvas({ width: largura, height: altura });
            if (!canvas) return;
            var dataUrl = canvas.toDataURL("image/png");
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
