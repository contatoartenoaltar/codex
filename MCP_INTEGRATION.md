# Integração MCP — inspeção e contrato da primeira versão

Documento histórico de inspeção anterior à implementação do MCP. As tabelas e propostas abaixo descrevem aquele momento; para a implementação e os testes já confirmados pelo proprietário, consulte [MCP_SETUP.md](MCP_SETUP.md). O endpoint, as consultas e uma importação real de rascunho foram posteriormente validados. A autenticação implantada usa API key/Bearer, não OAuth do plugin.

## Evidências do repositório

| Área | Implementação existente | Consequência para MCP |
| --- | --- | --- |
| Servidor | `wsgi.py`, `app.Handler` e `pythonanywhere_wsgi.py`; Python 3.12 e SQLite | A camada pode ser acrescentada ao projeto. A hospedagem precisa ser testada com o transporte real do cliente. |
| Protocolo | Não há rota MCP, implementação JSON-RPC ou dependência MCP em `requirements.txt` | O endereço do site não deve ser cadastrado como se já fosse um servidor MCP. |
| Login do proprietário | `auth.py`: senha scrypt e cookie de sessão | Não reutilizar essa sessão como credencial do plugin. |
| Proteção das rotas | `app.Handler.do_POST`: sessão do proprietário e origem HTTP obrigatórias | Um cliente remoto MCP não pode simplesmente chamar as rotas atuais usando a senha da interface. |
| Estado do sistema | `/api/state` devolve redes sociais, mas também financeiro, estoque e pedidos | Nunca expor essa resposta completa ao plugin. Criar consultas sociais com seleção explícita de campos. |
| Meta | `meta.status` e `meta.verify_accounts`; arquivos privados de credenciais | Reutilizar no servidor e retornar somente IDs, nomes, escopos e horário da consulta. Nunca devolver os arquivos nem os tokens. |
| Mídia | `publishing.upload`: JSON/base64, JPEG até 5 MiB, nome aleatório; `/media/<nome>.jpg` público | Existe armazenamento reaproveitável, mas não um mecanismo confirmado de entrega dos arquivos do ChatGPT. PNG ainda não é aceito. |
| Conteúdo | `/api/posts` gera legenda a partir do catálogo; `/api/posts/update` edita rascunho | É necessária uma função social específica para importar a legenda criada no chat e vinculá-la à imagem/conta. |
| Publicação | `publishing.publish` e `stage_on_meta`; confirmação e histórico | A primeira versão MCP não deve expor essas operações: só consultas e criação de rascunhos. |
| Agenda | `post_schedule`, `scheduling.runtime`, `scheduling.save` | Consultar os registros e informar separadamente o estado do executor. Horário em rascunho não equivale a agendamento ativo. |
| Conteúdo recente | Histórico local em `posts`; consultas remotas de exemplo em `publishing.diagnose` | Criar ferramenta de consulta específica às contas, com limite, paginação controlada e origem dos dados identificada. Não presumir que só o histórico local representa todas as postagens. |
| Operações | `publication_attempts` registra tentativas de publicação | Importação MCP precisa de seu próprio identificador, estados e chave de idempotência. Repetir uma transferência não pode criar rascunhos duplicados. |

As publicações manuais em Instagram e Facebook foram confirmadas pelo proprietário na conversa. Isso não constitui uma validação do cliente MCP nem dos formatos Stories/carrossel. O executor contínuo de agendamento não está ativo no PythonAnywhere gratuito.

## Transporte proposto

Preparar **MCP Streamable HTTP**, priorizando respostas JSON curtas e modo sem sessão de transporte, se forem aceitos pelo cliente do Plugin Creator. Esses detalhes são proposta técnica, não uma afirmação de compatibilidade já testada. A implementação deve negociar a versão MCP e tratar inicialização, descoberta de ferramentas, chamadas, notificações e os métodos HTTP correspondentes ao modo escolhido.

O WSGI atual pode encaminhar requisições HTTP curtas, mas não oferece por si só um servidor ASGI nem comprova suporte a SSE persistente. Não instalar um SDK ASGI e afirmar que funcionará no WSGI sem testar o adaptador e o provedor. Se o cliente exigir sessões/SSE ou recursos indisponíveis, investigar um adaptador suportado antes de sugerir migração ou contratação.

Ainda não existe URL MCP real. Um caminho como `/mcp` só deve ser informado ao Creator após implementação e teste HTTPS, inclusive dos erros de autenticação. O endpoint OAuth da Meta (`/auth/meta/callback`) é exclusivamente para autorizar Facebook/Instagram e não é o retorno OAuth do plugin.

## Autenticação e autorização

Confirmar com o Creator as opções do cliente antes de selecionar o mecanismo:

