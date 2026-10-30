# Criação diária autônoma de feeds

O proprietário corrigiu o fluxo: não quer escolher modelo ou tema diariamente.
A seleção manual é agora apenas uma ferramenta opcional de exceção.

O padrão preparado é Instagram **@arte.no.altar**, um feed diário às **12h**,
**America/Sao_Paulo**, até três dias à frente. Se o horário estiver ocupado,
preservar o conteúdo existente e procurar uma janela de 15 minutos até 14h.
Esse padrão foi informado na conversa. A ativação registra a política exata na
hospedagem; ainda não houve teste real de publicação dessa nova rotina.

## Funcionamento

O cron existente prioriza a publicação. Nas chamadas ociosas, executa uma etapa
da criação se houver uma política ativa. Não é preciso outro serviço ou abrir
o chat. A conexão própria de leitura do Drive é reutilizada, sem alterar originais.

A primeira análise percorre uma imagem por chamada. Para 84 imagens, pode levar
cerca de 84 chamadas ociosas do cron, além dos períodos de publicação. A montagem
começa depois dessa análise inicial. Os nomes genéricos não são usados para
adivinhar o tema: o Tesseract lê localmente o texto dominante, com limites de
confiança, tamanho e tempo. Palavras pequenas de um versículo não bastam.
As três amostras já abertas na conversa têm temas conferidos visualmente,
vinculados a hashes; o repositório não contém seus originais ou IDs privados.

O sorteio usa modelos prontos sem reposição. Cópias idênticas são agrupadas pela
identidade dos pixels e não ganham duas chances. Fotos semelhantes com pixels
diferentes ficam para revisão, em vez de serem contadas como modelos novos.
Essa comparação é uma triagem, não prova de que todas as fotografias do mesmo
envelope foram identificadas; validar o catálogo real na implantação.

Novos modelos são consultados antes de reiniciar um ciclo. Enquanto houver casos
incertos, os modelos prontos podem ser usados uma vez, mas o ciclo não é reiniciado
para contornar a regra. No ciclo seguinte, evitar repetir imediatamente o último
modelo quando houver alternativas. As frases aprovadas também alternam sem
reposição por tema. A composição usa a base local e os originais preservados,
sem chamadas diárias a APIs de IA pagas.

## Autorização e recuperação

`enable` verifica a conta exata e a permissão de publicação junto à Meta. Nunca
substitui a conta por outra. A política privada guarda conta, fuso, horário e
hashes do template e das frases. Uma mudança nesses conteúdos exige reativação
da política; não passa a autorizar conteúdo diferente silenciosamente.

`scheduling.save_automatic` é separado da confirmação conversacional: valida
a política e o vínculo entre reserva, modelo, composição e conta. Não inventa
uma confirmação humana. Somente composições dessa política e na revisão original
podem ser agendadas. Publicações manuais e pelo chat mantêm suas confirmações.

Reserva de modelo, dia, ciclo e ID da composição ficam no banco. Interrupções
reutilizam o mesmo rascunho; há bloqueio entre execuções simultâneas. O original
é conferido novamente por hash. Se mudou, volta à análise e não recebe o tema
antigo. Cancelamentos são respeitados e não recriados para o mesmo dia. Edições
manuais também impedem o agendamento desse rascunho pela rotina. Resultados
incertos de publicação continuam exigindo revisão; não há reenvio automático.

## Atualização e ativação única

```bash
cd /home/artenoaltar/arte-no-altar
git pull --ff-only origin main
python3.12 -m pip install --user -r requirements.txt
python3.12 feed_autonomy.py enable
```

Usar o Python do virtualenv caso exista. O comando verifica o executável gratuito
`tesseract` antes de ativar. Ele está disponível e o OCR em português foi testado
neste ambiente; sua presença ainda precisa ser confirmada no PythonAnywhere.
Se faltar lá, resolver a instalação, sem contratar API paga ou ativar sem OCR.

Depois, PythonAnywhere **Web → Reload** e atualizar o site. Não mudar URL, chave
ou frequência do cron existente nem apagar o banco. Até atualizar e ativar a
hospedagem, a implementação não muda a operação real do site.

O Estúdio de conteúdo mostra o andamento e os modelos prontos, em análise e em
revisão. Consultar no terminal: `python3.12 feed_autonomy.py status`.
Para parar a criação: `python3.12 feed_autonomy.py disable`. Isso preserva os
agendamentos existentes; usar as funções de cancelamento se precisar interrompê-los.

## Exceções reunidas para revisão

Letras decorativas podem não ser reconhecidas. Temas sem chamadas aprovadas
também ficam separados; não inventar frases para incluí-los. Para eu ajudar a
revisar as exceções de uma vez, gerar o pacote:

```bash
python3.12 feed_autonomy.py export-review
```

O arquivo privado `.local/revisao-modelos.zip` contém miniaturas identificadas e
`classificacao.json`, sem banco ou credenciais. Baixar pelo painel Files autenticado;
não tornar `.local` pública. Depois da revisão visual, o JSON recebe o tema e,
quando houver outra foto do mesmo modelo, `same_model_as` com o ID correspondente.
Não usar nomes dos arquivos para concluir o tema ou afirmar que modelos são distintos.
Temas fora dos quatro atuais continuam pendentes até terem textos aprovados.

Aplicar o JSON revisado com:

```bash
python3.12 feed_autonomy.py import-review --file CAMINHO_DO_JSON
```

A importação confere todos os hashes numa transação e mantém o histórico ao
agrupar referências. Essa revisão do catálogo não é uma escolha diária de modelos.

## Validação pendente na hospedagem

Os testes de Drive e Meta são simulados; houve teste real apenas do OCR local.
A leitura dos 84 originais e os agendamentos anteriores foram validados pelo
proprietário, mas o índice completo, seus agrupamentos e a publicação pela nova
política ainda precisam ser observados no PythonAnywhere. Stories e carrosséis
não foram ativados por essa implementação.
