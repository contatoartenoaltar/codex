# Arte no Altar — conexão MCP e atualização do plugin

## Estado confirmado pelo proprietário

O endpoint foi implantado, o plugin privado foi instalado e consultas sociais
funcionaram. Uma importação real de JPEG e legenda foi confirmada pelo recibo e
pela visualização no sistema. O agendamento na interface também publicou com o
console parado e as abas fechadas, usando acionamento HTTP externo. Esses testes
não garantem acesso a arquivos locais em todas as sessões. O proprietário também
confirmou a importação após atualizar o plugin para 0.1.1. O agendamento pelo
plugin 0.2.0 foi atualizado no aplicativo e o proprietário mostrou um agendamento
real do rascunho #3 para 30/10/2026 às 10h15, America/Sao_Paulo, com recibo, fila e
executor ativo. Depois, o proprietário confirmou a publicação desse post, concluindo
o teste real do fluxo de agendamento pelo plugin.
O acompanhamento das pendências está em [PENDENCIAS.md](PENDENCIAS.md).

### Cancelamento e reagendamento no plugin 0.3.0

Acrescenta `social_cancel_schedule` e `social_reschedule_draft`, totalizando nove
ferramentas. Estão implementadas com testes locais; implantação e validação real
no aplicativo ainda pendentes. A preparação não altera a fila da hospedagem.

Ambas exigem `post_id`, `revision`, `account_id`, `channel`, `expected_due_at`
(timestamp numérico original retornado por `social_get_draft`), `idempotency_key`
própria e `confirmed=true`. O reagendamento também exige `desired_at` com o novo
horário em RFC 3339 com offset de São Paulo. A habilidade deve mostrar conta,
conteúdo e horário original, além do horário novo ao reagendar, antes da confirmação.

Só pode ser alterado um item `queued`, com publicação ainda `scheduled`, revisão
e horário originais correspondentes. Um envio `running` ou `processing` não é
interrompido. Cancelar não exige executor ativo e devolve o conteúdo ao rascunho.
Reagendar exige executor ativo e as validações de JPEG, data futura e conflitos.
Cancelamento, nova reserva e recibo são uma única transação: se houver falha, o
agendamento original permanece. A revisão é incrementada para invalidar cópias
antigas. O botão de cancelar na interface também verifica revisão e horário.

Os recibos `cancellation_accepted` e `reschedule_accepted` são históricos. Repetir
uma chamada com a mesma chave e dados devolve o recibo, sem cancelar um agendamento
posterior nem restaurar um horário antigo. Consultar o rascunho continua necessário
para o estado atual. A migração da tabela preserva os recibos de agendamento 0.2.0.
Nenhuma dessas ferramentas remove uma publicação remota.

### Agendamento no plugin 0.2.0

Acrescenta duas ferramentas às cinco existentes:

| Ferramenta | Contrato |
| --- | --- |
| `social_get_draft` | Recebe `post_id`; retorna somente conta social autorizada, canal, legenda, URL da imagem, revisão, estado da publicação/fila e executor. Não lê financeiro nem credenciais. |
| `social_schedule_draft` | Recebe `post_id`, `revision`, `account_id`, `channel`, `desired_at` em RFC 3339 com offset de São Paulo, `idempotency_key` própria e `confirmed=true`. Coloca somente esse rascunho revisado na fila futura existente. Não publica durante a chamada. |

O fluxo é consultar contas/agenda/rascunho, mostrar conta, imagem, legenda, formato
e data/hora e receber autorização explícita de envio automático futuro. Depois,
agendar e consultar recibo e estado atual da fila. Uma confirmação de somente
importar rascunho não autoriza o envio futuro. Uma revisão explícita para importar
e agendar o mesmo conteúdo pode cobrir as duas etapas, sem confirmação repetida.

O servidor exige executor ativo, foto JPEG, revisão e destino correspondentes e
horário entre dois minutos e noventa dias no futuro. Outro item ativo na mesma
conta, canal e minuto gera conflito. Registro da fila e recibo são atômicos. O
controle de duplicação é feito sob transação, inclusive entre chamadas concorrentes.
Chaves de importação e agendamento são distintas; repetir o agendamento com a mesma
chave e dados devolve o recibo anterior, mesmo se cancelado, sem reativar a fila.

`social_get_operation` agora também retorna `schedule_accepted`, com data/hora e ID
do rascunho. Esse é um recibo histórico de aceite, não confirmação de publicação nem
garantia de que continua na fila. Use `social_get_draft` ou agenda para o estado
local atual; o ID remoto só aparece depois de o executor registrar a publicação.
Na versão 0.2.0, cancelamento e reagendamento permaneciam na interface; a versão
0.3.0 acrescenta as duas ações ao MCP, conforme descrito acima. Sem ferramenta de
publicação imediata, Stories, carrosséis ou Drive. A anotação do agendamento é de escrita e
ação com efeito externo futuro, não consulta somente leitura.

Para atualizar uma instalação já configurada, primeiro atualize o código e clique
em **Web → Reload** no PythonAnywhere. Depois execute no console:

