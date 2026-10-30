# Feeds ambientados em lotes de três dias

O proprietário aprovou a amostra com o produto recortado, perspectiva e sombras,
e pediu três artes por lote. O lote seguinte será criado no terceiro dia do atual.
Não preparar a pasta inteira nem manter uma reposição móvel diária de três itens.

## Montagem real

`product_scene.py` extrai o papel do envelope de sua fotografia e projeta a
impressão original no envelope frontal e na pilha sobre a mesa. O resto da
fotografia não vira um retângulo sobre o cenário. As sombras e a espessura são
aplicadas fora da impressão; não há redesenho de letras, logos ou QR Codes por IA.

Os quinze cabeçalhos foram preparados uma vez, abertos e conferidos visualmente.
São componentes locais com a tipografia 3D, sem esticar letras em tempo de execução.
`headers/manifest.json` vincula cada arquivo a sua chamada e hash. O servidor não
faz chamadas de geração de imagens ou textos para os lotes diários.

Duas amostras integralmente visíveis tiveram cantos conferidos e vinculados ao
hash do original, sem guardar suas fotos no repositório. Para as outras, o OpenCV
local procura o contorno completo do papel e confere formato, margem e bordas.
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

Usar o Python do virtualenv, se houver. A dependência gratuita adicional é
`opencv-python-headless`; nenhuma API paga é necessária. O comando verifica a
conta exata @arte.no.altar, cancela somente a fila ligada à rotina anterior e
prepara até três rascunhos de teste. Há limite de tentativas: se não encontrar três
recortes confiáveis, informa o número realmente criado, em vez de publicar uma
montagem incorreta. O cron pode continuar tentando completar esse primeiro lote
em modo de teste, mas não agenda ou publica seus rascunhos.

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

Os testes cobrem: recorte de papel sem levar o fundo, preservação de marcadores
impressos, rejeição de contornos inválidos, banco de quinze cabeçalhos, ciclos,
acesso a somente três candidatas entre dez, espera até o terceiro dia, lote de
rascunhos sem agendamento, promoção das mesmas imagens aprovadas, recuperação,
cancelamentos e bloqueio de execução concorrente. Drive/Meta são simulados.
Duas amostras reais foram renderizadas localmente pela mesma montagem; outra
amostra oculta foi retida. O primeiro lote real da hospedagem ainda precisa ser
conferido. Stories e carrosséis não fazem parte desta mudança.
