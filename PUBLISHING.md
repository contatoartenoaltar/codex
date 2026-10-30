# Publicações manuais na Meta

O sistema permite revisar um rascunho, escolher a conta verificada, editar a legenda e confirmar um envio. Não existe agendamento, publicação em lote, carrossel, stories, vídeo ou atendimento automático nesta etapa. O mesmo conteúdo nas duas redes exige um rascunho para cada canal. A autorização continua sendo da Meta, sem Metricool.

## Atualizar no PythonAnywhere

```bash
cd ~/arte-no-altar
git pull --ff-only origin main
mkdir -p .local/media
```

Não há nova dependência Python. Na aba **Web → Static files**, adicione exatamente:

| URL | Directory |
| --- | --- |
| `/media/` | `/home/artenoaltar/arte-no-altar/.local/media` |

Clique em **Reload** e atualize a página do sistema. Não mapeie `.local/` inteira: essa pasta contém credenciais, banco de dados e arquivos privados. Somente a subpasta `media` deve ficar acessível. A rota estática é necessária especialmente no plano gratuito, que pode ter um único processo: a Meta precisa buscar a imagem sem aguardar a própria requisição de publicação terminar. No servidor Waitress com múltiplas threads existe também uma rota equivalente implementada no aplicativo.

## Primeira publicação

1. Verifique contas e permissões. Prepare um rascunho para o canal desejado.
2. Use **Revisar e publicar**. Escolha a conta, revise a legenda e, se necessário, envie uma arte final em JPEG de até 5 MB. O upload disponibiliza a imagem por um link público aleatório para ser buscado pela Meta, mesmo antes do envio do post. Não envie imagens com informações privadas.
3. Instagram exige uma imagem, com largura de 320 a 1.440 px e proporção entre 4:5 e 1,91:1. Uma arte de 1080 × 1080 px é uma opção compatível. O sistema verifica cabeçalho e dimensões; a Meta faz a validação final do JPEG. Facebook admite texto sem imagem ou uma foto JPEG.
4. **Salvar rascunho** não publica. **Publicar agora** solicita confirmação do canal e da conta antes do envio.
5. No Instagram, o primeiro envio cria um contêiner para processar a imagem. Depois use **Concluir publicação no Instagram**, com nova confirmação. Se a imagem ainda estiver em preparação, aguarde e consulte novamente; não há um processo de agendamento em segundo plano.
6. **Publicado · confirmado pela Meta** só aparece após uma resposta da API com identificador. Confira o resultado no aplicativo da rede social. Os testes automatizados utilizam a Meta simulada; a primeira publicação real ainda precisa dessa validação pelo proprietário.

## Proteção contra duplicações e recuperação

Cada rascunho tem revisão e estado persistidos no SQLite. Um envio usa uma atualização condicional e registra uma tentativa com cópia da conta, legenda e imagem antes de chamar a API. Cliques repetidos não repetem o mesmo envio. Os estados são rascunho, enviando, imagem em preparação, resultado a conferir e publicado.

Falhas de rede e respostas sem confirmação deixam o rascunho bloqueado em **Resultado exige conferência**. Não há reenvio automático. Confira a conta na rede social; somente se o post não existir, use **Conferi: não foi publicada** para liberar uma nova revisão. Confirmar isso incorretamente pode duplicar uma postagem. O histórico da tentativa anterior é preservado. Interrupções do processo durante o envio podem deixar o registro em **Envio em andamento**: nesse caso, não altere o banco nem repita o pedido; é necessário reconciliar manualmente o resultado com a rede.

Excluir um registro publicado no sistema não exclui a publicação na Meta. Registros em envio, processamento ou revisão não podem ser excluídos pelo botão local. Apagar ou editar conteúdo remoto não está implementado.

## Dados, permissões e armazenamento

Antes de cada envio, o servidor consulta novamente os ativos e escopos. O destino é validado contra a conta e o canal retornados pela Meta. O Facebook exige também obter o token de acesso da página com a autorização do proprietário. Tarefas do usuário, análise do aplicativo, restrições da conta e limites da Meta ainda podem impedir uma publicação, mesmo com o escopo declarado. Nenhum token é enviado ao navegador. Requests de escrita usam HTTPS, cabeçalho Authorization, prova HMAC do segredo e destino Graph fixo, sem redirecionamentos.

O upload requer login e proteção de origem. Somente nomes JPEG aleatórios são servidos, com MIME `image/jpeg` e `nosniff`; não é possível acessar caminhos arbitrários. Há limite local de 100 MB para essa pasta; não há limpeza automática. O plano gratuito também tem sua própria cota de armazenamento. Remover uma imagem de um rascunho não a apaga fisicamente, pois a Meta pode ainda precisar buscá-la. Gerencie retenção e backups antes de remover arquivos.

Inclua a pasta `.local/media` em backup privado junto do banco. O backup SQLite contém o histórico e as referências, mas não inclui os arquivos de imagem. Os arquivos de credenciais devem permanecer privados e nunca ficar sob a rota estática, no GitHub ou em logs.

## Diagnóstico de falhas sem reenviar

Em registros com **Resultado exige conferência**, use **Diagnosticar sem publicar**. O servidor faz somente consultas GET dos dez posts mais recentes, procurando legendas iguais; não publica, não remove posts e não libera o bloqueio de reenvio. Um resultado sem correspondência não prova ausência. O navegador confere a resposta JPEG da própria imagem e identifica quando ela vem da rota do aplicativo, em vez do mapeamento estático. Isso ajuda a localizar a configuração ausente no PythonAnywhere, mas não confirma a conectividade a partir da Meta.

Novas respostas HTTP de erro da Meta são reduzidas a status HTTP, código, subcódigo e categorias locais (como imagem, autorização ou permissões). O texto bruto, URLs e valores do provedor não são exibidos. Erros antigos registrados antes desse ajuste não podem ter seus detalhes recuperados automaticamente. Se a publicação sair da revisão após uma falha, confira o cartão e use o diagnóstico; não confirme uma nova tentativa sem conferir antes a conta na rede social.
