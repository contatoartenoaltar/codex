# Rotina de conteúdo — Arte no Altar

**Decisão mais recente:** o proprietário aprovou a nova ambientação com o envelope
recortado sobre a mesa, perspectiva e sombras. Pediu lotes de três artes: um feed
por dia e, no terceiro dia, preparação do próximo lote de três. O código atual
usará o novo compositor e cabeçalhos 3D prontos para as quinze frases. A primeira
execução na hospedagem será um lote de teste em rascunho, antes de retomar envios.
A aprovação da amostra não comprova recortes corretos dos 84 arquivos.
**Instruções atuais de atualização e teste:** [FEED_BATCHES.md](FEED_BATCHES.md).


**Atualização vigente:** o proprietário aprovou quinze frases curtas genéricas.
A criação diária agora independe de tema e não usa OCR/Tesseract. A rotação de
imagens, a conferência de possíveis duplicações e os agendamentos existentes
são preservados. O banco genérico tem ciclo de quinze chamadas. É necessário
atualizar e reativar a política na hospedagem; ver [FEED_AUTONOMY.md](FEED_AUTONOMY.md).
As referências abaixo à classificação e às doze frases por tema são históricas.


Referência fornecida pelo proprietário para o projeto próprio. Distinguir o fluxo já utilizado no Metricool das funcionalidades que ainda precisam ser construídas na Arte no Altar. Registrar requisitos não significa que as integrações, formatos ou automações estejam implementados.

## Objetivo e arquitetura desejada

Decisão mais recente: o proprietário não quer selecionar modelo ou tema no dia a
dia. A rotina de [FEED_AUTONOMY.md](FEED_AUTONOMY.md) implementa classificação
local, seleção sem reposição, frases alternadas e preparação/agendamento pela
política autorizada. Padrão preparado: Instagram @arte.no.altar, um feed às 12h,
São Paulo, até três dias à frente. Ela depende de ativação inicial e validação
na hospedagem; não afirmar que os testes locais já são publicação real.

O objetivo atualizado é usar imagens originais de uma pasta do Google Drive como fonte para montar novas artes e legendas e realizar as postagens automaticamente, substituindo o Metricool. O fluxo não deve depender de o proprietário anexar cada imagem individualmente ao chat. O acesso autorizado à pasta e a leitura real de 84 PNGs foram validados na hospedagem; a ligação com a montagem e a rotina diária ainda precisa ser implementada.

Após validar o agendamento pelo plugin, o proprietário retomou explicitamente
essa ideia: escolher aleatoriamente modelos do Drive e criar artes para feed,
Stories e carrosséis. O foco agora é integrar seleção de originais, criação das
artes/legendas e envio ao sistema, e não apenas acrescentar Stories isoladamente.
A aleatoriedade deve respeitar a rotação sem repetição descrita abaixo. O
proprietário definiu que a rotina deve funcionar todos os dias, mesmo sem abrir
o ChatGPT, com execução no servidor. Escolheu montagem automática com layouts e
textos aprovados, sem API de IA paga. A criação diária não deve depender de novas
chamadas de geração por IA. O Plus não fornece créditos de API ao servidor; não
contratar nem executar chamadas pagas sem autorização.

No modo de montagem automática, o ChatGPT pode preparar cenários, layouts e textos
durante a configuração; o servidor combina esses elementos aprovados com as fotos
originais a cada execução diária. Isso não deve ser apresentado como uma geração
nova por IA em cada execução. O acesso autônomo à pasta privada também exige uma
autenticação própria do servidor; conectar o Google Drive apenas ao ChatGPT não
fornece automaticamente esse acesso ao PythonAnywhere.

A ativação diária deverá ter configuração e autorização do proprietário para os
layouts, os modelos e o calendário que poderão ser usados automaticamente. Depois
de ativada, a rotina deve manter os próximos três dias preparados sem depender de
confirmação diária na conversa, respeitando as regras aprovadas. A confirmação por
post continua valendo para as operações conversacionais atuais do plugin; não
fingir uma confirmação humana para ativar a nova rotina ainda não implementada.

