# Arte no Altar — Gestão

**Decisão mais recente:** o proprietário aprovou a nova ambientação com o envelope
recortado sobre a mesa, perspectiva e sombras. Pediu lotes de três artes: um feed
por dia e, no terceiro dia, preparação do próximo lote de três. O código atual
usará o novo compositor e cabeçalhos 3D prontos para as quinze frases. A primeira
execução na hospedagem será um lote de teste em rascunho, antes de retomar envios.
A aprovação da amostra não comprova recortes corretos dos 84 arquivos.
**Instruções atuais de atualização e teste:** [FEED_BATCHES.md](FEED_BATCHES.md).


**Status mais recente:** o proprietário rejeitou o resultado real da montagem
automática. O envelope deve ser integrado ao ambiente, com perspectiva e sombra,
preservando a impressão; o título não pode ficar esticado. A aprovação da arte
de referência não valida o compositor atual. Usar `feed_autonomy.py pause-review`
para parar a criação e cancelar somente a fila gerada pela rotina. A reativação
fica bloqueada até corrigir e aprovar uma saída real do compositor.


**Atualização vigente:** o proprietário aprovou quinze frases curtas genéricas.
A criação diária agora independe de tema e não usa OCR/Tesseract. A rotação de
imagens, a conferência de possíveis duplicações e os agendamentos existentes
são preservados. O banco genérico tem ciclo de quinze chamadas. É necessário
atualizar e reativar a política na hospedagem; ver [FEED_AUTONOMY.md](FEED_AUTONOMY.md).
As referências abaixo à classificação e às doze frases por tema são históricas.


Sistema inicial para gestão individual da Arte no Altar, feito com Python 3.12+ e SQLite, sem dependências externas.

```bash
cd /workspace/codex
python app.py
```

O servidor atende em `127.0.0.1:8000`. Os dados ficam em `.local/arte-no-altar.db`; faça backup desse arquivo com o servidor parado. `ARTENOALTAR_DB` permite escolher outro arquivo. `PORT` altera a porta.

Antes do primeiro acesso, cadastre sua senha com `python app.py set-password` no terminal seguro. A senha deve ter pelo menos 12 caracteres; não envie pelo chat. Não existe senha padrão. Para backup durante o uso, execute `python backup.py /caminho-seguro/backup.db`.

Para hospedagem HTTPS, consulte [DEPLOY.md](DEPLOY.md). A opção prioritária é tentar o plano gratuito do PythonAnywhere com o adaptador WSGI; confirme a disponibilidade e os limites antes de criar a conta. Para um servidor próprio, instale `requirements.txt` e use `python serve.py`, com endereço público e banco persistente configurados. A instalação pública está em https://artenoaltar.pythonanywhere.com; confira as instruções antes de alterar a hospedagem.

Validação: `python -m unittest discover -s tests -v`.

## Recursos

- Receitas, despesas e saldo realizado (não inclui parcelas futuras ou conciliação bancária).
- Cadastro de materiais e ajuste manual de estoque; pedidos não baixam materiais automaticamente.
- Cadastro de pedidos e acompanhamento de etapas; pedidos não geram lançamentos financeiros automaticamente.
- Catálogo comercial com os produtos e preços fornecidos pelo proprietário.
- Rascunhos de publicações e respostas comerciais baseadas no catálogo, disponíveis sem serviço externo. Os rascunhos usam modelos de texto; não são geração por IA.
- Geração opcional de legendas por IA usando a API da OpenAI: disponibilize `ARTENOALTAR_AI_KEY` de forma segura no processo e, opcionalmente, `ARTENOALTAR_AI_MODEL` (padrão: `gpt-4.1-mini`). O acesso a `api.openai.com` precisa estar permitido. A chave fica exclusivamente no servidor. Não inclua segredos no Git. Custos são cobrados pelo provedor. Apenas o produto selecionado e informações públicas da gráfica são enviados.

## Limites desta versão

O login oficial da Meta, a consulta de contas e o envio manual de publicações estão implementados. Leia [META.md](META.md) para configurar a autorização e [PUBLISHING.md](PUBLISHING.md) para configurar a rota estática de imagens e revisar o fluxo de envio. O proprietário confirmou publicações reais nos feeds do Instagram e Facebook. O botão de criar conteúdo prepara um rascunho; o envio exige revisão e confirmação separadas. A fila de agendamento também publicou em teste real com acionamento externo. WhatsApp e recebimento automático de mensagens não estão implementados. O assistente comercial local segue regras e não é um chat de IA. Ele pede confirmação humana para preços não cadastrados, frete, estoque, prazos e exceções.

