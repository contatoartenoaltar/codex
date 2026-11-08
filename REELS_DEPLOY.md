# Reels automáticos — implantação isolada

O fluxo recebe vídeos MP4 ou MOV já finalizados no Edits, com música licenciada já
incorporada, copia o arquivo sem recodificar, publica um Reel por dia e também o
exibe no Feed. Ele usa banco, chave HTTP, pasta de mídia e job próprios. A fila
nasce **desativada** e não modifica as filas de Feed, Stories ou Carrosséis.

Este roteiro separa preparação de ativação. Nesta entrega, execute no máximo as
etapas de preparação e verificação. A ativação real e o primeiro Reel ficam para
uma etapa supervisionada posterior.

## 1. Verificação antes de configurar

No Bash Console do PythonAnywhere:

```bash
cd /home/artenoaltar/arte-no-altar
git pull --ff-only origin main
python3.12 -m unittest \
  tests.test_reels_queue \
  tests.test_reels_drive \
  tests.test_reels_meta_client \
  tests.test_reels_media \
  tests.test_reels_http \
  tests.test_reels_validator \
  tests.test_reels_automation -q
command -v ffprobe || true
```

Quando `ffprobe` estiver disponível, ele lê os metadados sem alterar vídeo ou
áudio. Quando não estiver, o módulo usa o leitor MP4 interno, também somente
leitura e sem dependências adicionais. Se os testes falharem, pare aqui. Não
ative a fila nem altere os jobs que já publicam Feed, Stories e Carrosséis.

## 2. Preparar os diretórios privados

Use uma pasta nova para a fila e a pasta `.local` atual para a autorização da
Meta e a credencial de leitura do Drive:

```bash
REELS_DIR=/home/artenoaltar/arte-no-altar/.local/reels-live
META_DIR=/home/artenoaltar/arte-no-altar/.local
DRIVE_DIR=/home/artenoaltar/arte-no-altar/.local
install -d -m 700 "$REELS_DIR"

python3.12 -m reels.http configure \
  --directory "$REELS_DIR" \
  --origin https://artenoaltar.pythonanywhere.com

python3.12 -m reels.queue configure \
  --directory "$REELS_DIR" \
  --account-id 17841436823298466 \
  --confirm CONFIGURE-REELS-DISABLED
```

Esses comandos criam o banco e a chave exclusiva `reels-trigger.key`, ambos
privados. A publicação continua desativada. Não mostre a chave em capturas de
tela, comandos compartilhados ou mensagens.

## 3. Configurar a pasta de vídeos do Drive

Crie uma pasta dedicada no Drive e compartilhe-a como **Leitor** com a mesma
conta de serviço já usada pela aplicação. Coloque ali somente MP4 ou MOV
verticais finalizados: H.264 ou HEVC, áudio AAC, entre 3 e 90 segundos, até 1 GB
(1.000.000.000 bytes), de preferência 1080 × 1920. O sistema não remove nem
altera arquivos no Drive.

Depois de obter o ID ou link da pasta:

```bash
python3.12 -m reels.drive configure \
  --directory "$DRIVE_DIR" \
  --folder DRIVE_FOLDER_ID_OR_URL

python3.12 -m reels.drive status --directory "$DRIVE_DIR"
python3.12 -m reels.automation preflight --drive-directory "$DRIVE_DIR"
python3.12 -m reels.queue status --directory "$REELS_DIR"
```

O primeiro resultado informa o e-mail da conta de serviço e confirma
`"publishing_enabled": false`. O status do Drive precisa indicar catálogo
completo. O preflight baixa e valida um MP4/MOV real, remove a cópia temporária e
também confirma `"publishing_enabled": false`. Arquivos inválidos são ignorados
e contados; não bloqueiam outros vídeos válidos.

## 4. Adicionar o wrapper WSGI sem ativar publicações

Faça uma cópia privada do WSGI atual. Preserve todas as variáveis existentes e
adicione antes do import final:

```python
os.environ["ARTENOALTAR_REELS_DIR"] = "/home/artenoaltar/arte-no-altar/.local/reels-live"
os.environ["ARTENOALTAR_REELS_META_DIR"] = "/home/artenoaltar/arte-no-altar/.local"
os.environ["ARTENOALTAR_REELS_DRIVE_DIR"] = "/home/artenoaltar/arte-no-altar/.local"
```

