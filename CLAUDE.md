# CLAUDE.md — Dashboard de Controle de Tráfego Pago (TEMPLATE)

> Este arquivo é lido automaticamente pelo Claude Code ao abrir o repositório.
> Este é o repositório **TEMPLATE**, genérico — ainda não configurado para
> nenhum cliente. A engine (`build/template.html`, `build/build.py`,
> `ia-worker/worker.js`) é genérica e não deve ser editada por cliente; os
> valores do cliente ficam em **`build/config.py`** (config do funil) e
> **`config.js`** (metadados de publicação no GitHub). Veja também `README.md`
> para a visão geral e o passo a passo completo de publicação.

---

## ✅ CHECKLIST DE NOVO CLIENTE

Ordem para colocar um cliente novo no ar. Cada item aponta o arquivo e o marcador.

1. [ ] **Config do cliente** — copie `build/config.example.py` para
   `build/config.py` e preencha (comentado campo a campo no próprio arquivo):
   - `SPREADSHEET_ID`, `GID_META`, `GID_SALES` (planilha do cliente)
   - `TAX_FACTOR`, `MAIN_PRODUCT_PREFIX`, `COUNT_ALL_AS_PAID` (regras de negócio)
   - `CLIENT_NAME`, `CLIENT_SUB`, `TAX_LABEL`, `MAIN_PRODUCT` (rótulos exibidos)
   - `CAC_TARGET`, `ROAS_TARGET`, `REPORT_BAND_LOW`, `REPORT_BAND_HIGH` (metas da aba Relatórios)
2. [ ] **Este arquivo (`CLAUDE.md`)** — preencher a seção "Fontes de dados" abaixo
   com a planilha real do cliente (abas/colunas) e ajustar a regra de
   atribuição/produto principal se for diferente do padrão do template.
3. [ ] **`README.md`** — preencher: título, nome do produto principal (o resto
   já lê de `config.js`/`build/config.py`).
4. [ ] **`config.js`** (raiz do repo) — copie `config.example.js` para
   `config.js` e preencha `GITHUB_USERNAME`, `GITHUB_REPOSITORY`,
   `PROJECT_NAME`. Depois substitua manualmente os placeholders
   `<GITHUB_USERNAME>`/`<GITHUB_REPOSITORY>` que aparecem em `SETUP-CRON.md` e
   `README.md` pelos mesmos valores (são docs Markdown estáticos, a
   substituição não é automática).
5. [ ] **`SETUP-CRON.md`** — depois do passo acima, gere um **token
   fine-grained novo** (GitHub → Settings → Developer settings → Fine-grained
   tokens) escopado só para esse repositório, permissão Actions: Read and
   write; cadastre no cron-job.org (nunca commitar o token).
6. [ ] **GitHub Pages** — confirmar que o workflow `.github/workflows/deploy.yml`
   está na branch `main` e que o Pages foi habilitado (ele se autoconfigura na
   1ª execução via `actions/configure-pages`).
7. [ ] **Worker da IA Insights** — criar um Worker novo na Cloudflare (nome
   próprio do cliente) e ajustar `ia-worker/wrangler.toml` (`name = "..."`,
   troque o placeholder `nomecliente-ia-insights`). Passo a passo completo em
   `SETUP-IA.md`.
8. [ ] **4 Secrets do repositório no GitHub** (Settings → Secrets and variables →
   Actions → New repository secret):
   - `CLOUDFLARE_API_TOKEN`
   - `CLOUDFLARE_ACCOUNT_ID`
   - `ANTHROPIC_API_KEY`
   - `INSIGHTS_PASSWORD`
9. [ ] **Disparar o primeiro deploy do Worker** — um commit tocando qualquer
   arquivo dentro de `ia-worker/` já dispara `.github/workflows/deploy-worker.yml`
   automaticamente (ou rode manualmente pela aba Actions, se o workflow tiver
   `workflow_dispatch`).
10. [ ] **Embutir a URL do Worker no build** — copiar a URL do Worker (exibida na
    Cloudflare) para `IA_WORKER_URL` em `build/config.py` e rodar/disparar um novo
    build. Isso faz os insights aparecerem para **qualquer visitante**, em qualquer
    navegador, sem precisar configurar nada — a persistência é no Worker (KV), não
    no navegador. Na aba **IA Insights** → **⚙ Configurar**, só é preciso colar a
    senha (a mesma do secret `INSIGHTS_PASSWORD`) para poder **gerar** novos
    insights; o campo "Worker URL" ali é opcional (só para apontar a um backend
    diferente do padrão embutido).
