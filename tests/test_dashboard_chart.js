const assert=require('node:assert/strict');
const {test}=require('node:test');
const {series,render}=require('../static/dashboard-chart.js');

test('pedido recebido integra as entradas sem somar duas vezes no resultado',()=>{
 const rows=[
  {date:'2026-10-30',kind:'income',amount:39900,order_id:1},
  {date:'2026-10-30',kind:'income',amount:5000,order_id:null},
  {date:'2026-10-30',kind:'expense',amount:10000,order_id:null}
 ];
 const model=series(rows,'7','2026-10-30');
 assert.deepEqual(model.totals,{sales:39900,income:44900,expense:10000});
 assert.equal(model.balance,34900);
 assert.deepEqual(model.buckets.at(-1),{...model.buckets.at(-1),sales:39900,income:44900,expense:10000});
});

test('sete dias incluem o dia de referência e preenchem dias sem movimento',()=>{
 const model=series([
  {date:'2026-10-23',kind:'income',amount:9900},
  {date:'2026-10-24',kind:'income',amount:14900},
  {date:'2026-10-30',kind:'expense',amount:1000},
  {date:'2026-10-31',kind:'income',amount:20000}
 ],'7','2026-10-30');
 assert.equal(model.first,'2026-10-24');
 assert.equal(model.buckets.length,7);
 assert.equal(model.buckets[0].income,14900);
 assert.equal(model.buckets[1].income,0);
 assert.equal(model.buckets.at(-1).expense,1000);
 assert.equal(model.totals.income,14900);
});

test('trinta dias atravessam mês e ano sem depender do fuso do navegador',()=>{
 const model=series([{date:'2025-12-31',kind:'income',amount:9900,order_id:3}],'30','2026-01-03');
 assert.equal(model.first,'2025-12-05');
 assert.equal(model.buckets.length,30);
 assert.equal(model.buckets.find(b=>b.key==='2025-12-31').sales,9900);
 assert.match(render([],'30','2026-01-03'),/05\/12\/2025 a 03\/01\/2026/);
});

test('ano agrupa por mês e exclui ano anterior e lançamentos futuros',()=>{
 const model=series([
  {date:'2025-12-31',kind:'income',amount:99999},
  {date:'2026-01-01',kind:'income',amount:9900,order_id:2},
  {date:'2026-01-31',kind:'income',amount:14900,order_id:3},
  {date:'2026-02-05',kind:'expense',amount:2000},
  {date:'2026-03-01',kind:'income',amount:99999}
 ],'year','2026-02-28');
 assert.deepEqual(model.buckets.map(b=>b.key),['2026-01','2026-02']);
 assert.equal(model.buckets[0].sales,24800);
 assert.equal(model.buckets[1].expense,2000);
 assert.equal(model.balance,22800);
});

test('ano bissexto mantém o dia 29 e datas inválidas não entram no gráfico',()=>{
 const model=series([
  {date:'2024-02-29',kind:'income',amount:9900},
  {date:'2024-02-30',kind:'income',amount:99999}
 ],'7','2024-03-01');
 assert.equal(model.buckets.find(b=>b.key==='2024-02-29').income,9900);
 assert.equal(model.totals.income,9900);
});

test('movimentações manuais sem vínculo não são inventadas como vendas',()=>{
 const model=series([{date:'2026-10-30',kind:'income',amount:22900}],'7','2026-10-30');
 assert.equal(model.totals.sales,0);
 assert.equal(model.totals.income,22900);
 assert.equal(model.balance,22900);
});

test('somente despesas mostra resultado negativo e dados vazios não geram valores fictícios',()=>{
 const rows=[{date:'2026-10-30',kind:'expense',amount:3500}];
 assert.equal(series(rows,'30','2026-10-30').balance,-3500);
 assert.match(render(rows,'30','2026-10-30'),/chart-result negative/);
 const empty=series([],'30','2026-10-30');
 assert.deepEqual(empty.totals,{sales:0,income:0,expense:0});
 const html=render([],'30','2026-10-30');
 assert.match(html,/Nenhuma movimentação neste período/);
 assert.doesNotMatch(html,/NaN|Infinity/);
});

test('dados inválidos são descartados e a agregação preserva os registros originais',()=>{
 const rows=[{date:'2026-10-30',kind:'income',amount:9900,order_id:1},
  {date:'2026-10-30',kind:'income',amount:-1},
  {date:'2026-10-30',kind:'income',amount:'9900'},
  {date:'2026-10-30',kind:'income',amount:NaN},
  {date:'2026-10-30',kind:'invalid',amount:9900},
  {date:'30/10/2026',kind:'income',amount:9900}];
 rows.forEach(Object.freeze);Object.freeze(rows);
 const model=series(rows,'30','2026-10-30');
 assert.equal(model.totals.income,9900);
 assert.equal(model.count,1);
 assert.equal(rows.length,6);
});

test('valores grandes continuam finitos e centavos são preservados',()=>{
 const html=render([{date:'2026-10-30',kind:'income',amount:1000000000000,order_id:1}],'year','2026-10-30');
 assert.doesNotMatch(html,/NaN|Infinity|height:-/);
 const model=series([{date:'2026-10-30',kind:'income',amount:101},{date:'2026-10-30',kind:'expense',amount:99}],'7','2026-10-30');
 assert.equal(model.balance,2);
});

test('período inválido usa 30 dias e data de referência inválida exibe erro claro',()=>{
 assert.equal(series([],'invalid','2026-10-30').buckets.length,30);
 assert.throws(()=>series([],'7','2026-02-30'),/Data de referência indisponível/);
 assert.throws(()=>series([],'7','<script>'),/Data de referência indisponível/);
});
