# Arte no Altar — Gestão

**Estado atual — 30/10/2026:** a nova referência de feed integrado foi aprovada e
sua implementação autorizada. `continuous-scene-v2` usa cenário contínuo, quinze
frases transparentes e impressão original nas faces dos envelopes, com perspectiva
e luz coerentes. O proprietário aprovou o resultado na hospedagem, mas relatou
um único rascunho: a captura mostra seis modelos prontos no índice e 78 em revisão.
A revisão atual corrige a contagem por lote e a retomada do teste, informa quais
modelos ainda estão disponíveis sem repetição e preserva conteúdos existentes.
Falta aplicar essa correção de controle, consultar o diagnóstico e completar as
duas artes restantes; os modelos em revisão não foram liberados em bloco.

Após essa revisão e ativação, o cron existente cria três artes por lote e, no
terceiro dia, prepara as três seguintes: um feed diário às 12h de São Paulo,
sem escolher temas/modelos, sem preparar os 84 arquivos e sem API de IA paga.
Instruções de atualização, teste e ativação: [FEED_BATCHES.md](FEED_BATCHES.md).
Os layouts rejeitados, inclusive `ambient-scene-v1`, permanecem apenas no
[histórico visual](COMPOSITION_REVIEW.md). Stories e carrosséis não mudaram.

Sistema para gestão individual da Arte no Altar, feito com Python 3.12+ e SQLite.
As dependências de hospedagem, Drive e composição estão em `requirements.txt`.

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

O fluxo principal é a [criação autônoma](FEED_AUTONOMY.md) em lotes de três dias,
Instagram @arte.no.altar, com sorteio sem reposição de modelos e quinze frases
genéricas. Não usa OCR nem depende de escolhas diárias. O formulário manual é
opcional; suas chamadas antigas por tema permanecem para compatibilidade.
O feed final tem 1080 × 1350 e WhatsApp **35 9 8442-8442**.

O [conector de leitura da pasta de originais](DRIVE_SETUP.md) já foi autorizado e
consultado no PythonAnywhere pelo proprietário: 84 PNGs, sem subpastas ou atalhos.
O download de três amostras foi validado e a [primeira proposta de layouts](LAYOUTS.md)
foi rejeitada pelo proprietário, que pediu reiniciar os layouts do zero após ver
as artes com a logo. A aprovação anterior do preto e dourado foi substituída;
`black-gold-v1` fica somente como histórico. A logo original e as fotos já estão
disponíveis em armazenamento privado para a nova composição.
Depois das propostas anteriores rejeitadas, o proprietário aprovou a referência
integrada e autorizou o compositor atual. A aprovação não comprova sua implantação
nem a revisão do lote real. O conector continua somente de leitura; esta correção
não implementa Stories ou carrosséis.

A versão 0.3.0 acrescenta cancelamento e reagendamento confirmados pelo plugin,
com testes isolados e preservação do horário anterior se a nova reserva falhar.
Exige revisão e horário conferidos; o botão de cancelar no site também recusa uma
visão desatualizada. O proprietário confirmou o teste real no Instagram: agendar,
reagendar e cancelar o rascunho #1, terminando em rascunho, revisão 3 e sem
agendamento ativo para esse conteúdo.
