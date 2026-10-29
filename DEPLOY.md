# Hospedagem da Arte no Altar

Preparação de código não equivale a uma implantação online. A conta de hospedagem, a publicação no GitHub e o domínio ainda precisam ser configurados. Não altere o site comercial existente.

## Prioridade: opção gratuita no PythonAnywhere

Consulte a oferta atual em https://www.pythonanywhere.com/ e escolha somente o plano gratuito, caso esteja disponível. Não selecione um plano pago. A disponibilidade, a região, o endereço e os limites são definidos pelo provedor e ainda não foram confirmados nesta tarefa. Essa opção não exige domínio próprio: usa o subdomínio fornecido no painel. Não há integração de implantação dessa conta disponível neste chat.

1. Crie a conta gratuita, sem enviar sua senha ao chat. Em um console Bash do provedor, clone o repositório GitHub `contatoartenoaltar/codex` para `/home/SEU_USUARIO/arte-no-altar` depois que o código estiver no GitHub. O repositório pode ser público, mas `.local`, `.env`, bancos e segredos nunca devem ser enviados.
2. Na aba Web, crie uma aplicação com configuração manual e Python 3.12+ (se não estiver disponível gratuitamente, pare antes de contratar um plano; a compatibilidade precisa ser revista). Não execute `python app.py` nem `serve.py` nesse provedor: ele já fornece o servidor WSGI.
3. Abra o arquivo de configuração WSGI mostrado pelo painel. Use o conteúdo de `pythonanywhere_wsgi.py`, substituindo `SEU_USUARIO` pelo nome real da conta e o endereço HTTPS pelo domínio exato informado no painel (incluindo eventual região). A origem não deve ter barra final.
4. No console, execute `cd /home/SEU_USUARIO/arte-no-altar` e `python3.12 app.py set-password`. Cadastre sua senha de pelo menos 12 caracteres duas vezes. Nada é exibido enquanto você digita. Não envie a senha pelo chat. Para recuperar o acesso, repita o comando; ele encerra todas as sessões anteriores. Use o mesmo Python selecionado para o aplicativo Web.
5. Recarregue a aplicação pelo painel e abra o endereço HTTPS pelo computador e celular. Teste login, um lançamento e logout. Sem sessão, `/api/state` deve retornar 401. Recarregue novamente a aplicação e confirme que o lançamento foi preservado antes de inserir dados reais.

O arquivo do SQLite deve ficar na pasta persistente da conta, conforme o modelo WSGI. O plano gratuito pode ter limites de armazenamento, CPU, acesso externo e exigência de renovação periódica; confirme tudo no painel. Não use serviços com disco temporário para guardar o único banco da empresa. O acesso à API de IA pode não estar disponível no plano gratuito e sua utilização pode ter custo separado. Os modelos locais e a gestão funcionam sem API externa.

O banco inicia vazio em uma hospedagem nova. Para migrar dados existentes, transfira um backup por canal seguro para o disco persistente e restaure com o serviço parado. Não coloque o banco no GitHub.

## Outros servidores

Python 3.12+, `pip install -r requirements.txt` e `python serve.py`. Configure `PORT`, `ARTENOALTAR_ORIGIN=https://gestao.seudominio` e `ARTENOALTAR_DB` com caminho absoluto persistente. Use um proxy HTTPS confiável na frente do Waitress, preservando o cabeçalho Host original; restrinja o acesso direto à porta interna. O processo usa um único disco SQLite e não deve escalar para réplicas com discos independentes. O servidor local `python app.py` é somente para desenvolvimento.

## Backups

Execute `python backup.py /caminho-seguro/backup-AAAA-MM-DD.db`. O comando não sobrescreve arquivos e verifica a integridade. Backups contêm os dados comerciais e o hash de acesso: guarde fora do servidor, em armazenamento privado. Agende esse comando no provedor escolhido; o agendamento e cópia externa ainda não estão configurados. Teste restauração em uma instância separada. Para restaurar, pare o serviço, preserve o banco atual, copie o backup para `ARTENOALTAR_DB` e reinicie.

## Acesso

Login individual, senha protegida com scrypt, cookies HttpOnly/SameSite=Strict/Secure em produção, expiração de sessão em 12 horas e limitação após 10 tentativas inválidas em 10 minutos. Não há cadastro público. Formulários precisam da origem configurada, evitando submissões por outros sites. O endpoint de saúde não retorna dados comerciais.

A chave opcional `ARTENOALTAR_AI_KEY` deve ser cadastrada como segredo no provedor. Meta, Instagram, Facebook e WhatsApp permanecem sem conexão. Esta implantação não ativa essas integrações automaticamente.
