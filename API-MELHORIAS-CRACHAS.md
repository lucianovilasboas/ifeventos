# Melhorias na API de crachás do ifeventos

## Contexto

Ao gerar os crachás da SNCT 2026 pela API de produção, o endpoint disponível gerou um PDF geral com crachás de todas as pessoas com algum papel no evento.

Endpoint atual identificado:

```text
GET /api/v1/eventos/{evento_id}/crachas.pdf
```

Descrição no schema:

```text
PDF com os crachás de todas as pessoas com papel no evento.
```

O endpoint não expõe, atualmente, parâmetros para filtrar previamente por papel ou selecionar modelo de crachá.

## Problema observado

A tentativa de obter apenas crachás de palestrantes exigiu gerar primeiro o PDF completo e filtrar páginas depois.

Esse método é frágil porque:

- o filtro acontece depois da geração, não na origem dos dados;
- uma página pode conter mais de um crachá;
- a extração textual do PDF pode não representar perfeitamente o conteúdo visual;
- crachás de participantes podem passar junto por erro de detecção;
- não há garantia de compatibilidade caso o layout do PDF mude.

Resultado prático observado: vieram alguns crachás de participantes junto com os de palestrantes.

## Melhoria recomendada

Alterar a API para aplicar o filtro antes da geração do PDF.

Sugestão de assinatura:

```text
GET /api/v1/eventos/{evento_id}/crachas.pdf?papel=palestrante
```

Possíveis valores para `papel`:

- `participante`
- `palestrante`
- `organizador`
- `todos` ou parâmetro ausente, mantendo o comportamento atual

Também seria útil permitir seleção de modelo:

```text
GET /api/v1/eventos/{evento_id}/crachas.pdf?papel=palestrante&modelo=<nome_do_modelo>
```

Exemplos:

```text
GET /api/v1/eventos/14/crachas.pdf?papel=palestrante
GET /api/v1/eventos/14/crachas.pdf?papel=participante
GET /api/v1/eventos/14/crachas.pdf?papel=palestrante&modelo=compacto
GET /api/v1/eventos/14/crachas.pdf?papel=palestrante&modelo=credenciamento
```

## Comportamento esperado

Quando `papel=palestrante` for informado:

- a API deve selecionar apenas pessoas com papel de palestrante no evento;
- o PDF deve ser gerado já filtrado;
- nenhum crachá de participante comum deve aparecer;
- organizadores só devem aparecer se também forem palestrantes e se essa for a regra desejada;
- a contagem de crachás/páginas deve corresponder ao conjunto filtrado.

Quando `modelo` for informado:

- a API deve usar o layout/modelo solicitado;
- se o modelo não existir, retornar erro claro, por exemplo `400 modelo inválido`;
- se o parâmetro for omitido, manter o modelo padrão atual.

## Compatibilidade

Para não quebrar usos existentes, o endpoint sem parâmetros deve manter o comportamento atual:

```text
GET /api/v1/eventos/{evento_id}/crachas.pdf
```

deve continuar retornando todos os crachás de pessoas com papel no evento.

## Critérios de aceite

1. `GET /eventos/{id}/crachas.pdf` continua funcionando como hoje.
2. `GET /eventos/{id}/crachas.pdf?papel=palestrante` retorna somente crachás de palestrantes.
3. `GET /eventos/{id}/crachas.pdf?papel=participante` retorna somente participantes, sem palestrantes/organizadores, se essa distinção existir na regra de negócio.
4. `GET /eventos/{id}/crachas.pdf?papel=organizador` retorna somente organizadores.
5. Parâmetro inválido em `papel` retorna erro claro, sem gerar PDF incorreto.
6. `modelo=<nome>` seleciona o layout correto quando houver mais de um modelo.
7. Parâmetro inválido em `modelo` retorna erro claro.
8. Testes automatizados cobrem pelo menos:
   - caminho feliz para palestrantes;
   - caminho feliz para participantes;
   - parâmetro `papel` inválido;
   - parâmetro `modelo` inválido;
   - comportamento sem parâmetros preservado.

## Observação

Gerar um PDF externo fora da API é possível, usando a API apenas para consultar dados e montar o layout localmente. Porém, para uso institucional e recorrente, a solução correta é filtrar e selecionar modelo dentro da própria API, antes da geração do PDF.
