// Metadados de publicação (GitHub/infra) — TEMPLATE.
//
// Este arquivo NÃO é lido pelo dashboard em runtime (o app é um HTML estático
// gerado por build/build.py; os dados do funil e da senha da IA Insights são
// tratados separadamente — ver build/config.py e SETUP-IA.md). Ele serve como
// referência única para os valores que você repete manualmente nos lugares
// abaixo, para não perder o fio de qual valor vai onde.
//
// Copie para `config.js` e preencha:
//     cp config.example.js config.js
//
// Depois, use estes MESMOS valores para substituir os placeholders
// `<GITHUB_USERNAME>` / `<GITHUB_REPOSITORY>` que aparecem em:
//   - SETUP-CRON.md (URL da API do GitHub e URL do Pages)
//   - README.md (URL pública do Pages)
//   - CLAUDE.md (URL pública do Pages)
// (São documentos Markdown estáticos, por isso a substituição é manual —
// busque por `<GITHUB_USERNAME>` e `<GITHUB_REPOSITORY>` no repositório.)
window.CONFIG = {
  // Usuário ou organização dona do repositório no GitHub.
  GITHUB_USERNAME: "",       // ex.: "seu-usuario"

  // Nome do repositório no GitHub (o mesmo que você usou ao criar o repo a
  // partir deste template).
  GITHUB_REPOSITORY: "",     // ex.: "dashboard-nome-do-cliente"

  // Nome do projeto/cliente, usado só como referência em documentação e no
  // nome do Worker sugerido em ia-worker/wrangler.toml (ex.: "nomecliente-ia-insights").
  PROJECT_NAME: "",          // ex.: "Nome do Cliente"

  // Preenchido automaticamente a partir de GITHUB_USERNAME/GITHUB_REPOSITORY
  // acima — é a URL pública que o dashboard terá depois de ativar o Pages.
  get PAGES_URL() {
    return `https://${this.GITHUB_USERNAME}.github.io/${this.GITHUB_REPOSITORY}/`;
  },
};
