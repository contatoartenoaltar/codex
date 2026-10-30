# Agendamento de postagens

A fila e o executor estão implementados. O proprietário confirmou publicações reais agendadas com o console e, depois, com o console parado e as abas fechadas. O acionamento externo foi configurado no cron-job.org a cada minuto. Os testes locais usam Meta simulada; o relato do proprietário valida os testes reais feitos, não garante disponibilidade permanente futura.

O acionamento por HTTP com chave exclusiva está descrito em [SCHEDULER_HTTP.md](SCHEDULER_HTTP.md). O plugin 0.2.0 acrescenta agendamento confirmado nessa mesma fila, sem criar outro executor; veja [MCP_SETUP.md](MCP_SETUP.md). Essa nova ferramenta ainda precisa de implantação e teste real no aplicativo.

## Revisão e autorização

Na revisão do rascunho, escolha a conta, legenda, imagem e **Data e hora para agendar (São Paulo)**. O fuso é sempre `America/Sao_Paulo`, independentemente do relógio ou fuso do navegador. **Agendar publicação** pede autorização explícita do envio automático futuro e só é aceito quando há sinal recente do executor ativo. **Salvar rascunho** e **Publicar agora** continuam sendo ações distintas.

O horário deve estar entre 2 minutos e 90 dias no futuro. O executor confere a fila a cada 30–60 segundos; não há garantia de pontualidade ao segundo. No Instagram, a preparação de imagem pode acrescentar mais ciclos. Se um conteúdo estiver atrasado por mais de 30 minutos, não é enviado automaticamente: vai para revisão. Não reutilize uma autorização antiga para publicar dias depois de um período de indisponibilidade.

O cartão mostra horário de São Paulo e estado do executor. Enquanto estiver na fila, **Cancelar agendamento** devolve o conteúdo para rascunho e invalida a revisão anterior. Depois que o envio começa, o cancelamento não é oferecido; confira o resultado na rede. Para editar, cancele primeiro e agende novamente. Não é possível enviar manualmente, alterar ou excluir um rascunho sob controle da fila ativa.

## Executor

O executor precisa acessar o MESMO banco, imagens e credenciais da instalação Web. Executá-lo no computador pessoal sem acesso seguro a esses arquivos não controla automaticamente o banco do PythonAnywhere. Não copie segredos para o chat ou GitHub e não exponha o SQLite na rede.

Para um servidor próprio ou recurso contínuo autorizado do provedor:

```bash
cd /home/artenoaltar/arte-no-altar
ARTENOALTAR_ORIGIN=https://artenoaltar.pythonanywhere.com python3.12 scheduling.py --loop
```

Esse processo precisa ser supervisionado pela hospedagem e reiniciar após interrupções. Não use `nohup` no plano gratuito para fingir disponibilidade permanente. Um console aberto é útil para teste acompanhado, mas não é garantia de funcionamento contínuo. Ao encerrar normalmente, o processo desativa seu sinal de funcionamento. Após uma interrupção abrupta, o sinal fica inativo em aproximadamente 150 segundos.

Se o provedor permitir tarefas a cada minuto, configure o comando:

```bash
cd /home/artenoaltar/arte-no-altar && ARTENOALTAR_ORIGIN=https://artenoaltar.pythonanywhere.com python3.12 scheduling.py --cron
```

Uma tarefa diária não atende a essa frequência. O proprietário verificou a aba Tasks: o plano gratuito não oferece Scheduled tasks nem Always-on tasks. Não contrate plano pago. O modo `--cron` declara que esse comando será chamado pelo agendador externo a cada minuto; executá-lo manualmente uma vez não configura o agendador. Na instalação do proprietário, o cron-job.org chama o endpoint HTTP protegido, não este comando de console.

Para diagnóstico local, uma execução isolada de `python3.12 scheduling.py` processa no máximo um item vencido e não anuncia um executor contínuo ativo. Ela pode publicar conteúdos já autorizados e vencidos no banco indicado: use banco temporário nos testes.

No PythonAnywhere, o console e o WSGI precisam apontar para o mesmo `ARTENOALTAR_DB` (por padrão `.local/arte-no-altar.db`). O executor também precisa de ARTENOALTAR_ORIGIN definido no seu processo; a variável configurada no arquivo WSGI não é herdada automaticamente por consoles e tarefas. Cada tick reconfirma permissões. O Facebook usa arquivo JPEG direto ou texto; o Instagram usa a foto não publicada na página vinculada para hospedar a imagem na Meta, a alternativa já validada pelo proprietário. No horário autorizado, o executor conclui automaticamente a segunda etapa do Instagram; a autorização é dada ao agendar, sem novo clique no momento do envio.

## Falhas e integridade

As tabelas `post_schedule` e `scheduler_runtime` são adicionadas sem apagar os registros existentes e fazem parte do backup SQLite. O executor reivindica um item dentro de uma transação curta antes das chamadas remotas. Instâncias concorrentes não reivindicam o mesmo item. Um envio interrompido por mais de dez minutos é marcado para conferência, sem retomada automática da operação incerta. Falhas não geram tentativas infinitas. Confira a rede antes de liberar novo envio.

Se o token expirar, a conta perder permissão, a página vinculada não estiver acessível, o JPEG sumir ou o servidor ficar indisponível, o envio poderá falhar. O aplicativo não deve ser considerado um agendador operacional antes de validar o executor na hospedagem e realizar um teste real futuro, autorizado pelo proprietário, com o navegador fechado.
