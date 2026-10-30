# Arte no Altar — Gestão

Sistema inicial para gestão individual da Arte no Altar, feito com Python 3.12+ e SQLite, sem dependências externas.

```bash
cd /workspace/codex
python app.py
```

O servidor atende em `127.0.0.1:8000`. Os dados ficam em `.local/arte-no-altar.db`; faça backup desse arquivo com o servidor parado. `ARTENOALTAR_DB` permite escolher outro arquivo. `PORT` altera a porta.

Antes do primeiro acesso, cadastre sua senha com `python app.py set-password` no terminal seguro. A senha deve ter pelo menos 12 caracteres; não envie pelo chat. Não existe senha padrão. Para backup durante o uso, execute `python backup.py /caminho-seguro/backup.db`.

Para hospedagem HTTPS, consulte [DEPLOY.md](DEPLOY.md). A opção prioritária é tentar o plano gratuito do PythonAnywhere com o adaptador WSGI; confirme a disponibilidade e os limites antes de criar a conta. Para um servidor próprio, instale `requirements.txt` e use `python serve.py`, com endereço público e banco persistente configurados. Ainda não foi implantado.

Validação: `python -m unittest discover -s tests -v`.

## Recursos

- Receitas, despesas e saldo realizado (não inclui parcelas futuras ou conciliação bancária).
- Cadastro de materiais e ajuste manual de estoque; pedidos não baixam materiais automaticamente.
- Cadastro de pedidos e acompanhamento de etapas; pedidos não geram lançamentos financeiros automaticamente.
- Catálogo comercial com os produtos e preços fornecidos pelo proprietário.
- Rascunhos de publicações e respostas comerciais baseadas no catálogo, disponíveis sem serviço externo. Os rascunhos usam modelos de texto; não são geração por IA.
- Geração opcional de legendas por IA usando a API da OpenAI: disponibilize `ARTENOALTAR_AI_KEY` de forma segura no processo e, opcionalmente, `ARTENOALTAR_AI_MODEL` (padrão: `gpt-4.1-mini`). O acesso a `api.openai.com` precisa estar permitido. A chave fica exclusivamente no servidor. Não inclua segredos no Git. Custos são cobrados pelo provedor. Apenas o produto selecionado e informações públicas da gráfica são enviados.

## Limites desta versão

Instagram, Facebook, WhatsApp, publicação, agendamento automático e recebimento de mensagens **não estão conectados**. O login oficial inicial da Meta e o endereço de retorno estão implementados; leia [META.md](META.md) para configurar as credenciais no servidor e validar a autorização real. Uma autorização recebida ainda não confirma contas ou poderes de publicação. A área de conteúdo guarda rascunhos para revisão e cópia manual. O assistente comercial local segue regras e não é um chat de IA. Ele pede confirmação humana para preços não cadastrados, frete, estoque, prazos e exceções.

O acesso tem login individual, sessões de 12 horas, limitação de tentativas e proteção contra submissões de outros sites. `python app.py` é um servidor local de desenvolvimento; use o servidor de produção com HTTPS conforme DEPLOY.md para acesso público. A hospedagem real, o domínio, o agendamento de backups externos e a integração oficial com a Meta ainda não foram configurados. Não é um sistema contábil ou fiscal.