Uma importação de imagem e legenda pelo MCP, seguida de recibo e visualização no sistema, foi confirmada pelo proprietário. Isso valida aquele teste, não a seleção e criação automática a partir do Drive. Não prometer acesso a arquivos só por conhecer seus nomes ou links internos. O proprietário utiliza ChatGPT Plus: não presumir autorização para contratar API de geração. A criação autônoma fora da conversa precisa de mecanismo de geração e execução especificamente definido e testado; o Plus e o conector de consultas não comprovam essa capacidade por si sós.

## Fluxo automático a implementar

1. Ler a pasta privada de originais autorizada no Drive, usando IDs estáveis dos arquivos. Não exigir que a pasta inteira se torne pública e não substituir a autorização da API por scraping de links de compartilhamento.
2. Sortear aleatoriamente um modelo ainda não utilizado no ciclo atual, respeitando a regra de rotação abaixo e consultando a agenda antes de preencher os próximos três dias. O proprietário informou que cancelou manualmente todos os agendamentos no Metricool.
3. Montar artes com templates e as fotos originais preservadas, criando cenários e chamadas fora da impressão do envelope. Não reconstruir textos, logos ou QR Codes com geração de imagem.
4. Gerar legendas a partir do catálogo e das respostas comerciais aprovadas. A rotina de aprovação dos templates/lotes e a autorização de publicação automática precisam ficar explícitas; não usar um simples pedido de resumo como autorização de envio.
5. Guardar versões finais em pasta de saída separada dos originais, conferindo os arquivos e mantendo a ligação entre origem, template, legenda, formato e horário.
6. Enviar pelos canais da Meta e acompanhar o resultado. O executor de fotos de feed já publicou com acionamento externo; Stories, carrosséis e geração autônoma ainda precisam de implementação e testes próprios.

A pasta de origem não é necessariamente a pasta de saída “03-Artes para postagens”. Usar o link já fornecido sem pedir novamente, nem solicitar senhas, tokens ou compartilhamento público. Nesta conversa, as ferramentas de Drive ainda não estavam disponíveis quando o link foi fornecido.

O proprietário confirmou que essa pasta reúne os modelos à venda e que possui
projeto Google Cloud. A consulta real em `drive_source.py`, executada na hospedagem
e mostrada pelo proprietário, encontrou 84 PNGs, sem subpastas ou atalhos. Ainda
é preciso conferir quais imagens representam o mesmo modelo antes de ativar a
rotação. O comando de amostras está preparado para avaliar os originais e aprovar
layouts, sem modificar o Drive nem ativar a rotina diária. Instruções em
[DRIVE_SETUP.md](DRIVE_SETUP.md). As ferramentas do plugin Drive continuam não
disponibilizadas nesta conversa; a consulta real foi feita pelo servidor.

O proprietário havia adiado Drive, templates e rotação para priorizar o
agendamento. Com o controle da fila validado, retomou essa integração como foco
atual. Backups e alertas continuam adiados. Ver [PENDENCIAS.md](PENDENCIAS.md).

## Rotação obrigatória dos modelos

Cada nova arte que utilizar um modelo de envelope como referência deve escolher um modelo diferente dos já usados no ciclo atual. Só permitir repetição depois que todos os modelos da pasta tiverem sido utilizados; então iniciar um novo ciclo. A regra vale entre dias, lotes e formatos, não apenas dentro de um mesmo lote.

Dentro de cada ciclo, o sorteio deve considerar somente os modelos ainda não
usados ou reservados por outra criação em andamento; não fazer sorteios
independentes de todos os arquivos que permitam repetir antes de completar o ciclo.

O controle deve identificar o modelo, e não apenas o arquivo: fotografias, recortes ou versões diferentes do mesmo envelope não contam como modelos novos. Registrar de forma persistente o ciclo, o modelo e a arte criada, para não reiniciar a rotação ao fechar o chat ou reiniciar o sistema. Artes já criadas contam como uso mesmo antes da publicação; reservar modelos durante a criação para evitar escolhas duplicadas simultâneas.

