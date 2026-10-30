# Criação diária de feeds com frases genéricas

**Decisão mais recente:** o proprietário aprovou a nova ambientação com o envelope
recortado sobre a mesa, perspectiva e sombras. Pediu lotes de três artes: um feed
por dia e, no terceiro dia, preparação do próximo lote de três. O código atual
usará o novo compositor e cabeçalhos 3D prontos para as quinze frases. A primeira
execução na hospedagem será um lote de teste em rascunho, antes de retomar envios.
A aprovação da amostra não comprova recortes corretos dos 84 arquivos.
**Instruções atuais de atualização e teste:** [FEED_BATCHES.md](FEED_BATCHES.md).


**Status mais recente:** o proprietário rejeitou o resultado real da montagem
automática. O envelope deve ser integrado ao ambiente, com perspectiva e sombra,
preservando a impressão; o título não pode ficar esticado. A aprovação da arte
de referência não valida o compositor atual. Usar `feed_autonomy.py pause-review`
para parar a criação e cancelar somente a fila gerada pela rotina. A reativação
fica bloqueada até corrigir e aprovar uma saída real do compositor.


O proprietário aprovou quinze chamadas curtas genéricas e pediu que a rotina
não dependa mais de identificar dízimos, ofertas, primícias ou Santa Ceia.
O fluxo principal é automático; o formulário manual é apenas opcional.

## Fluxo atual

- Instagram **@arte.no.altar**, um feed por dia às **12h**, São Paulo, até três dias
  preparados. Se houver outro agendamento, buscar janela livre até 14h.
- Sortear um modelo da pasta autorizada do Drive e uma das quinze chamadas.
- Usar cada frase uma vez no ciclo de quinze, evitando repetição imediata na virada.
- Montar em **1080 × 1350**, mantendo a foto inteira e o botão com **35 9 8442-8442**.
- Agendar pela política autorizada, sem escolhas diárias ou confirmação por arte.

O cron existente executa a criação somente quando a fila de publicação estiver
ociosa. Não usa OCR, não depende do Tesseract e não chama APIs de IA pagas. Os
métodos antigos de reconhecimento permanecem apenas para compatibilidade histórica;
não são chamados pelo fluxo atual. As chamadas antigas por tema também ficam
somente para preservar referências de composições anteriores.

## Frases aprovadas

1. Envelopes com a sua identidade
2. Sua igreja em cada detalhe
3. Personalização que faz a diferença
4. Feitos para a sua igreja
5. Seu modelo, sua identidade
6. Envelopes que levam propósito
7. Cada detalhe comunica cuidado
8. A marca da sua igreja
9. Sua identidade merece destaque
10. Pequenos detalhes, grande significado
11. Sua igreja, seu estilo
12. Personalize com a Arte no Altar
13. Cuidado em cada impressão
14. Transforme detalhes em identidade
15. Envelopes personalizados para sua igreja

## Controle das imagens

A classificação por tema saiu, mas a conferência de arquivos e duplicações continua.
O banco registra IDs, hashes, identidade dos pixels, similaridade visual e uso por
ciclo. Cópias idênticas são agrupadas; fotos diferentes possivelmente do mesmo
modelo ficam para revisão. Essa triagem não é prova de que todas as fotos de um
modelo foram detectadas; conferir as exceções reais. Não reiniciar o ciclo para
contornar pendências, e consultar novos arquivos antes de permitir repetição.

Na atualização, os hashes e comparações já calculados são reaproveitados para
arquivos que não mudaram. Falta de reconhecimento de tema deixa de ser motivo
para retenção. Dúvidas de duplicação continuam retidas. Imagens ainda não conferidas
são processadas gradualmente, uma por chamada ociosa. Não reiniciar todo o índice
nem apagar histórico. Reservas sem arte criada são migradas para o banco genérico;
rascunhos e agendamentos anteriores são preservados.

## Atualização da hospedagem

```bash
cd /home/artenoaltar/arte-no-altar
git pull --ff-only origin main
python3.12 feed_autonomy.py enable
```

Depois, **Web → Reload** e atualizar o site. A reativação registra o novo banco de
textos aprovado, preservando a identidade da política, a conta e a rotação de
imagens. Não mudar o cron ou suas chaves; não é necessário atualizar o plugin.
Até atualizar e reativar, a hospedagem continua com a versão anterior.

Consultar: `python3.12 feed_autonomy.py status`. A rotina segue ativa com o chat e
as abas fechados. O painel mostra imagens prontas, em conferência e possíveis
duplicações. Para pausar a criação: `python3.12 feed_autonomy.py disable`.
Isso não cancela agendamentos existentes; usar as funções próprias para cancelá-los.

## Política e recuperação

A ativação verifica a conta exata e sua permissão na Meta. A política privada
vincula conta, calendário, template e banco de frases. Sem essa política ativa,
a chave do cron não autoriza criar nem agendar novos conteúdos.
`scheduling.save_automatic` valida o vínculo entre reserva, composição e política,
sem inventar confirmação humana. As operações conversacionais mantêm suas regras.

Os registros e bloqueios impedem criações duplicadas após interrupções e execuções
simultâneas. Cancelamentos não são recriados, e rascunhos alterados manualmente
não são agendados pela rotina. Mudanças no original exigem nova conferência.
Resultados incertos da Meta continuam para revisão, sem reenvio automático.

## Revisão excepcional

Se restarem fotos possivelmente duplicadas, o comando abaixo reúne miniaturas e
metadados num pacote privado, sem banco ou credenciais:

```bash
python3.12 feed_autonomy.py export-review
```

O arquivo é `.local/revisao-modelos.zip`, acessível somente pelo painel Files
autenticado. Não expor `.local`. A revisão passa a ser de identidade dos modelos,
não de tema. O campo `theme` do JSON deve ser `generico`; `same_model_as` indica
outra foto do mesmo modelo. A importação confere hashes numa transação:

```bash
python3.12 feed_autonomy.py import-review --file CAMINHO_DO_JSON
```

A aprovação das frases não comprova publicação: a nova versão ainda precisa ser
atualizada na hospedagem e ter sua montagem e publicação real observadas.
Stories e carrosséis permanecem separados desta rotina de feeds.