11. [ ] **Testar** — clicar em **Gerar insights** e confirmar que os cards aparecem
    (e continuam aparecendo depois de recarregar a página em outro navegador).

---

## O que é

Dashboard de **Controle de Tráfego Pago** — app de BI estático (HTML/CSS/JS + Chart.js
via CDN) publicado no **GitHub Pages**, que cruza o gerenciador **Meta Ads** com a lista
de **Compradores** e se atualiza a cada ~30 min (build na nuvem via GitHub Actions,
disparado pelo cron-job.org). **Somente leitura** das planilhas.

- **URL pública:** `https://<GITHUB_USERNAME>.github.io/<GITHUB_REPOSITORY>/`
  (preencha `config.js` — ver checklist acima)
- **Cliente/projeto:** preencher em `build/config.py` (`CLIENT_NAME`/`CLIENT_SUB`)
- **Tipo de funil:** VSL / tráfego direto (não há etapa de Leads/MQL) —
  `Gasto → Impressões → Cliques → Page Views → Checkouts → Vendas → Faturamento`

## Fontes de dados (Google Sheets)

> Preencha esta seção com os dados da planilha real do cliente depois de
> configurar `build/config.py` (item 2 do checklist).

Spreadsheet ID: preenchido em `SPREADSHEET_ID` (`build/config.py`) — as duas abas
abaixo ficam, por padrão, na mesma planilha (leitura via export CSV).

| Aba | gid | Colunas usadas (exemplo — ajuste à planilha real) |
|-----|-----|----------------|
| **Meta Ads** | `GID_META` | Day · Campaign Name · Ad Set Name · Ad Name · Amount Spent · Impressions · Link Clicks · Landing Page Views · Checkouts Initiated |
| **Compradores** | `GID_SALES` | Produto · Nome · Email · Data · Valor · **Faturamento** (se houver) · utm_source · utm_medium · utm_content · utm_term · utm_campaign · Status · … |

**Pontos de atenção ao configurar um cliente novo** (verifique contra a planilha real):
- **Coluna de receita**: por padrão o alias de `val` prioriza `faturamento` sobre
  `valor` (`header_index` em `build/build.py`) — confirme qual coluna representa o
  valor líquido/bruto correto para este cliente e ajuste o alias se necessário.
- **Coluna de status de pagamento**: se a planilha tiver uma coluna confiável de
  status pago/aprovado, deixe `COUNT_ALL_AS_PAID = False` em `build/config.py`
  (o build filtra por `is_paid()`). Se for uma lista de compradores onde toda
  linha já é uma compra concretizada, deixe `True`.
- **Identificador do anúncio**: confirme em qual coluna UTM o cliente manda o
  nome do anúncio (`Ad Name` real do Meta) — muitas vezes é `UTM Content`, não
  `UTM Term` (que costuma carregar o *posicionamento*: Reels/Feed/Stories). O
  match Meta↔venda deve usar essa coluna.

URL de export CSV: `https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={GID}`

### Métricas do funil VSL (`build.py` + `template.html`)
`Gasto → Impressões → Cliques → Page Views → Checkouts → Vendas → Faturamento`

Gasto · Impressões · CPM · Cliques · CPC · CTR · Page Views · CPV · CR (Cliques/PageViews) ·
Checkouts · CPIC · VisCHK (Checkouts/PageViews) · Vendas · CAC (Gasto/Vendas) ·
ConvCHK (Vendas/Checkouts) · Faturamento · ROAS (Faturamento/Gasto) · Ticket (Faturamento/Vendas).

### Produto principal / atribuição
- **Produto principal** = `MAIN_PRODUCT_PREFIX` (definido em `build/config.py`). Base de
  **Vendas / CAC / ConvCHK / Ticket**.
- **Faturamento / ROAS** = soma de **todos os produtos** do funil (orderbumps/upsells).
- Uma venda entra no funil se: é o produto principal **OU** a combinação **`UTM Campaign`
  + `UTM Content`** (campanha + anúncio) casa com uma linha real do Meta (captura
  orderbumps/upsells que carregam a UTM do anúncio). O match exige campanha **e**
  anúncio juntos — nomes de anúncio (`AD01`, `AD02`...) podem se repetir entre campanhas
  diferentes; casar só pelo nome do anúncio atribuiria a venda à campanha errada. Quando
  casa, a venda herda a campanha/conjunto **reais do Meta** (fica na mesma linha do
  gasto nas tabelas). Vendas de outros funis (UTM/produto não relacionados) ficam de
  fora. Só conta status pago.
