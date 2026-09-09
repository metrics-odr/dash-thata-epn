# GUIA — Geração diária dos Briefings do Gestor (aba Relatórios)

> Lido pela **Routine diária (23h59 BRT)** do Claude Code que regenera
> `build/relatorios.json`. **Não usa a API paga da Anthropic** — roda na
> assinatura do Claude Code (sem consumir créditos). Toda a matemática vem de
> `build/gerar_relatorios.py`, rodado pelo **GitHub Actions** (não pela
> Routine — o sandbox do agente não alcança o Google Sheets); o Claude só
> **redige os textos**.
>
> **Por que 23h59 e não de manhã:** rodando no fim do dia, o período "hoje"
> é analisado com o dia **quase inteiro** de dados (não só as primeiras horas).
> Por isso a Routine também migra o texto: o que estava em "hoje" (analisado
> ontem à noite, já com o dia completo) vira o novo "ontem"; e escreve um
> "hoje" novo do zero para o dia que acabou de fechar. Ver passo 4.
>
> **Antes de redigir, leia `build/METODO-ODR-ANALISE.md`.** Ele traz o
> método de raciocínio (Método ODR): como identificar o funil, mapear
> dependências entre métricas, achar causa raiz, distinguir sintoma/
> hipótese/evidência e priorizar ações — é genérico e vale para qualquer
> funil. Este guia (`GUIA-RELATORIOS.md`) traz o passo a passo operacional
> da Routine e as particularidades **deste** funil (VSL/tráfego direto):
> métricas específicas, tags de ação e formato do JSON.

## O que a Routine faz (passo a passo)

