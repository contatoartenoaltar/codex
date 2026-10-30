# Acionamento externo do agendamento

O proprietário confirmou um teste real de publicação agendada com o executor rodando no console. Este acionamento HTTP é a alternativa para não depender daquele console: um serviço externo chama o site a cada minuto e o próprio PythonAnywhere processa a fila, com seu banco, imagens e credenciais locais.

O endpoint está implementado e tem testes com publicação simulada. A instalação na hospedagem, a configuração do serviço externo e o teste real com o console parado ainda precisam ser feitos. Isso não adiciona Stories, carrosséis nem agendamento pelo plugin MCP.

## Instalação no PythonAnywhere

1. Antes da troca, confira os agendamentos existentes. Para encerrar o executor de teste em `--loop`, use **Ctrl+C** no console em que ele está rodando. Não cole comandos no processo ainda em execução.
2. Atualize o código no console Bash e crie a chave exclusiva:

```bash
cd /home/artenoaltar/arte-no-altar
git pull --ff-only origin main
python3.12 scheduler_http.py configure
```

O comando usa o diretório do mesmo banco indicado por `ARTENOALTAR_DB`, ou `.local` por padrão. Se a instalação Web usa outro caminho, defina a mesma variável no console antes de configurar. Não altere nem apague o banco existente.

Os arquivos `.local/scheduler-key.txt` e `.local/scheduler-key.sha256` são privados, com permissão 600. O primeiro contém a chave; o segundo contém somente seu hash. Não envie nenhum deles ao chat, ao GitHub ou a uma pasta pública. A chave do MCP e os tokens da Meta não são usados para autenticar este acionamento.

3. Na aba **Web** do PythonAnywhere, clique em **Reload**. Não precisa alterar o WSGI se ele já define `ARTENOALTAR_ORIGIN` como a origem HTTPS correta e aponta para o mesmo banco. O hash do acionamento é lido do arquivo privado a cada chamada.

## Configuração do serviço externo

Uma opção a conferir é [cron-job.org](https://cron-job.org/). Verifique as condições atuais da modalidade gratuita antes de cadastrar a tarefa; não contrate plano pago. A configuração exige acesso do proprietário à conta nesse serviço, que não foi criada nem conectada por este código.

Configure uma tarefa com:

| Campo | Valor |
| --- | --- |
| Nome | Arte no Altar — agendamentos |
| URL | `https://artenoaltar.pythonanywhere.com/internal/scheduler/tick` |
| Método | `POST` |
| Corpo | Vazio |
| Frequência | A cada minuto, todos os dias |
| Cabeçalho | Nome `Authorization`; valor `Bearer ` seguido do conteúdo de `.local/scheduler-key.txt` |

Use o conteúdo do arquivo, não seu nome, caminho ou hash. Não coloque a chave na URL. Deixe desativadas as opções de salvar corpos de respostas, se disponíveis; a resposta já é limitada a um estado sem dados comerciais. Não configure cabeçalho `Origin`, cookies de sessão ou credenciais da Meta.

Quem tiver essa chave pode acionar os agendamentos já autorizados. Guarde-a somente no formulário seguro do serviço escolhido. Ela não permite criar agendamentos, alterar conteúdos, entrar no sistema ou consultar financeiro, estoque e clientes. Para revogar, remova o arquivo `.local/scheduler-key.sha256` pelo painel Files; para substituir, execute `python3.12 scheduler_http.py configure --rotate` e atualize o cabeçalho no serviço.

## Validação antes de confiar na rotina

1. Com o executor de console parado e sem novas publicações de teste autorizadas, execute a chamada de teste do serviço. Uma fila vazia deve responder HTTP 200 com `{"status":"idle"}`. Caso já existam conteúdos autorizados e vencidos, a chamada pode processá-los.
2. Confirme chamadas automáticas com sucesso a cada minuto no histórico do serviço. No site, atualize a página e confira **Executor: ativo**. Uma chamada manual isolada não comprova execução permanente.
3. Escolha uma foto de feed, revise conta, imagem e legenda e agende um teste real para pelo menos cinco minutos à frente. A confirmação no site autoriza a publicação futura.
4. Feche as abas do site e mantenha o executor de console parado. Depois do horário, confira o post na rede e o resultado no sistema. O Instagram pode precisar de mais de uma chamada para preparar e concluir a publicação.

## Comportamento e limites

- Cada chamada processa no máximo um item da fila; rascunhos e horários futuros não são enviados. O endpoint não aceita corpo nem parâmetros para selecionar conta, post ou horário.
- Chamadas simultâneas retornam `busy`; chamadas com intervalo menor que 30 segundos retornam `throttled`. Ambos são HTTP 200 para não transformar um acionamento redundante em falha do serviço. A reivindicação do post também é atômica no banco.
- Uma chamada interrompida mantém uma trava de até dez minutos. Operações incertas continuam indo para revisão, sem reenvio automático. Depois de uma falha, confira a rede antes de liberar nova tentativa.
- Sem chamada bem-sucedida por aproximadamente 150 segundos, o executor passa a inativo e o sistema bloqueia novos agendamentos. Itens com atraso acima de 30 minutos vão para revisão.
- O horário continua sendo interpretado em `America/Sao_Paulo`. Chamadas são periódicas, sem pontualidade ao segundo; atrasos, indisponibilidade do serviço, timeout HTTP, expiração de tokens e limites da hospedagem podem impedir a publicação.
- Confira os limites atuais do plano gratuito do agendador (frequência, tempo máximo de requisição, tratamento de falhas e desativação automática) e do PythonAnywhere. A disponibilidade do site gratuito e sua renovação continuam necessárias. Esta alternativa não garante funcionamento ininterrupto nem substitui a conferência das falhas.
