# Feeds integrados em lotes de três dias

**Estado atual — 30/10/2026:** o proprietário aplicou a correção e a saída real
confirmou três rascunhos, IDs **4, 5 e 6**, em modo de teste. Depois da ativação,
a captura mostrou #4 e #5 na fila e #6 ainda aguardando seu ciclo do cron.
O proprietário confirmou em seguida **todos agendados para 31/10, 01/11 e
02/11/2026**, no Instagram @arte.no.altar. A criação e o agendamento do primeiro
lote estão validados na hospedagem. A publicação nessas datas e a preparação
do segundo lote ainda são etapas futuras, não confirmadas.

A rotina está configurada para um feed às 12h de São Paulo por dia e preparação
das próximas três artes no terceiro dia, **02/11/2026**. A última captura de
geração mostrou 76 imagens restantes em revisão/reavaliação; elas não foram
liberadas em bloco nem foi reiniciado o histórico de modelos.

Serão três artes por lote. O seguinte será criado no terceiro dia do atual.
Não preparar a pasta inteira nem manter uma reposição móvel diária de três itens.

## Montagem real

`product_scene.py` usa um cenário contínuo com mesa, papéis, espessura, sombras
e contato de WhatsApp. Somente a superfície impressa da foto original é projetada
nas faces calibradas da pilha e do envelope frontal, respeitando sua oclusão.
A luz do papel modula discretamente a impressão, entre 0,94 e 1,04. Letras,
logos e QR Codes vêm do original, sem redesenho por IA; seus pixels são
reamostrados e iluminados, não preservados literalmente.

As quinze chamadas são PNGs transparentes preparados e conferidos uma vez, sem
painel opaco nem letras esticadas. `typography/manifest.json` vincula cada arquivo
à frase e ao hash; `scene-v2.json` vincula cenário e geometria. A rotina do servidor
não chama geração de imagens ou textos por IA e não exige abrir o chat diariamente.

Duas amostras integralmente visíveis tiveram cantos conferidos e vinculados ao
hash do original, sem guardar suas fotos no repositório. Para as outras, o OpenCV
local procura o contorno completo do papel e confere formato, margem e bordas.
O recortador `paper-quad-v2` combina contornos com segmentos longos de borda e
exige papel visível e continuidade nas quatro laterais. As duas amostras completas
também foram detectadas automaticamente, com as dicas manuais desativadas.
Papel parcialmente oculto ou recorte sem confiança vai para revisão, sem fallback
para a montagem retangular rejeitada. Uma amostra com livro sobre parte do papel
foi corretamente retida. Não declarar os 84 recortes validados a partir disso.

## Cadência e histórico

Cada lote tem três datas consecutivas, um feed às 12h de São Paulo por dia. O próximo
lote começa a ser preparado no terceiro dia, para os três dias seguintes. O cron
existente executa as etapas sem abrir o chat. No dia intermediário não busca outras
imagens. A consulta de metadados da pasta não significa preparar todas as artes.

O modelo e a frase são sorteados sem reposição nos ciclos existentes. Uma candidata
com recorte inválido não cria arte nem consome a data do lote: outra candidata é
tentada. Fotos possivelmente duplicadas continuam separadas, e um ciclo não é
reiniciado para contornar pendências. Arquivos e reservas anteriores permanecem
no histórico; publicações manuais não são alteradas.

## Teste real na hospedagem

```bash
cd /home/artenoaltar/arte-no-altar
git pull --ff-only origin main
python3.12 -m pip install --user --no-cache-dir -r requirements.txt
python3.12 feed_autonomy.py prepare-batch
```

Usar o Python do virtualenv, se houver. Se as dependências já estão atualizadas,
não é necessário repetir a instalação. A dependência gratuita de recorte é
`opencv-python-headless`; nenhuma API paga é necessária. O comando verifica a
conta exata @arte.no.altar, cancela somente a fila ligada à rotina anterior e
prepara até três rascunhos de teste. Há limite de tentativas: se não encontrar três
recortes confiáveis, informa o número realmente criado, em vez de publicar uma
montagem incorreta. O cron pode continuar tentando completar esse primeiro lote
em modo de teste, mas não agenda ou publica seus rascunhos.

Para continuar o lote bloqueado depois de atualizar, com saída curta:

```bash
python3.12 feed_autonomy.py prepare-batch --summary
```

