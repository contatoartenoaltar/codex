# Conexão Meta — autorização inicial

Implementação própria, sem Metricool ou intermediários. A API da Meta continua sendo necessária para acessar Instagram/Facebook. Esta etapa implementa o login, o retorno da autorização e uma consulta de leitura para identificar contas e permissões. O envio manual está documentado em PUBLISHING.md. Agendamento, webhooks e atendimento automático ainda não estão implementados. Não há publicação ou mensagem enviada por este fluxo.

## Atualização no PythonAnywhere

No console Bash:

```bash
cd ~/arte-no-altar
git pull --ff-only origin main
```

Na aba Web, clique em Reload. O WSGI existente define `ARTENOALTAR_ORIGIN=https://artenoaltar.pythonanywhere.com` e o caminho persistente do banco. Novas tabelas de estados OAuth são criadas ao reiniciar, sem alterar os registros da empresa.

## Aplicativo e segredo

Use o aplicativo **Arte no Altar Social** e a configuração **Instagram API (Unified Login)** criados pelo proprietário. Os identificadores públicos apresentados na Meta são sugeridos pelo comando abaixo; confirme-os no painel e altere se necessário. A chave secreta é encontrada no painel de configurações básicas do aplicativo, sendo acessível somente ao administrador. Não envie essa chave ao chat ou ao GitHub.

No console seguro do PythonAnywhere, execute:

```bash
cd ~/arte-no-altar
python3.12 meta.py configure
```

Confirme o ID do aplicativo e da configuração. Cole a chave secreta somente na pergunta do terminal: a entrada fica oculta e não vai ao histórico do shell. O comando salva `.local/meta-config.json` com permissão 600. Não há nenhuma chave padrão ou incluída no código. Não compartilhe esse arquivo. Se já houver configuração, o comando a substitui e remove a autorização local anterior. Recarregue o Web app.

Alternativamente, configure no processo `ARTENOALTAR_META_APP_ID`, `ARTENOALTAR_META_APP_SECRET` e `ARTENOALTAR_META_CONFIG_ID`. Não coloque valores secretos em arquivos versionados. A versão Graph padrão é `v24.0`; confira compatibilidade com o aplicativo e a documentação atual da Meta antes de atualizar a versão. O fluxo real ainda precisa de validação com a conta autorizada.

## Retorno da autorização

Depois da atualização, abra `https://artenoaltar.pythonanywhere.com/auth/meta/callback`. Deve aparecer uma página dizendo que o endereço de retorno está pronto, sem pedir tokens.

Na tela **API setup with Unified login**, registre exatamente esta URL de redirecionamento e salve:

```text
https://artenoaltar.pythonanywhere.com/auth/meta/callback
```

Se a Meta solicitar domínio do aplicativo, use `artenoaltar.pythonanywhere.com`. Não configure URLs de exclusão de dados, política de privacidade ou webhooks fictícias. Esses endpoints e documentos ainda precisam ser preparados se exigidos. Mantenha somente os ativos e permissões necessários para sua empresa na configuração da Meta. Autorizações para Facebook e Instagram dependem das permissões e ativos efetivamente concedidos: o modelo Unified Login do Instagram não comprova acesso a uma página Facebook.

No sistema, entre com sua senha e abra **Estúdio de conteúdo → Conectar à Meta**. O navegador abre a autorização oficial no Facebook. Depois de autorizar, use **Continuar no sistema** na página de retorno. O sistema identifica a etapa como **Autorização recebida**, sem afirmar que as contas já foram verificadas.

Se o aplicativo ainda estiver em desenvolvimento, confirme os papéis de administrador/testador e os requisitos indicados pela Meta para as contas utilizadas. A aprovação de permissões, a verificação empresarial e a liberação do aplicativo são processos da Meta; os testes simulados não substituem essas validações.

## Rede e segurança

A troca do código exige HTTPS de saída para `graph.facebook.com` no PythonAnywhere. A conta gratuita pode limitar destinos; em caso de bloqueio, não remova o proxy nem desative TLS. Confira a lista permitida ou solicite a inclusão oficial ao provedor, sem contratar plano pago sem autorização. Ainda não foi testado acesso à Meta a partir da conta real do usuário.

O código usa um estado aleatório de uso único, com validade de 10 minutos, associado ao navegador e à sessão de login válida. Um cookie separado HttpOnly/Secure/SameSite=Lax é usado no retorno de outro domínio; a sessão principal continua SameSite=Strict. Retornos cancelados, repetidos, expirados e de outro navegador são recusados. Não são exibidos erros brutos da Meta, códigos ou tokens na interface. O segredo é enviado no corpo da requisição HTTPS, sem seguir redirecionamentos.

O token é guardado em `.local/meta-connection.json`, com permissão 600. Ele não é criptografado em disco: a proteção depende do acesso privado à conta e ao sistema de arquivos do provedor. O arquivo não é servido pelo aplicativo nem enviado à API do navegador. Use armazenamento privado e não inclua os arquivos em logs, capturas, GitHub ou backups públicos. O backup SQLite não contém esses arquivos: preserve-os separadamente em local privado ou reconecte após uma restauração.

**Remover autorização local** apaga o token do sistema e os estados pendentes; não revoga automaticamente as permissões na Meta. Para revogação completa, remova o acesso nas configurações de integrações da Meta. Uma autorização pode ser revogada pela Meta antes do prazo declarado; isso será tratado na validação das futuras chamadas às contas.

## Validação executada

`python -m unittest discover -s tests -v` cobre a autorização com respostas de rede simuladas, consulta do status sem segredos, expiração, sessão encerrada, navegador incorreto, recusa, repetição do retorno e falha de rede. A integração real, as contas e os poderes de publicação continuam pendentes até a configuração no servidor e a autorização na Meta.


## Verificar contas e permissões

Depois de receber a autorização, clique em **Verificar contas e permissões** no Estúdio de conteúdo. O servidor consulta a validade e os escopos do token em `/debug_token`; usa os ativos concedidos de `instagram_basic` para identificar contas Instagram e, quando houver `pages_show_list`, consulta `/me/accounts` para identificar páginas Facebook. A ausência de uma conta não prova que ela não existe: pode indicar que o ativo ou a permissão não foi concedido. Se a Meta não retornar os ativos nesse tipo de token, será necessário revisar a configuração e as permissões no painel; o sistema não inventa uma associação.

Os escopos `instagram_content_publish` e `pages_manage_posts` são apresentados como permissões declaradas, sem prometer que uma publicação funcionará. Esta consulta não publica nem envia mensagens; o envio manual exige confirmação separada, conforme PUBLISHING.md. Uma concessão no token pode ser insuficiente para um ativo específico; a confirmação final depende de uma operação real autorizada posteriormente.

A última consulta é salva em `.local/meta-verification.json` com permissão 600, com nomes, IDs de contas, escopos, horário e uma impressão digital do token, sem incluir o token. O status é histórico, não uma checagem contínua de revogação. Uma nova verificação remove o resultado anterior antes da consulta para não apresentar resultados antigos como atuais em caso de erro. A remoção da autorização local também remove a verificação. Nenhuma URL de paginação fornecida pela API é seguida; a consulta fica restrita ao destino Graph configurado e aos primeiros 50 resultados de páginas e 20 contas Instagram.

As consultas usam HTTPS, cabeçalho Authorization, prova HMAC do segredo para consultas de ativos e não seguem redirecionamentos. O endpoint oficial de introspecção exige o token consultado como parâmetro `input_token`; não registre URLs dessas consultas em logs ou ferramentas de diagnóstico. Erros brutos do provedor nunca são mostrados no navegador.
