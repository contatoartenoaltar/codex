# Feeds autônomos com frases genéricas, em lotes de três dias

**Estado atual — 30/10/2026:** o proprietário aprovou a nova referência integrada
e autorizou implementar a montagem correspondente. `continuous-scene-v2` está
implementado, com duas amostras reais renderizadas localmente. O proprietário
aprovou depois o resultado na hospedagem, mas relatou um único rascunho. A captura
mostra seis modelos prontos no índice, 78 em revisão e `waiting` em modo de teste.
A correção atual distingue disponibilidade de contagem do índice, conta o lote
certo e retoma tentativas sem arte. Faltam o diagnóstico atualizado na hospedagem
e duas artes para completar o lote. Ver [FEED_BATCHES.md](FEED_BATCHES.md).

O proprietário aprovou quinze chamadas curtas genéricas e pediu que a rotina
não dependa mais de identificar dízimos, ofertas, primícias ou Santa Ceia.
O fluxo principal é automático; o formulário manual é apenas opcional.

## Fluxo atual

- Instagram **@arte.no.altar**, um feed por dia às **12h**, São Paulo, em lotes
  de três datas consecutivas. No terceiro dia preparar o próximo lote de três.
  Se houver outro agendamento, buscar janela livre até 14h.
- Sortear um modelo da pasta autorizada do Drive e uma das quinze chamadas.
- Usar cada frase uma vez no ciclo de quinze, evitando repetição imediata na virada.
- Montar em **1080 × 1350** com impressão original projetada nos papéis de um
  cenário contínuo, quinze chamadas transparentes e WhatsApp **35 9 8442-8442**.
- Depois do teste inicial e da ativação, agendar pela política autorizada,
  sem escolhas diárias ou confirmação por arte.

O cron existente executa a criação somente quando a fila de publicação estiver
ociosa. Não usa OCR, não depende do Tesseract e não chama APIs de IA pagas. Os
métodos antigos de reconhecimento permanecem apenas para compatibilidade histórica;
não são chamados pelo fluxo atual. As chamadas antigas por tema também ficam
somente para preservar referências de composições anteriores.
O cenário e as chamadas são arquivos locais preparados uma vez. A montagem
respeita perspectiva e oclusão e aplica variação discreta de luz à impressão,
sem redesenhar seu texto, logos ou QR Codes. Não há painel opaco sobre o cenário.

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
são processadas conforme a necessidade do lote, uma por chamada ociosa; não é
necessário preparar a pasta inteira. Não reiniciar todo o índice
nem apagar histórico. Reservas sem arte criada são migradas para o banco genérico;
rascunhos e agendamentos anteriores são preservados.

## Atualização da hospedagem

```bash
cd /home/artenoaltar/arte-no-altar
git pull --ff-only origin main
python3.12 -m pip install --user --no-cache-dir -r requirements.txt
python3.12 feed_autonomy.py prepare-batch
```

Usar o Python do virtualenv, se houver; a instalação pode ser omitida quando as
dependências já estão atualizadas. `prepare-batch` pausa a fila automática antiga
e prepara até três rascunhos de teste, sem agendar ou publicar. Depois, **Web →
Reload**, atualizar o site e conferir os rascunhos no Estúdio. A revisão deve usar
essas saídas reais, sem tomar a referência gerada no chat como prova do servidor.

Depois de validar o lote, `python3.12 feed_autonomy.py enable --approve-layout`
ativa a política e agenda os mesmos arquivos. O histórico de modelos e frases é
preservado. Não mudar o cron ou suas chaves; não é necessário atualizar o plugin.
Até executar a atualização, a hospedagem continua com a versão anterior.

Consultar: `python3.12 feed_autonomy.py status`. Depois de ativada, a rotina executa
com o chat e as abas fechados. O painel mostra imagens prontas, em conferência e possíveis
duplicações. Para pausar a criação: `python3.12 feed_autonomy.py disable`.
Isso não cancela agendamentos existentes. `pause-review` também cancela somente
a fila ligada à rotina automática e bloqueia a retomada sem revisão; envios já
iniciados e publicações manuais não são cancelados por esse comando.

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

## Histórico visual

A montagem retangular e `ambient-scene-v1`, com cabeçalho opaco, foram rejeitadas.
A aprovação da nova referência integrada autorizou implementar `continuous-scene-v2`;
não é aprovação de uma saída ainda não conferida na hospedagem. Stories e
carrosséis não fazem parte desta atualização.

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
