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
  const context = vm.createContext({document, Intl});
  const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
  // Carrega as funções reais da interface sem iniciar rede ou eventos do site.
  vm.runInContext(source.slice(0, source.indexOf("\ndocument.addEventListener('click'")), context);
  vm.runInContext(`state = {business_date: '2026-10-31', transactions: [], orders: [], inventory: []}`, context);
  return {context, nodes};
}

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
});

test('pedido existente oferece edição com os valores atuais', () => {
  const {context, nodes} = app();
  vm.runInContext(`state.products = [
    {id: 'envelopes', name: 'Envelopes personalizados'},
    {id: 'calendarios', name: 'Calendários personalizados'}
  ]; state.stages = ['Novo']; state.orders = [{
    id: 7, customer: 'Igreja & Missão', product: 'Envelopes personalizados',
    quantity: 200, total: 14900, status: 'Novo', notes: '<revisar>', transaction_id: 3
  }]`, context);
  const list = vm.runInContext('orders()', context);
  assert.ok(list.includes('data-edit-order="7"'));
  vm.runInContext("modal('orders-edit', 7)", context);
  const html = nodes.get('#fields').innerHTML;
  assert.ok(html.includes('value="Igreja &amp; Missão"'));
  assert.ok(html.includes('<option value="envelopes" selected>'));
  assert.ok(html.includes('value="200"'));
  assert.ok(html.includes('value="149.00"'));
  assert.ok(html.includes('&lt;revisar&gt;'));
  assert.ok(html.includes('receita vinculada serão corrigidos junto com o pedido'));
});
