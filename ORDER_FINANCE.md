# Pedidos e financeiro

Regra definida pelo proprietário em 30/10/2026: **um pedido novo já representa
pagamento recebido**. O cadastro grava o pedido na etapa **Novo** e lança o
total como receita, na data de São Paulo. A etapa passa a acompanhar apenas a
produção; concluir, reabrir ou cancelar não gera outra receita nem estorna dinheiro.
Pedidos com total zero não geram lançamento de valor zero.

Pedido e receita são gravados na mesma transação SQLite: uma falha não deixa
pedido salvo sem a receita correspondente. Um vínculo único no banco impede
duas receitas para o mesmo pedido, inclusive em solicitações simultâneas de
lançamento. O salvamento da interface fica desabilitado durante o envio.

## Aplicação na hospedagem

O código preparado e os testes locais não comprovam a atualização da hospedagem.
No Bash do PythonAnywhere:

```bash
cd /home/artenoaltar/arte-no-altar
git pull --ff-only origin main
```

Depois, **Web → Reload** e recarregar o sistema no navegador (Ctrl+F5).
O início da aplicação acrescenta apenas o vínculo do pedido aos lançamentos,
sem apagar dados nem criar receitas retroativas automaticamente.

## Pedido existente sem receita

Em **Pedidos**, clicar em **Lançar receita**, conferir o total e informar a data
real do recebimento. A receita usa o valor salvo no pedido e aparece no
Financeiro e nos totais da Visão geral. A coluna Financeiro mostra **Receita
lançada**. O Financeiro também avisa quando há pedidos antigos sem vínculo.
Não repetir recebimentos já lançados manualmente: registros anteriores não
possuem vínculo e o sistema não tenta adivinhar se uma entrada é daquele pedido.

O pedido já concluído relatado pelo proprietário precisa desse lançamento
uma vez, sem recadastrar o cliente ou alterar a etapa. Também é possível lançar
receita de pedido antigo na etapa Novo ou Em produção; pedidos cancelados não
aceitam novo recebimento.

## Correções e limites

- O botão de edição permite corrigir cliente, produto, quantidade, total e
  observações. Se o pedido possui receita vinculada, o valor e a descrição do
  mesmo lançamento são atualizados na mesma transação, preservando sua data e
  impedindo duplicação.
- O botão de exclusão pede confirmação. Se houver receita vinculada, a mensagem
  informa isso e o pedido e sua receita são apagados juntos, na mesma transação.
- O valor integral é considerado recebido no cadastro, conforme a regra
  solicitada. Parcelas, sinal e contas a receber não estão implementados.
- A receita identifica número do pedido, cliente e produto. Sua data usa São
  Paulo, mesmo se o servidor estiver em UTC.
- Cancelar ou reabrir não presume devolução ao cliente. Um reembolso efetivo
  deve ser registrado no Financeiro como despesa.
- A exclusão conjunta impede que outro cliente herde uma receita antiga por
  reutilização do ID. Excluir a receita é uma correção, não um estorno bancário.
- Apagar uma receita não a recria ao recarregar o site ou mudar a etapa. O
  recebimento só é recriado se o proprietário usar **Lançar receita** novamente.

Testes cobrem cadastro, persistência, mudança de etapas, receita retroativa,
concorrência, falha com rollback, atualização de banco antigo, exclusão,
autenticação e data de São Paulo. Nada disso movimenta conta bancária.

Validação local: a suíte completa e os testes de interface cobrem também a edição
atômica do pedido e da receita vinculada. Falta validação pelo proprietário na
hospedagem.
