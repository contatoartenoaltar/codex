# Stories — plano de conexão e implantação

Código preparado **localmente**. Não houve push, implantação, configuração da
hospedagem, leitura de credenciais reais ou envio à Meta nesta etapa. Este
roteiro descreve uma implantação futura, sujeita à aprovação do proprietário.
Não executar a ativação como diagnóstico.

## Arquitetura

- `stories/meta_client.py`: Graph HTTPS em destino fixo, autenticação no
  cabeçalho, prova HMAC, redirecionamentos recusados e erros sem segredos.
- Conta empresarial `arte.no.altar`, permissões e página vinculada conferidas
  antes de cada etapa. A autorização existente é usada somente por leitura:
  sem renovar token, reconectar ou gravar a verificação do feed.
- `stories/http.py`: `POST /internal/stories/tick`, com chave nova e exclusiva,
  conferência de Host, sem Origin, corpo ou parâmetros. Uma trava impede
  acionamentos concorrentes e há intervalo mínimo de 30 segundos.
- `stories/wsgi.py`: nova entrada opcional. Todas as rotas atuais são delegadas
  ao `wsgi.application` existente, com o mesmo ambiente e função de resposta.
- `story-queue.sqlite3`: banco próprio, sem acesso ao banco comercial.

`app.py`, `wsgi.py`, `meta.py`, `publishing.py`, `scheduling.py`,
`scheduler_http.py`, requisitos e layouts do feed não foram modificados.

## Fluxo de envio preparado

Cada tick faz no máximo **uma escrita remota**:

1. Enviar o JPEG à página vinculada com `published=false`; guardar o ID da foto
   de apoio. A foto fica na Meta, mas não vira um post no feed do Facebook.
2. Consultar uma URL atual na CDN oficial, conferir a proporção vertical e
   criar o contêiner com `media_type=STORIES`; guardar o ID.
3. Conferir o processamento e, somente a partir do horário autorizado, chamar
   `media_publish` e guardar o ID confirmado.

A preparação real pode começar cinco minutos antes das 07h30; a publicação
nunca é chamada antes do horário reservado. O momento de exibição depende
da Meta, cron e hospedagem. Cada chamada tem timeout de cinco segundos; uma
etapa pode fazer até cinco chamadas. Medir duração e pontualidade no teste real.

IDs de apoio e contêiner são preservados entre etapas. Timeout, arte alterada,
falha ou interrupção exigem conferência, sem repetição automática da escrita.
Fotos de apoio não publicadas permanecem na Meta; sua remoção não foi implementada.

## Preparação futura no PythonAnywhere

Conferir versão instalada, agenda atual, caminho da autorização e recursos
gratuitos disponíveis. Preparar backup privado do banco comercial e uma cópia
da configuração WSGI atual. Não copiar segredos ao chat ou ao Cloud.

Usar um diretório **novo**, diferente da simulação, por exemplo:

```bash
STORY_DIR=/home/artenoaltar/arte-no-altar/.local/stories-live
python3.12 -m stories.queue --directory "$STORY_DIR" \
  --account ID_INSTAGRAM_CONFIRMADO --confirm configure-live
python3.12 -m stories.http --directory "$STORY_DIR" \
  --origin https://artenoaltar.pythonanywhere.com
```

Usar o Python do virtualenv da aplicação, se houver. O ID precisa ser o número
da conta correta. Ambos os comandos mantêm os envios desativados. O segundo
cria `stories-trigger.key` e `stories-http.json`, privados, sem exibir a chave
ou sobrescrever arquivos existentes. Não usar a chave do feed ou do MCP.

Conferir a conta pelo cliente em modo de consulta antes do primeiro envio.
Preparar as três artes e revisar textos e horários:

```bash
python3.12 -m stories.queue --directory "$STORY_DIR" prepare
python3.12 -m stories.queue --directory "$STORY_DIR" agenda
```

A fila antiga de simulação não pode ser promovida. Os dias serão calculados na
implantação; não reaproveitar horários vencidos, apagar histórico ou enviar um
lote antigo para contornar bloqueios. A rotina real é inicialmente desativada.

## Entrada Web — alteração pontual, somente após aprovação

Na configuração WSGI **do painel**, preservar os caminhos, banco comercial,
origem HTTPS e demais definições. Acrescentar:

```python
os.environ['ARTENOALTAR_STORIES_DIR'] = '/home/artenoaltar/arte-no-altar/.local/stories-live'
os.environ['ARTENOALTAR_STORIES_META_DIR'] = '/home/artenoaltar/arte-no-altar/.local'
```

O segundo caminho é um exemplo: confirmar onde está a autorização já usada.
Trocar somente a importação da aplicação por:

```python
from stories.wsgi import application
```

Não modificar o `wsgi.py` do repositório. Não mapear `.local` ou a pasta de
Stories como arquivos públicos: a arte será hospedada na própria Meta.
Após Reload, conferir saúde, login e consulta do Financeiro. As rotas antigas
continuam no aplicativo original. Uma chamada válida aos Stories desativados
deve retornar `disabled`, sem ler a autorização Meta.

## Novo job e ativação — aprovação separada

Criar uma tarefa independente, inicialmente desativada, somente se a conta
gratuita do agendador comportar outro job. Não alterar o job atual ou contratar
serviço pago para contornar limites.

| Campo | Valor |
| --- | --- |
| URL | `https://artenoaltar.pythonanywhere.com/internal/stories/tick` |
| Método | POST |
| Corpo | Vazio |
| Frequência | A cada minuto |
| Cabeçalho | `Authorization: Bearer ` seguido da chave exclusiva dos Stories |

Não informar Origin, cookies, tokens Meta ou chave na URL. O endpoint não
recebe conteúdo, conta ou horário: processa apenas a política já autorizada.

Após revisão do lote, aprovação do teste real e conferência do acionamento:

```bash
python3.12 -m stories.queue --directory "$STORY_DIR" \
  --batch ID_DO_LOTE_REVISADO --confirm queue
python3.12 -m stories.queue --directory "$STORY_DIR" --confirm enable-live
```

Esses comandos autorizam publicação real quando houver acionamento válido.
A primeira publicação precisa ser conferida no Instagram além do ID retornado.
Depois, conferir a reposição no terceiro dia, sem alterar a rotina do feed.

## Pausa e reversão

`python3.12 -m stories.queue --directory "$STORY_DIR" pause` bloqueia próximos
ticks; uma requisição já iniciada pode terminar. Pausar somente o job dos Stories
também não altera o feed. Itens em processamento/revisão exigem conferência
antes de retomar. Nunca repetir um resultado incerto sem consultar o Instagram.

Para retirar a entrada opcional, restaurar a importação WSGI anterior e usar
Reload. Preservar banco, imagens e recibos de Stories para diagnóstico; não
restaurar o banco comercial para desfazer esta adição.

## Evidência e limites

Testes usam credenciais fictícias e HTTP simulado. Cobrem o fluxo completo de
apoio → contêiner → publicação, separação de modos, concorrência, interrupção,
integridade, sanitização, preservação da autorização lida e das rotas existentes.
Não comprovam conectividade, permissões ou publicação na conta real.

Referência: [documentação oficial da Meta no Postman](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api)
e o fluxo de imagem de apoio já existente no feed. A compatibilidade real deste
novo fluxo de Stories continua pendente do teste supervisionado na hospedagem.
