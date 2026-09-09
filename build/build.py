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
# Upsell/downsell pós-compra (opcional — ver comentários em config.example.py)
UPSELL_PRODUCT_PREFIX = getattr(cfg, "UPSELL_PRODUCT_PREFIX", "") or ""
UPSELL_SPLIT_VALUE = getattr(cfg, "UPSELL_SPLIT_VALUE", 0.0) or 0.0
UPSELL_USL_LABEL = getattr(cfg, "UPSELL_USL_LABEL", "") or "Upsell"
UPSELL_DSL_LABEL = getattr(cfg, "UPSELL_DSL_LABEL", "") or "Downsell"

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


def is_active_status(status: str) -> bool:
    return norm(status) in ("active", "ativo", "ativa")


def _flatten_active_by_name(status_by_camp_name):
    """{(campanha, nome): (day, status)} -> {nome: ativo} agregando por nome
    (OR entre campanhas que colidem no mesmo nome de conjunto/anúncio)."""
    out = {}
    for (_camp, name), (_day, status) in status_by_camp_name.items():
        out[name] = out.get(name, False) or is_active_status(status)
    return out


def is_main_product(prod: str) -> bool:
    return norm(prod).startswith(MAIN_PRODUCT_PREFIX)


def is_upsell_product(prod: str) -> bool:
    return bool(UPSELL_PRODUCT_PREFIX) and norm(prod).startswith(UPSELL_PRODUCT_PREFIX)


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


# Algumas planilhas de Compradores não têm utm_campaign/utm_medium/utm_content em
# colunas próprias — só um campo único concatenado (ex. "Detalhe UTM"). Nesses
# casos, o padrão observado é: os "|" que fazem parte do NOME da campanha/conjunto
# (convenção do cliente de usar " | " como separador visual dentro do nome) vêm
# sempre com espaço nos dois lados; o "|" que separa de fato um parâmetro UTM do
# próximo não tem espaço nos dois lados. Faz o split só nesse segundo tipo.
_UTM_DETAIL_SPLIT = re.compile(r"(?<!\s)\|(?!\s)")


