# Arte no Altar — conexão MCP e atualização do plugin

## Estado confirmado pelo proprietário

O endpoint foi implantado, o plugin privado foi instalado e consultas sociais
funcionaram. Uma importação real de JPEG e legenda foi confirmada pelo recibo e
pela visualização no sistema. O agendamento na interface também publicou com o
console parado e as abas fechadas, usando acionamento HTTP externo. Esses testes
não garantem acesso a arquivos locais em todas as sessões nem adicionam ferramentas
de publicação/agendamento ao plugin.

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
ou pelo gerenciador do plugin e conferir a versão 0.1.1 no cliente. A sessão atual
pode continuar usando instruções em cache; depois da atualização, abra uma sessão
com o plugin atualizado e o arquivo real disponível. Não apague o rascunho nem
troque a chave MCP para resolver uma instrução antiga.

O script de empacotamento abaixo valida o endpoint antes de gerar uma distribuição
nova. Um pacote somente de atualização das instruções também pode manter o mesmo
`mcp.json` do ZIP 0.1.0 previamente validado, sem mudar URL ou autenticação; isso
não equivale a realizar um novo teste remoto de conexão ou de transferência.

## Entrega desta alteração

Implementa `/mcp` em Python padrão, Streamable HTTP JSON sem sessão/SSE, protocolo
2025-06-18, autenticação API key/Bearer e cinco ferramentas sociais. A configuração
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
   O script solicita a credencial sem eco, testa somente leituras, recusa redirects
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
  PNG, Stories, carrossel, Drive e publicação MCP não são suportados. Não adicionar
  downloader de URLs arbitrárias. A solução de anexos deve usar suporte real do
  cliente e passar por teste. O proprietário já cancelou a agenda do Metricool.
- `confirmed=true` registra a confirmação no contrato; a skill é responsável por
  mostrar conta, imagem, legenda, formato e horário e aguardar a resposta humana.
  Não é uma assinatura criptográfica do consentimento.
- Horário desejado exige RFC 3339 com offset de São Paulo; é somente metadado do
  recibo. Recibo `draft_imported` confirma a importação, não publicação posterior.
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
inválidos, idempotência, recibo e garantia de não publicar/não agendar. Testes de
imagem usam fixture sintética de cabeçalho; não substituem aceite com foto real.

## Diagnóstico da conexão do aplicativo

Após atualizar o código e recarregar o WSGI, o servidor mantém no máximo 30 eventos técnicos de conexão: horário, status HTTP, categoria do resultado, versão de protocolo com formato de data e presença do cabeçalho Origin. Não registra valores de autenticação, chave, hash, cabeçalhos completos, IP, legendas, imagens ou argumentos das ferramentas. O diagnóstico não muda as permissões nem libera autenticação.

No aplicativo, atualize o servidor MCP e tente somente a consulta de contas. Depois, no Bash da hospedagem:

```bash
cd ~/arte-no-altar
python3.12 social_mcp.py diagnose
```

O comando mostra os últimos 15 eventos em horário de São Paulo. Se nenhum evento novo aparecer no momento da tentativa, o cliente não chegou ao endpoint nesta janela de observação; não conclua que a chave esteja errada. Se houver recusa, a categoria distingue integração desativada, Bearer ausente/formato inválido, chave divergente, origem, método HTTP, versão, Accept, tipo ou tamanho de conteúdo e JSON inválido. `initialize_recebido` e `tools_list_recebido` indicam recebimento, não provam que o cliente disponibilizou as ferramentas ao modelo. Não exponha esse diagnóstico como rota pública e não compartilhe outros arquivos privados para investigar o problema.
