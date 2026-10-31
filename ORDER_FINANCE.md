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

- O valor integral é considerado recebido no cadastro, conforme a regra
  solicitada. Parcelas, sinal e contas a receber não estão implementados.
- A receita identifica número do pedido, cliente e produto. Sua data usa São
  Paulo, mesmo se o servidor estiver em UTC.
- Cancelar ou reabrir não presume devolução ao cliente. Um reembolso efetivo
  deve ser registrado no Financeiro como despesa.
- Não é possível excluir um pedido enquanto existir receita vinculada. Para
  corrigir um cadastro errado, excluir primeiro seu lançamento no Financeiro e
  depois o pedido. Isso impede que outro cliente herde o vínculo por reutilização
  do ID. Excluir a receita é uma correção, não um estorno bancário.
- Apagar uma receita não a recria ao recarregar o site ou mudar a etapa. O
  recebimento só é recriado se o proprietário usar **Lançar receita** novamente.

Testes cobrem cadastro, persistência, mudança de etapas, receita retroativa,
concorrência, falha com rollback, atualização de banco antigo, exclusão,
autenticação e data de São Paulo. Nada disso movimenta conta bancária.

Validação local: **191 testes passaram** na suíte completa. Sintaxe JavaScript e
renderização das situações de receita pendente/lançada e dos formulários também
foram conferidas. Falta validação pelo proprietário na hospedagem.
