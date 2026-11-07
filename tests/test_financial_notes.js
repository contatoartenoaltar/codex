const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function app() {
  const nodes = new Map();
  const document = {querySelectorAll() { return []; }, querySelector(selector) {
    if (!nodes.has(selector)) nodes.set(selector, {dataset: {}, showModal() {}});
    return nodes.get(selector);
  }};
  const DashboardChart = {render() { return '<section data-test-chart></section>'; }, bind() {}};
  const context = vm.createContext({document, Intl, DashboardChart});
  const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
  // Carrega as funções reais da interface sem iniciar rede ou eventos do site.
  vm.runInContext(source.slice(0, source.indexOf("\ndocument.addEventListener('click'")), context);
  vm.runInContext(`state = {business_date: '2026-10-31', transactions: [], orders: [], inventory: []}`, context);
  return {context, nodes};
}

test('visão geral mantém somente o card oficial Em caixa no gráfico', () => {
  const {context} = app();
  const html = vm.runInContext('dashboard()', context);
  assert.ok(html.includes('data-test-chart'));
  assert.ok(html.includes('dashboard-stats'));
  assert.ok(!html.includes('Saldo em caixa'));
});

test('novo lançamento mantém os campos existentes e oferece observações opcionais', () => {
  const {context, nodes} = app();
  vm.runInContext("modal('transactions')", context);
  const html = nodes.get('#fields').innerHTML;
  for (const name of ['description', 'kind', 'amount', 'date']) {
    assert.ok(html.includes(`name="${name}"`));
  }
  const textarea = html.match(/<textarea\b[^>]*name="notes"[^>]*>/)[0];
  assert.ok(textarea.includes('maxlength="3000"'));
  assert.ok(!textarea.includes('required'));
  assert.ok(html.includes('Observações (opcional)'));
  assert.ok(html.includes('<option value="investment">Investimento</option>'));
});

test('financeiro mostra observações como texto seguro e mantém registros sem observações', () => {
  const {context} = app();
  vm.runInContext(`state.transactions = [
    {id: 1, date: '2026-10-31', description: 'Recebimento', kind: 'income', amount: 12000,
     notes: '<img src=x onerror=alert(1)> & detalhes\\nSegunda linha'},
    {id: 2, date: '2026-10-31', description: 'Papel', kind: 'expense', amount: 2000}
  ]`, context);
  const html = vm.runInContext('finance()', context);
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt; &amp; detalhes\nSegunda linha'));
  assert.ok(!html.includes('<img src=x'));
  assert.equal((html.match(/<summary>Observações<\/summary>/g) || []).length, 1);
  assert.ok(html.includes('Recebimento'));
  assert.ok(html.includes('Papel'));
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(stats())', context)),
    {income: 12000, expense: 2000, investment: 0, balance: 10000, active: 0, low: 0});
  assert.equal((html.match(/data-edit-transaction=/g) || []).length, 1);
  assert.ok(html.includes('data-edit-transaction="2"'));
});

test('edição de despesa preenche o formulário e preserva os textos com segurança', () => {
  const {context, nodes} = app();
  vm.runInContext(`state.transactions = [{
    id: 8, date: '2026-10-30', description: 'Papel & tinta', kind: 'expense', amount: 6543,
    notes: '<corrigir> & Fornecedor'
  }]`, context);
  vm.runInContext("modal('transactions-edit', 8)", context);
  const html = nodes.get('#fields').innerHTML;
  assert.equal(nodes.get('#form-title').textContent, 'Editar despesa');
  assert.ok(html.includes('value="Papel &amp; tinta"'));
  assert.ok(html.includes('value="65.43"'));
  assert.ok(html.includes('value="2026-10-30"'));
  assert.ok(html.includes('&lt;corrigir&gt; &amp; Fornecedor'));
  assert.ok(html.includes('continuará classificado como Despesa'));
});

test('pedido existente oferece edição com os valores atuais', () => {
  const {context, nodes} = app();
  vm.runInContext(`state.products = [
    {id: 'envelopes', name: 'Envelopes personalizados'},
    {id: 'calendarios', name: 'Calendários personalizados'}
  ]; state.stages = ['Novo']; state.orders = [{
    id: 7, customer: 'Igreja & Missão', product: 'Envelopes personalizados',
    quantity: 200, total: 14900, status: 'Novo', notes: '<revisar>', transaction_id: 3
  }]; state.transactions = [{id: 3, date: '2026-10-31', kind: 'income', amount: 14900, order_id: 7}]`, context);
  const list = vm.runInContext('orders()', context);
  assert.ok(list.includes('data-edit-order="7"'));
  assert.ok(list.includes('data-delete="orders" data-id="7"'));
  assert.ok(list.includes('aria-label="Excluir pedido 7"'));
  vm.runInContext("modal('orders-edit', 7)", context);
  const html = nodes.get('#fields').innerHTML;
  assert.ok(html.includes('value="Igreja &amp; Missão"'));
  assert.ok(html.includes('<option value="envelopes" selected>'));
  assert.ok(html.includes('value="200"'));
  assert.ok(html.includes('value="149.00"'));
  assert.ok(html.includes('&lt;revisar&gt;'));
  assert.ok(html.includes('receita vinculada serão corrigidos junto com o pedido'));
});

