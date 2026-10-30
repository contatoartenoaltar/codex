# Situação e próximos passos — Arte no Altar

**Atualização vigente:** o proprietário aprovou quinze frases curtas genéricas.
A criação diária agora independe de tema e não usa OCR/Tesseract. A rotação de
imagens, a conferência de possíveis duplicações e os agendamentos existentes
são preservados. O banco genérico tem ciclo de quinze chamadas. É necessário
atualizar e reativar a política na hospedagem; ver [FEED_AUTONOMY.md](FEED_AUTONOMY.md).
As referências abaixo à classificação e às doze frases por tema são históricas.


Atualizado com os relatos e a captura fornecidos pelo proprietário em 30/10/2026.
Este registro não é uma consulta em tempo real à hospedagem ou à Meta.

## Validado pelo proprietário

- Publicação de uma foto de feed no Instagram e na página Facebook.
- Criação de imagem e legenda na conversa e importação como rascunho pelo plugin,
  com visualização no sistema e recibo; novo teste confirmado após a atualização 0.1.1.
- Publicação agendada pelo sistema, usando cron-job.org a cada minuto, com o console
  parado e as abas fechadas.
- Atualização do plugin privado para 0.2.0, preservando a conexão MCP.
- Revisão e confirmação pelo plugin do rascunho #3 para Instagram @arte.no.altar,
  em 30/10/2026 às 10h15, America/Sao_Paulo. O retorno informou fila e executor ativo,
  e a captura do sistema mostrou esse agendamento.
- O proprietário confirmou depois a publicação desse rascunho #3 no Instagram,
  concluindo o teste de revisão, agendamento pelo plugin e execução automática.
- Plugin 0.3.0 atualizado e ferramentas de reagendar/cancelar disponíveis após
  reconectar o MCP. O proprietário confirmou o teste real do #1 no Instagram:
  agendar em 30/10/2026 às 11h10, reagendar às 11h20 e cancelar ao final. Os três
  recibos foram consultados; o estado final informado foi rascunho, revisão 3,
  agendamento cancelado e nenhum agendamento ativo para esse conteúdo.

## Teste do agendamento pelo plugin concluído

A publicação do rascunho #3 foi confirmada pelo proprietário. Não tratar esse post
como pendente nem recriá-lo para repetir o teste. Recibos e presença na fila, por si
sós, continuam não comprovando publicação de outros conteúdos.

O teste de cancelamento e reagendamento do #1 também foi concluído. Não reativar
esse agendamento para repetir o teste: ele deve permanecer cancelado, salvo nova
solicitação e confirmação do proprietário.

## Próximas melhorias propostas

**Correção mais recente:** o proprietário não quer escolher modelo ou tema.
A rotina autônoma foi implementada com OCR local, índice gradual, sorteio sem
reposição e frases alternadas. O padrão preparado é Instagram @arte.no.altar,
um feed diário às 12h, até três dias à frente. A ativação grava a política e
habilita etapas nas chamadas ociosas do cron existente. O painel mostra seu
andamento; a seleção manual ficou secundária. Casos incertos ficam separados
e impedem reiniciar o ciclo. Ver [FEED_AUTONOMY.md](FEED_AUTONOMY.md).
Faltam implantação, verificação do Tesseract na hospedagem, ativação, análise
real dos 84 arquivos e teste de publicação pela nova política. Não apresentar
os testes locais como comprovação dessas etapas reais.

**Atualização:** após as propostas rejeitadas abaixo, o proprietário aprovou o
novo feed comercial e doze chamadas curtas. A montagem com Drive e alternância
persistente das frases foi integrada ao Estúdio de conteúdo. Ver
[FEED_COMPOSITION.md](FEED_COMPOSITION.md) para implantação e teste real.
O modelo e seu tema ainda são selecionados no painel; agrupamento, sorteio geral
sem repetição e criação diária sem abrir o chat permanecem pendentes. O cron e
os agendamentos existentes não foram alterados.