O acesso tem login individual, sessões de 12 horas, limitação de tentativas e proteção contra submissões de outros sites. `python app.py` é um servidor local de desenvolvimento; use o servidor de produção com HTTPS conforme DEPLOY.md para acesso público. A hospedagem no subdomínio gratuito do PythonAnywhere, o envio pela Meta e o acionamento externo da fila foram validados pelo proprietário. Backups externos automáticos continuam pendentes. Não é um sistema contábil ou fiscal.

## Agendamento

A fila persistente, o formulário de horário de São Paulo, o cancelamento e o executor estão implementados; consulte [SCHEDULING.md](SCHEDULING.md). O proprietário confirmou publicação com console parado e abas fechadas, usando cron-job.org a cada minuto e o [acionamento HTTP protegido](SCHEDULER_HTTP.md). O sistema bloqueia novos agendamentos sem sinal recente do executor. O teste real confirmado não garante disponibilidade permanente no plano gratuito.

## Rotina editorial e conexão com ChatGPT

[CONTENT_WORKFLOW.md](CONTENT_WORKFLOW.md) registra a rotina aprovada de Stories e carrosséis, a preservação das artes originais, o armazenamento no Drive e o fluxo anterior via conector Metricool. Esse documento distingue os requisitos futuros das funcionalidades já validadas. O objetivo é transferir conteúdo criado no ChatGPT para o sistema próprio; registrar o fluxo não ativa a conexão ou a automação.

[MCP_INTEGRATION.md](MCP_INTEGRATION.md) preserva a inspeção histórica anterior à implementação. [MCP_SETUP.md](MCP_SETUP.md) descreve a conexão implantada e o plugin 0.2.0: consultas, importações de rascunho, agendamento pelo plugin e publicação final de um teste real foram confirmados pelo proprietário. Cada sessão precisa ter acesso real ao JPEG para importar; um rascunho existente pode ser agendado pelo ID sem reenviar a imagem. Atualizar o servidor não atualiza automaticamente a habilidade do plugin privado instalado.

O estado confirmado, o teste validado e as melhorias propostas estão em [PENDENCIAS.md](PENDENCIAS.md). O proprietário retomou a integração com Drive para selecionar aleatoriamente modelos sem repetição e criar artes para feed, Stories e carrosséis. Backups e alertas permanecem adiados.

O fluxo principal agora é a [criação diária autônoma](FEED_AUTONOMY.md), conforme
pedido do proprietário: classificar, sortear e montar sem escolhas diárias.
O padrão preparado é um feed às 12h, Instagram @arte.no.altar, com até três dias
à frente e acionamento pelo cron existente. Ainda requer atualização, ativação
e validação real na hospedagem. O formulário abaixo é opcional.

A [montagem de feed](FEED_COMPOSITION.md) já está integrada ao Estúdio de conteúdo:
modelo do Drive e tema selecionados no painel, doze chamadas aprovadas alternadas
com histórico persistente e exportação 1080 × 1350 para rascunho. O layout comercial
atual foi aprovado após as propostas anteriores. Implantação e teste real do novo
fluxo, rotação dos modelos e criação diária ainda estão pendentes.

O [conector de leitura da pasta de originais](DRIVE_SETUP.md) já foi autorizado e
consultado no PythonAnywhere pelo proprietário: 84 PNGs, sem subpastas ou atalhos.
O download de três amostras foi validado e a [primeira proposta de layouts](LAYOUTS.md)
foi rejeitada pelo proprietário, que pediu reiniciar os layouts do zero após ver
as artes com a logo. A aprovação anterior do preto e dourado foi substituída;
`black-gold-v1` fica somente como histórico. A logo original e as fotos já estão
disponíveis em armazenamento privado para a nova composição.
O proprietário forneceu uma nova referência comercial de feed em 1080 × 1350;
a prévia com título branco/dourado, foto grande e botão de WhatsApp aguarda avaliação.
Essa etapa não ativa geração diária, escrita no Drive ou novos formatos de publicação.

A versão 0.3.0 acrescenta cancelamento e reagendamento confirmados pelo plugin,
com testes isolados e preservação do horário anterior se a nova reserva falhar.
Exige revisão e horário conferidos; o botão de cancelar no site também recusa uma
visão desatualizada. O proprietário confirmou o teste real no Instagram: agendar,
reagendar e cancelar o rascunho #1, terminando em rascunho, revisão 3 e sem
agendamento ativo para esse conteúdo.