```bash
cd /home/artenoaltar/arte-no-altar
python3.12 package_social_plugin.py https://artenoaltar.pythonanywhere.com/mcp --configured-key
```

Esse comando administrativo usa a chave MCP privada já existente no diretório do
banco, sem imprimi-la. Não lê a chave do cron, senha ou tokens da Meta. Valida a
descoberta das nove ferramentas e consulta somente contas; não agenda um teste.
Grava `.local/arte-no-altar-0.3.0.zip` (ou o diretório privado do banco configurado).
Baixe pelo painel **Files** autenticado, atualize o mesmo plugin privado pelo
Plugin Creator e confirme a versão 0.3.0. Não exponha `.local` como rota estática.
Atualizar o servidor não atualiza a habilidade instalada no aplicativo.

Depois de confirmar as nove ferramentas no aplicativo, revise um rascunho e um
horário futuro real, autorize o teste e confira recibo, fila e publicação na rede.
Nenhum novo agendamento real foi criado pelos testes locais desta versão. Depois
da implantação, o proprietário confirmou pelo aplicativo o teste descrito acima.

### Correção 0.1.1

A versão 0.1.0 continha, na habilidade e na descrição da ferramenta, uma afirmação
genérica de que a transferência ainda não estava validada. A consulta de contas
também retornava uma flag fixa `chatgpt_file_transfer_verified=false`, apesar de o
servidor não conseguir avaliar o acesso aos arquivos de cada cliente. Isso podia
levar a uma recusa sem verificar a imagem da sessão atual.

A versão 0.1.1 informa a capacidade real de importar bytes JPEG e exige verificar
o acesso ao arquivo e o transporte na sessão atual. Não declara que o servidor
consegue ler caminhos `C:/...`, não inventa base64 e não remove a confirmação do
conteúdo. Se a transferência estiver bloqueada, o cliente deve identificar a etapa
concreta antes de oferecer upload manual no sistema.

Atualizar o GitHub ou dar Reload no PythonAnywhere não atualiza o plugin privado
instalado. Também é necessário atualizar seu pacote/habilidade pelo Plugin Creator
ou pelo gerenciador do plugin e conferir a versão atual no cliente. A sessão atual
pode continuar usando instruções em cache; depois da atualização, abra uma sessão
com o plugin atualizado e o arquivo real disponível. Não apague o rascunho nem
troque a chave MCP para resolver uma instrução antiga.

O script de empacotamento abaixo valida o endpoint antes de gerar uma distribuição
nova. Um pacote somente de atualização das instruções também pode manter o mesmo
`mcp.json` do ZIP 0.1.0 previamente validado, sem mudar URL ou autenticação; isso
não equivale a realizar um novo teste remoto de conexão ou de transferência.

## Entrega desta alteração

Implementa `/mcp` em Python padrão, Streamable HTTP JSON sem sessão/SSE, protocolo
2025-06-18, autenticação API key/Bearer e nove ferramentas sociais. A configuração
do Plugin Creator aceita `auth.type=api_key` com `headerScheme=bearer`.
Não usa OpenAPI nem o OAuth da Meta como autenticação do plugin.

Os testes locais não comprovam implantação HTTPS ou integração real com ChatGPT.
Em uma instalação nova, implantar e verificar o endpoint antes de instalar o
pacote conectado. Não cadastrar a página inicial como endpoint. `plugin/` é fonte
do pacote e suas instruções; o script só adiciona `mcp.json` após verificação remota.

## Implantação no PythonAnywhere

1. Revisar/integrar esta branch e atualizar o código na instalação existente.
   Fazer backup do banco com a rotina existente antes de atualizar. `app.initialize()`
   cria a tabela de recibos sem alterar registros comerciais.
2. Gerar uma credencial aleatória exclusiva com ao menos 32 caracteres em console
   privado. Não usar senha da interface ou tokens Meta. Guardar em gerenciador seguro.
3. Definir `ARTENOALTAR_MCP_KEY_SHA256` no processo WSGI: SHA-256 hexadecimal da
   credencial. Pode solicitar a credencial sem eco com `getpass` e calcular o hash
   com `hashlib.sha256(key.encode()).hexdigest()`. Não colocar a credencial ou hash
   no Git/chat. Sem hash configurado, o endpoint fica desativado (401).
4. Se o cliente enviar Origin, configurar `ARTENOALTAR_MCP_ALLOWED_ORIGINS` com as
   origens exatas observadas/documentadas, separadas por vírgula. O padrão recusa
   todas as requisições com Origin e permite clientes técnicos sem esse cabeçalho,
   sempre exigindo Bearer. Não usar wildcard ou liberar origens arbitrárias.
5. Recarregar a aplicação pelo painel Web. Verificar que sem credencial `/mcp`
   responde 401; com credencial, initialize e tools/list funcionam e GET dá 405.
   Confirmar `Content-Type` no adaptador WSGI e não iniciar processo contínuo/SSE.
6. Executar no console com o código atualizado:
   `python package_social_plugin.py https://artenoaltar.pythonanywhere.com/mcp`.
   O script solicita a credencial sem eco (ou usa o arquivo privado com
   `--configured-key`), testa somente leituras, recusa redirects
   e verifica os schemas. O ZIP não contém credenciais. Validar manualmente também
   credencial incorreta/revogada e tentativas de ferramentas não sociais.
