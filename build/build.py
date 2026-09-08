#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dashboard de Controle de Tráfego Pago — Funil VSL/tráfego direto (Meta Ads × Compradores).
Os valores do cliente (planilha, produto, taxa, rótulos, metas, worker da IA)
ficam em `build/config.py` — veja `build/config.example.py` para o modelo e
comentários de cada campo. Este arquivo (build.py) é a ENGINE, genérica para
qualquer cliente; não deve ser editado por cliente.

Lê duas abas de uma planilha Google (export CSV público) e emite os REGISTROS
BRUTOS (meta[] / sales[]) dentro do HTML. Todo o cálculo/filtro/gráfico roda no
navegador (ver build/template.html). Somente leitura; nunca escreve nas planilhas.

Funil VSL / tráfego direto — não há etapa de "Leads"/"MQL":
    Gasto → Impressões → Cliques → Page Views → Checkouts → Vendas → Faturamento

Teste local: python build/build.py --meta-file meta.csv --sales-file sales.csv --out dist/index.html
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone, timedelta

try:
    import config as cfg
except ImportError:
    sys.exit(
        "ERRO: build/config.py não encontrado.\n"
        "Copie o modelo e preencha os valores do cliente:\n"
        "    cp build/config.example.py build/config.py\n"
        "Veja os comentários em cada campo de build/config.example.py."
    )

_REQUIRED = ("SPREADSHEET_ID", "GID_META", "GID_SALES", "MAIN_PRODUCT_PREFIX",
             "CLIENT_NAME", "MAIN_PRODUCT")
_missing = [name for name in _REQUIRED if not getattr(cfg, name, "")]
if _missing:
    sys.exit(
        "ERRO: build/config.py está com campo(s) obrigatório(s) vazio(s): "
        + ", ".join(_missing) + ".\n"
        "Preencha build/config.py antes de rodar o build (ver build/config.example.py)."
    )

SPREADSHEET_ID = cfg.SPREADSHEET_ID
GID_META = cfg.GID_META
GID_SALES = cfg.GID_SALES
TAX_FACTOR = cfg.TAX_FACTOR
MAIN_PRODUCT_PREFIX = cfg.MAIN_PRODUCT_PREFIX
COUNT_ALL_AS_PAID = cfg.COUNT_ALL_AS_PAID
CLIENT_NAME = cfg.CLIENT_NAME
CLIENT_SUB = cfg.CLIENT_SUB
TAX_LABEL = cfg.TAX_LABEL
MAIN_PRODUCT = cfg.MAIN_PRODUCT
CAC_TARGET = cfg.CAC_TARGET
ROAS_TARGET = cfg.ROAS_TARGET
REPORT_BAND_LOW = cfg.REPORT_BAND_LOW
REPORT_BAND_HIGH = cfg.REPORT_BAND_HIGH
IA_WORKER_URL = cfg.IA_WORKER_URL

EXPORT_URL = "https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
BRT = timezone(timedelta(hours=-3))   # horário de Brasília (exibição)


# --------------------------------------------------------------------------- #
# Leitura (só leitura das planilhas)
# --------------------------------------------------------------------------- #
def fetch_csv(url: str) -> list[list[str]]:
    req = urllib.request.Request(url, headers={"User-Agent": "dash-vsl-bot/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return list(csv.reader(io.StringIO(raw)))


def read_csv_file(path: str) -> list[list[str]]:
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        return list(csv.reader(f))


def load_rows(url: str, local: str | None) -> list[list[str]]:
    return read_csv_file(local) if local else fetch_csv(url)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str | None) -> str:
    return strip_accents((s or "").strip().lower())


def to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v).strip())
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_date(v: str) -> str | None:
    if not v:
        return None
    s = str(v).strip()
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d/%m/%y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def is_test_row(rowtext: str) -> bool:
    return "<test lead" in rowtext.lower()


def is_paid(status: str) -> bool:
    """Considera venda apenas status pago/aprovado. Sem coluna Status -> conta."""
    sn = norm(status)
    if not sn:
        return True
    return any(k in sn for k in ("pag", "aprov", "paid", "conclu", "complet", "ativ"))


def is_main_product(prod: str) -> bool:
    return norm(prod).startswith(MAIN_PRODUCT_PREFIX)


