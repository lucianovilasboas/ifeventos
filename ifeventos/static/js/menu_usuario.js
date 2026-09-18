/**
 * Menu do usuário (avatar) — contexto + conta.
 *
 * Toggle próprio (sem Bootstrap) para funcionar também na landing, que não
 * carrega o bundle. Abre/fecha no clique do avatar, fecha ao clicar fora, no
 * Esc e ao navegar. "Meu perfil" abre o modal de edição quando ele existe na
 * página (telas internas); fora delas, cai no link do painel.
 */
(function () {
    const menus = document.querySelectorAll('[data-menu-usuario]');
    if (!menus.length) return;

    function fechar(menu) {
        const painel = menu.querySelector('[data-menu-painel]');
        const gatilho = menu.querySelector('[data-menu-gatilho]');
        if (painel) painel.hidden = true;
        if (gatilho) gatilho.setAttribute('aria-expanded', 'false');
    }

    function fecharTodos(exceto) {
        menus.forEach(function (menu) {
            if (menu !== exceto) fechar(menu);
        });
    }

    menus.forEach(function (menu) {
        const gatilho = menu.querySelector('[data-menu-gatilho]');
        const painel = menu.querySelector('[data-menu-painel]');
        if (!gatilho || !painel) return;

        gatilho.addEventListener('click', function (evento) {
            evento.stopPropagation();
            const abrir = painel.hidden;
            fecharTodos(menu);
            painel.hidden = !abrir;
            gatilho.setAttribute('aria-expanded', abrir ? 'true' : 'false');
        });

        const perfil = menu.querySelector('[data-menu-perfil]');
        if (perfil) {
            perfil.addEventListener('click', function () {
                const modal = document.getElementById('editProfileModal');
                if (modal && window.bootstrap && window.bootstrap.Modal) {
                    window.bootstrap.Modal.getOrCreateInstance(modal).show();
                } else if (perfil.dataset.perfilUrl) {
                    window.location.href = perfil.dataset.perfilUrl;
                }
                fecharTodos();
            });
        }
    });

    // Clique/toque fora fecha. O clique no gatilho para a propagação para não
    // reabrir/fechar no mesmo evento.
    document.addEventListener('click', function () {
        fecharTodos();
    });
    document.addEventListener('keydown', function (evento) {
        if (evento.key === 'Escape') fecharTodos();
    });
})();
