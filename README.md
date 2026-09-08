# Dashboard de Controle de Tráfego Pago (VSL/Tráfego Direto) — TEMPLATE

> Este repositório é um **template reutilizável**. Ele ainda não está configurado
> para nenhum cliente — siga o guia abaixo (ou o **CHECKLIST DE NOVO CLIENTE** no
> topo do `CLAUDE.md`) para colocar um dashboard no ar em ~15-20 minutos.

## Visão geral

Dashboard de BI estática (HTML/CSS/JS + Chart.js via CDN) publicada no **GitHub
Pages**, que cruza o gerenciador **Meta Ads** com uma lista de **Compradores**
(duas abas de uma planilha Google Sheets) e se atualiza sozinha a cada ~30 min
(build na nuvem via GitHub Actions, disparado pelo cron-job.org). **Somente
leitura** das planilhas — o dashboard nunca escreve nelas.

Funil coberto: **VSL / tráfego direto** (sem etapa de Leads/MQL) —
`Gasto → Impressões → Cliques → Page Views → Checkouts → Vendas → Faturamento`.

Como funciona, por dentro:

1. `build/build.py` lê 2 abas da planilha (Meta Ads + Compradores) via export CSV
   público e emite os registros brutos dentro do HTML final.
2. Toda a lógica (KPIs, filtros, gráficos, heatmap, imposto, tema) roda **no
   navegador** (`build/template.html` + `build/app.js`) — o Python não agrega nada,
   só emite as linhas cruas. Isso garante que KPIs, gráficos e tabelas nunca
   divergem entre si.
3. Um commit na `main` dispara o GitHub Actions, que builda e publica no Pages.
4. O `cron-job.org` chama o mesmo workflow a cada 30 min, então o dashboard fica
   sempre atualizado mesmo sem ninguém commitar nada (ver `SETUP-CRON.md`).
5. Uma aba opcional de **IA Insights** manda o funil para um Cloudflare Worker que
   chama a Claude e devolve uma análise (ver `SETUP-IA.md`).

Nenhuma dessas peças exige servidor próprio ou banco de dados — tudo roda em
serviços gratuitos (GitHub Pages, GitHub Actions, cron-job.org) mais,
opcionalmente, o Cloudflare Workers (também com camada gratuita) para a IA.

## Requisitos

- Uma conta no **GitHub** (para hospedar o repositório e publicar no Pages).
- Uma **planilha Google Sheets** com 2 abas — Meta Ads e Compradores — com o
  compartilhamento em **"Qualquer pessoa com o link pode visualizar"** (o build
  lê via export CSV público, somente leitura; a planilha nunca é editada).
- **Python 3.10+** só se você quiser testar o build localmente antes de publicar
  (o GitHub Actions já roda o Python sozinho, você não precisa instalar nada
  para só publicar).
- Uma conta gratuita em **[cron-job.org](https://cron-job.org)** (dispara o
  build a cada 30 min).
- *Opcional* — para a aba **IA Insights**: conta na **Cloudflare** (Workers) e
  uma chave de API da **Anthropic** (`sk-ant-...`).

## Como instalar (visão rápida)

1. Crie o repositório a partir deste template (veja "Como publicar no GitHub"
   abaixo).
2. Copie `build/config.example.py` → `build/config.py` e preencha com os dados
   do cliente (veja "Como configurar a planilha" abaixo).
3. Copie `config.example.js` → `config.js` e preencha os metadados do GitHub
   (veja "Como preencher o config.js" abaixo).
4. Habilite o GitHub Pages e o cron-job.org (veja as seções correspondentes).
5. *Opcional:* configure o Cloudflare Worker para a aba IA Insights.
6. Teste localmente (opcional) e depois publique.

Teste local do build (não é obrigatório — o Actions builda sozinho):
```bash
python build/build.py --meta-file meta.csv --sales-file sales.csv --out dist/index.html
```
`meta.csv`/`sales.csv` são exports locais das abas, usados só para não depender
da internet durante o desenvolvimento. Sem `--meta-file`/`--sales-file`, o build
busca as planilhas reais via `SPREADSHEET_ID`/`GID_*` de `build/config.py`.

## Como publicar no GitHub

1. No GitHub, abra este repositório-template e clique em **"Use this template"**
   → **"Create a new repository"** (ou faça um *fork*, se preferir).
2. Dê um nome ao novo repositório (ex.: `dashboard-nome-do-cliente`) e crie.
3. Clone o repositório novo na sua máquina (ou edite direto pela interface do
   GitHub / Claude Code / Codespaces).
4. Preencha `build/config.py` e `config.js` (veja as seções abaixo).
5. Commit e push para a branch `main` — esse push já dispara o primeiro build
   (`.github/workflows/deploy.yml`, no gatilho `push`).

## Como ativar o GitHub Pages

O workflow `.github/workflows/deploy.yml` habilita o Pages **sozinho** na
primeira execução (`actions/configure-pages` com `enablement: true`), então
normalmente você não precisa mexer em nada manualmente. Para conferir/forçar:

