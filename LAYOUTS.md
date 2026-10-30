# Primeira proposta de layouts — aguardando aprovação

O proprietário enviou o pacote de três amostras obtido pelo conector do Drive.
As três imagens foram abertas e conferidas: PNG RGB, 1448 × 1086 px, com os
checksums correspondentes ao catálogo. São cenas prontas de envelopes sobre mesa,
com a impressão já integrada à fotografia. Não recriar essa impressão por IA.

`layout_preview.py` produz uma primeira proposta reproduzível com Pillow:

- Feed 1080 × 1350, com uma foto completa e chamada para orçamento.
- Story 1080 × 1920, com outra foto completa e chamada para pedido.
- Carrossel de três slides 1080 × 1350, com pergunta, resposta/terceira foto e
  chamada para atendimento. O modelo aparece somente no slide da resposta; os
  outros dois slides são texto, sem reutilizar outro envelope.

A proposta usa fundo escuro e dourado, fontes com licença aberta, chamadas externas
e WhatsApp (35) 98442-8442. As fotos são apenas redimensionadas proporcionalmente e
inseridas inteiras. Não há recorte, máscara, texto ou efeito sobre a área da foto.
Os originais não são sobrescritos. Os testes comparam a área inserida à foto inteira
redimensionada. Isso não é uma validação de leitura do QR Code original; revisar a
imagem final e os códigos antes de liberar uma rotina de publicação.

## Situação da aprovação

As artes ainda são propostas. A logo oficial não foi enviada; o nome da empresa
aparece em identificação tipográfica provisória. Não apresentar isso como aplicação
da logo oficial nem ativar a rotina diária a partir dessas prévias.

O manifesto tem `approved=false`. A aprovação visual pelo proprietário, a inclusão
da logo oficial e a definição do calendário/autorizações da rotina permanecem
pendentes. As fotos e as propostas ficam em `.local`, sem entrar no repositório.

O manifesto registra os IDs e hashes dos três modelos usados nas montagens. Ao
implementar o ciclo sem repetição, considerar também essas referências já usadas
nas artes criadas, além dos registros anteriores de criação/publicação; não
reiniciar a rotação apenas por mudar de sessão.

## Reprodução privada na hospedagem

Depois de atualizar o código e instalar dependências com o Python usado na conta:

```bash
cd /home/artenoaltar/arte-no-altar
git pull --ff-only origin main
python3.12 -m pip install --user -r requirements.txt
python3.12 layout_preview.py --samples .local/modelos-amostra.zip
```

Se a instalação usa virtualenv, use seu Python em vez de `--user`. Quando houver
uma logo PNG/JPEG aprovada disponível localmente, acrescente `--logo CAMINHO_DA_LOGO`.

O comando cria PNGs e JPEGs em `.local/layout-review/`, uma folha `preview.png`,
`proposta.json` e `.local/proposta-layouts.zip`. O ZIP contém somente os arquivos
de saída definidos, sem chaves, banco ou outros arquivos da pasta privada. Baixar
pelo painel Files autenticado; não expor `.local` como diretório público.

## Próximas etapas

Esta entrega é somente a montagem visual inicial. Não cria rascunhos, agendamentos
ou publicações. Não usa API de IA paga e não altera os 84 originais do Drive.
Stories e carrosséis ainda não estão disponíveis no importador/publicador atual;
renderizar uma imagem nesses formatos não implementa seu envio à Meta.

Depois de revisar os layouts, implementar catálogo de modelos distintos, sorteio
persistente sem reposição, composição por modelos aprovados, textos aprovados,
novos formatos nas APIs e rotina diária com autorização do proprietário. Não
marcar modelos como usados só por ter baixado amostras de referência.
