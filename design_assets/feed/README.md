# Base contínua de montagem do feed

`scene-v2.jpg` reúne ambiente, mesa, papéis sem impressão, sombras e CTA numa
única fotografia-base. Não contém fotos privadas dos produtos nem credenciais.
`scene-v2.json` calibra as faces dos papéis e a oclusão da pilha pelo envelope
frontal. A impressão vem dos pixels do arquivo original do Drive, por projeção
geométrica e discreto ajuste de luz; letras, logos e QR Codes não são recriados
por IA. Fontes parcialmente ocultas continuam para revisão.

`typography/00.png` a `14.png` são as chamadas aprovadas, em RGBA transparente,
com proporções preservadas e sem painel de fundo. O manifesto vincula texto,
arquivo e hash. O cenário e a primeira tipografia foram preparados no chat;
as outras chamadas reaproveitam o banco anterior com transparência. Nada disso
exige geração por IA durante a execução diária no servidor.

Os scripts de desenvolvimento `tools/prepare_feed_scene.py` e
`tools/prepare_feed_typography.py` documentam a preparação dos assets. A rotina
diária apenas lê os arquivos prontos; não depende dos arquivos do chat.

`template.jpg` e `headers/` preservam a implementação anterior como histórico
e compatibilidade com temas manuais antigos. A rotina genérica atual não os usa
como cenário ou painéis de título.
