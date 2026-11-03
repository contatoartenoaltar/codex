# Automação de carrosséis

## Conteúdo aprovado

O catálogo oficial de perguntas e respostas está em
`design_assets/carousel/approved-faq.json`. Ele contém 14 temas aprovados pelo
proprietário em 03/11/2026. A composição deve reproduzir as respostas desse
arquivo sem acrescentar preços, prazos, descontos, disponibilidade ou condições.

Cada item do catálogo representa um carrossel completo. A rotação automática
deve registrar o identificador do item usado e percorrer os 14 itens antes de
recomeçar o ciclo. Uma mudança no texto ou nos dados comerciais exige nova
aprovação e uma nova versão do catálogo.

## Estrutura visual proposta

A capa de referência foi aprovada em 03/11/2026 e está em
`design_assets/carousel/reference/shipping-cover-approved.png`. O manifesto
`design_assets/carousel/reference/manifest.json` registra o arquivo e seu hash.
Ela define a logo oficial colorida no topo sobre preto, sem placa clara; título
branco e dourado; mapa, rotas e ícones nas cores da marca; produto sobre base
clara; e o botão **Deslize para descobrir** no rodapé. Não reinterpretar essas
posições nos demais slides. A produção deve exportar em 1080 × 1350 px.

O primeiro piloto deve usar entre três e cinco slides em 1080 × 1350 px:

1. pergunta em destaque;
2. resposta aprovada;
3. modelo de produto preservado e integrado à cena;
4. apoio visual, somente quando houver informação aprovada suficiente;
5. chamada para o site ou WhatsApp.

Slides sem conteúdo suficiente podem ser omitidos. A automação nunca deve
alongar uma resposta com informações inventadas. Textos, logotipos, cores e QR
Codes dos modelos de envelopes precisam ser preservados.

## Implantação prevista

1. Criar uma publicação principal e armazenar seus slides em ordem.
2. Exibir a sequência completa no Estúdio de conteúdo para revisão.
3. Agendar ou cancelar o carrossel como uma única publicação.
4. Preparar e confirmar cada contêiner filho na Meta.
5. Criar o contêiner `CAROUSEL` somente depois que todos os filhos estiverem
   prontos e publicar uma única vez.
6. Persistir cada identificador remoto para que o cron possa continuar a partir
   da etapa confirmada sem duplicar uma publicação.
7. Interromper a fila para revisão quando a Meta não confirmar o resultado.

O catálogo e este documento não ativam geração, agendamento ou publicação.
