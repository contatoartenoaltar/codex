# Stories comerciais — prévias isoladas

Esta etapa gera somente imagens locais de revisão em 1080 × 1920.
Ela não acessa a Meta, não agenda publicações e não grava no banco do feed ou
na fila dos Stories de versículos.

```bash
python3 promotional_story.py caminho/do/modelo.jpg .local/promotional-story-preview.jpg
```

A composição usa o cenário publicitário aprovado e retifica somente a face
impressa do envelope. Mesa, pilha, parede e outros elementos da foto original
ficam fora da montagem. Se a face completa não puder ser identificada com
segurança, o modelo fica fora daquele lote e outro é escolhido. O lote diário
exige 10 modelos diferentes e registra os horários 04:00, 06:00, 08:00, 10:00,
12:10, 14:00, 16:00, 18:00, 20:00 e 22:00. O manifesto de prévia sempre mantém
`publishing_enabled` como `false`. Cada lote usa também 10 chamadas diferentes,
uma por Story. A seleção diária deve percorrer o catálogo antes de reiniciar o
ciclo de modelos e nunca pode repetir um modelo dentro do mesmo dia.
