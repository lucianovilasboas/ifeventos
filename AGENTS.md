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

## Testes

```bash
docker exec app_django bash -lc 'cd /ifeventos && python manage.py test -v 1'
```
