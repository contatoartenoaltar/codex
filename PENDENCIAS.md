# Situação e próximos passos — Arte no Altar

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

1. Configurar backups externos automáticos e sua restauração, mantendo imagens e
   configurações privadas protegidas; alertas de falha ou necessidade de reconexão
   à Meta também estão pendentes. Não confundir status consultável com alerta enviado.
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

- Conexão com a pasta privada de originais no Google Drive, catálogo de modelos e
  pasta de saída para as artes finais. O link de origem já foi fornecido; o acesso
  e o conteúdo ainda não foram validados nesta conversa.
- Montagem por templates com fotos originais preservadas, sem recriar textos,
  logos ou QR Codes do envelope.
- Controle persistente de rotação: cada nova arte usa um modelo ainda não usado;
  repetir somente após todos os modelos da pasta terem sido utilizados. Fotos
  diferentes do mesmo envelope não contam como modelos novos.

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