- Se não houver coluna de Receita, não há Receita/ROAS/Ticket — ajuste o texto desta
  seção se o cliente novo tiver uma regra diferente.

### Imposto Meta Ads
Toggle ON aplica o `TAX_FACTOR` (definido em `build/config.py`) sobre os custos do Meta.

### Convenções de campanha
`Campaign Name = utm_campaign`, `Ad Set Name = utm_medium`, `Ad Name = utm_content`
(⚠️ **confira se não é** `utm_term` no caso deste cliente — essa coluna costuma
carregar o **posicionamento** do anúncio, não o nome dele — ver "Pontos de atenção"
acima). O match com o Meta (campo `meta`, usado pela aba Meta Ads) exige
`utm_campaign`+`utm_content` batendo com uma linha real do Meta; quando casa, a venda
herda a campanha/conjunto reais do Meta (para o gasto e a venda caírem na mesma linha
das tabelas).

## IA Insights

Aba de análise por IA (Claude) do funil e das estruturas ativas — ver `SETUP-IA.md`
para o passo a passo completo de configuração do backend (Cloudflare Worker +
deploy automático via GitHub Actions).

**Persistência:** o último resultado gerado fica salvo no **Worker (KV namespace
`INSIGHTS_KV`)**, não no navegador — por isso qualquer visitante, em qualquer
navegador, vê os mesmos insights sem precisar gerar de novo. A URL do Worker vem
embutida no build (`IA_WORKER_URL` em `build/config.py`); a senha (`INSIGHTS_PASSWORD`)
só é exigida para **gerar** novos insights (POST), não para ler os já gerados
(GET, público). O workflow `deploy-worker.yml` cria o KV namespace sozinho no
primeiro deploy; se o `CLOUDFLARE_API_TOKEN` não tiver a permissão "Workers KV
Storage: Edit", ele publica o Worker sem persistência (volta ao comportamento
antigo, sem quebrar o deploy) e avisa no log do Actions.

## Arquitetura / arquivos

A dashboard é montada a partir de **arquivos separados** (visual x lógica), costurados
pelo `build.py` no `render()` — assim dá para mexer só em cor/layout sem tocar na lógica:

```
build/build.py             # ENGINE: lê os 2 CSVs (read-only), emite meta[]/sales[] e COSTURA os arquivos abaixo
build/config.py            # CONFIG DO CLIENTE (copie de config.example.py e preencha)
build/config.example.py    # modelo comentado de build/config.py
build/template.html        # esqueleto HTML (placeholders __STYLES__ / __APP_JS__ / __DATA_JSON__)
build/identidade-visual.css # ⭐ TODAS as cores (temas claro/escuro, paleta de gráficos, heatmap). Edite AQUI p/ mexer só em cor.
build/estilos.css          # layout/componentes (CSS não-cor)
build/app.js               # lógica + renderização (gráficos/heatmap leem as cores via CSS vars)
.github/workflows/deploy.yml         # roda build.py e publica no Pages
.github/workflows/deploy-worker.yml  # publica o Worker da IA Insights (Cloudflare)
.github/workflows/gerar-relatorios-metrics.yml # 23:50 BRT: busca as planilhas e commita relatorios_metrics.json
ia-worker/worker.js    # backend da aba IA Insights (ENGINE — não editar por cliente)
ia-worker/wrangler.toml # nome do Worker (preencher por cliente, placeholder nomecliente-ia-insights)
build/relatorios.json  # briefings do Gestor por período (aba Relatórios) — VERSIONADO
build/relatorios_metrics.json # números por período (gerado pelo Actions, lido pela Routine) — VERSIONADO
build/gerar_relatorios.py # calcula as métricas por período (rodado pelo Actions, não pela Routine)
build/GUIA-RELATORIOS.md  # passo a passo da Routine que regenera os briefings
dist/index.html        # saída gerada (gitignored; o Actions reconstrói)
GUIA-REPLICACAO.md     # engine explicada + solução dos problemas de publicação
config.js               # metadados de publicação (GitHub) — copie de config.example.js
SETUP-CRON.md          # valores do cron-job.org (owner/repo com placeholders)
SETUP-IA.md            # passo a passo da aba IA Insights
```