Ao incluir novos modelos na pasta, utilizá-los antes de permitir a repetição de modelos já usados. Consultar e conferir o catálogo da pasta antes de afirmar que o ciclo terminou. Essa seleção e seu controle persistente ainda precisam ser implementados e validados na integração com o Drive.

## Planejamento aprovado

Conta Instagram: **@arte.no.altar**. Fuso obrigatório: **America/Sao_Paulo**.

| Frequência | Horário | Formato e tema |
| --- | --- | --- |
| Todos os dias | 07h30 | Story “Palavra da Manhã” |
| Todos os dias | 10h00 | Story de produtos |
| Todos os dias | 16h00 | Story com chamada para WhatsApp |
| Segunda, quarta e sexta | 12h00 | Carrossel com pergunta e resposta de clientes |

Manter os próximos três dias programados. Antes de criar ou agendar, consultar a agenda e os conteúdos recentes para evitar conflitos de horários e repetição de temas ou modelos de envelopes. Não considerar um plano de horários como autorização para publicar imediatamente um lote de conteúdos ainda não revisados. Vídeos e Reels permanecem manuais.

## Imagens e identidade visual

Atualização posterior às rejeições registradas abaixo: o proprietário aprovou o
novo feed comercial com botão e número `35 9 8442-8442`, as doze chamadas curtas
e sua integração. `feed_composer.py` monta o feed com a foto preservada e alterna
as chamadas por tema. O painel salva o resultado como rascunho; ainda faltam a
classificação dos modelos, o sorteio sem repetição e a execução diária autônoma.
Detalhes e implantação em [FEED_COMPOSITION.md](FEED_COMPOSITION.md).

Decisão visual atual: o proprietário rejeitou a primeira proposta de feed, Story
e carrossel com logo e pediu começar os layouts do zero. Essa decisão substitui
a aprovação anterior do preto e dourado. O script `layout_preview.py` ainda gera
essa proposta antiga; não usá-lo como template aprovado para a rotina.

O feed foi definido em **1080 × 1350 px (4:5)**. O proprietário enviou uma nova
referência comercial com título branco/dourado volumoso, produto grande sobre
madeira e botão dourado para WhatsApp. A nova prévia está em avaliação;
a referência não reaprova a composição rejeitada. Para o Story diário “Palavra da Manhã”,
enviou uma referência clara, com luz do amanhecer, Bíblia aberta, folhagem, cruz,
logo integrada ao topo, versículo preto com palavra cursiva dourada e curvas nas
cores da marca no rodapé. A produção do Story será em **1080 × 1920 px (9:16)**.
Essa referência de Story não deve ser tratada como exemplo do feed.

Haverá um versículo bíblico todos os dias. Manter texto e referência como campos
editáveis, com citações conferidas; a tradução bíblica ainda precisa ser definida
antes da montagem do catálogo de textos. O exemplo recebido usa Filipenses 4:13.
Ver detalhes em [LAYOUTS.md](LAYOUTS.md). O envio da referência não significa que
o template ou a publicação automática de Stories estejam implementados.

O padrão anteriormente relatado, agora apenas histórico da proposta rejeitada, era:

- Títulos brancos e dourados em 3D; fundo preto e dourado.
- Mesa de madeira e iluminação quente; envelope integrado naturalmente à cena.
- Botão de WhatsApp e logo oficial da Arte no Altar sobre fundo branco.

Regras gerais que permanecem:

- Cada arte de produto deve usar um modelo diferente de envelope.
- Telefone comercial: **(35) 98442-8442**.
- Alternar chamadas: “Peça seu orçamento”, “Faça seu pedido” e “Fale conosco”.

Preservar integralmente a impressão original dos envelopes: textos, logos, cores, desenhos e QR Codes. Todas as chamadas externas devem ficar fora do envelope. Priorizar templates com camadas e fotografias originais como elementos preservados; não pedir à geração de imagens que reconstrua a impressão. Qualquer montagem precisa passar por revisão visual. Se um QR Code for deformado ou o texto original mudar, a arte não deve ser aprovada.

A rotina anterior encontrou falhas nessa preservação e deixou incompleta a refação de conteúdos para 30 e 31/10. Isso é contexto histórico; não presume que esses arquivos estejam disponíveis no projeto ou que os respectivos agendamentos ainda estejam pendentes. Consultar a origem antes de refazer ou agendar para essas datas.

