# Novos modelos de envelopes

Fluxo isolado para criar **cinco candidatos por dia**, um de cada tema:

- Dízimos
- Ofertas
- Primícias
- Santa Ceia
- Missões

Os 88 arquivos da pasta `Artes Base` são consultados como referências somente de leitura. A IA
cria uma base visual original e o sistema aplica o título localmente, evitando
texto deformado. O arquivo final mede `1492 × 1054 px`, passa por validação e é
salvo na subpasta de revisão do respectivo tema. Nenhum original é substituído,
movido ou excluído.

## Pastas criadas no Drive

Pasta principal de saída: `Novos Modelos de Envelopes - IA`

| Tema | ID da subpasta |
| --- | --- |
| Dízimos | `1f_4g1VnMk7Di-mCyTjXmPrKGpMBz4qwF` |
| Ofertas | `1NHXi-g7cphMBgEbboN5hY8mShkhptMXG` |
| Primícias | `1G-NI1QBkll4dIC9lQ65v_gWMo9dKJ-9W` |
| Santa Ceia | `17_V-RhjOC1WCF3oCEzM_8ybV5ktxUszp` |
| Missões | `1Bt0B1udsG_IaRi9bBROHCehm6og8g9Eb` |

Antes do primeiro teste na hospedagem, compartilhar **somente a pasta principal
de saída** com a conta de serviço já usada pelo sistema, como **Editor**. Manter a
pasta dos modelos aprovados como **Leitor**.

## Segurança e custo

A rotina nasce desativada. A chave de texto existente não é reutilizada: a
geração exige o segredo `ARTENOALTAR_IMAGE_AI_KEY`. O modelo padrão é
`gpt-image-1.5`, configurável em `ARTENOALTAR_IMAGE_AI_MODEL`.

Cinco imagens por dia equivalem a aproximadamente 150 gerações por mês. O plano
ChatGPT Plus não inclui essas chamadas do servidor. Conferir o preço vigente da
API e aprovar o orçamento antes de cadastrar a chave e ativar a rotina.

## Configuração na hospedagem

```bash
cd /home/artenoaltar/arte-no-altar
git pull --ff-only origin main

python3.12 -m envelope_models.automation configure \
  --source 12uLNB8R1DLOaZhRgTAJDTJswFUmkJiYG \
  --dizimos 1f_4g1VnMk7Di-mCyTjXmPrKGpMBz4qwF \
  --ofertas 1NHXi-g7cphMBgEbboN5hY8mShkhptMXG \
  --primicias 1G-NI1QBkll4dIC9lQ65v_gWMo9dKJ-9W \
  --santa-ceia 17_V-RhjOC1WCF3oCEzM_8ybV5ktxUszp \
  --missoes 1Bt0B1udsG_IaRi9bBROHCehm6og8g9Eb

python3.12 -m envelope_models.automation status
```

Esse comando configura tudo em modo desativado. A ativação será feita somente
depois da aprovação do primeiro lote e do custo da API:

```bash
python3.12 -m envelope_models.automation enable \
  --confirm ENABLE-FIVE-ENVELOPE-MODELS-PER-DAY
```

O executor diário chama:

```bash
python3.12 -m envelope_models.automation run
```

O banco impede criar duas artes do mesmo tema no mesmo dia. As referências entram
em rotação global: os cinco temas do dia usam arquivos distintos, arquivos ainda
não usados têm prioridade e depois são escolhidos os menos usados.
Resultados ficam com estado `review`; aprovação comercial e envio para impressão
continuam separados desta rotina.