### Aba Relatórios (relatórios automáticos do funil)
Aba entre **Meta Ads** e **IA Insights**. Reaproveita os filtros de data da topbar
e os dados já embutidos (`meta[]`/`sales[]`) — tudo calculado no navegador (custo
zero): cards **Visão Geral Total** (todas as vendas) e **Tráfego** (só Meta Ads),
tabela diária resumida (Total | Ads), visão por campanha, **Top 5 / Piores 5
anúncios** (com link do criativo via coluna *Creative Instagram Permalink* →
`ad_links`, se a planilha do cliente tiver essa coluna). **Código de cor**
(vermelho/amarelo/verde/ciano) só em **CAC** e **ROAS**, conforme
`CAC_TARGET`/`ROAS_TARGET` em `build/config.py` (desempenho = ROAS `valor/meta`,
CAC `meta/valor`).

O **Briefing do Gestor** (texto interpretativo por período) é **pré-gerado por IA**
e lido de `build/relatorios.json` — **sem chamada de API no navegador nem créditos
da Anthropic**. Regeneração em **2 etapas diárias** (o sandbox do agente não alcança
o Google Sheets, só o runner do GitHub Actions — ver "problemas conhecidos" #4):
**23:50 BRT** o workflow `gerar-relatorios-metrics.yml` busca as planilhas e commita
`build/relatorios_metrics.json` (só números); **23:59 BRT** uma **Routine do
Claude Code** lê esse arquivo, migra o texto que estava em "hoje" para "ontem" e
redige os 9 briefings do zero seguindo `build/GUIA-RELATORIOS.md`, commitando
`relatorios.json`. Rodar no fim do dia (não de manhã) garante que "hoje" seja
analisado com o dia quase completo. Se o JSON não existir, a aba mostra tudo
menos o briefing (cards/tabelas seguem funcionando). Configure essa Routine (ou
equivalente) por cliente — não vem pronta neste template.

O `build.py` **não agrega**: exporta as linhas cruas e toda a lógica (filtros, KPIs,
tabelas, gráficos, heatmap, imposto, tema) roda no navegador.

Teste local:
`python build/build.py --meta-file meta.csv --sales-file sales.csv --out dist/index.html`

## Publicação — problemas conhecidos e soluções

1. **Push com integração somente‑leitura:** se `git push`/MCP derem `403 Resource not
   accessible by integration`, faça push com o **PAT do usuário** direto ao github.com
   (`git push https://x-access-token:<TOKEN>@github.com/<owner>/<repo>.git main:main`).
   **Nunca** grave o token no `.git/config` (use a URL efêmera).
2. **cron-job.org só funciona na `main`:** `workflow_dispatch` só existe na branch padrão.
3. **Pages liga sozinho:** `actions/configure-pages@v5` com `enablement: true`
   (+ `permissions: {pages: write, id-token: write}`).
4. **Proxy do sandbox:** o agente NÃO alcança `docs.google.com`, `*.github.io` nem a API
   REST de Actions/Pages e nem `api.cloudflare.com` — mas o runner do Actions alcança
   tudo. Teste dados com CSV local; deploys da Cloudflare passam pelo GitHub Actions.
5. **Token exposto no chat:** revogar e gerar um novo (fine‑grained, só Actions: r/w no repo).
6. **"Senha incorreta" na aba IA Insights após um deploy:** normalmente indica que os
   secrets `ANTHROPIC_API_KEY`/`INSIGHTS_PASSWORD` não estão cadastrados como Secrets
   do repositório no GitHub — o workflow `deploy-worker.yml` os reaplica no Worker a
   cada deploy; sem eles cadastrados, o Worker fica sem senha válida.
7. **Insights "somem":** se estiverem salvos só no navegador (versões antigas do
   template), limpar dados do navegador apaga tudo. A partir desta versão a
   persistência é no Worker (KV) — ver seção "IA Insights" acima; confirme que
   `IA_WORKER_URL` está preenchido em `build/config.py` e que o log do deploy do Worker
   não mostrou o aviso de KV sem permissão.
8. **Venda não aparece na aba Meta Ads (ou aparece na campanha errada):** confirme
   qual coluna UTM da planilha do cliente carrega o identificador real do anúncio do
   Meta (`Ad Name`) — nem sempre é `UTM Content`; `UTM Term` costuma carregar o
   **posicionamento** (`Instagram_Reels`/`Feed`/`Stories`), não o nome do anúncio.
   Casar pela coluna errada zera as atribuições. Além disso, nomes de anúncio podem se
   repetir entre campanhas diferentes — o match precisa ser **campanha+anúncio juntos**
   (`UTM Campaign`+`UTM Content`), senão a venda pode ser atribuída à campanha errada.
   Confira o valor real do `Ad Name` na API/painel do Meta e compare com as colunas
   UTM antes de mexer no alias.