Substitua somente o import final da aplicação por:

```python
from reels.wsgi import application
```

`reels.wsgi` delega todas as demais rotas para `carousel_posts.wsgi`, que mantém
o encadeamento atual de Carrosséis, Stories promocionais, Stories e aplicativo.
Após **Reload**, confira login, Visão geral, Financeiro, Estúdio e as próximas
publicações já existentes.

Teste o novo acionador ainda desativado sem imprimir a chave:

```bash
REELS_KEY="$(cat "$REELS_DIR/reels-trigger.key")"
curl --silent --show-error --request POST \
  --header "Authorization: Bearer $REELS_KEY" \
  https://artenoaltar.pythonanywhere.com/internal/reels/tick
unset REELS_KEY
```

A resposta esperada é `{"status":"disabled"}`. Qualquer outro resultado deve
ser investigado antes de continuar.

## 5. Job externo preparado, ainda desativado

O job futuro é independente dos jobs atuais:

| Campo | Valor |
| --- | --- |
| URL | `https://artenoaltar.pythonanywhere.com/internal/reels/tick` |
| Método | `POST` |
| Corpo | vazio |
| Frequência | a cada minuto |
| Cabeçalho | `Authorization: Bearer ` seguido da chave exclusiva dos Reels |

Ele pode ser criado no cron-job.org com **Enable job** desligado. Não reutilize
nem edite o job de Feed, Stories ou Carrosséis.

## 6. Ativação futura supervisionada

Esta etapa não faz parte da preparação. Só deve ser executada após conferir um
MP4/MOV real, a conta `@arte.no.altar`, a resposta `disabled`, o WSGI e o job novo.
O texto de confirmação é intencionalmente específico:

```bash
python3.12 -m reels.queue enable \
  --directory "$REELS_DIR" \
  --account-id 17841436823298466 \
  --confirm ENABLE-ONE-REEL-PER-DAY
```

Depois disso, habilite somente o job novo. A automação agenda no máximo um Reel
por dia, inicialmente alternando 11h, 17h e 21h no horário de São Paulo. Quando
existirem dados comparáveis suficientes, aplica o horário escolhido pelo módulo
de Insights somente a publicações futuras. Um item já agendado não muda de hora.

O primeiro Reel deve ser conferido no Instagram. Uma resposta final incerta vai
para revisão e não é publicada novamente às cegas.

Os próximos Reels usam diretamente a mesma legenda padrão oficial do Feed em
`design_assets/feed/caption.txt`. Para aplicar essa legenda a um Reel ainda na
fila sem mudar seu horário, use `python3.12 -m reels.automation
apply-feed-caption --reels-directory "$REELS_DIR"`.

A cópia privada do vídeo é removida depois de uma publicação confirmada ou de um
cancelamento; o arquivo original permanece no Drive e o recibo fica no banco.
Se o status mostrar `review` ou `invalid_files` maior que zero, a Agenda Visual
exibe o aviso e não prepara outro Reel enquanto houver uma publicação incerta.

## Pausa imediata e reversão

Para impedir novas operações da fila:

```bash
python3.12 -m reels.queue pause --directory "$REELS_DIR"
python3.12 -m reels.queue status --directory "$REELS_DIR"
```

Desative também somente o job dos Reels. Uma chamada já iniciada pode terminar;
consulte o Instagram antes de repetir qualquer item em processamento ou revisão.
Para remover o wrapper, restaure o import WSGI anterior e faça Reload. Preserve o
banco e os recibos da fila para diagnóstico; não restaure o banco comercial.

Se a chave do job for exibida ou compartilhada, mantenha o job desligado, rode
`python3.12 -m reels.http rotate --directory "$REELS_DIR"` e substitua somente o
valor do cabeçalho `Authorization` pelo novo conteúdo de `reels-trigger.key`.

## Limites desta entrega

Os testes usam Drive e Meta simulados. Eles validam isolamento, integridade do
MP4/MOV, o leitor interno sem `ffprobe`, autorização, concorrência, publicação única
e falha fechada, mas não provam que a Meta aceitará o primeiro vídeo real.
Nenhum Reel real é publicado durante a preparação.
