# Montagem de feed com modelos do Drive

O proprietário aprovou o layout comercial com título branco/dourado, foto grande
e botão com `35 9 8442-8442`, após rejeitar as propostas anteriores. Aprovou também
as doze chamadas curtas, três por tema, e pediu sua integração. O banco está em
`feed_composer.PHRASES`; não acrescentar frases geradas livremente nessa execução.

## Fluxo integrado ao Estúdio de conteúdo

1. Carregar os modelos da pasta de originais já configurada no Drive.
2. Selecionar a imagem, seu tema (Dízimos, Ofertas, Primícias ou Santa Ceia) e o canal.
3. Montar a arte em 1080 × 1350 e salvar imagem e legenda como rascunho.
4. Conferir a correspondência entre envelope e tema, a arte final e a legenda.
   Escolher a conta na revisão e usar o agendamento existente após confirmação.

As frases são sorteadas sem reposição dentro de cada tema. Ao usar as três,
inicia-se outro ciclo, sem repetir de imediato a última chamada anterior.
O histórico fica no banco, sobrevive a reinicializações e não depende do chat.
Repetir a mesma solicitação retorna o conteúdo já criado. Se o rascunho mudou de
estado, a resposta informa seu estado atual; se foi excluído, não o recria.

O modelo é selecionado explicitamente nesta etapa. **Ainda não há sorteio diário
automático de modelos.** A contagem de 84 arquivos não identifica modelos únicos:
fotografias diferentes do mesmo envelope precisam ser agrupadas e os temas
conferidos antes de ativar a rotação geral sem repetição. O registro de cada
composição já guarda ID e SHA-256 do original, tema, frase, ciclo e rascunho para
essa futura integração. O exemplo local de montagem usou a amostra já conhecida
somente para verificar o compositor, sem criar conteúdo na hospedagem.

## Montagem e isolamento

`design_assets/feed/template.jpg` é a base vazia com o botão fixo, preparada uma
vez durante a configuração. Não contém nenhum modelo do Drive. O servidor usa
Pillow, as fontes distribuídas no projeto e esse arquivo local; não chama APIs
de IA para gerar imagens ou textos diariamente. Não há logo ou rodapé adicional,
seguindo a referência escolhida pelo proprietário.

A fotografia é redimensionada proporcionalmente e inserida inteira, sem recorte,
deformação, texto ou efeitos sobre seus pixels. O PNG original não é alterado.
O tema fica em dourado e o complemento em branco, com ajuste para caber no título.
O JPEG final é guardado na mídia do sistema para revisão. O Drive permanece de
leitura. As chamadas são as aprovadas; a legenda não inventa preços ou condições.

Os novos endpoints `POST /api/feed/models` e `POST /api/feed/compose` exigem sessão
do proprietário e a proteção de origem já usada pelo painel. Não aceitam a chave
MCP como login e não expõem credenciais do Drive ou da Meta. Nenhuma ferramenta
MCP ou pacote de plugin foi alterado nesta etapa. A composição não agenda nem
publica; preserva o fluxo de revisão e confirmação existente.

Uma transação protege criação do rascunho e alternância das frases. Falhas não
consomem uma frase e removem mídia recém-criada. O exemplo pronto não significa
que o layout de todo modelo ou a leitura dos QR Codes esteja automaticamente
validada; conferir as artes finais.

## Atualização na hospedagem

```bash
cd /home/artenoaltar/arte-no-altar
git pull --ff-only origin main
python3.12 -m pip install --user -r requirements.txt
```

Se a conta usa virtualenv, instalar com o Python dele. Depois, em **Web**, usar
**Reload** no site e atualizar a página do sistema. O WSGI existente chama
`app.initialize()`; a migração aditiva cria `feed_compositions` sem alterar os
rascunhos, agendamentos ou histórico já existentes. Não apagar ou recriar o banco.
As credenciais privadas de Drive já configuradas continuam no servidor.

No Estúdio de conteúdo, a seção **Feed com seus modelos do Drive** ficará
disponível. A implantação e o teste real desse novo fluxo na hospedagem ainda
precisam ser executados pelo proprietário; testes locais usam Drive simulado.

## Próximas etapas

Agrupar e classificar modelos, completar o sorteio persistente sem reposição e
definir a frequência dos feeds para a execução diária. A chamada do cron atual
continua executando somente a fila de publicação autorizada; não foi modificada
para criar artes. Stories e carrosséis continuam como trabalhos separados.
