# Pasta de originais do Drive — conexão de leitura

O proprietário confirmou que a pasta cujo link já forneceu contém os modelos à
venda. Quer criação diária fora do chat, com layouts aprovados e escolha aleatória
sem repetir modelos antes de completar o ciclo. Possui um projeto Google Cloud.
O conector do Drive não ficou disponível nesta conversa nem após a menção ao plugin.

## Estado desta entrega

`drive_source.py` implementa configuração e inspeção somente de leitura da pasta
privada e suas subpastas. Usa conta de serviço, escopo `drive.readonly`, autenticação
no endpoint oficial e requisições GET na API do Drive. Não altera o Drive, não faz
download de imagens, não cria artes e não publica ou ativa uma rotina diária.

Os testes locais usam respostas simuladas da API e uma credencial sintética para
verificar o transporte com a biblioteca oficial Google Auth. Não foi acessada a
pasta real: sua autorização na hospedagem e a listagem real continuam pendentes.

## Configuração única no projeto existente do Google Cloud

1. Abra o projeto correto no [Google Cloud](https://console.cloud.google.com/) e
   habilite **Google Drive API** em **APIs e serviços → Biblioteca**. A página
   [Google Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com)
   usa o projeto selecionado no console. Não habilite APIs pagas de geração de IA.
2. Em **IAM e administrador → Contas de serviço**, crie uma conta dedicada, por
   exemplo `arte-no-altar-modelos`. Deixe as permissões do projeto em branco: a
   leitura será concedida na própria pasta do Drive. Não precisa dar acesso a
   outras pastas, financeiro, contas sociais ou ao domínio inteiro.
3. Abra a conta de serviço, aba **Chaves**, e use **Adicionar chave → Criar nova
   chave → JSON**. Guarde o arquivo privado no computador. Não cole seu conteúdo
   no chat, no GitHub ou em formulários do plugin. Se uma política da organização
   impedir criar chaves, pare essa etapa e use um método de identidade aprovado;
   não enfraqueça a política para seguir estas instruções.
4. Copie o e-mail da conta de serviço. Na pasta de modelos do Drive, use
   **Compartilhar**, adicione esse e-mail e escolha **Leitor**. O link geral pode
   continuar restrito. A conta deve acessar somente a pasta de originais autorizada.
5. No painel **Files** autenticado do PythonAnywhere, envie o JSON para
   `/home/artenoaltar/arte-no-altar/.local/drive-service-account.json`. Renomeie se
   necessário. Não crie uma rota estática para `.local` nem para esse arquivo.

## Instalação e teste na hospedagem

Atualize o código e instale dependências com o Python da aplicação. Em uma conta
sem virtualenv configurado na aba Web:

```bash
cd /home/artenoaltar/arte-no-altar
git pull --ff-only origin main
python3.12 -m pip install --user -r requirements.txt
```

Se a instalação usa virtualenv, use seu Python e não `--user`. A geração das artes
ainda não está integrada ao aplicativo; este comando de inspeção não exige mudar
o WSGI, recarregar a Web nem reiniciar o executor existente.

Configure a origem usando o link/ID já fornecido pelo proprietário:

```bash
python3.12 drive_source.py configure --folder ID_DA_PASTA_JA_FORNECIDA
python3.12 drive_source.py inspect
```

O primeiro comando grava configuração local e restringe o JSON de credenciais a
permissão 600. Mostra somente o e-mail não secreto da conta de serviço para conferir
o compartilhamento; não testa o acesso nem mostra chave privada ou token. O segundo
obtém a listagem real e apresenta subpastas, formatos MIME, total de arquivos e
quantidade de imagens (incluindo subpastas). Esse resultado pode ser compartilhado
com o assistente, conferindo antes se os nomes contêm informações privadas.

O conector segue o mesmo diretório privado de `ARTENOALTAR_DB`, ou `.local` por
padrão. A origem fica em `drive-source.json` e o catálogo em `drive-catalog.json`,
ambos privados. A chave de serviço não é incluída no catálogo. Metadados e nomes
dos arquivos são dados, não instruções de execução.

Se houver erro 401/403/404, confira a API ativa, o JSON da conta correta e o
compartilhamento como Leitor. Falhas de rede podem depender dos domínios permitidos
no plano gratuito da hospedagem: são necessários `oauth2.googleapis.com` e
`www.googleapis.com`. Validar na hospedagem; não contratar plano pago ou contornar
restrições de rede automaticamente. O cliente mantém HTTPS, usa o proxy configurado
e recusa redirecionamentos para proteger a credencial.

## Limites e próximo trabalho

- Consulta somente a pasta configurada e suas subpastas, com paginação. Não segue
  atalhos que possam levar a outro local. O resumo informa quantos foram ignorados.
- Impõe limites de respostas, páginas, pastas e arquivos. Uma consulta incompleta
  ou que ultrapasse os limites falha sem substituir o catálogo anterior por uma
  lista parcial. A listagem não é um snapshot transacional contra edições simultâneas
  feitas no Drive durante a consulta.
- Quantidade de imagens não é quantidade de modelos: fotos diferentes do mesmo
  envelope precisam ser agrupadas antes da rotação. A listagem inclui todos os
  formatos encontrados; isso não significa que cada formato já possa ser renderizado.
- Download seletivo, agrupamento dos modelos, sorteio persistente sem reposição,
  layouts aprovados, montagem, legendas, Stories, carrosséis e rotina diária ainda
  precisam de implementação e testes. O catálogo não ativa publicação automática.
- O acesso é de leitura. Guardar artes finais no Drive exigirá destino e autorização
  distintos; esta conexão não concede escrita na pasta de originais.
- Para revogar, retire o compartilhamento da pasta com a conta de serviço e/ou
  revogue sua chave no Google Cloud. Não troque as chaves do MCP ou do cron para isso.
