# Stories — lotes de três dias em módulo isolado

Escopo inicial: fila e executor isolados, com Meta simulada.
Etapa posterior autorizada: preparar adaptador Meta, HTTP e entrada WSGI locais,
sem ativar envios ou alterar a hospedagem. Ver [STORIES_DEPLOY.md](STORIES_DEPLOY.md).
O proprietário pediu a mesma cadência do feed: três dias, um Story diário,
com preparação do próximo lote no terceiro dia. O horário é 07h30 em
`America/Sao_Paulo`. Não há reposição móvel de três itens a cada dia.

## Estado desta implementação

- Layout com texto aprovado pelo proprietário após abrir o JPEG no Drive.
- Seis versículos ARC conferidos, com fonte registrada em `stories/verses.json`.
- Geração de três artes, datas consecutivas e sorteio sem reposição no ciclo.
- Banco **novo e independente** `story-queue.sqlite3`, no diretório informado.
- Reinícios e chamadas simultâneas não recriam o lote nem repetem envios.
- Preparação das três artes e registro do lote são atômicos; falha desfaz
  somente os arquivos novos e os registros desta tentativa.
- Horários vencidos, alterações de arquivos, resultados incertos e interrupções
  exigem conferência. O executor não repete um envio incerto automaticamente.
- Produção, aplicativo, cron existente, fila de feed e banco comercial intactos.

**Nenhum Story foi agendado ou publicado no Instagram nesta etapa.** O modo
padrão é simulação e a política inicia desativada. O modo real exige um diretório
novo, configuração e ativação explícitas, com transporte correspondente. A fila
de testes não pode ser promovida para envio. O cliente real usa a autorização
existente por leitura e faz chamadas Graph; nos testes, HTTP e credenciais são
fictícios. Aprovar o layout não ativa envios.

## Preparação local

Com o mesmo ambiente virtual já usado nos testes:

```bash
python -m stories.queue --directory /caminho/privado/story-test prepare
python -m stories.queue --directory /caminho/privado/story-test agenda
```

Esse diretório precisa ser exclusivo do módulo. O comando não abre o banco do
sistema nem copia dados de produção. Se o horário de hoje não tiver ao menos
dois minutos de antecedência, o primeiro dia será amanhã. Um lote atrasado não
é retroativamente deslocado nem enviado fora do horário autorizado.

Um lote inicial fica em rascunho. A função `queue_batch(..., confirmed=True)`
reserva os horários **locais** após conferir os três arquivos e seus manifestos.
`enable_simulation(..., confirmed=True)` autoriza somente o teste de uma conta
fictícia. `tick` usa um transporte injetado pelos testes para exercitar criação
de contêiner `STORIES`, processamento e envio simulado. Os comandos reais estão
separados no plano de implantação; não os usar como diagnóstico.
`pause` interrompe os próximos ticks; não desfaz uma etapa
de envio que já começou.

No terceiro dia, o tick ocioso pode preparar e reservar o lote seguinte sob essa
política explicitamente ativada, em seu modo correspondente. Um lote que ainda esteja em rascunho não provoca
novos lotes. Se a rotina ficar indisponível, ela não tenta publicar datas antigas;
atrasos acima de 30 minutos ficam para revisão.

## Aprovação e integridade

`stories/assets/approval.json` vincula a aprovação ao template, geometria e
fontes exatos, além do hash do JPEG conferido. Alterar esses assets ou o
manifesto impede enfileirar/enviar até uma nova revisão. Cada item preserva
o versículo completo, ciclo, data, imagem, hashes e tentativas de seu modo.
O destaque precisa ser um trecho exato da ARC; não é paráfrase gerada por IA.

O catálogo inicial de seis passagens permite validar dois lotes completos
sem repetição. Expandir o catálogo continua recomendado para a rotina diária.
A próxima passagem é sorteada entre as ainda não usadas, antes de reiniciar
o ciclo; o primeiro item do novo ciclo não repete o último do anterior.

## Verificação

```bash
python -m unittest discover -s tests -p 'test_story*.py' -v
python -m unittest discover -s tests -v
node tests/test_dashboard_chart.js
node tests/test_financial_notes.js
```

Os testes usam diretórios temporários e conta/Meta fictícias. Cobrem cadência,
fuso, concorrência, reinício, rotação, rollback, confirmação, troca de conta,
integridade, pausa, atraso e interrupção. O compositor continua sem API paga.

## Etapa seguinte — implantação ainda não realizada ou autorizada

O adaptador real, a rota privada e a entrada WSGI opcional estão preparados em
código local. Confirmar conta empresarial e permissões e revisar
[STORIES_DEPLOY.md](STORIES_DEPLOY.md). Somente após aprovação: backup, publicação
do código, implantação, teste real supervisionado e ativação. Não reaproveitar
nem alterar silenciosamente o endpoint, a chave ou o cron atual do feed.
