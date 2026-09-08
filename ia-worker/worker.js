/**
 * Cloudflare Worker — backend da aba "IA Insights" do dashboard de tráfego direto/VSL.
 * Deploy automatizado via GitHub Actions (.github/workflows/deploy-worker.yml),
 * que reaplica os secrets ANTHROPIC_API_KEY e INSIGHTS_PASSWORD a cada publicacao
 * e provisiona o KV namespace usado para persistir o último resultado.
 *
 * A página (GitHub Pages, pública) envia um POST com { password, data } para
 * GERAR insights (exige senha) e um GET (sem senha) para LER o último resultado
 * já gerado — isso é o que permite qualquer visitante, em qualquer navegador,
 * ver os insights sem precisar clicar em "Gerar" de novo. O Worker valida a
 * senha, chama a API da Anthropic (Claude) com um system prompt de especialista
 * em tráfego pago / VSL / high-ticket, devolve os insights em JSON e grava uma
 * cópia no KV (binding INSIGHTS_KV) para as próximas leituras via GET. A chave
 * da Anthropic e a senha ficam como SECRETS do Worker — nunca na página pública.
 *
 * Secrets necessários (Settings → Variables and Secrets):
 *   ANTHROPIC_API_KEY  = sua chave sk-ant-...
 *   INSIGHTS_PASSWORD  = a senha que você digita na aba IA Insights
 *
 * Binding necessário: KV namespace INSIGHTS_KV (ver wrangler.toml — provisionado
 * automaticamente pelo workflow de deploy).
 */

const MODEL = "claude-sonnet-5";
const ANTHROPIC_URL = "https://api.anthropic.com/v1/messages";

const SYSTEM_PROMPT = `Você é um especialista sênior em tráfego pago, funis de VSL (Video Sales Letter) e produtos high-ticket. Analisa dados de um funil de tráfego direto (Meta Ads → VSL → Checkout → Venda) e gera insights acionáveis.

Domine as métricas e suas correlações (etapa a etapa do funil):
- CPM (custo por mil impressões), CTR (cliques/impressões): saúde do criativo e da segmentação.
- Connect Rate / CR = Page Views / Cliques: consistência entre anúncio e página e velocidade de carregamento (perda aqui = página lenta ou promessa do anúncio ≠ página).
- CPV (custo por page view).
- VisCHK = Checkouts / Page Views: força da VSL/oferta em levar ao checkout (CTA, prova, oferta, retenção do vídeo).
- ConvLP = Vendas / Page Views: conversão geral da página em venda.
- ConvCHK = Vendas / Checkouts: fricção do checkout (formas de pagamento, preço, confiança, remarketing/recuperação).
- CAC = Gasto / Vendas; ROAS = Faturamento / Gasto; Ticket = Faturamento / Vendas.

Diagnóstico de gargalos:
- CTR baixo → gancho/criativo do anúncio, primeiros 3s, segmentação; melhorar copy para qualificar melhor o público.
- CR baixo → velocidade da página de destino, coerência anúncio→página.
- VisCHK baixo → avaliar conversão da VSL, CTA, oferta, prova social, retenção do vídeo.
- ConvCHK baixo → personalização/otimização do checkout, formas de pagamento, preço/parcelamento, remarketing.
- CAC alto vs ROAS/Ticket → qualificação do público na copy, oferta, ou reduzir verba de estruturas ineficientes.

Análise de TENDÊNCIA e SATURAÇÃO (obrigatória quando os dados trazem comparativo_periodo, serie_diaria e tendencia por estrutura):
- Compare a janela recente vs a anterior. Sinais clássicos de saturação/fadiga de criativo: CPM subindo + CTR caindo + CPA/CAC subindo + ROAS caindo ao longo dos dias. Quando ocorrer, sinalize e recomende renovar criativo, ampliar público, ou reduzir verba da estrutura fatigada.
- Use o campo "tendencia" de cada estrutura (cac_recente vs cac_anterior, roas_recente vs roas_anterior, gasto_recente vs gasto_anterior) para dizer se ela está MELHORANDO ou PIORANDO — não julgue só pela média do período inteiro.
- Uma estrutura com boa média mas piorando rápido merece cautela; uma piorando de verdade merece corte antes de uma com média ruim mas estável.

Guardrails de mercado (siga como boa prática de tráfego pago):
- VOLUME MÍNIMO antes de agir: não recomende cortar/escalar estrutura com pouquíssimo gasto ou pouquíssimas vendas (decisão em cima de ruído estatístico). Diga quando faltam dados para concluir.
- FASE DE APRENDIZADO do Meta: conjuntos precisam de ~50 conversões/semana para sair do aprendizado; evite recomendar edições que resetem o aprendizado sem necessidade.
- ESCALA em passos: aumentos de verba de ~20% por vez (evita estourar o aprendizado). Não recomende dobrar verba de uma vez.
- Considere sazonalidade de dia da semana ao ler a serie_diaria (não confunda queda de fim de semana com saturação).

Ajustes de verba (quando uma campanha/conjunto/anúncio se destaca muito acima ou abaixo da média da conta E tem volume suficiente): recomende AUMENTAR verba (passos de ~20%) em estruturas com ROAS/CAC muito melhores que a média e escala saudável, e REDUZIR/PAUSAR nas muito piores ou claramente saturadas. Regras: campanhas ABO → ajuste no CONJUNTO; campanhas CBO → ajuste na CAMPANHA (é possível definir mín/máx de gasto por conjunto). Sugira um percentual (ex.: +20%, -30%).

Compare estruturas contra a MÉDIA da própria conta (não use benchmarks fixos). Priorize por impacto financeiro. Seja específico e direto.

Responda SOMENTE com um objeto JSON válido (sem markdown, sem texto fora do JSON), no formato:
{"insights":[{"nivel":"funil|campanha|conjunto|anuncio","metrica":"nome da métrica","severidade":"alta|media|baixa","titulo":"resumo curto","diagnostico":"o que os dados mostram","recomendacao":"ação concreta a executar","estrutura":"nome da campanha/conjunto/anúncio (ou vazio)","verba":{"acao":"aumentar|reduzir|manter","percentual":20,"nivel_ajuste":"conjunto|campanha","observacao":"ABO/CBO e mín-máx se aplicável"}}]}
O campo "verba" só deve existir quando houver recomendação de mudança de orçamento; caso contrário, omita-o. Gere de 4 a 8 insights, dos mais relevantes aos menos. Seja direto: "diagnostico" e "recomendacao" em 1-2 frases cada, sem repetir números já citados em outros campos.`;

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Max-Age": "86400",
};

