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

## Estrutura visual aprovada

A capa de referência foi aprovada em 03/11/2026 e está em
`design_assets/carousel/reference/shipping-cover-approved.png`. O manifesto
`design_assets/carousel/reference/manifest.json` registra o arquivo e seu hash.
Ela define a logo oficial colorida no topo sobre preto, sem placa clara; título
branco e dourado; mapa, rotas e ícones nas cores da marca; produto sobre base
clara; e o botão **Deslize para descobrir** no rodapé. Não reinterpretar essas
posições nos demais slides. A produção deve exportar em 1080 × 1350 px.

Cada carrossel usa exatamente três slides em 1080 × 1350 px:

1. pergunta em destaque;
2. resposta aprovada;
3. chamada para o site e WhatsApp.

O tema de envio reutiliza as três artes aprovadas. Os outros treze temas usam
cenários próprios e recebem o texto, a logo e o CTA pelo compositor local. A
execução diária não chama IA nem serviço pago. A automação nunca deve alongar
uma resposta com informações inventadas.

## Rotina automática aprovada

A fila mantém as próximas três datas de carrossel preparadas: segunda, quarta e
sexta, às 12h, no fuso `America/Sao_Paulo`. Os quatorze temas completam um ciclo
antes de qualquer repetição. Depois da ativação única, cada carrossel é criado e
enfileirado sem aprovação individual.

Catálogo, logo, artes aprovadas e cenários fazem parte de uma assinatura de
integridade. Qualquer mudança pausa a criação automática para revisão. O banco e
os arquivos são isolados das filas de Feed e Stories.

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

O código permanece desativado por padrão até a implantação e a ativação única na
hospedagem.