def split_utm_detail(raw: str) -> tuple[str, str, str, str]:
    """"medium|campaign|term|content" (ordem observada: Ad Set|Campaign|Posicionamento|Ad Name)."""
    parts = [p.strip() for p in _UTM_DETAIL_SPLIT.split(raw or "")]
    parts += [""] * (4 - len(parts))
    return parts[0], parts[1], parts[2], parts[3]


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
         # Video views usados só nas taxas HR/BR/ER da tabela de Anúncios
         # (build/app.js) — opcionais, sem fallback posicional, mesmo motivo
         # do "impr" acima (planilhas sem essas colunas ficam com "--").
         "vv3": ["3-second video views", "3 second video views"],
         "vv50": ["video watches at 50%", "video watches 50%"],
         "vv95": ["video watches at 95%", "video watches 95%"],
         # Link do criativo no Instagram (coluna acrescentada pelo cliente na aba
         # Meta Ads). Usada na aba Relatórios (Top/Piores anúncios) para linkar o
         # anúncio. Aliases cobrem variações do cabeçalho.
         "link": ["creative instagram permalink", "instagram permalink", "permalink",
                  "creative link", "link do anuncio", "link do criativo"],
         # Status ATIVO/PAUSADO de cada nível (opcional — planilhas sem essas
         # colunas simplesmente não mostram o indicativo). Usado só para o
         # "sinal" visual ao lado do nome nas tabelas de otimização; não afeta
         # nenhum cálculo/filtro.
         "campaign_status": ["campaign status", "status da campanha"],
         "adset_status": ["ad set status", "adset status", "status do conjunto"],
         "ad_status": ["ad status", "status do anuncio"]},
        # Sem fallback posicional p/ "impr": algumas planilhas não têm Impressions
        # (o build funciona sem, CPM/CTR ficam "--"); com fallback fixo, a ausência
        # da coluna faria "impr" apontar por engano p/ Link Clicks (deslocamento).
        {"day": 0, "campaign": 1, "adset": 2, "ad": 3, "spent": 4,
         "clicks": 6, "pv": 7, "ck": 8},
    )

    meta = []
    # Status (ativo/pausado) mais recente de cada campanha/conjunto/anúncio —
    # a planilha repete o status em toda linha diária, então guarda-se o de
    # maior data por chave. Conjunto/anúncio são rastreados por (campanha, nome)
    # — não só pelo nome — porque nomes de anúncio (e, potencialmente, de
    # conjunto) se repetem entre campanhas diferentes (ex. "AD03" existindo em
    # duas campanhas distintas); rastrear só por nome faz o status de um
    # anúncio pausado numa campanha vazar e sobrescrever o de um anúncio ativo
    # com o mesmo nome em outra campanha.
    camp_status, adset_status, ad_status = {}, {}, {}
    def _track_status(store, key, day, status):
        if not status:
            return
        prev = store.get(key)
        if prev is None or (day or "") >= (prev[0] or ""):
            store[key] = (day, status)
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
        day = parse_date(cell(row, midx["day"]))
        _track_status(camp_status, camp, day, cell(row, midx["campaign_status"]))
        _track_status(adset_status, (norm(camp), adset), day, cell(row, midx["adset_status"]))
        _track_status(ad_status, (norm(camp), ad), day, cell(row, midx["ad_status"]))
        meta.append({
            "d": day,
            "camp": camp, "adset": adset, "ad": ad,
            "sp": round(to_float(cell(row, midx["spent"])), 4),
            "im": to_float(cell(row, midx["impr"])),
            "cl": to_float(cell(row, midx["clicks"])),
            "pv": to_float(cell(row, midx["pv"])),
            "ck": to_float(cell(row, midx["ck"])),
            "vv3": to_float(cell(row, midx["vv3"])),
            "vv50": to_float(cell(row, midx["vv50"])),
            "vv95": to_float(cell(row, midx["vv95"])),
        })

    # ---------------- Aba COMPRADORES ----------------
    # Colunas reais: Data de Criação · Cliente / Nome · Cliente / E-mail · Produto ·
    #   Valor da Venda · UTM Content · UTM Campaign · UTM Medium · UTM Source · Status
    sheader = sales_rows[0] if sales_rows else []
    sidx = header_index(
        sheader,
        {"created": ["data de criacao", "data", "created", "created_time"],
         "name": ["cliente / nome", "comprador(a)", "comprador", "nome", "full_name"],
         "email": ["cliente / e-mail", "e-mail", "email"],
         "prod": ["produto", "product"],
         # Receita do funil = coluna de faturamento líquido EM DÓLAR (Valor +
         # orderbumps por comprador). Gasto do Meta Ads e todo cálculo interno
         # (CAC, ROAS, Ticket) são em USD por baixo — só o brl() em app.js
         # converte pela cotação ao formatar (ver CLAUDE.md "Toggle de moeda").
         # Por isso "val" TEM que vir de uma coluna em dólar: "fat. liquido
         # (usd)" cobre o cabeçalho real "Fat. líquido (USD)" — tem que vir
         # ANTES de "valor" nos aliases, senão casa por engano com "Valor
         # compra (orig.)" (que tem "valor" como substring e aparece antes na
         # planilha). NUNCA usar a coluna "(BRL)" aqui: ela é o mesmo valor
         # reconvertido pra reais e, neste cliente, vem quebrada com "#REF!"
         # em parte das vendas — além de, mesmo quando preenchida, misturar
         # moeda com o resto do cálculo (double-conversion: BRL tratado como
         # USD e depois multiplicado de novo pela cotação na exibição).
         "val": ["fat. liquido (usd)", "faturamento liquido (usd)",
                 "faturamento liquido", "faturamento",
                 "valor da venda", "valor", "value", "amount"],
         "utm_content": ["utm content", "utm_content"],
         "utm_campaign": ["utm campaign", "utm_campaign"],
         "utm_medium": ["utm medium", "utm_medium"],
         # Fallback p/ planilhas sem colunas UTM próprias: 1 campo concatenado
         # (ver split_utm_detail acima).
         "utm_detail": ["detalhe utm", "utm detail", "detalhe do utm"],
         "status": ["status"]},
        # Fallback posicional só p/ colunas que existem nesta planilha
        # (Produto·Nome·Email·Data·Valor·Taxas·Faturamento). Sem fallback p/
        # utm_*/status: a planilha não tem essas colunas, então ausência -> vazio
        # (evita casar por posição com Taxas/Faturamento). Se um dia houver colunas
        # UTM nomeadas, o match por nome acima as detecta normalmente.
        {"created": 3, "name": 1, "email": 2, "prod": 0, "val": 6},
    )

    # Se não há colunas utm_campaign/utm_content nomeadas mas há um campo único
    # ("Detalhe UTM"), usa o split por linha (ver split_utm_detail).
    use_utm_detail = (sidx["utm_campaign"] is None and sidx["utm_content"] is None
                       and sidx["utm_detail"] is not None)

    # 1ª passada: parseia todas as linhas pagas do funil (produto principal OU
    # upsell/downsell dele) e resolve o match direto com o Meta pela UTM própria.
    raw_rows = []
    for row in sales_rows[1:]:
        if not any((c or "").strip() for c in row):
            continue
        if is_test_row(" ".join(str(c) for c in row)):
            continue
        if not COUNT_ALL_AS_PAID and not is_paid(cell(row, sidx["status"])):
            continue
        prod = cell(row, sidx["prod"])
        if use_utm_detail:
            det_medium, det_campaign, _det_term, det_content = split_utm_detail(cell(row, sidx["utm_detail"]))
        # O identificador do anúncio no Meta (Ad Name = "AD01", "AD02"...) vem do
        # UTM Content. O UTM Term carrega o POSICIONAMENTO (Instagram_Reels/Feed/
        # Stories), não o anúncio — por isso o match é pelo UTM Content.
        ad = (det_content if use_utm_detail else cell(row, sidx["utm_content"])) or "(sem anúncio)"
        sale_camp = (det_campaign if use_utm_detail else cell(row, sidx["utm_campaign"])) or "(sem campanha)"
        adset_own = (det_medium if use_utm_detail else cell(row, sidx["utm_medium"])) or "(sem conjunto)"
        main = is_main_product(prod)
        upsell = (not main) and is_upsell_product(prod)
        if not (main or upsell):
            continue
        # Match com o Meta = campanha + anúncio juntos (o mesmo Ad Name se repete
        # entre campanhas; casar só pelo anúncio atribui a venda à campanha errada).
        meta_key = (norm(sale_camp), norm(ad))
        meta_hit = ad_map.get(meta_key)
        raw_rows.append({
            "d": parse_date(cell(row, sidx["created"])),
            "prod": prod, "main": main, "upsell": upsell,
            "sale_camp": sale_camp, "ad": ad, "adset_own": adset_own, "meta_hit": meta_hit,
            "email_n": norm(cell(row, sidx["email"])),
            "val": to_float(cell(row, sidx["val"])),
            "nm": first_last_initial(cell(row, sidx["name"])),
            "em": mask_email(cell(row, sidx["email"])),
        })

    # Upsell/downsell normalmente não carrega UTM própria (é uma oferta pós-compra
    # na página de obrigado, não um novo clique de anúncio) — por isso herda a
    # campanha/anúncio/atribuição Meta da compra do produto PRINCIPAL do MESMO
    # comprador (mesma sessão de checkout), casando pelo e-mail.
    email_attr = {}
    for r in raw_rows:
        if r["main"] and r["email_n"]:
            if r["meta_hit"] is not None:
                camp, adset, is_meta = r["meta_hit"][0], r["meta_hit"][1], True
            else:
                camp, adset, is_meta = r["sale_camp"], r["adset_own"], False
            email_attr[r["email_n"]] = (camp, adset, r["ad"], is_meta)

    sales = []
    for r in raw_rows:
        if r["meta_hit"] is not None:
            camp, adset, ad_out, is_meta = r["meta_hit"][0], r["meta_hit"][1], r["ad"], True
        elif r["upsell"] and r["email_n"] in email_attr:
            camp, adset, ad_out, is_meta = email_attr[r["email_n"]]
        else:
            camp, adset, ad_out, is_meta = r["sale_camp"], r["adset_own"], r["ad"], False
        val = r["val"]
        prod_out = r["prod"] or "—"
        if r["upsell"]:
            # As 2 ofertas (upsell caro / downsell barato) vêm com o MESMO texto de
            # produto na planilha — só o valor da venda diferencia qual foi aceita.
            prod_out = UPSELL_USL_LABEL if val >= UPSELL_SPLIT_VALUE else UPSELL_DSL_LABEL
        sales.append({
            "d": r["d"],
            "camp": camp, "adset": adset, "ad": ad_out,
            "prod": prod_out,
            "val": round(val, 2),
            # Vendas/CAC/ConvCHK/Ticket são só do produto principal — upsell/downsell
            # entram no Faturamento/ROAS (val acima) mas não em "main".
            "main": 1 if r["main"] else 0,
            # meta=1 quando a venda (ou, p/ upsell/downsell, a compra do produto
            # principal do mesmo comprador) casa com campanha+anúncio real do Meta.
            "meta": 1 if is_meta else 0,
            "nm": r["nm"], "em": r["em"],
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
        # Status ATIVO/PAUSADO (mais recente) de cada campanha/conjunto/anúncio,
        # usado só p/ o indicativo visual nas tabelas de otimização (não tem
        # nenhum efeito em cálculo/filtro). Só entram nomes com status conhecido.
        # adset_status/ad_status são rastreados por (campanha, nome) — ver
        # _track_status acima — porque o mesmo nome pode existir em campanhas
        # diferentes como anúncios/conjuntos DISTINTOS. As tabelas de Conjuntos/
        # Anúncios agregam por nome (mesma lógica que já soma o gasto entre
        # campanhas quando o nome colide), então aqui achatamos para o nome
        # como chave, marcando ATIVO se QUALQUER anúncio/conjunto real com
        # aquele nome estiver ativo — consistente com a agregação de gasto.
        "camp_active": {k: is_active_status(v[1]) for k, v in camp_status.items()},
        "adset_active": _flatten_active_by_name(adset_status),
        "ad_active": _flatten_active_by_name(ad_status),
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
    print(f"  sales   : {len(data['sales'])} linhas (funil) · Vendas(principal): {vendas} · Fat: US$ {fat:,.2f}", file=sys.stderr)
    print(f"  out     : {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