const KV_KEY = "latest";

// Extrai { insights: [...] } da resposta do modelo, tolerando cercas de
// markdown (```json ... ```) ou texto em volta do JSON.
function extractInsights(text) {
  if (!text) return null;
  let t = String(text).trim();
  const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) t = fence[1].trim();
  const candidates = [t];
  const s = t.indexOf("{"), e = t.lastIndexOf("}");
  if (s >= 0 && e > s) candidates.push(t.slice(s, e + 1));
  for (const c of candidates) {
    try {
      const p = JSON.parse(c);
      if (p && Array.isArray(p.insights)) return p;
    } catch (_) {}
  }
  return null;
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });

    // Leitura pública do último resultado gerado — sem senha. É o que faz os
    // insights aparecerem para qualquer visitante, em qualquer navegador.
    if (request.method === "GET") {
      if (!env.INSIGHTS_KV) return json({ insights: null });
      let stored;
      try { stored = await env.INSIGHTS_KV.get(KV_KEY, "json"); } catch { stored = null; }
      return json(stored || { insights: null });
    }

    if (request.method !== "POST") return json({ error: "Use GET ou POST." }, 405);

    let payload;
    try { payload = await request.json(); }
    catch { return json({ error: "JSON inválido." }, 400); }

    if (!env.INSIGHTS_PASSWORD || payload.password !== env.INSIGHTS_PASSWORD) {
      return json({ error: "Senha incorreta." }, 401);
    }
    if (!env.ANTHROPIC_API_KEY) {
      return json({ error: "ANTHROPIC_API_KEY não configurada no Worker." }, 500);
    }

    const userMsg = "Dados do funil e das estruturas ativas (período/filtro atual). "
      + "Analise e gere os insights conforme instruído.\n\n"
      + JSON.stringify(payload.data ?? {});

    let resp;
    try {
      resp = await fetch(ANTHROPIC_URL, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-api-key": env.ANTHROPIC_API_KEY,
          "anthropic-version": "2023-06-01",
        },
        body: JSON.stringify({
          model: MODEL,
          max_tokens: 16000,
          system: SYSTEM_PROMPT,
          messages: [{ role: "user", content: userMsg }],
        }),
      });
    } catch (e) {
      return json({ error: "Falha ao chamar a Anthropic: " + e.message }, 502);
    }

    const raw = await resp.text();
    if (!resp.ok) return json({ error: "Anthropic HTTP " + resp.status, detail: raw.slice(0, 800) }, 502);

    let data;
    try { data = JSON.parse(raw); } catch { return json({ error: "Resposta não-JSON da Anthropic." }, 502); }

    if (data.stop_reason === "refusal") return json({ error: "A IA recusou a solicitação." }, 200);

    const text = (data.content || []).filter(b => b.type === "text").map(b => b.text).join("");
    const parsed = extractInsights(text);
    if (!parsed) {
      return json({
        error: "Não foi possível interpretar os insights.",
        stop_reason: data.stop_reason || null,
        raw: text.slice(0, 1500),
      }, 200);
    }
    const result = {
      insights: parsed.insights,
      usage: data.usage || null,
      at: Date.now(),
      from: payload?.data?.periodo?.de ?? null,
      to: payload?.data?.periodo?.ate ?? null,
    };
    if (env.INSIGHTS_KV) {
      try { await env.INSIGHTS_KV.put(KV_KEY, JSON.stringify(result)); } catch (_) {}
    }
    return json(result);
  },
};
