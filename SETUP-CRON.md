# Ativação + configuração do cron-job.org (TEMPLATE)

> owner/repo: `<GITHUB_USERNAME>/<GITHUB_REPOSITORY>` · URL do Pages:
> `https://<GITHUB_USERNAME>.github.io/<GITHUB_REPOSITORY>/`. O **token
> nunca é comitado** no repositório: ele vai apenas no cron-job.org.

## Passo 1 — Colocar na branch `main` (uma vez)

`workflow_dispatch` (o que o cron-job.org chama) **só existe na branch padrão**.
Faça o merge para a `main`. Na 1ª execução o workflow habilita o GitHub Pages
automaticamente (`actions/configure-pages` com `enablement: true`).

URL pública após publicar: `https://<GITHUB_USERNAME>.github.io/<GITHUB_REPOSITORY>/`

Disparar a 1ª execução na mão: aba **Actions** → *Build & Deploy Dashboard* → **Run workflow**.

## Passo 2 — Token (fine-grained, recomendado)

GitHub → *Settings* → *Developer settings* → **Fine-grained tokens** → *Generate*:
- Repository access: **Only select repositories → `<GITHUB_REPOSITORY>`**
- Permissions → **Actions: Read and write**

Guarde o token; ele vai só no cron-job.org.

## Passo 3 — Criar o cron job em https://cron-job.org

### URL
```
https://api.github.com/repos/<GITHUB_USERNAME>/<GITHUB_REPOSITORY>/actions/workflows/deploy.yml/dispatches
```
### Método
```
POST
```
### Schedule
```
A cada 30 minutos  (Every 30 minutes)
```
### Headers (um por linha)
```
Accept: application/vnd.github+json
```
```
Authorization: Bearer SEU_TOKEN_AQUI
```
```
X-GitHub-Api-Version: 2022-11-28
```
```
Content-Type: application/json
```
### Request body
```
{"ref":"main"}
```

## Como saber se funcionou
- Resposta esperada da API: **HTTP 204 No Content**.
- Em **Actions** aparece uma nova execução a cada disparo.
- 401/403 = token errado/sem permissão **Actions: write**.
- 404 = confira owner/repo/nome do arquivo (`deploy.yml`) e se está na `main`.
- 422 = o workflow ainda não está na `main`.

## Observações
- A página lê as planilhas **somente leitura**; nunca escreve nelas.
- O `schedule` nativo (`*/30 * * * *`) fica como backup; o cron-job.org é a fonte
  principal de pontualidade.