## Legendas e informações comerciais

Perguntas e respostas devem vir das informações do proprietário: envio, localização, personalização, pedido mínimo, preços e formas de pagamento. Não inventar descontos, frete grátis, disponibilidade, prazos ou condições comerciais.

Nos carrosséis, apresentar a dúvida, explicar a resposta e terminar com chamada para WhatsApp. A legenda dos Stories deve poder ficar vazia: a mensagem principal fica na imagem. Isso exige adaptar as validações atuais, que exigem legenda não vazia para a publicação de feed.

Não atualizar a tabela de preços com base em uma arte antiga; confirmar qual tabela está vigente. A conta é de uma gráfica cristã em Poços de Caldas/MG, com envio para todo o Brasil.

## Arquivos e comprovação

No fluxo anterior, cada PNG final era enviado à pasta **“03-Artes para postagens”** do Google Drive, em subpastas pela data de publicação. Os nomes identificavam data, horário, formato e número do slide. Conferir a listagem após enviar, em vez de afirmar sucesso apenas por ter tentado a operação.

Não alterar o compartilhamento de pastas inteiras para torná-las públicas sem necessidade. Guardar separadamente o original aprovado e qualquer versão exportada para publicação. A versão atual do sistema aceita JPEG; ingestão de PNG, conversão e múltiplos slides precisam ser implementadas e validadas. Não modificar os originais para satisfazer uma limitação de formato.

## Histórico do Metricool

O fluxo anterior usava o conector do Metricool no ChatGPT, marca **blogId 7655912**. Não era uma integração própria desenvolvida neste repositório.

Os agendamentos tinham horário local e fuso explícito, rede Instagram, `instagramData.type = "STORY"` para Stories e `instagramData.type = "POST"` para carrosséis, slides na ordem correta, `autoPublish = true` e `draft = false`. Depois, a agenda era consultada novamente para conferir horário, imagens, formato e status pendente.

Esses são parâmetros do Metricool, não nomes de campos da API Meta. Não copiá-los diretamente para a integração própria. No sistema próprio, implementar equivalentes para formato, ordem, revisão, confirmação, consulta da agenda e comprovação do resultado. A menção à integração Metricool na explicação recebida descreve a referência anterior; o objetivo confirmado nesta conversa continua sendo substituí-lo.

## Estado confirmado e próximos requisitos

- O proprietário validou publicações reais de uma foto no feed do Instagram e na página Facebook.
- O Instagram funcionou preparando o arquivo pela foto não publicada na página vinculada da Meta; buscar a imagem diretamente no PythonAnywhere havia falhado.
- A fila de agendamento, horário de São Paulo, cancelamento e executor estão implementados. O proprietário confirmou publicação real com o console e depois com o console parado e as abas fechadas, usando cron-job.org a cada minuto. O plano gratuito do PythonAnywhere não disponibiliza Scheduled tasks nem Always-on tasks; consulte SCHEDULER_HTTP.md para o acionamento HTTP protegido.
- A conexão MCP própria já fez consultas e importações reais de rascunho com imagem e legenda, inclusive após a atualização 0.1.1. O plugin 0.2.0 foi atualizado e colocou o rascunho #3 na fila após revisão e confirmação; o proprietário confirmou depois sua publicação final. Integração com Drive, Stories, carrosséis e rotina automática de três dias continuam pendentes.
- A transferência por conexão deve admitir envio dos arquivos, formatos distintos, slides ordenados, consulta de horários existentes e retorno de IDs/status verificáveis. Nunca expor credenciais da Meta ao chat.
- Planejar Stories e carrosséis como novos formatos; não apresentar o envio atual de uma única foto como se já cobrisse a rotina inteira.

Antes de escolher um mecanismo de conexão, conferir quais opções de aplicativos personalizados estão disponíveis na conta ChatGPT. Antes de prometer automação contínua gratuita, validar o executor e seus limites reais. Não contratar serviço pago ou uso de API de geração sem autorização.
