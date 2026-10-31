/* Gráfico local: os recebimentos de pedidos são uma parte das entradas. */
(function (root) {
 'use strict';
 const periods = {'7':'Últimos 7 dias','30':'Últimos 30 dias',year:'Este ano'};
 const colors = {sales:'#b68a32',income:'#1686a0',expense:'#c7427e'};
 const labels = {sales:'Vendas',income:'Entradas',expense:'Saídas'};
 const money = value => new Intl.NumberFormat('pt-BR',{style:'currency',currency:'BRL'}).format(value/100);
 const escape = text => String(text).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const iso = day => day.toISOString().slice(0,10);
 const parse = day => {
  if(typeof day!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(day))return null;
  const date=new Date(day+'T00:00:00Z');
  return Number.isFinite(date.getTime())&&iso(date)===day?date:null;
 };
 const formatDay = (day,year=false) => new Intl.DateTimeFormat('pt-BR',{day:'2-digit',month:'2-digit',...(year?{year:'numeric'}:{}),timeZone:'UTC'}).format(parse(day));

 function series(transactions,period,today){
  const end=parse(today);
  if(!end)throw Error('Data de referência indisponível. Atualize o sistema.');
  if(!Object.hasOwn(periods,period))period='30';
  const monthly=period==='year',start=new Date(end),buckets=[];
  if(monthly)start.setUTCMonth(0,1);else start.setUTCDate(start.getUTCDate()-Number(period)+1);
  for(const date=new Date(start);date<=end;monthly?date.setUTCMonth(date.getUTCMonth()+1):date.setUTCDate(date.getUTCDate()+1)){
   const day=iso(date),key=monthly?day.slice(0,7):day;
   buckets.push({key,label:monthly?new Intl.DateTimeFormat('pt-BR',{month:'short',timeZone:'UTC'}).format(date).replace('.',''):formatDay(day),
    title:monthly?new Intl.DateTimeFormat('pt-BR',{month:'long',year:'numeric',timeZone:'UTC'}).format(date):new Intl.DateTimeFormat('pt-BR',{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(date),
    sales:0,income:0,expense:0});
  }
  const lookup=new Map(buckets.map(bucket=>[bucket.key,bucket]));
  const first=iso(start);
  let count=0;
  for(const transaction of transactions){
   if(!parse(transaction.date)||transaction.date<first||transaction.date>today||!['income','expense'].includes(transaction.kind)||!Number.isSafeInteger(transaction.amount)||transaction.amount<0)continue;
   const bucket=lookup.get(monthly?transaction.date.slice(0,7):transaction.date);
   if(!bucket)continue;
   bucket[transaction.kind]+=transaction.amount;
   if(transaction.kind==='income'&&Number.isSafeInteger(transaction.order_id)&&transaction.order_id>0)bucket.sales+=transaction.amount;
   count++;
  }
  const totals=buckets.reduce((sum,bucket)=>({sales:sum.sales+bucket.sales,income:sum.income+bucket.income,expense:sum.expense+bucket.expense}),{sales:0,income:0,expense:0});
  return {period,monthly,buckets,totals,count,first,last:today,balance:totals.income-totals.expense};
 }

 function chart(model){
  const highest=Math.max(100,...model.buckets.flatMap(b=>[b.sales,b.income,b.expense]));
  const rough=highest/4,power=10**Math.floor(Math.log10(rough));
  const step=[1,2,5,10].map(n=>n*power).find(n=>n>=rough);
  const maximum=Math.ceil(highest/step)*step;
  const grid=[];
  for(let value=0;value<=maximum;value+=step){
   const tick=new Intl.NumberFormat('pt-BR',{notation:'compact',maximumFractionDigits:1}).format(value/100);
   grid.push(`<div class="chart-grid" style="bottom:${value/maximum*100}%"><span>R$ ${escape(tick)}</span></div>`);
  }
  const labelEvery=Math.max(1,Math.ceil(model.buckets.length/6));
  const bars=model.buckets.map((bucket,index)=>{
   const info=`${bucket.title}. Vendas: ${money(bucket.sales)}. Entradas: ${money(bucket.income)}. Saídas: ${money(bucket.expense)}.`;
   const showLabel=(index%labelEvery===0&&index<=model.buckets.length-1-labelEvery/2)||index===model.buckets.length-1;
   return `<div class="chart-column" data-chart-index="${index}" tabindex="${index===0?'0':'-1'}" role="img" aria-label="${escape(info)}"><div class="chart-bars">${Object.keys(colors).map(key=>`<span style="height:${bucket[key]/maximum*100}%;background:${colors[key]}"></span>`).join('')}</div>${showLabel?`<span class="chart-axis">${escape(bucket.label)}</span>`:''}</div>`;
  }).join('');
  return `<div class="business-chart-canvas" role="group" aria-label="Vendas, entradas e saídas em reais" aria-describedby="chart-description"><div class="chart-coordinate">${grid.join('')}<div class="chart-columns" style="grid-template-columns:repeat(${model.buckets.length},minmax(0,1fr))">${bars}</div></div></div>`;
 }

 function render(transactions,period,today){
  const model=series(transactions,period,today);
  const totalCards=Object.keys(colors).map(key=>`<div class="chart-total" style="--series-color:${colors[key]}"><span><i aria-hidden="true"></i>${labels[key]}</span><strong>${money(model.totals[key])}</strong><small>${{sales:'Recebimentos de pedidos',income:'Todas as receitas',expense:'Despesas registradas'}[key]}</small></div>`).join('');
  return `<section class="card business-chart-card" aria-labelledby="business-chart-title"><div class="business-chart-head"><div><span class="eyebrow">SEU NEGÓCIO EM NÚMEROS</span><h2 id="business-chart-title">Vendas, entradas e saídas</h2><p>De ${formatDay(model.first,model.first.slice(0,4)!==model.last.slice(0,4))} a ${formatDay(model.last,true)}</p></div><label class="chart-period" for="chart-period">Período<select id="chart-period">${Object.entries(periods).map(([value,label])=>`<option value="${value}" ${model.period===value?'selected':''}>${label}</option>`).join('')}</select></label></div><div class="chart-totals">${totalCards}</div><div class="business-chart-plot">${chart(model)}${model.count?'':`<div class="chart-empty"><strong>Nenhuma movimentação neste período</strong><span>Seu gráfico aparece conforme você registra pedidos e lançamentos.</span></div>`}<div class="chart-tooltip" role="status" hidden></div></div><div class="chart-foot"><p id="chart-description">Vendas fazem parte das entradas. Valores pela data do recebimento.<span class="chart-keyboard-hint"> Use as setas para consultar as datas no gráfico.</span></p><div class="chart-result ${model.balance<0?'negative':''}"><span>Resultado do período</span><strong>${money(model.balance)}</strong></div></div><details class="chart-data"><summary>Ver valores por ${model.monthly?'mês':'dia'}</summary><div class="table-wrap"><table><caption class="sr-only">Valores do gráfico em reais</caption><thead><tr><th scope="col">${model.monthly?'MÊS':'DIA'}</th><th scope="col">VENDAS</th><th scope="col">ENTRADAS</th><th scope="col">SAÍDAS</th></tr></thead><tbody>${model.buckets.map(b=>`<tr><th scope="row">${escape(b.title)}</th><td>${money(b.sales)}</td><td>${money(b.income)}</td><td>${money(b.expense)}</td></tr>`).join('')}</tbody></table></div></details></section>`;
 }

 function bind(root,transactions,period,today,onChange){
  const select=root.querySelector('#chart-period'),plot=root.querySelector('.business-chart-plot');
  if(!select||!plot)return;
  select.addEventListener('change',()=>onChange(select.value));
  const model=series(transactions,period,today),tooltip=plot.querySelector('.chart-tooltip');
  const groups=Array.from(plot.querySelectorAll('[data-chart-index]'));
  const hide=()=>{tooltip.hidden=true};
  function show(group,event){
   const bucket=model.buckets[Number(group.dataset.chartIndex)];
   if(!bucket)return;
   tooltip.innerHTML=`<b>${escape(bucket.title)}</b>${Object.keys(colors).map(key=>`<span><i style="background:${colors[key]}"></i>${labels[key]}<strong>${money(bucket[key])}</strong></span>`).join('')}`;
   tooltip.hidden=false;
   const box=plot.getBoundingClientRect(),target=group.getBoundingClientRect();
   const x=(event?.clientX??(target.left+target.width/2))-box.left;
   const y=(event?.clientY??target.top)-box.top;
   tooltip.style.left=Math.max(4,Math.min(box.width-tooltip.offsetWidth-4,x-tooltip.offsetWidth/2))+'px';
   tooltip.style.top=Math.max(4,Math.min(box.height-tooltip.offsetHeight-4,y-tooltip.offsetHeight-14))+'px';
  }
  plot.addEventListener('pointermove',event=>{const group=event.target.closest('[data-chart-index]');if(group)show(group,event);else hide()});
  plot.addEventListener('pointerleave',hide);
  plot.addEventListener('click',event=>{const group=event.target.closest('[data-chart-index]');if(group)show(group,event);else hide()});
  plot.addEventListener('focusin',event=>{const group=event.target.closest('[data-chart-index]');if(group)show(group)});
  plot.addEventListener('focusout',hide);
  plot.addEventListener('keydown',event=>{
   if(event.key==='Escape'){hide();return}
   const group=event.target.closest('[data-chart-index]');
   if(!group||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
   event.preventDefault();
   const index=Number(group.dataset.chartIndex),next=event.key==='Home'?0:event.key==='End'?groups.length-1:Math.max(0,Math.min(groups.length-1,index+(event.key==='ArrowLeft'?-1:1)));
   groups.forEach((g,i)=>g.setAttribute('tabindex',i===next?'0':'-1'));
   groups[next].focus();
  });
 }
 const api={series,render,bind};
 if(typeof module==='object'&&module.exports)module.exports=api;
 else root.DashboardChart=api;
})(typeof globalThis!=='undefined'?globalThis:this);