1. No repositório, vá em **Settings → Pages**.
2. Confirme que **Source** está como **"GitHub Actions"** (não "Deploy from a
   branch").
3. Se o Pages ainda não tiver rodado nenhuma vez, dispare manualmente: aba
   **Actions** → workflow **"Build & Deploy Dashboard"** → **Run workflow**
   (branch `main`).
4. Depois do primeiro deploy bem-sucedido, a URL pública aparece em **Settings
   → Pages** e é sempre `https://<GITHUB_USERNAME>.github.io/<GITHUB_REPOSITORY>/`.
5. Configure o cron-job.org para dar continuidade aos builds automáticos a cada
   30 min — passo a passo completo em **`SETUP-CRON.md`** (ele já vem com
   placeholders `<GITHUB_USERNAME>`/`<GITHUB_REPOSITORY>` para você substituir
   pelos valores do seu `config.js`).

## Como configurar a planilha/API (Google Sheets)

1. Na planilha do cliente, garanta que **Meta Ads** e **Compradores** estão em
   abas separadas (podem estar na mesma planilha — é o padrão deste template).
2. Compartilhamento: **Arquivo → Compartilhar → Acesso geral → "Qualquer
   pessoa com o link"** → papel **"Leitor"**. O build só lê (`export?format=csv`),
   nunca escreve.
3. Pegue o **Spreadsheet ID** da URL da planilha:
   `https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit#gid=...`
4. Pegue o **gid** de cada aba (o número depois de `gid=` na URL, ao clicar em
   cada aba).
5. Cole os três valores em `build/config.py` (`SPREADSHEET_ID`, `GID_META`,
   `GID_SALES` — ver comentários no próprio arquivo).
6. Confira os nomes das colunas da planilha real contra os aliases esperados em
   `header_index` (`build/build.py`) — o template já reconhece várias variações
   comuns (`"Amount Spent"`/`"valor gasto"`/`"gasto"`, etc.), mas planilhas muito
   diferentes podem precisar de um alias novo.
7. Ajuste as regras de negócio em `build/config.py`: `MAIN_PRODUCT_PREFIX`
   (produto principal), `TAX_FACTOR` (imposto do Meta, `1.0` se não houver) e
   `COUNT_ALL_AS_PAID` (se a planilha não tiver uma coluna de status de
   pagamento confiável). Detalhes de cada campo nos comentários do arquivo.

## Como configurar o Cloudflare Worker (aba IA Insights — opcional)

A aba IA Insights não é obrigatória para o resto do dashboard funcionar — sem
ela configurada, a aba simplesmente fica indisponível. Passo a passo completo,
com prints e troubleshooting, está em **`SETUP-IA.md`**. Resumo:

1. Crie um Worker novo na Cloudflare ("Start from scratch") e cole o conteúdo
   de `ia-worker/worker.js`.
2. Pegue o **Account ID** da Cloudflare e crie um **API Token** com permissão
   *Workers Scripts: Edit* + *Workers KV Storage: Edit*.
3. Cadastre 4 *Secrets* no repositório GitHub (**Settings → Secrets and
   variables → Actions**): `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`,
   `ANTHROPIC_API_KEY`, `INSIGHTS_PASSWORD`.
4. Ajuste `ia-worker/wrangler.toml` (`name = "..."`, troque o placeholder
   `nomecliente-ia-insights`).
5. Um commit tocando qualquer arquivo em `ia-worker/` dispara o deploy
   automático do Worker (`.github/workflows/deploy-worker.yml`), que também
   cria o KV namespace de persistência e aplica os secrets.
6. Copie a URL pública do Worker (formato `https://SEU-WORKER.SEU-SUBDOMINIO.workers.dev`)
   para `IA_WORKER_URL` em `build/config.py` e dispare um novo build.
7. Na aba **IA Insights** → **⚙ Configurar**, cole a senha (mesma de
   `INSIGHTS_PASSWORD`) e clique em **Gerar insights** para testar.

## Como preencher o `config.js`

`config.js` (raiz do repositório) **não é lido pelo dashboard em runtime** — o
app publicado é um HTML estático gerado por `build/build.py`, e os dados
sensíveis (senha da IA Insights) nunca ficam em código público. `config.js`
existe para centralizar, num só lugar, os valores que você digita manualmente
em vários documentos deste template:

```js
window.CONFIG = {
  GITHUB_USERNAME: "",    // usuário/organização dona do repositório
  GITHUB_REPOSITORY: "",  // nome do repositório no GitHub
  PROJECT_NAME: "",       // nome do cliente/projeto (referência/documentação)
  get PAGES_URL() { return `https://${this.GITHUB_USERNAME}.github.io/${this.GITHUB_REPOSITORY}/`; },
};
```

Passo a passo:
1. `cp config.example.js config.js`.
2. Preencha `GITHUB_USERNAME`, `GITHUB_REPOSITORY` e `PROJECT_NAME`.
3. Use esses **mesmos valores** para substituir manualmente os placeholders
   `<GITHUB_USERNAME>` e `<GITHUB_REPOSITORY>` que aparecem em `SETUP-CRON.md`,
   `README.md` (este arquivo) e `CLAUDE.md` — são documentos Markdown estáticos,
   então a substituição não é automática (busque pelo texto exato no
   repositório e troque em cada ocorrência).

A configuração que **de fato** é lida pelo build (planilha, produto, imposto,
metas, URL do Worker) fica em `build/config.py` — ver "Como configurar a
planilha/API" acima.

## Como atualizar o template

Este repositório é a **engine** compartilhada entre todos os clientes que
usarem o template. Se você mantém vários dashboards a partir dele:

1. Faça as melhorias de engine (bugs, features, layout) num clone limpo deste
   template — **nunca** num repositório já configurado para um cliente
   específico, para não misturar config real com mudança de engine.
2. Arquivos de **engine** (não editar por cliente): `build/build.py`,
   `build/template.html`, `build/app.js`, `build/estilos.css`,
   `build/identidade-visual.css`, `ia-worker/worker.js`, os workflows em
   `.github/workflows/`.
3. Arquivos de **config por cliente** (não devem ir para o template): os
   `build/config.py`, `config.js`, `ia-worker/wrangler.toml` (campo `name`) e
   `build/relatorios.json`/`build/relatorios_metrics.json` já preenchidos de
   um cliente específico.
4. Para levar uma melhoria de engine a um cliente já publicado: copie os
   arquivos de engine atualizados para o repositório do cliente, **preservando**
   o `build/config.py`, `config.js` e `wrangler.toml` dele — teste local antes
   de commitar na `main`.
5. Para adaptar a um funil diferente (ex.: com etapa de Leads/MQL): ver seção 9
   de `GUIA-REPLICACAO.md`.

## Métricas do funil VSL

Gasto · Impressões · **CPM** · Cliques · **CPC** · **CTR** · Page Views · **CPV** ·
**CR** (Cliques/Page Views) · Checkouts · **CPIC** · **VisCHK** (Checkouts/Page Views) ·
Vendas · **CAC** (Gasto/Vendas) · **ConvCHK** (Vendas/Checkouts) · Faturamento ·
**ROAS** (Faturamento/Gasto) · **Ticket Médio** (Faturamento/Vendas).

- **Produto principal** (base de Vendas / CAC / ConvCHK / Ticket): configurável em
  `MAIN_PRODUCT_PREFIX` (`build/config.py`).
- **Faturamento / ROAS**: consideram **todos os produtos** do funil (orderbumps e
  upsells inclusos), atribuídos ao tráfego rastreado.
- **Imposto Meta**: toggle ON aplica o fator configurado em `TAX_FACTOR` (`build/config.py`).

## O que a dashboard mostra

- **Aba 1 — Visão Geral:** KPIs principais/secundários do funil VSL, gráfico combinado
  diário (Vendas + Gasto/Faturamento/ROAS), barras por campanha/anúncio/produto
  e tabela diária com heatmap.
- **Aba 2 — Meta Ads:** funil em etapas, combinado diário, faturamento por
  anúncio, tabela diária e 3 tabelas hierárquicas (Campanha → Conjunto → Anúncio) com
  **filtro cruzado**, além da lista de compradores.
- **Aba 3 — Relatórios:** cards de visão geral/tráfego, tabela diária, visão por
  campanha e Top/Piores anúncios, com briefing interpretativo pré-gerado por IA
  (opcional — ver `build/GUIA-RELATORIOS.md`).
- **Aba 4 — IA Insights:** análise por IA (Claude) do funil e das estruturas ativas,
  com detecção de tendência/saturação e recomendações de verba. Ver `SETUP-IA.md`.

Recursos: filtro global de data + presets, toggle de imposto, tema claro/escuro,
tabelas com ordenação/redimensionamento/multi-seleção, cache-bust.

## Arquivos

- `build/template.html` — a **engine** (CSS + JS). Não editar por cliente.
- `build/build.py` — a **engine** de leitura das planilhas. Não editar por cliente.
- `build/config.py` — **config do cliente** (Spreadsheet ID, gids, imposto,
  produto principal, rótulos, metas, URL do Worker). Copie de `build/config.example.py`.
- `config.js` — metadados de publicação (usuário/repo do GitHub) usados como
  referência para os placeholders na documentação. Copie de `config.example.js`.
- `.github/workflows/deploy.yml` — build + deploy no Pages.
- `.github/workflows/deploy-worker.yml` — deploy automático do Worker da IA Insights.
- `.github/workflows/gerar-relatorios-metrics.yml` — números da aba Relatórios.
- `ia-worker/worker.js` — backend da aba IA Insights (engine, genérico).
- `ia-worker/wrangler.toml` — nome do Worker (preencher por cliente).
- `GUIA-REPLICACAO.md` — arquitetura, CSS/JS e solução dos problemas de publicação.
- `CLAUDE.md` — contexto do projeto + checklist de novo cliente.
- `SETUP-CRON.md` — configuração do cron-job.org.
- `SETUP-IA.md` — configuração da aba IA Insights (Cloudflare Worker).
- `LICENSE` — licença deste template.

## Privacidade

O e‑mail dos compradores é **mascarado** no build (a página é pública). Para exibir
contatos completos, use repositório/Pages **privado**.
