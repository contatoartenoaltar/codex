# Story Palavra da Manhã — prévia local

Esta etapa acrescenta somente `stories/`, documentação e testes isolados.
O compositor não importa `app`, não conecta a banco nem chama a Meta.
A fila local posterior usa somente seu banco independente de simulação;
consulte [STORIES_BATCHES.md](STORIES_BATCHES.md).
Os módulos, layouts e rotinas existentes não foram alterados.

Decisões do proprietário: tradução **Almeida Revista e Corrigida (ARC)** e
**nenhuma marca, logo, nome da empresa ou perfil na arte**. A referência visual
reenviada e a proposta aprovada na conversa orientam o fundo, a faixa dourada,
a serifada preta grande, a cursiva dourada e as curvas coloridas do rodapé.
A instrução posterior de não incluir marca prevalece sobre a referência antiga.

O catálogo contém seis passagens conferidas, com texto, referência, fonte e data.
Permite validar dois lotes sem repetição, mas não é uma autorização de publicação.
Texto e referência são compostos por fonte local, separados do fundo; não são
gerados dentro da imagem. O destaque preserva um trecho final exato da citação;
quebras de linha não podem trocar palavras. Texto que não cabe é recusado, sem
corte nem compressão horizontal das letras.

O template fixo foi preparado uma vez a partir da proposta visual aprovada,
retirando versículo, referência e tradução. Mantém a faixa, cenário, divisor e
rodapé como imagem. A versão 1080 × 1920 está em `stories/assets/`, junto ao
manifesto de hashes do fundo e das fontes. Os arquivos fotográficos do feed,
suas fontes e o layout anterior permanecem intactos.

O estilo e a composição executável com fontes locais foram aprovados pelo
proprietário depois de abrir o JPEG com texto no Drive. Não se afirma identidade
de pixels ou identificação exata das fontes da imagem original. A aprovação
fica vinculada aos hashes em `stories/assets/approval.json`; trocar template,
geometria ou fontes invalida `layout_approved` até uma nova conferência.
Não há API de IA em execução no compositor.

## Gerar uma prévia

Use o ambiente virtual com as dependências já declaradas em requirements.txt:

```bash
python -m stories.preview \
  --output /caminho/privado/palavra-da-manha.jpg \
  --verse php-4-13
```

O template é incluído; não é necessário fornecer outro fundo. O parâmetro opcional
`--background` aceita somente uma cópia idêntica desse template. Alteração de
fundo ou fonte bloqueia a exportação até a revisão dos assets.
A exportação gera JPEG RGB 1080 × 1920 e manifesto JSON de revisão, com hashes,
fonte do versículo e limites de cada área de texto. Não sobrescreve arquivos
existentes, não troca o fundo e não estica letras.
As margens editoriais deixam texto importante afastado das bordas; conferir
a apresentação no Instagram continua necessário antes de aprovar o layout.

Testes do módulo: `python -m unittest discover -s tests -p test_story_preview.py -v`.

## Fontes locais

- Playfair Display Bold: texto principal preto.
- Great Vibes: destaque com preenchimento dourado em gradiente.
- Manrope Regular: referência e tradução.

As fontes são distribuídas sem modificação, com licença SIL Open Font License
em `stories/fonts/`. Playfair Display e Great Vibes vieram do repositório
[Google Fonts](https://github.com/google/fonts/tree/main/ofl), diretórios
`playfairdisplay` e `greatvibes`. Manrope é uma cópia do asset já existente;
o arquivo usado pelo restante do sistema não foi alterado.

## Próxima etapa, dependente de nova aprovação

A fila e o executor isolados para simulação estão descritos em
[STORIES_BATCHES.md](STORIES_BATCHES.md). O adaptador real, a rota e a entrada WSGI foram preparados localmente; ver
[STORIES_DEPLOY.md](STORIES_DEPLOY.md). Implantação e ativação na hospedagem
continuam pendentes de aprovação. Não alterar o cron ou o banco atual para testar a prévia.
