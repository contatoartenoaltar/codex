# Revisão da ambientação dos envelopes

**Retorno da hospedagem — 30/10/2026:** o proprietário aprovou o resultado real
do novo compositor e informou somente um rascunho. O status mostra `preview`,
`waiting`, seis modelos prontos e 78 em revisão; a causa exata exige o novo
diagnóstico por lote. A montagem visual deixa de ser a pendência principal:
agora é necessário completar as duas artes restantes, preservando a primeira.
Ver [FEED_BATCHES.md](FEED_BATCHES.md) para a revisão da contagem e retomada.

**Estado atual — 30/10/2026:** o proprietário aprovou a nova referência visual
integrada e autorizou implementar a montagem automática correspondente. A referência
gerada no chat está em
`/workspace/generated_images/exec-ff790868-fabc-4431-bb08-ab278f28e69b.png`;
ela define a direção visual, mas não é uma saída do servidor.

O compositor `continuous-scene-v2` está implementado em `product_scene.py`: cenário
contínuo, quinze chamadas com transparência e impressão original projetada nas faces
dos papéis. Perspectiva, bordas, espessura, sombras e oclusão seguem a mesma cena.
A impressão recebe ajuste discreto de luminosidade do papel, de 0,94 a 1,04;
não há redesenho de letras, logos ou QR Codes por IA nem igualdade literal dos pixels.
WhatsApp: **35 9 8442-8442**. Feed: **1080 × 1350**.

Duas amostras reais foram renderizadas e conferidas localmente em
`.local/design-review/continuous-01.png` e `continuous-03.png`. A amostra com parte
do papel oculta por um livro continua retida. Isso não valida os recortes dos
84 arquivos nem constitui aprovação do primeiro lote da hospedagem.

Falta completar e conferir três rascunhos produzidos pelo mesmo código,
conforme [FEED_BATCHES.md](FEED_BATCHES.md). Depois da configuração e da revisão
desse lote, a rotina dispensa API de IA paga e conversa diária. Prepara três artes;
no terceiro dia prepara as três seguintes. Não processa a pasta inteira.
Nenhuma ação remota, importação, agendamento ou publicação foi executada nesta revisão.

## Histórico — propostas superadas

`ambient-scene-v1` foi rejeitado porque frase, envelopes e cenário ainda pareciam
partes separadas. A aprovação anterior dessa amostra não autoriza retomar esse
layout. O cabeçalho opaco e a pilha montada separadamente deixaram de ser o fluxo atual.

**Decisão daquela etapa:** o proprietário aprovou a nova ambientação com o envelope
recortado sobre a mesa, perspectiva e sombras. Pediu lotes de três artes: um feed
por dia e, no terceiro dia, preparação do próximo lote de três. O código atual
usará o novo compositor e cabeçalhos 3D prontos para as quinze frases. A primeira
execução na hospedagem será um lote de teste em rascunho, antes de retomar envios.
A aprovação da amostra não comprova recortes corretos dos 84 arquivos.
**Instruções atuais de atualização e teste:** [FEED_BATCHES.md](FEED_BATCHES.md).


O proprietário rejeitou a montagem realmente produzida na hospedagem: havia uma
foto retangular sobre o cenário e um título esticado. Esclareceu que os envelopes
devem parecer inseridos no ambiente. A aprovação anterior da imagem de referência
não é aprovação do compositor que gerou esse resultado. Os testes anteriores
verificavam preservação da foto, estado e dimensões; não comprovavam fidelidade visual.

Foi preparada uma amostra privada em `.local/design-review/ambient-scene-preview.png`.
Ela usa a impressão original do envelope de Primícias, extraída por quatro pontos
do papel na amostra recebida. A face é projetada sobre um envelope frontal e a
pilha, com espessura, perspectiva e sombras na mesa do template. A impressão não
é redesenhada por geração de imagens. O fundo da fotografia original fica fora
da montagem. O cabeçalho é um elemento 3D preparado uma vez, com uma das quinze
frases aprovadas, sem esticar os glifos.

Essa é uma amostra de composição feita por código, ainda com pontos de recorte
marcados para uma amostra específica. Não demonstra extração automática confiável
dos 84 arquivos. As outras imagens precisam de recortes/conferência adequados na
configuração inicial, e os quinze cabeçalhos precisam ter o mesmo tratamento.
Não substituir a revisão por outra imagem de IA que o código real não reproduza.
A nova saída precisa de avaliação visual antes de integrar e retomar a rotina.

O comando `feed_autonomy.py pause-review` desativa novas criações, devolve para
rascunho os agendamentos ainda na fila que estejam ligados às composições da
rotina e preserva os demais agendamentos e os arquivos. Envios já iniciados não
são cancelados; o comando informa sua quantidade para conferência na rede.
A política fica marcada para revisão visual, impedindo reativação por engano.

Não afirmar que a rotina remota já foi pausada apenas porque o comando foi
implementado e testado localmente: o proprietário precisa executá-lo no servidor.
