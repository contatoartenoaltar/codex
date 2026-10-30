# Arte no Altar — Gestão

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

O login oficial da Meta, a consulta de contas e o envio manual de publicações estão implementados. Leia [META.md](META.md) para configurar a autorização e [PUBLISHING.md](PUBLISHING.md) para configurar a rota estática de imagens e revisar o fluxo de envio. O proprietário confirmou publicações reais nos feeds do Instagram e Facebook. O botão de criar conteúdo prepara um rascunho; o envio exige revisão e confirmação separadas. A fila de agendamento está implementada, com execução em produção ainda pendente. WhatsApp e recebimento automático de mensagens não estão implementados. O assistente comercial local segue regras e não é um chat de IA. Ele pede confirmação humana para preços não cadastrados, frete, estoque, prazos e exceções.

O acesso tem login individual, sessões de 12 horas, limitação de tentativas e proteção contra submissões de outros sites. `python app.py` é um servidor local de desenvolvimento; use o servidor de produção com HTTPS conforme DEPLOY.md para acesso público. A hospedagem no subdomínio gratuito do PythonAnywhere e o envio pela Meta foram validados pelo proprietário. Backups externos automáticos e execução contínua de agendamentos continuam pendentes. Não é um sistema contábil ou fiscal.

## Agendamento

A fila persistente, o formulário de horário de São Paulo, o cancelamento e o executor estão implementados; consulte [SCHEDULING.md](SCHEDULING.md). O proprietário confirmou um teste real com o executor no console. Para operar sem console, a alternativa de [acionamento HTTP protegido](SCHEDULER_HTTP.md) precisa ser instalada e conectada a um serviço externo a cada minuto; sua validação real ainda está pendente. O sistema bloqueia novos agendamentos sem sinal recente do executor. Não confunda a implementação da fila com disponibilidade permanente no plano gratuito.

## Rotina editorial e conexão com ChatGPT

[CONTENT_WORKFLOW.md](CONTENT_WORKFLOW.md) registra a rotina aprovada de Stories e carrosséis, a preservação das artes originais, o armazenamento no Drive e o fluxo anterior via conector Metricool. Esse documento distingue os requisitos futuros das funcionalidades já validadas. O objetivo é transferir conteúdo criado no ChatGPT para o sistema próprio; registrar o fluxo não ativa a conexão ou a automação.

[MCP_INTEGRATION.md](MCP_INTEGRATION.md) preserva a inspeção histórica anterior à implementação. [MCP_SETUP.md](MCP_SETUP.md) descreve a conexão implantada e a atualização do plugin 0.1.1: consultas e uma importação real de rascunho foram confirmadas pelo proprietário; cada sessão ainda precisa ter acesso real ao JPEG e às ferramentas para transferi-lo. Atualizar o servidor não atualiza automaticamente a habilidade do plugin privado instalado.
