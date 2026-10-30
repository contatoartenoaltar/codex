# Rotina de conteúdo — Arte no Altar

Referência fornecida pelo proprietário para o projeto próprio. Distinguir o fluxo já utilizado no Metricool das funcionalidades que ainda precisam ser construídas na Arte no Altar. Registrar requisitos não significa que as integrações, formatos ou automações estejam implementados.

## Objetivo e arquitetura desejada

O ChatGPT cria as imagens e legendas durante a conversa e envia os conteúdos por uma conexão, como acontecia com o conector do Metricool. O objetivo aceito neste projeto é substituir o Metricool por nosso sistema, sem contratar outro gerenciador de redes. Não pressupor que o usuário deseje geração autônoma pela API da OpenAI: o proprietário utiliza ChatGPT Plus e quer aproveitar a criação dentro do chat.

Transferir conteúdo criado no chat não exige, por si só, uma chamada à API de geração. Ainda é necessário implementar uma conexão autenticada compatível com as opções disponíveis na conta ChatGPT e verificar como a ferramenta entrega os arquivos de imagem. Não prometer acesso a arquivos gerados só por conhecer seus nomes ou links internos. O funcionamento sem uma conversa aberta exige executor de agendamentos separado; a assinatura Plus não fornece esse executor.

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

Usar artes aprovadas como referência e arquivos originais dos envelopes disponíveis no Google Drive. Padrão visual relatado como aprovado:

- Títulos brancos e dourados em 3D; fundo preto e dourado.
- Mesa de madeira e iluminação quente; envelope integrado naturalmente à cena.
- Botão de WhatsApp e logo oficial da Arte no Altar sobre fundo branco.
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
- A fila de agendamento, horário de São Paulo, cancelamento e executor estão implementados. O plano gratuito do PythonAnywhere não disponibiliza Scheduled tasks nem Always-on tasks. A execução automática em produção ainda não foi ativada.
- Não existem ainda conexão própria com ChatGPT, integração com Drive, Stories, carrosséis ou rotina automática de três dias.
- A transferência por conexão deve admitir envio dos arquivos, formatos distintos, slides ordenados, consulta de horários existentes e retorno de IDs/status verificáveis. Nunca expor credenciais da Meta ao chat.
- Planejar Stories e carrosséis como novos formatos; não apresentar o envio atual de uma única foto como se já cobrisse a rotina inteira.

Antes de escolher um mecanismo de conexão, conferir quais opções de aplicativos personalizados estão disponíveis na conta ChatGPT. Antes de prometer automação contínua gratuita, validar o executor e seus limites reais. Não contratar serviço pago ou uso de API de geração sem autorização.
