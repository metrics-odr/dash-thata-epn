# Aba "IA Insights" — backend (Cloudflare Worker)

A aba **IA Insights** manda os dados do funil para um **Cloudflare Worker**, que
chama a IA (Claude) e devolve os insights. A **chave da Anthropic** e a **senha**
ficam como *secrets* do Worker — nunca na página pública. A página só guarda, no
seu navegador, a **URL do Worker** e a **senha** que você digita.

> Nada roda sozinho: a IA só é chamada quando você clica em **Gerar insights**.

## Opção A — Automático via GitHub Actions (recomendado)

Depois de configurado uma vez, qualquer ajuste futuro em `ia-worker/worker.js`
publica sozinho — sem repetir nada manualmente na Cloudflare.

### A.1 — Criar o Worker na Cloudflare (uma vez)

1. Acesse **dash.cloudflare.com** e faça login.
2. No menu lateral esquerdo, clique em **Compute (Workers)** (nome atual do menu;
   em contas mais antigas pode aparecer como "Workers & Pages").
3. Clique na aba **Workers**.
4. Clique no botão **Create**.
5. Escolha **"Start from scratch"** (não use um template pronto de exemplo).
6. Dê um nome ao Worker, igual ao que você vai colocar em `ia-worker/wrangler.toml`
   (ex.: `nomecliente-ia-insights`) → clique em **Deploy**.
7. Clique em **Edit code**, apague todo o conteúdo e cole o conteúdo de
   **`ia-worker/worker.js`** deste repositório → clique em **Deploy** (ou
   **Save and Deploy**).
8. Copie a **URL** do Worker exibida (formato
   `https://nomecliente-ia-insights.SEU-SUBDOMINIO.workers.dev`) — vai usar no
   passo A.4.

### A.2 — Pegar o Account ID e criar o API Token da Cloudflare

1. Ainda no dashboard, na tela do Worker (ou em **Compute (Workers)**), veja a
   barra lateral direita: o **Account ID** aparece ali (32 caracteres). Copie.
2. Clique no ícone do seu perfil (canto superior direito) → **My Profile**.
3. Menu lateral → **API Tokens** → botão **Create Token**.
4. Procure o template **"Edit Cloudflare Workers"** → **Use template**.
5. Confirme as permissões **Account → Workers Scripts → Edit** e **Account →
   Workers KV Storage → Edit** (o template já costuma incluir as duas; se só
   tiver Workers Scripts, adicione Workers KV Storage manualmente — é o que
   permite ao deploy criar o KV namespace que guarda os insights) → **Continue
   to summary** → **Create Token**.
6. Copie o token exibido (só aparece uma vez).

### A.3 — Cadastrar os 4 Secrets no GitHub

No repositório do cliente no GitHub:

1. **Settings → Secrets and variables → Actions → New repository secret**.
2. Cadastre, um de cada vez (**Add secret** depois de cada um):
   - `CLOUDFLARE_API_TOKEN` = o token do passo A.2.6
   - `CLOUDFLARE_ACCOUNT_ID` = o Account ID do passo A.2.1
   - `ANTHROPIC_API_KEY` = a chave `sk-ant-...` do cliente
   - `INSIGHTS_PASSWORD` = a senha que você quer usar na aba IA Insights

### A.4 — Disparar o primeiro deploy automático

1. Confirme que `ia-worker/wrangler.toml` tem o **mesmo nome** de Worker do passo A.1.6.
2. Faça um commit tocando qualquer arquivo dentro de `ia-worker/` (isso dispara o
   workflow `.github/workflows/deploy-worker.yml`).
3. Na aba **Actions** do repositório, confira a execução **"Deploy IA Worker
   (Cloudflare)"** — espere ficar verde. Um dos passos cria automaticamente o KV
   namespace (`INSIGHTS_KV`) que guarda o último resultado gerado; se o log mostrar
   um aviso (`::warning`) dizendo que não conseguiu criar o KV, confira a permissão
   "Workers KV Storage: Edit" no token (passo A.2.5) — o Worker ainda assim é
   publicado, só fica temporariamente sem persistência.
4. Esse deploy já publica o Worker **e** aplica os dois secrets
   (`ANTHROPIC_API_KEY`, `INSIGHTS_PASSWORD`) nele automaticamente — não precisa
   repetir a Opção B abaixo.

### A.5 — Embutir a URL do Worker no build

1. Copie a **URL do Worker** (passo A.1.8).
2. Cole em `IA_WORKER_URL` (`build/build.py`) e rode/dispare um novo build.
3. Pronto: **qualquer visitante**, em qualquer navegador, já vê os insights
   assim que abrir a aba — a página lê o resultado direto do Worker (KV), não
   do navegador. Na aba **IA Insights** → **⚙ Configurar**, só é preciso colar a
   **senha** (a mesma de `INSIGHTS_PASSWORD`) para poder **gerar** novos
   insights; o campo "Worker URL" ali é opcional (só para testar outro backend).
4. Clique em **Gerar insights** para testar — o resultado passa a valer para
   todo mundo, em qualquer navegador, até a próxima geração.

## Opção B — Manual (sem GitHub Actions)

Use só se não quiser depender do Actions para o Worker.

1. Siga a Opção A.1 para criar o Worker e colar o código.
2. Na página do Worker, aba **Settings** → seção **Variables and Secrets** → **Add**:
   - Tipo **Secret** → nome `ANTHROPIC_API_KEY` → valor `sk-ant-...`
   - Tipo **Secret** → nome `INSIGHTS_PASSWORD` → valor da senha
   - Clique em **Save** (ou **Deploy**) para aplicar.
3. Configure a URL + senha na aba IA Insights (igual ao passo A.5).

### Opção B (linha de comando, via Wrangler)

```bash
cd ia-worker
npx wrangler deploy
echo "SUA_CHAVE_ANTHROPIC" | npx wrangler secret put ANTHROPIC_API_KEY
echo "SUA_SENHA"          | npx wrangler secret put INSIGHTS_PASSWORD
```
Depois copie a URL que o deploy imprime e configure na aba IA Insights (passo A.5).

## Segurança

- A chave da Anthropic vive **só no Worker** (secret). A senha protege o endpoint
  para ninguém com o link gastar seus tokens — ela não fica no código público, só
  no seu navegador (localStorage) e como secret no Worker/GitHub.
- Recomendo **rotacionar a chave da Anthropic** depois de configurar tudo, e nunca
  colar tokens/chaves reais em nenhum arquivo deste repositório.
- Custo: cada clique em **Gerar insights** = 1 chamada à API (poucos centavos).