# ----- Máscara de PII (a página publicada é pública) ----- #
def mask_email(e: str) -> str:
    e = (e or "").strip()
    if "@" not in e:
        return "—"
    user, dom = e.split("@", 1)
    keep = user[:2] if len(user) > 2 else user[:1]
    return f"{keep}****@{dom}"


def first_last_initial(name: str) -> str:
    parts = (name or "").strip().split()
    if not parts:
        return "—"
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][:1]}."


# --------------------------------------------------------------------------- #
# Indexação de colunas (por nome, com fallback posicional)
# --------------------------------------------------------------------------- #
def header_index(header, wanted, fallback):
    idx = {}
    hn = [norm(h) for h in header]
    for key, aliases in wanted.items():
        found = None
        for a in aliases:
            a = norm(a)
            for i, h in enumerate(hn):
                if h == a or (a and a in h):
                    found = i
                    break
            if found is not None:
                break
        idx[key] = found if found is not None else fallback.get(key)
    return idx


def cell(row, i):
    if i is None or i < 0 or i >= len(row):
        return ""
    return (row[i] or "").strip()


# --------------------------------------------------------------------------- #
# Processamento -> registros brutos
# --------------------------------------------------------------------------- #
def process(meta_rows, sales_rows):
    # ---------------- Aba META ADS ----------------
    # Colunas reais: Day · Campaign Name · Ad Set Name · Ad Name · Amount Spent ·
    #   Impressions · Link Clicks · Landing Page Views · Checkouts Initiated · ...
    mheader = meta_rows[0] if meta_rows else []
    midx = header_index(
        mheader,
        {"day": ["day", "data"], "campaign": ["campaign name", "campaign"],
         "adset": ["ad set name", "adset", "ad set"], "ad": ["ad name"],
         "spent": ["amount spent", "valor gasto", "gasto"], "impr": ["impressions", "impress"],
         "clicks": ["link clicks", "clicks", "cliques"],
         "pv": ["landing page views", "page views", "pageview", "landing"],
         "ck": ["checkouts initiated", "checkouts", "initiate checkout", "checkout"],
         # Link do criativo no Instagram (coluna acrescentada pelo cliente na aba
         # Meta Ads). Usada na aba Relatórios (Top/Piores anúncios) para linkar o
         # anúncio. Aliases cobrem variações do cabeçalho.
         "link": ["creative instagram permalink", "instagram permalink", "permalink",
                  "creative link", "link do anuncio", "link do criativo"]},
        {"day": 0, "campaign": 1, "adset": 2, "ad": 3, "spent": 4, "impr": 5,
         "clicks": 6, "pv": 7, "ck": 8},
    )

    meta = []
    # (campanha, anúncio) normalizados -> (campanha, conjunto) reais do Meta.
    # A chave inclui a CAMPANHA porque o mesmo nome de anúncio (ex. "AD01") se
    # repete em campanhas diferentes; casar só pelo nome do anúncio atribuiria a
    # venda à campanha errada (era o caso da campanha "Bidcap"). Guardar os nomes
    # do Meta também alinha a venda à mesma linha do gasto nas tabelas.
    ad_map = {}
    # Anúncio (nome, ex. "AD07") -> 1 permalink do Instagram. "Qualquer um
    # correlato" ao anúncio serve (o mesmo criativo pode rodar em várias
    # campanhas); guardamos o primeiro link não-vazio encontrado.
    ad_links = {}
    for row in meta_rows[1:]:
        if not any((c or "").strip() for c in row):
            continue
        if is_test_row(" ".join(str(c) for c in row)):
            continue
        camp = cell(row, midx["campaign"]) or "(sem campanha)"
        adset = cell(row, midx["adset"]) or "(sem conjunto)"
        ad = cell(row, midx["ad"]) or "(sem anúncio)"
        key = (norm(camp), norm(ad))
        if key not in ad_map:
            ad_map[key] = (camp, adset)
        link = cell(row, midx["link"])
        if link and ad not in ad_links:
            ad_links[ad] = link
        meta.append({
            "d": parse_date(cell(row, midx["day"])),
            "camp": camp, "adset": adset, "ad": ad,
            "sp": round(to_float(cell(row, midx["spent"])), 4),
            "im": to_float(cell(row, midx["impr"])),
            "cl": to_float(cell(row, midx["clicks"])),
            "pv": to_float(cell(row, midx["pv"])),
            "ck": to_float(cell(row, midx["ck"])),
        })

    # ---------------- Aba COMPRADORES ----------------
    # Colunas reais: Data de Criação · Cliente / Nome · Cliente / E-mail · Produto ·
    #   Valor da Venda · UTM Content · UTM Campaign · UTM Medium · UTM Source · Status
    sheader = sales_rows[0] if sales_rows else []
    sidx = header_index(
        sheader,
        {"created": ["data de criacao", "data", "created", "created_time"],
         "name": ["cliente / nome", "nome", "full_name"],
         "email": ["cliente / e-mail", "e-mail", "email"],
         "prod": ["produto", "product"],
         # Receita do funil = coluna "Faturamento" (Valor + orderbumps por comprador),
         # por isso "faturamento" vem ANTES de "valor" nos aliases.
         "val": ["faturamento", "valor da venda", "valor", "value", "amount"],
         "utm_content": ["utm content", "utm_content"],
         "utm_campaign": ["utm campaign", "utm_campaign"],
         "utm_medium": ["utm medium", "utm_medium"],
         "status": ["status"]},
        # Fallback posicional só p/ colunas que existem nesta planilha
        # (Produto·Nome·Email·Data·Valor·Taxas·Faturamento). Sem fallback p/
        # utm_*/status: a planilha não tem essas colunas, então ausência -> vazio
        # (evita casar por posição com Taxas/Faturamento). Se um dia houver colunas
        # UTM nomeadas, o match por nome acima as detecta normalmente.
        {"created": 3, "name": 1, "email": 2, "prod": 0, "val": 6},
    )

    sales = []
    for row in sales_rows[1:]:
        if not any((c or "").strip() for c in row):
            continue
        if is_test_row(" ".join(str(c) for c in row)):
            continue
        if not COUNT_ALL_AS_PAID and not is_paid(cell(row, sidx["status"])):
            continue
        prod = cell(row, sidx["prod"])
        # O identificador do anúncio no Meta (Ad Name = "AD01", "AD02"...) vem do
        # UTM Content. O UTM Term carrega o POSICIONAMENTO (Instagram_Reels/Feed/
        # Stories), não o anúncio — por isso o match é pelo UTM Content.
        ad = cell(row, sidx["utm_content"]) or "(sem anúncio)"
        sale_camp = cell(row, sidx["utm_campaign"]) or "(sem campanha)"
        main = is_main_product(prod)
        # Match com o Meta = campanha + anúncio juntos (o mesmo Ad Name se repete
        # entre campanhas; casar só pelo anúncio atribui a venda à campanha errada).
        meta_key = (norm(sale_camp), norm(ad))
        meta_hit = ad_map.get(meta_key)
        # Atribuição ao tráfego rastreado: produto principal OU par campanha+anúncio
        # que existe no Meta (captura orderbumps/upsells que carregam a UTM do anúncio).
        attributed = main or (meta_hit is not None)
        if not attributed:
            continue
        # Quando casa com o Meta, usa a campanha/conjunto REAIS do Meta (mantém a
        # venda na mesma linha do gasto nas tabelas). Senão, usa as UTMs da venda.
        if meta_hit is not None:
            camp, adset = meta_hit
        else:
            camp = sale_camp
            adset = cell(row, sidx["utm_medium"]) or "(sem conjunto)"
        sales.append({
            "d": parse_date(cell(row, sidx["created"])),
            "camp": camp, "adset": adset, "ad": ad,
            "prod": prod or "—",
            "val": round(to_float(cell(row, sidx["val"])), 2),
            "main": 1 if main else 0,
            # meta=1 quando a venda casa com campanha+anúncio real do Meta (tráfego
            # pago). Vendas do produto principal sem esse match (orgânico/direto, ou
            # UTM sem anúncio identificável) têm meta=0.
            "meta": 1 if meta_hit is not None else 0,
            "nm": first_last_initial(cell(row, sidx["name"])),
            "em": mask_email(cell(row, sidx["email"])),
        })

    dates = sorted({d for d in ([m["d"] for m in meta if m["d"]] + [s["d"] for s in sales if s["d"]])})
    now_brt = datetime.now(BRT)
    return {
        "build": {
            "generated_at_brt": now_brt.strftime("%d/%m/%Y %H:%M"),
            "build_id": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "today": now_brt.strftime("%Y-%m-%d"),
            "date_min": dates[0] if dates else None,
            "date_max": dates[-1] if dates else None,
            "tax_factor": TAX_FACTOR,
            "client_name": CLIENT_NAME,
            "client_sub": CLIENT_SUB,
            "tax_label": TAX_LABEL,
            "main_product": MAIN_PRODUCT,
            "main_product_prefix": MAIN_PRODUCT_PREFIX,
            "ia_worker_url": IA_WORKER_URL,
            # Metas da aba Relatórios (código de cor de CAC/ROAS)
            "cac_target": CAC_TARGET,
            "roas_target": ROAS_TARGET,
            "report_band_low": REPORT_BAND_LOW,
            "report_band_high": REPORT_BAND_HIGH,
        },
        "meta": meta,
        "sales": sales,
        "ad_links": ad_links,
        # Briefings do Gestor por período (gerados por IA 1x/dia via Routine e
        # salvos em build/relatorios.json). Preenchido em process()/main via
        # load_briefings(); fica {} se o arquivo não existir.
        "briefings": {},
    }


