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

Novas respostas HTTP de erro da Meta incluem status HTTP, código, subcódigo, categorias locais e descrições com credenciais, endereços e identificadores opacos removidos. O corpo JSON bruto, cabeçalhos de autenticação e segredos não são exibidos. Erros antigos registrados antes desse ajuste não podem ter seus detalhes recuperados automaticamente. Se a publicação sair da revisão após uma falha, confira o cartão e use o diagnóstico; não confirme uma nova tentativa sem conferir antes a conta na rede social.


## Testar preparação da imagem sem publicar no feed

Em falhas de Instagram, o cartão oferece **Testar preparação sem publicar**. A ação exige confirmar que o post não apareceu na conta. Ela faz uma nova tentativa da etapa de criação de contêiner (`/{ig_id}/media`), que envia a imagem e legenda à Meta, mas não chama `media_publish`. Não é uma consulta somente leitura: cria um contêiner não publicado e registra uma tentativa no histórico. Os mesmos bloqueios de concorrência, revisão e permissões se aplicam.

Se a preparação for aceita, o registro passa para **Imagem em preparação**, sem identificador de postagem no feed. O botão **Concluir publicação no Instagram** continua exigindo confirmação separada e não deve ser acionado como parte de um diagnóstico. Se houver recusa, o cartão permanece bloqueado para revisão, mostrando a descrição sanitizada retornada pela Meta. Não são feitas retentativas automáticas. Falhas antigas não ganham retroativamente uma explicação que não foi registrada.

## Preparação alternativa por arquivo na própria Meta

O botão **Preparar por arquivo via Meta** está disponível para rascunhos Instagram com resultado a conferir. Ele exige confirmação de que a publicação não apareceu. Primeiro procura, entre as páginas concedidas, uma página cujo `instagram_business_account` corresponda exatamente ao destino do rascunho. Não escolhe uma página arbitrária. Envia o JPEG por multipart para `/{page_id}/photos` com `published=false`, obtém `images` da foto e utiliza o endereço HTTPS da CDN da Meta para criar o contêiner do Instagram. O teste não chama `media_publish` nem cria um post no feed do Facebook.

Esta alternativa evita que o serviço de publicação do Instagram precise buscar a imagem no PythonAnywhere, mas não prova que a hospedagem tenha causado o erro original. O depurador do Facebook e o serviço de ingestão do Instagram podem ter comportamentos distintos. A aceitação real da alternativa deve ser verificada na conta do proprietário.

A foto não publicada fica armazenada na Meta. Seu ID é registrado na tabela `publication_staged_media`; uma nova tentativa com o mesmo rascunho e arquivo reutiliza esse ID e consulta um endereço atualizado, sem reenviar o arquivo automaticamente. A exclusão remota dessas fotos não está implementada. Se o upload remoto terminar sem confirmação do ID, o sistema mantém o estado de revisão; não há repetição automática. A legenda não é incluída na foto de apoio do Facebook. Depois de preparar o contêiner, uma eventual publicação Instagram continua exigindo confirmação separada em **Concluir publicação no Instagram**.

Os testes cobrem a página vinculada, o upload binário, `published=false`, a reutilização da foto de apoio e a ausência da operação de publicação no feed. Não foram enviadas fotos reais durante esses testes.