Repetir `prepare-batch` durante um teste ativo continua o mesmo lote e preserva
seus rascunhos, arquivos e agendamentos manuais. O contador usa a conta e a
política atuais. Uma reserva interrompida sem composição nem post pode ser
liberada; conteúdos editados, cancelados, excluídos ou com composição anterior
permanecem protegidos. Três reservas interrompidas não significam três artes.

`posts` agora usa IDs não reutilizáveis. A migração atômica preserva os dados,
colunas, índices e histórico e avança a sequência acima dos IDs antigos. Uma
colisão já existente só é recuperada em modo de teste quando a composição nova
é dona do rascunho inalterado, sem conta ou tentativa de envio, e herdou um
agendamento terminal cujo horário precede a criação dessa composição. O rascunho
recebe ID novo, mantendo os mesmos bytes da imagem e a legenda; o agendamento e
os recibos antigos não são alterados. A recuperação fica registrada em `feed_repairs`.
Conteúdo com revisão manual, envio iniciado ou sem essa evidência continua protegido.

Na falta de modelos disponíveis, a rotina reavalia uma imagem ainda não usada
por chamada, comparando hash, possível duplicação e recorte completo. Registra
o motivo e a versão do recortador: uma candidata rejeitada não é baixada de novo
a cada minuto. A primeira chamada que completa o lote encerra essa preparação;
não reprocessa as 78 imagens em bloco. O histórico de uso e o ciclo não são apagados.

## Quando o lote não chega a três

```bash
python3.12 feed_autonomy.py status
```

O campo `batch` informa `drafts`, `prepared`, `target`, `slot_states`,
`available_models`, `used_ready_models`, `review_models`, `reviews_to_recheck`,
`review_reasons`, `blocked_slots`, os estados individuais em `slots` e
`waiting_reason`, sempre do lote da conta e política atuais. `available_models`
conta modelos prontos ainda não usados neste ciclo; `models.ready` inclui os já
usados. `models_need_review` indica falta de candidatas liberadas, enquanto
`batch_needs_review` indica conteúdo protegido ou inconsistência nas reservas.
O diagnóstico é somente de leitura: não reinicia ciclos nem libera as 78 imagens
indiscriminadamente. `reviewing_models` indica a reavaliação gradual de candidatas.
Não afirmar que o lote remoto ficou completo antes da nova consulta na hospedagem.

Depois, **Web → Reload**, atualizar o site e conferir os novos rascunhos no Estúdio
de conteúdo. Esse teste usa as imagens reais do Drive, a mesma extração e os mesmos
arquivos que a rotina usará. Não usar outra prévia de IA para afirmar que o servidor
reproduziu o resultado. Não executar novamente o modo público antes de conferir.

## Retomada após validar o lote de teste

```bash
python3.12 feed_autonomy.py enable --approve-layout
```

Esse passo registra a aprovação da nova montagem. Com o mesmo banco de assets,
a política é preservada e os rascunhos de teste são agendados sem gerar imagens
novas. Edições manuais ou cancelamentos continuam respeitados. A rotina passa a
publicar os três itens e preparar o lote seguinte no terceiro dia. No modo de
teste, ela não cria lotes posteriores nem publica, mesmo com o cron funcionando.

Trocar os assets da composição cria uma nova identidade de política para não
reativar reservas de outro layout por engano. `pause-review` continua disponível
para interromper a criação e cancelar somente a fila automática, se necessário.

## Verificação local e limites

Suíte local: **175 testes aprovados**; verificações de sintaxe JavaScript e de
diferenças também passaram. Drive e Meta são simulados nesses testes; nenhum
lote de produção foi criado por essa verificação.

Os testes cobrem: recorte de papel sem levar o fundo, conteúdo de marcadores
impressos, rejeição de contornos inválidos, banco de quinze chamadas transparentes, ciclos,
acesso a somente três candidatas entre dez, espera até o terceiro dia, lote de
rascunhos sem agendamento, promoção das mesmas imagens aprovadas, recuperação,
cancelamentos e bloqueio de execução concorrente. Drive/Meta são simulados.
Duas amostras reais foram renderizadas localmente pela mesma montagem; outra
amostra oculta foi retida. O primeiro lote real da hospedagem ainda precisa ser
conferido. Stories e carrosséis não fazem parte desta mudança.

## Histórico visual

A montagem retangular e `ambient-scene-v1` foram rejeitados. A nova aprovação
da referência integrada autorizou a implementação de `continuous-scene-v2`;
não reaprova os layouts anteriores. Ver [COMPOSITION_REVIEW.md](COMPOSITION_REVIEW.md).