> **Arquitetura em 2 etapas** (o sandbox do agente não alcança
> `docs.google.com`, só o runner do GitHub Actions alcança — ver CLAUDE.md,
> "problemas conhecidos" #4):
> 1. O workflow `.github/workflows/gerar-relatorios-metrics.yml` roda no
>    GitHub Actions **~9 min antes** (23:50 BRT), busca os CSVs públicos das
>    planilhas (`python build/gerar_relatorios.py`, sem argumentos = busca ao
>    vivo) e commita `build/relatorios_metrics.json` na `main`. **Só números,
>    sem IA.**
> 2. A Routine do Claude Code (23:59 BRT) só precisa dar **pull** na `main`
>    para já ter esse arquivo pronto — não baixa planilha nem roda script.

1. **Checkout / pull** da branch de produção (`main`) já atualizada.
2. **Confira se `build/relatorios_metrics.json` está fresco** (chave
   `gerado_em`/`hoje` do JSON deve ser a data de hoje em BRT). Se estiver
   desatualizado ou ausente (o workflow do passo anterior pode atrasar ou
   falhar):
   - Dispare o workflow manualmente (`gerar-relatorios-metrics.yml`,
     `workflow_dispatch`, branch `main`) via GitHub MCP, aguarde a conclusão
     (normalmente < 2 min) e dê `git pull` de novo.
   - Se mesmo assim não atualizar, **não invente números** — pare e relate o
     problema (não escreva os briefings com dados velhos).
3. `build/relatorios_metrics.json` traz os números de todos os períodos
   (`hoje, ontem, 3d, 7d, 14d, 30d, mes, mespass, todo`) — isso NÃO é texto,
   só matemática (gerada por `build/gerar_relatorios.py`, que reaproveita
   `build.process` — mesma fonte de verdade do site). Cada item de
   `top_anuncios`/`piores_anuncios` traz `nome` (ex. "AD07") **junto com**
   `campanha` e `conjunto` — o nome do anúncio sozinho **não é único**: o
   mesmo `nome` pode aparecer em campanhas diferentes (ver CLAUDE.md, seção
   "Produto principal / atribuição"). **Sempre cite a campanha (e o
   conjunto, quando ajudar) ao lado do nome do anúncio no texto** — nunca
   escreva só "AD07 converteu bem" sem dizer em qual campanha/conjunto.
4. **Migrar hoje → ontem, depois redigir os 9 briefings do zero.**
   - Leia o `build/relatorios.json` **atual** antes de sobrescrever.
   - Copie o `html` que está em `periodos.hoje` para dentro de `periodos.ontem`
     (substitui o `ontem` antigo). Esse texto foi escrito no fim do dia anterior
     com o dia já quase completo, então ele descreve bem o que agora é "ontem".
   - Escreva um **`hoje` inteiramente novo**, do zero, analisando o dia atual
     (agora com dados quase completos) — não reaproveite o texto antigo do `hoje`.
   - **Reescreva também os outros 7 períodos** (`3d, 7d, 14d, 30d, mes, mespass,
     todo`) **do zero**, a partir dos números atuais de `relatorios_metrics.json`.
     Não copie/cole texto de execuções anteriores — releia os dados e redija de
     novo a cada execução, mesmo que a conclusão continue parecida.
   - Siga o **Guia de interpretação** abaixo. Atualize `generated_at` para a
     data/hora BRT atual (`DD/MM/AAAA HH:MM`).
5. **Commit + push** de `build/relatorios.json` na `main`. O deploy automático
   (~30 min) embute o arquivo no site; a aba passa a exibir o texto novo.
6. **Verificação obrigatória** (uma execução anterior falhou nesse ponto sem
   avisar ninguém): depois do push, rode `git log -1 --stat -- build/relatorios.json`
   e confirme que o commit novo aparece com a data de hoje, e confirme `git status`
   limpo. Se qualquer passo (leitura do metrics.json, commit, push) falhar, **não**
   tente workarounds arriscados — pare e relate exatamente em qual passo falhou
   e a mensagem de erro.

> Se algum passo falhar, **não** apague o `relatorios.json` existente — a página
> continua mostrando a última geração válida.

## Guia de interpretação (resumo — funil VSL)

Trate cada métrica como **diagnóstico probabilístico**, nunca como regra
absoluta. **Sempre** leia junto com a etapa anterior e a posterior. Ordem do
funil: `Gasto → Impressões → Cliques → Page Views → Checkouts → Vendas → Faturamento`.

- **CTR** (Cliques/Impressões): interesse do criativo. Baixo *pode ser bom* se
  CAC baixo e ROAS/ConvCHK altos (anúncio qualifica melhor). Só é problema se
  vier junto de CAC alto / ROAS ruim.
- **Connect Rate / CR** (Page Views/Cliques): saúde da ponte anúncio→página.
  Baixo (< ~60%) → investigar **velocidade da página, pixel/CAPI, atribuição
  (iOS/adblock/LGPD)** — mas se CAC e ROAS seguem saudáveis, provavelmente é
  mensuração, não gargalo real.
- **VisCHK** (Checkouts/Page Views): poder de convencimento da VSL/oferta.
  Costuma ser a principal alavanca. Cai naturalmente em escala / público mais
  frio — compare com o ganho de volume antes de chamar de gargalo.
- **ConvCHK** (Vendas/Checkouts): eficiência do checkout. Baixo → checkout/
  pagamento/gateway, OU **atraso natural de compra** (inicia hoje, paga amanhã —
  comum em ticket alto). Leia com Ticket, CAC e o dia seguinte.
- **CAC**: quase sempre **efeito**, não causa. CAC alto → achar a etapa anterior
  que perdeu eficiência. Pode ser saudável se Ticket/LTV subiram e ROAS segue bom.
- **ROAS**: consequência de CAC × Ticket × conversão. Não otimizar isoladamente.
  ROAS menor pode ser aceitável em fase de escala/teste.
- **Ticket**: valor por venda (com order bumps/upsells). Baixo pode ser proposital.

Heurísticas: CTR baixo + ROAS/CAC bons = anúncio qualifica (não mexer). CR baixo
+ ROAS/CAC estáveis = mensuração, não página. VisCHK cai geral = VSL/página/pixel;
cai só num conjunto = público daquele conjunto. Volume baixo = ruído: não corte
estrutura por 1–2 dias ruins; priorize tendência sobre valor absoluto.

## Metas e código de cor (só CAC e ROAS)

Metas em `build/config.py` (`CAC_TARGET`, `ROAS_TARGET`); vêm no metrics JSON em
`metas`. Desempenho: ROAS `valor/meta`; CAC `meta/valor`. Faixas: `<0,70`
vermelho · `0,70–0,99` amarelo · `1,00–1,29` verde · `≥1,30` ciano. **Não repita
o código de cor no texto** — ele já aparece nos cards/tabelas; o briefing
interpreta *por que* e *o que fazer*.

## Tom e conteúdo esperado

Português, **profundo mas sem enrolação**, pouco técnico (explique quando
necessário). Para cada período: o que aconteceu com as campanhas, leitura do
funil (cruzando métricas), e **sugestões de ação** por campanha, conjunto ou
anúncio, usando sempre uma das 4 tags abaixo:

- **`Escalar`** — estrutura clara vencedora (CAC/ROAS bons e volume que já dá
  para confiar): aumentar verba (ex.: "+20% no conjunto Y", "copiar os TOP Ads
  para uma CBO de escala").
- **`Otimizar`** — estrutura que converte mas tem espaço de melhoria óbvio
  antes de escalar ou cortar (ex.: público/criativo/posicionamento a ajustar,
  CAC no limite da meta, ConvCHK baixa com o resto do funil saudável): ação
  concreta de ajuste, não só "aguardar".
- **`Cortar`** — estrutura que só gasta sem retorno e já teve gasto suficiente
  para julgar (ex.: "pausar anúncio X após ~1 CAC sem venda").
- **`Observar`** — dado insuficiente (pouco gasto/tempo de vida) ou oscilação
  normal de tráfego frio: aguardar mais dias antes de agir.

Não invente números que não estejam no metrics JSON. Ao citar um anúncio (ex.
"AD07"), **sempre** diga também a campanha (e o conjunto, se relevante) — o
nome do anúncio sozinho não identifica a estrutura, já que o mesmo nome pode
rodar em campanhas diferentes.

## Formato de `build/relatorios.json`

```json
{
  "generated_at": "DD/MM/AAAA HH:MM",
  "fonte": "Gerado automaticamente a partir dos dados do funil (Meta Ads × Compradores).",
  "periodos": {
    "hoje":    {"html": "<h3>Resumo do período</h3><p>…</p><h3>Leitura do funil</h3><p>…</p><h3>Estruturas — escalar, cortar e observar</h3><ul>…</ul><h3>Recomendações do gestor</h3><p>…</p>"},
    "ontem":   {"html": "…"},
    "3d":      {"html": "…"},
    "7d":      {"html": "…"},
    "14d":     {"html": "…"},
    "30d":     {"html": "…"},
    "mes":     {"html": "…"},
    "mespass": {"html": "…"},
    "todo":    {"html": "…"}
  }
}
```

- As **chaves de período são fixas** (mesmos ids dos botões da topbar). Todas as 9
  devem existir.
- HTML permitido no `html`: `<h3> <p> <ul> <li> <b>` e
  `<span class="tag escala|otimiza|corte|observar">Escalar|Otimizar|Cortar|Observar</span>`
  (chips coloridos de ação — classe CSS em inglês/abreviada, texto visível em
  português. Note que a classe de "Otimizar" é `otimiza`, não `otimizar`).
- Se um período não tiver dados (ex.: `mespass` sem vendas no mês anterior),
  escreva um `html` curto dizendo que não houve investimento/vendas no período.