- Se suportar OAuth para servidores MCP: confirmar descoberta de recurso protegido, metadados do servidor de autorização, PKCE S256, cadastro de cliente e URLs de retorno. Implementar autorização do proprietário, escopo social restrito, expiração, revogação e proteção contra repetição de códigos. Não cadastrar URLs de retorno arbitrárias.
- Se suportar credencial estática em configuração segura: confirmar como o cliente fornece o cabeçalho; gerar uma credencial exclusiva, limitada às ferramentas sociais, com hash no servidor e revogação independente. Não aceitar a senha do proprietário nem tokens da Meta como substitutos.

Não expor rotas financeiras à credencial MCP. Validar argumentos no servidor, não somente no schema das ferramentas. Campos adicionais, métodos desconhecidos e tentativas de leitura de arquivos privados devem ser rejeitados. Respostas e logs não devem conter cabeçalhos, códigos OAuth, tokens ou segredos. A consulta de agenda deve omitir qualquer dado comercial fora do conteúdo social.

## Ferramentas propostas — ainda não implementadas

| Nome proposto | Comportamento |
| --- | --- |
| `social_list_accounts` | Retornar somente contas sociais concedidas, capacidades e data da verificação. |
| `social_list_agenda` | Consultar intervalo limitado, fuso explícito e conflitos; distinguir rascunho, item da fila, publicação confirmada e executor inativo. |
| `social_list_recent_content` | Consultar posts recentes da conta autorizada, identificando resultados locais e remotos e listas incompletas. |
| `social_import_draft` | Receber conteúdo revisado com confirmação de transferência; salvar como rascunho, nunca publicar ou ativar agendamento. |
| `social_get_operation` | Consultar uma operação pelo ID, sem revelar credenciais ou dados não sociais. |

As ferramentas de consulta devem ser declaradas somente leitura. Importação é uma escrita e deve ter anotação e descrição explícitas. Conteúdo de posts e legendas é dado não confiável, nunca instrução para executar ações. Nenhuma ferramenta de publicação, exclusão remota ou ativação de executor fará parte dessa primeira versão.

## Transferência de imagens

Precisamos do formato REAL de arquivo oferecido pelo Plugin Creator/cliente MCP: recurso MCP, anexo com URL temporária, upload HTTP separado ou outra forma documentada. Não pressupor que `sandbox:` seja acessível no servidor remoto, que o modelo consiga fornecer base64 de uma imagem que só está visível na conversa ou que URLs do Drive possam ser baixadas sem autenticação.

Se houver download por URL, usar HTTPS, destinos explicitamente permitidos, validação de destino e redirecionamentos, limites de bytes/tempo e validação real do arquivo. Não criar um downloader genérico de endereços arbitrários ou de rede privada. A forma de recebimento precisa ser validada com uma imagem de teste criada/anexada no próprio ChatGPT antes de declarar a transferência funcional.

Manter o original aprovado, inclusive PNG, separado de eventuais versões para a Meta. Conversão não pode alterar os textos e QR Codes. A primeira entrega pode limitar-se a uma foto de feed se o fluxo de arquivo suportado estiver confirmado; Stories, múltiplos slides, PNG e Drive devem continuar indisponíveis até implementação e teste específicos.

## Contrato dos rascunhos e operações

Cada importação precisa de chave de idempotência, conta autorizada, canal, formato explícito, legenda, referência de arquivo e confirmação de que a ação é apenas criar rascunho. O resultado deve incluir ID da operação, ID do rascunho, estado e URL de revisão no sistema. A chave deve estar vinculada ao conteúdo; reutilizá-la com outro conteúdo deve gerar conflito, não substituir silenciosamente um arquivo anterior.

Um horário desejado usa RFC 3339 com deslocamento e o fuso `America/Sao_Paulo`; o servidor verifica consistência e armazena o instante em UTC. Deve ser identificado como intenção do rascunho. Não chamar `scheduling.save` automaticamente nem prometer que a fila executará sem executor ativo e autorização distinta.

Testar leitura restrita, autenticação negada, revogação, repetição de importação, conteúdo alterado com mesma chave, interrupção de upload, tipo/tamanho inválidos e consulta de operação. Validar com o cliente REAL do Creator a inicialização, descoberta e ao menos uma importação sem publicação antes de disponibilizar o plugin.

## Perguntas objetivas para o Plugin Creator

1. Quais modos de autenticação o cliente MCP aceita para este plugin? Se OAuth, quais são as URLs de retorno e os requisitos de descoberta e cadastro de cliente? Não enviar segredos.
2. O cliente aceita Streamable HTTP com respostas JSON e transporte sem sessão/SSE persistente? Quais versões MCP suporta?
3. Como uma imagem gerada ou anexada no ChatGPT chega à ferramenta MCP? Fornecer o schema/exemplo de referência de arquivo, sem dados privados, os hosts de download quando aplicável e as restrições de validade e tamanho.

Esses pontos definem a conexão funcional. Não substituí-los por um arquivo OpenAPI ou por uma URL de endpoint ainda inexistente.