7. Salvar o ZIP privado pelo Plugin Creator, conectar com a credencial exclusiva
   no formulário seguro, descobrir as ferramentas e fazer teste real de rascunho.
   Só declarar transferência disponível após comprovar a entrega dos bytes reais
   de uma imagem gerada/anexada no ChatGPT, importação, retry e consulta do recibo.

Não há acesso à hospedagem/configuração WSGI por este repositório. Fazer merge ou
gerar um pacote não recarrega automaticamente o PythonAnywhere.

## Limites e critérios de aceite

- Consulta de contas é cache previamente verificado na interface. Não chama Meta
  para atualizar contas. Retorna somente id, canal e nome; nenhum token/secret.
- Agenda é a fila local, limitada a 90 dias e 200 itens com indicador de truncamento.
  Executor inativo é reportado. Rascunhos com horário desejado não entram nessa fila.
- Conteúdo recente é histórico LOCAL, ordenado por id de criação, não data remota
  de publicação. Publicações externas à aplicação podem não aparecer. Não usar esse
  histórico para garantir ausência de repetição em toda a conta.
- Importador técnico aceita uma imagem JPEG base64 até 5 MiB e legenda. Usa a
  validação de mídia já existente, preserva os bytes e não faz conversão. Arquivo
  fica na mídia pública com nome aleatório conforme a arquitetura atual. Exibir
  essa prévia antes da confirmação; importar não equivale a postar na rede.
- Houve uma importação real validada pelo proprietário. Base64 é contrato técnico,
  não uma capacidade automática do modelo. Verificar leitura e transporte do arquivo
  na sessão atual antes de transferir ou recusar. Não pedir ao usuário para colar bytes.
  PNG, Stories, carrossel, Drive e publicação imediata MCP não são suportados. Não adicionar
  downloader de URLs arbitrárias. A solução de anexos deve usar suporte real do
  cliente e passar por teste. O proprietário já cancelou a agenda do Metricool.
- `confirmed=true` registra a confirmação no contrato; a skill é responsável por
  mostrar conta, imagem, legenda, formato e horário e aguardar a resposta humana.
  Não é uma assinatura criptográfica do consentimento.
- Horário desejado exige RFC 3339 com offset de São Paulo. Na importação é somente
  metadado; a fila é ativada somente por `social_schedule_draft` confirmado.
  Recibos `draft_imported` e `schedule_accepted` não comprovam publicação posterior.
- Idempotência usa hash do conteúdo e transação SQLite. Retry com mesma chave e
  conteúdo retorna o mesmo recibo; dados diferentes geram erro. Em desligamento
  abrupto pode sobrar imagem órfã, mas não rascunho parcialmente confirmado.
- Revogar/trocar a chave alterando o hash configurado e recarregando o WSGI.
  A chave não autentica rotas da interface nem libera `/api/state`.
- A proteção de mídia JPEG é a já existente (validação de cabeçalho/dimensões),
  não decodificação completa. Teste de arquivo real é obrigatório no aceite.
- Nenhum serviço pago, executor contínuo ou alteração em Metricool é ativado.

## Validação local

`python -m unittest discover -s tests -v`

Inclui autenticação negada/desativada, origem recusada, protocolo, dados sociais
com seleção de campos, conta não concedida, confirmação obrigatória, formatos
inválidos, idempotência, recibo, importação sem agendamento, confirmação distinta de
agendamento, revisão alterada, conta divergente, executor inativo, conflito de
horários, concorrência, rollback e consumo da fila pelo executor com Meta simulada. Testes de
imagem usam fixture sintética de cabeçalho; não substituem aceite com foto real.

## Diagnóstico da conexão do aplicativo

Após atualizar o código e recarregar o WSGI, o servidor mantém no máximo 30 eventos técnicos de conexão: horário, status HTTP, categoria do resultado, versão de protocolo com formato de data e presença do cabeçalho Origin. Não registra valores de autenticação, chave, hash, cabeçalhos completos, IP, legendas, imagens ou argumentos das ferramentas. O diagnóstico não muda as permissões nem libera autenticação.

No aplicativo, atualize o servidor MCP e tente somente a consulta de contas. Depois, no Bash da hospedagem:

```bash
cd ~/arte-no-altar
python3.12 social_mcp.py diagnose
```

O comando mostra os últimos 15 eventos em horário de São Paulo. Se nenhum evento novo aparecer no momento da tentativa, o cliente não chegou ao endpoint nesta janela de observação; não conclua que a chave esteja errada. Se houver recusa, a categoria distingue integração desativada, Bearer ausente/formato inválido, chave divergente, origem, método HTTP, versão, Accept, tipo ou tamanho de conteúdo e JSON inválido. `initialize_recebido` e `tools_list_recebido` indicam recebimento, não provam que o cliente disponibilizou as ferramentas ao modelo. Não exponha esse diagnóstico como rota pública e não compartilhe outros arquivos privados para investigar o problema.
