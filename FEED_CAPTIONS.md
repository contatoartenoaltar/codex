# Legenda padrão dos feeds

Em 30/10/2026, o proprietário forneceu e autorizou uma legenda fixa completa:
marca, apresentação, lista de produtos, preços dos envelopes, personalização,
localização, envio, pagamento, site, Instagram e nove hashtags. O texto publicado
está em [caption.txt](design_assets/feed/caption.txt): **981 caracteres**, sem
marcadores Markdown. As palavras, preços, emojis e quebras de linha fornecidos
foram preservados; o site aparece como `www.artenoaltar.com.br`.

Todas as novas composições de feed usam exatamente esse texto. Não acrescentar
a frase da imagem, outro telefone, hashtags extras ou uma abertura variável.
As quinze frases continuam alternando apenas nas imagens.

## Aplicar na hospedagem e nos três agendados

```bash
cd /home/artenoaltar/arte-no-altar
git pull --ff-only origin main
python3.12 feed_autonomy.py apply-caption-standard --summary
```

Depois, **Web → Reload**. Não executar `prepare-batch` nem ativar a rotina de
novo para trocar legendas. Os feeds #4, #5 e #6 já estão agendados para 31/10,
01/11 e 02/11/2026; este comando atualiza somente as legendas originais ainda na
fila da política e conta atuais, sem alterar imagem, conta, horário ou estado.
As revisões do conteúdo e da fila avançam juntas numa transação. O ID da
política, seu hash e o histórico dos ciclos permanecem os mesmos.

Repetir o comando não incrementa a revisão de novo nem duplica posts. Legendas
editadas manualmente, outras políticas, posts manuais/MCP, envios iniciados e
conteúdos já publicados são preservados. Os rascunhos de teste antigos não são
alterados, para manter a proteção de revisão da rotina.

O comando informa quantas legendas atualizou, quantas já usam o padrão e quais
foram preservadas para conferência. A implementação e os testes locais não
comprovam a aplicação na hospedagem; aguardar o retorno real do comando.

Validação local: **181 testes aprovados**, incluindo preservação dos arquivos e
horários, revisões sincronizadas, proteção de edições e rollback em conflito.