# --------------------------------------------------------------------------- #
# Briefings do Gestor (aba Relatórios) — texto gerado por IA 1x/dia
# --------------------------------------------------------------------------- #
def load_briefings(path: str) -> dict:
    """Lê build/relatorios.json (gerado pela Routine diária). Estrutura:
        {"generated_at": "...", "periodos": {"<preset>": {...}, ...}}
    Retorna o dict de períodos (ou {} se o arquivo não existir/for inválido).
    A geração NÃO acontece aqui — este build só lê o texto já pronto, sem
    chamar nenhuma API (custo zero no build/no navegador)."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except (ValueError, OSError):
        return {}


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
def render(data, template_path):
    # A dashboard é montada a partir de arquivos separados (visual x lógica):
    #   template.html          -> esqueleto HTML (com placeholders __STYLES__/__APP_JS__)
    #   identidade-visual.css  -> TODAS as cores (edite aqui p/ mexer só em cor)
    #   estilos.css            -> layout/componentes
    #   app.js                 -> lógica + renderização
    # Esta função só COSTURA os arquivos e injeta os dados; não altera nada deles.
    base = os.path.dirname(os.path.abspath(template_path))
    def readf(name):
        with open(os.path.join(base, name), "r", encoding="utf-8") as f:
            return f.read()
    with open(template_path, "r", encoding="utf-8") as f:
        tpl = f.read()
    styles = readf("identidade-visual.css") + "\n" + readf("estilos.css")
    tpl = tpl.replace("__STYLES__", styles)
    tpl = tpl.replace("__APP_JS__", readf("app.js"))
    tpl = tpl.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    tpl = tpl.replace("__BUILD_ID__", data["build"]["build_id"])
    tpl = tpl.replace("__GENERATED_BRT__", data["build"]["generated_at_brt"])
    return tpl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta-file")
    ap.add_argument("--sales-file")
    ap.add_argument("--template", default="build/template.html")
    ap.add_argument("--out", default="dist/index.html")
    args = ap.parse_args()

    meta_rows = load_rows(EXPORT_URL.format(sid=SPREADSHEET_ID, gid=GID_META), args.meta_file)
    sales_rows = load_rows(EXPORT_URL.format(sid=SPREADSHEET_ID, gid=GID_SALES), args.sales_file)
    data = process(meta_rows, sales_rows)

    # Briefings do Gestor (texto por IA, gerado 1x/dia pela Routine) — lidos do
    # arquivo versionado ao lado do template. Sem chamada de API no build.
    briefings_path = os.path.join(os.path.dirname(os.path.abspath(args.template)), "relatorios.json")
    data["briefings"] = load_briefings(briefings_path)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(render(data, args.template))

    b = data["build"]
    vendas = sum(s["main"] for s in data["sales"])
    fat = sum(s["val"] for s in data["sales"])
    print("== build ok ==", file=sys.stderr)
    print(f"  periodo : {b['date_min']} -> {b['date_max']}", file=sys.stderr)
    print(f"  meta    : {len(data['meta'])} linhas", file=sys.stderr)
    print(f"  sales   : {len(data['sales'])} linhas (funil) · Vendas(principal): {vendas} · Fat: R$ {fat:,.2f}", file=sys.stderr)
    print(f"  out     : {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
