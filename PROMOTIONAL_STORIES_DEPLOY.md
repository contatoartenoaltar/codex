# Implantação dos Stories promocionais

Este módulo é independente dos Stories bíblicos e do feed. Ele usa seu próprio banco,
diretório de mídia, chave HTTP, rota e variáveis de ambiente.

## Fluxo seguro

1. Inicialize um diretório novo com `python3.12 -m promotional_stories.queue --directory DIRETORIO agenda`.
2. Prepare um lote com `prepare` e `--drive-directory`, apontando para a configuração
   de leitura do catálogo. A consulta não altera o cache nem a configuração do feed.
3. Revise os 10 JPEGs e os horários 04:00, 06:00, 08:00, 10:00, 12:10,
   14:00, 16:00, 18:00, 20:00 e 22:00.
4. Somente após aprovação, use `queue --batch ID --confirm`.
5. Configure a conta com `configure-live --account ID --confirm`. Isso mantém o envio desligado.
6. Crie a chave privada da rota `/internal/promotional-stories/tick` com
   `python3.12 -m promotional_stories.http --directory DIRETORIO --origin https://DOMINIO`.
   Não reutilize a chave dos Stories bíblicos.
7. Aponte o WSGI para `promotional_stories.wsgi.application` e defina
   `ARTENOALTAR_PROMOTIONAL_STORIES_DIR` e `ARTENOALTAR_PROMOTIONAL_STORIES_META_DIR`.
8. A ativação final usa `enable-live --confirm` e deve ocorrer apenas após nova aprovação.
9. Após a aprovação do padrão recorrente, `enable-daily --confirm` fixa o hash do
   layout, títulos, horários e recorte autorizados. Uma tarefa diária executa
   `run-daily`; qualquer mudança nesse conjunto desliga a geração e pede revisão.

O executor nunca prepara, aprova ou coloca um lote na fila. Ele processa somente artes
já revisadas e falha para o estado `review` quando a confirmação da Meta é incerta.
Os arquivos de lotes publicados são removidos após 30 dias; o histórico de modelos e
publicações permanece no banco promocional para impedir repetições indevidas.