Primeira parte validada pelo proprietário: consulta autenticada pelo servidor,
somente leitura, encontrou 84 PNGs na pasta de originais, sem subpastas ou atalhos.
O download real de três amostras também funcionou e o ZIP foi enviado à conversa.
As três imagens PNG RGB de 1448 × 1086 px foram abertas e conferidas. A primeira
proposta de montagem está registrada em [LAYOUTS.md](LAYOUTS.md). Depois de ver
os cinco quadros com a logo, o proprietário rejeitou a proposta e pediu começar
os layouts do zero; essa decisão substitui a aprovação inicial do preto e dourado.
Não usar `black-gold-v1` na rotina. A logo recebida em `LOGOPNGAA.rar` e os originais
continuam disponíveis; não pedir novo envio. Preparar um novo feed para definir
a direção visual. O feed foi confirmado em 1080 × 1350. A referência comercial
foi recebida: título branco e dourado com volume, foto grande e botão dourado de
WhatsApp. A nova prévia `feed-gold-commercial-v2` está preparada e aguarda avaliação;
não está aprovada para publicação. Uma referência distinta
de Story “Palavra da Manhã” foi enviada, com fundo claro, amanhecer e Bíblia aberta;
o proprietário confirmou um versículo todos os dias. Preparar Stories em
1080 × 1920, com texto/referência conferidos; a tradução bíblica ainda está
em definição. Os arquivos anteriores
ficam apenas como histórico privado e não foram implantados na hospedagem.
Quantidade de imagens ainda não equivale a quantidade de
modelos distintos. Ver [DRIVE_SETUP.md](DRIVE_SETUP.md).

1. Integrar a pasta de originais do Drive ao fluxo de criação pelo ChatGPT. O
   proprietário retomou essa tarefa após validar o agendamento: catalogar modelos,
   sortear aleatoriamente sem repetição até completar o ciclo, criar imagens e
   legendas para feed, Stories e carrosséis e transferir ao sistema para revisão
   e agendamento. Validar acesso real aos arquivos; manter os originais preservados
   por montagem com camadas e guardar histórico do modelo/ciclo. O proprietário
   definiu execução diária mesmo sem abrir o chat e escolheu montagem automática
   com layouts e textos aprovados, sem API de IA paga. A rotina deve ser ativada
   somente após aprovação de layouts/modelos e calendário, sem pedir confirmação
   diária na conversa depois dessa autorização. Preparar autenticação própria do servidor para
   acessar a pasta privada. O link já foi fornecido; não pedir novamente nem
   torná-la pública.
2. Implementar e testar Stories: formato vertical, legenda opcional e diferenças
   de publicação de cada canal. A foto de feed atual não equivale a um Story.
3. Implementar e testar carrosséis: múltiplas imagens, ordem dos slides, revisão,
   importação, publicação e agendamento.
4. Planejar lotes dos próximos três dias a partir da rotina editorial, consultar
   horários existentes e evitar temas repetidos. Não há execução autônoma da criação
   de novas artes/legendas fora da conversa; definir e validar esse mecanismo antes
   de prometer que o ChatGPT gerará conteúdo continuamente.

Os itens restantes são propostas a priorizar; essa lista não autoriza agendar conteúdos
ainda não revisados nem contratar serviços.

## Adiado a pedido do proprietário

- **Lembrete para a próxima revisão das pendências:** retomar backup automático
  e alertas de falha. O proprietário pediu expressamente para deixar a implementação
  para outro momento e ser lembrado. Ainda faltam cópias externas automáticas,
  restauração e proteção das imagens/configurações privadas, além dos alertas de
  falhas de publicação ou necessidade de reconectar à Meta. Esse é um lembrete de
  acompanhamento do projeto, sem data definida ou notificação automática agendada.

A integração com Drive, os templates e a rotação já não estão adiados: o
proprietário os retomou como foco atual, com sorteio aleatório sem repetição.
Fotos diferentes do mesmo envelope não contam como modelos novos.

## Limites que permanecem

- Plugin atual: uma foto JPEG de feed, importação como rascunho, consulta e
  agendamento, cancelamento e reagendamento confirmados, com teste real do controle
  da fila no Instagram. Sem publicação imediata, Stories, carrosséis ou Drive.
- Vídeos e Reels continuam manuais, conforme a rotina informada.
- O histórico e a agenda do plugin são locais e podem omitir publicações externas.
- Executor depende de chamadas bem-sucedidas do cron-job.org, hospedagem disponível
  e autorização válida da Meta. O teste confirmado não garante disponibilidade futura.
- Não contratar serviços pagos nem uso de APIs pagas sem autorização. ChatGPT Plus
  não demonstra, por si só, execução de geração de conteúdo fora da conversa.
