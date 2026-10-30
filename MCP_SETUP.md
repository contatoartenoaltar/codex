# Arte no Altar — implantação pendente

## Entrega desta alteração

Implementa `/mcp` em Python padrão, Streamable HTTP JSON sem sessão/SSE, protocolo
2025-06-18, autenticação API key/Bearer e cinco ferramentas sociais. A configuração
do Plugin Creator aceita `auth.type=api_key` com `headerScheme=bearer`.
Não usa OpenAPI nem o OAuth da Meta como autenticação do plugin.

Os testes locais não comprovam implantação HTTPS ou integração real com ChatGPT.
O pacote conectado ainda não deve ser instalado: o endpoint precisa ser implantado
e verificado. Não cadastrar a página inicial como endpoint. `plugin/` é fonte do
pacote e suas instruções; o script só adiciona `mcp.json` após verificação remota.

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
- **Ainda não há entrega de anexo ChatGPT validada.** Base64 é contrato técnico,
  não uma capacidade automática do modelo. Não pedir para o usuário colar bytes.
  PNG, Stories, carrossel, Drive e publicação MCP não são suportados. Não adicionar
  downloader de URLs arbitrárias. A solução de anexos deve usar suporte real do
  cliente e passar por teste antes de substituir Metricool.
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
