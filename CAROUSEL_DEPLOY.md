# Implantação dos carrosséis automáticos

Esta rotina usa o mesmo acionador externo já adotado no plano gratuito do
PythonAnywhere. Ela fica desativada até o comando explícito de ativação.

## 1. Atualizar e preparar

No Bash Console do PythonAnywhere:

```bash
cd /home/artenoaltar/arte-no-altar
git pull --ff-only origin main
python3.12 -m unittest tests.test_carousel_posts
mkdir -m 700 -p /home/artenoaltar/arte-no-altar/.local/carousels-live
python3.12 -m carousel_posts.queue \
  --directory /home/artenoaltar/arte-no-altar/.local/carousels-live \
  initialize
python3.12 -m carousel_posts.http \
  --directory /home/artenoaltar/arte-no-altar/.local/carousels-live \
  --origin https://artenoaltar.pythonanywhere.com
```

O último comando cria `carousel-trigger.key` com permissão privada. Não exibir a
chave em capturas de tela ou mensagens.

## 2. Adicionar ao WSGI

Defina os diretórios antes dos imports de aplicações:

```python
os.environ["ARTENOALTAR_CAROUSELS_DIR"] = "/home/artenoaltar/arte-no-altar/.local/carousels-live"
os.environ["ARTENOALTAR_CAROUSELS_META_DIR"] = "/home/artenoaltar/arte-no-altar/.local"
```

Encaminhe `/internal/carousels/tick` para
`carousel_posts.wsgi.application`, preservando as rotas atuais do site e de
Stories. Faça backup do WSGI e valide sua sintaxe antes de substituir o arquivo.

## 3. Cron externo

Crie uma chamada `POST`, sem corpo, a cada minuto para:

```text
https://artenoaltar.pythonanywhere.com/internal/carousels/tick
```

Adicione o cabeçalho `Authorization: Bearer <conteúdo de carousel-trigger.key>`.
O endpoint executa no máximo uma etapa remota por chamada.

## 4. Ativação única

Somente depois de recarregar o Web App, testar autenticação e confirmar resposta
`{"status":"disabled"}`:

```bash
cd /home/artenoaltar/arte-no-altar
python3.12 -m carousel_posts.queue \
  --directory /home/artenoaltar/arte-no-altar/.local/carousels-live \
  enable --account 17841436823298466 --confirm
```

O comando cria automaticamente as próximas três publicações de segunda, quarta
e sexta, às 12h, e não exige aprovação individual. Consulte sem alterar:

```bash
python3.12 -m carousel_posts.queue \
  --directory /home/artenoaltar/arte-no-altar/.local/carousels-live \
  status
```

Para interromper novas operações imediatamente:

```bash
python3.12 -m carousel_posts.queue \
  --directory /home/artenoaltar/arte-no-altar/.local/carousels-live \
  disable
```
