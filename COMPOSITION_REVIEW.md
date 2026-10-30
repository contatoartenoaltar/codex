# Revisão da ambientação dos envelopes

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
