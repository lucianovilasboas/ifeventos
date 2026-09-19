# AGENTS.md — IF Eventos

## Fluxo de trabalho de implementação (obrigatório)

Sempre que o usuário pedir uma implementação neste repositório:

1. **Criar uma branch nova** a partir da `main` antes de alterar qualquer arquivo
   (padrão de nome: `fix/<tema>` ou `feat/<tema>`, conforme o tipo).
2. **Implementar** na branch.
3. **Testar** (ver comando abaixo).
4. **Parar e aguardar autorização.** O usuário autoriza o merge e o push; só então
   faça o merge/push. Nunca commitar, fazer merge ou push sem autorização explícita.

Nunca implemente direto na `main`.

## Ciclo V2.0 — Copiloto do Organizador (exceção temporária)

Enquanto o ciclo **V2.0** estiver em andamento, vale o fluxo de integração abaixo
(aprovado pelo usuário):

- Branch de integração **`release/v2.0`**, criada a partir da `main`.
- Cada frente/onda é uma `feat/<tema>` criada a partir de `release/v2.0` e
  mergeada **nela** (merges intra-ciclo são pré-autorizados).
- A `main` e a **produção ficam intocadas** até o ciclo terminar.
- No encerramento: `release/v2.0` → `main`, tag anotada `v2.0.0` e só então deploy.
- Checkpoints intermediários: tags `v2.0.0-dev.N` ao fim de cada onda.
- A versão do produto vem de `ifeventos/setup/version.py` (ver `CHANGELOG.md`).

## Testes

```bash
docker exec app_django bash -lc 'cd /ifeventos && python manage.py test -v 1'
```