test('financeiro filtra cartões e lançamentos pelo período escolhido', () => {
  const {context} = app();
  vm.runInContext(`state.transactions = [
    {id: 1, date: '2025-12-31', description: 'Ano anterior', kind: 'income', amount: 100},
    {id: 2, date: '2026-01-10', description: 'Receita anual', kind: 'income', amount: 1000},
    {id: 3, date: '2026-09-30', description: 'Mês anterior', kind: 'expense', amount: 200},
    {id: 4, date: '2026-10-01', description: 'Início do mês', kind: 'income', amount: 3000},
    {id: 5, date: '2026-10-24', description: 'Antes de sete dias', kind: 'expense', amount: 400},
    {id: 6, date: '2026-10-25', description: 'Dentro de sete dias', kind: 'investment', amount: 500},
    {id: 7, date: '2026-10-31', description: 'Hoje', kind: 'income', amount: 6000}
  ]`, context);

  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(financeRows().map(t=>t.id))', context)), [4,5,6,7]);
  let html = vm.runInContext('finance()', context);
  assert.ok(html.includes('Início do mês'));
  assert.ok(!html.includes('Mês anterior'));
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(stats(financeRows()))', context)),
    {income: 9000, expense: 900, investment: 500, balance: 8100, active: 0, low: 0});

  vm.runInContext("financePeriod = '7'", context);
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(financeRows().map(t=>t.id))', context)), [6,7]);
  html = vm.runInContext('finance()', context);
  assert.ok(html.includes('Dentro de sete dias'));
  assert.ok(!html.includes('Antes de sete dias'));

  vm.runInContext("financePeriod = 'year'", context);
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(financeRows().map(t=>t.id))', context)), [2,3,4,5,6,7]);
  html = vm.runInContext('finance()', context);
  assert.ok(html.includes('Receita anual'));
  assert.ok(!html.includes('Ano anterior'));
});

test('financeiro filtra lançamentos por receita, despesa e investimento sem alterar os totais do período', () => {
  const {context} = app();
  vm.runInContext(`state.transactions = [
    {id: 1, date: '2026-10-31', description: 'Venda', kind: 'income', amount: 10000},
    {id: 2, date: '2026-10-31', description: 'Papel', kind: 'expense', amount: 2000},
    {id: 3, date: '2026-10-31', description: 'Impressora', kind: 'investment', amount: 3000}
  ]`, context);

  let html = vm.runInContext('finance()', context);
  assert.ok(html.includes('Todos os tipos'));
  assert.ok(html.includes('Venda'));
  assert.ok(html.includes('Papel'));
  assert.ok(html.includes('Impressora'));

  vm.runInContext("financeKind = 'income'", context);
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(financeRows().map(t=>t.id))', context)), [1]);
  html = vm.runInContext('finance()', context);
  assert.ok(html.includes('Venda'));
  assert.ok(!html.includes('Papel'));
  assert.ok(!html.includes('Impressora'));
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(stats(periodTransactions(financePeriod)))', context)),
    {income: 10000, expense: 5000, investment: 3000, balance: 5000, active: 0, low: 0});

  vm.runInContext("financeKind = 'expense'", context);
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(financeRows().map(t=>t.id))', context)), [2]);

  vm.runInContext("financeKind = 'investment'", context);
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(financeRows().map(t=>t.id))', context)), [3]);
});

test('pedidos calcula vendas menos despesas e exclui investimentos do lucro', () => {
  const {context} = app();
  vm.runInContext(`state.stages = ['Novo']; state.orders = [
    {id: 1, customer: 'Venda antiga', product: 'Envelopes', quantity: 100, total: 1000, status: 'Novo', notes: '', transaction_id: 11},
    {id: 2, customer: 'Venda anual', product: 'Envelopes', quantity: 100, total: 2000, status: 'Novo', notes: '', transaction_id: 12},
    {id: 3, customer: 'Venda mensal', product: 'Envelopes', quantity: 100, total: 3000, status: 'Novo', notes: '', transaction_id: 13},
    {id: 4, customer: 'Venda recente', product: 'Envelopes', quantity: 100, total: 4000, status: 'Novo', notes: '', transaction_id: 14},
    {id: 5, customer: 'Pedido pendente', product: 'Envelopes', quantity: 100, total: 5000, status: 'Novo', notes: '', transaction_id: null}
  ]; state.transactions = [
    {id: 11, date: '2025-12-31', kind: 'income', amount: 1000, order_id: 1},
    {id: 12, date: '2026-01-10', kind: 'income', amount: 2000, order_id: 2},
    {id: 13, date: '2026-10-01', kind: 'income', amount: 3000, order_id: 3},
    {id: 14, date: '2026-10-30', kind: 'income', amount: 4000, order_id: 4},
    {id: 15, date: '2026-10-30', kind: 'income', amount: 9000, order_id: null},
    {id: 16, date: '2026-10-30', kind: 'expense', amount: 1500, order_id: null},
    {id: 17, date: '2026-10-30', kind: 'investment', amount: 8000, order_id: null}
  ]`, context);

  assert.deepEqual(JSON.parse(vm.runInContext(`JSON.stringify((()=>{const r=orderReport();return {sales:r.sales,expenses:r.expenses,profit:r.profit,orders:r.orders.map(o=>o.id)}})())`, context)),
    {sales: 7000, expenses: 1500, profit: 5500, orders: [3,4,5]});
  let html = vm.runInContext('orders()', context);
  assert.ok(html.includes('Investimentos não entram nesse cálculo'));
  assert.ok(html.includes('Venda mensal'));
  assert.ok(html.includes('Pedido pendente'));
  assert.ok(!html.includes('Venda anual'));

  vm.runInContext("orderPeriod = '7'", context);
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(orderReport().orders.map(o=>o.id))', context)), [4,5]);
  html = vm.runInContext('orders()', context);
  assert.ok(html.includes('Venda recente'));
  assert.ok(!html.includes('Venda mensal'));

  vm.runInContext("orderPeriod = 'year'", context);
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(orderReport().orders.map(o=>o.id))', context)), [2,3,4,5]);
});
