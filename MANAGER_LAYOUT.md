# Atualização visual do manager

O layout usa o menu branco e a referência aprovada em
`design_assets/manager/approved-layout.png`, com a última logo completa fornecida
pelo proprietário. A logo original está em `static/brand-logo.png`; Manrope e sua
licença estão em `static/manrope.ttf` e `static/manrope-OFL.txt`.

As alterações são de apresentação. Os filtros, séries, cálculos, cadastros,
integrações e confirmações existentes foram preservados. As novas rotas Python
servem somente a logo e a fonte. O JavaScript adicional desenha e anima o indicador
das abas; não altera seleção, foco, dados ou chamadas de rede.

## Revisão antes da publicação

A revisão visual está pendente, registrada em `design-qa.md`. Conferir uma prévia
em computador e celular antes de integrar a alteração na branch principal:

- Logo inteira e proporcional sobre o menu branco; textos e ícones legíveis.
- Menu móvel abre/fecha; links, logout e foco continuam acessíveis.
- Visão geral: filtros existentes, valores, tooltip e tabela do gráfico.
- Financeiro, Pedidos, Estoque, Atendimento e Catálogo: conteúdo e formulários.
- Estúdio: abas Agenda/Resultados, filtros, prévias e modais, sem enviar ou
  agendar conteúdo durante a conferência visual.
- Animação do gráfico e indicador das abas; opção de movimento reduzido.
- Ausência de controles cortados, rolagem lateral da página ou erros de console.

## Publicação após revisão

Depois de aprovar a prévia e integrar a alteração na `main` do GitHub, executar no
console Bash da conta existente do PythonAnywhere:

```bash
cd /home/artenoaltar/arte-no-altar
git pull --ff-only origin main
```

Na aba **Web**, clicar em **Reload**. Abrir o manager, atualizar a página e
conferir o menu, a logo, os gráficos, as abas e os formulários. Essa atualização
não exige reinstalar dependências, migrar banco ou reconfigurar integrações.

O envio de uma branch ou de um rascunho de revisão ao GitHub não atualiza o site
automaticamente.
