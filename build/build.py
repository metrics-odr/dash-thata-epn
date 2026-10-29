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
# Aba "Google Ads" (opcional) — mesma planilha. Sem GID_GOOGLE a aba some do build.
GID_GOOGLE = getattr(cfg, "GID_GOOGLE", "") or ""
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
# Coluna de faturamento alternativa, EM REAIS (correção manual do cliente sobre
# uma coluna de faturamento quebrada) — opcional. Quando configurada, tem
# prioridade sobre a coluna "val" (dólar) padrão, mas como todo o cálculo
# interno (CAC, ROAS, Ticket) é feito em USD por baixo (só o brl() em app.js
# converte pra exibir — ver CLAUDE.md "Toggle de moeda"), o valor lido dessa
# coluna é convertido BRL->USD pela cotação buscada em fetch_usd_brl_rate()
# antes de entrar em "val". Sem client configurando isso, nada muda.
REVENUE_BRL_ALIASES = getattr(cfg, "REVENUE_BRL_ALIASES", None) or []
FX_RATE_FALLBACK = getattr(cfg, "FX_RATE_FALLBACK", None) or 5.40

# Lista de reembolsos (opcional) — planilha PRÓPRIA (outro SPREADSHEET_ID). Toda
# venda que aparece nela (qualquer Status: Reembolsado / Pedido de reembolso /
# Chargeback) é DESCONTADA de sales[] (e portanto de todas as abas) e passa a
# alimentar a aba "Reembolsos" (refunds[]). Sem GID_REFUNDS a aba some.
REFUNDS_SPREADSHEET_ID = getattr(cfg, "REFUNDS_SPREADSHEET_ID", "") or ""
GID_REFUNDS = getattr(cfg, "GID_REFUNDS", "") or ""

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


def fetch_usd_brl_rate(fallback: float) -> tuple[float, bool]:
    """Cotação USD->BRL para converter uma coluna de faturamento em REAIS de
    volta pra dólar no build (ver REVENUE_BRL_ALIASES acima). Mesmas APIs (e
    mesma ordem) do fetchFxRate() do navegador em build/app.js — só que aqui
    roda 1x por build (o runner do GitHub Actions tem internet livre; o
    navegador não recalcula essa conversão, ela já vem pronta no JSON).
    Retorna (rate, is_live) — is_live=False quando caiu no fallback fixo de
    config.py (FX_RATE_FALLBACK), útil pra sinalizar no JSON de saída."""
    for url, path in (
        ("https://api.frankfurter.app/latest?from=USD&to=BRL", ("rates", "BRL")),
        ("https://open.er-api.com/v6/latest/USD", ("rates", "BRL")),
    ):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dash-vsl-bot/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                obj = json.loads(resp.read().decode("utf-8", errors="replace"))
            rate = obj
            for k in path:
                rate = rate.get(k) if isinstance(rate, dict) else None
            rate = float(rate)
            if rate > 0:
                return rate, True
        except Exception:
            continue
    return float(fallback), False


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


PAID_STATUS_KEYWORDS = getattr(
    cfg, "PAID_STATUS_KEYWORDS", ("pag", "aprov", "paid", "conclu", "complet", "ativ")
)


def is_paid(status: str) -> bool:
    """Considera venda apenas status pago/aprovado. Sem coluna Status -> conta.
    Keywords customizáveis por cliente via PAID_STATUS_KEYWORDS em config.py
    (default genérico acima, usado quando o cliente não sobrescreve)."""
    sn = norm(status)
    if not sn:
        return True
    return any(k in sn for k in PAID_STATUS_KEYWORDS)


def is_active_status(status: str) -> bool:
    return norm(status) in ("active", "ativo", "ativa")


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


def norm_origin(o: str) -> str:
    """Origem normalizada (a planilha varia: 'Facebook Ads', 'Facebook-AdsAUTO ALL ...')."""
    n = norm(o)
    if not n:
        return "(sem origem)"
    if n.startswith("facebook"):
        return "Facebook Ads"
    if n.startswith("(sem registro"):
        return "(sem registro)"
    return (o or "").strip()


def parse_date_ord(d) -> int:
    try:
        return datetime.strptime(d, "%Y-%m-%d").toordinal()
    except (TypeError, ValueError):
        return 0


def refund_extra(rec, funnel: int) -> dict:
    """Campos específicos do reembolso (status, oferta, país) que acompanham a venda."""
    return {"st": rec["status"], "off": rec["offer"] or "(sem oferta)",
            "cc": rec["country"] or "(n/d)", "tipo": rec["tipo"] or "(n/d)", "funnel": funnel}


def parse_refunds(refund_rows):
    """Lê a lista de reembolsos -> registros (dict). Qualquer linha da lista conta."""
    if not refund_rows:
        return []
    h = header_index(
        refund_rows[0],
        {"date": ["data"], "status": ["status"],
         "code": ["cod transacao", "cod. transacao", "codigo transacao"],
         "prod": ["produto"], "tipo": ["tipo"], "name": ["comprador(a)", "comprador", "nome"],
         "email": ["e-mail", "email"], "country": ["pais"], "orig": ["valor compra (orig"],
         "val_usd": ["fat. liquido (usd)", "faturamento liquido (usd)"],
         # a coluna de faturamento em reais da lista de reembolsos às vezes vem
         # com o cabeçalho quebrado ("#REF!") — mesmo conteúdo de "Faturamento Fixo".
         "val_brl": list(REVENUE_BRL_ALIASES) + ["#ref!"],
         "pay": ["metodo pagto", "metodo de pagamento"], "parc": ["parcelas"],
         "origem": ["origem"], "utm_detail": ["detalhe utm", "utm detail"],
         "offer": ["nome oferta"]},
        {})
    out = []
    for row in refund_rows[1:]:
        if not any((c or "").strip() for c in row) or is_test_row(" ".join(str(c) for c in row)):
            continue
        out.append({
            "d": parse_date(cell(row, h["date"])),
            "status": cell(row, h["status"]) or "Reembolsado",
            "code": cell(row, h["code"]),
            "prod": cell(row, h["prod"]),
            "tipo": cell(row, h["tipo"]),
            "name": cell(row, h["name"]),
            "email": cell(row, h["email"]),
            "email_n": norm(cell(row, h["email"])),
            "country": cell(row, h["country"]),
            "orig": to_float(cell(row, h["orig"])),
            "val_usd_raw": cell(row, h["val_usd"]),
            "val_brl_raw": cell(row, h["val_brl"]),
            "pay": cell(row, h["pay"]), "parc": cell(row, h["parc"]),
            "origem": cell(row, h["origem"]),
            "utm_detail": cell(row, h["utm_detail"]),
            "offer": cell(row, h["offer"]),
        })
    return out


# --------------------------------------------------------------------------- #
# Processamento -> registros brutos
# --------------------------------------------------------------------------- #
def process(meta_rows, sales_rows, fx_rate: float = FX_RATE_FALLBACK, fx_rate_live: bool = False,
            google_rows=None, refund_rows=None):
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
    # Status ATIVO/PAUSADO de cada linha (campanha/conjunto/anúncio) vai direto
    # em cada registro de `meta` (campos cs/as/ds abaixo) — cru, sem agregação
    # nenhuma aqui. Nomes de anúncio/conjunto se repetem entre campanhas
    # diferentes (ex. "AD03" existindo em várias campanhas como anúncios
    # DISTINTOS, com Ad ID diferente) — agregar por nome no build (como uma
    # versão anterior fazia) faz o status de um anúncio ativo numa campanha
    # vazar por engano para um anúncio pausado com o mesmo nome em outra
    # campanha. Por isso o "mais recente" é resolvido no navegador (build/app.js),
    # escopado pela MESMA seleção de campanha/conjunto (drill-down) que já
    # filtra as métricas da tabela — nunca misturando linhas de campanhas
    # diferentes — e ignorando o filtro de DATA da topbar (o status usa sempre
    # a linha mais recente disponível, não só as do período selecionado).
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
        camp_st = cell(row, midx["campaign_status"])
        adset_st = cell(row, midx["adset_status"])
        ad_st = cell(row, midx["ad_status"])
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
            # Status cru desta linha (None = coluna vazia/sem info nesta linha,
            # não conta na resolução do "mais recente" feita em app.js).
            "cs": is_active_status(camp_st) if camp_st else None,
            "as": is_active_status(adset_st) if adset_st else None,
            "ds": is_active_status(ad_st) if ad_st else None,
        })

    # ---------------- Aba GOOGLE ADS ----------------
    # Colunas: Day · Campaign Name · Ad Group · Ad Name · Cost · Impressions · Clicks
    # (a aba só vai até Cliques — sem Page Views/Checkouts, que ficam em branco).
    # Mesma lógica de cruzamento do Meta: campanha + anúncio (Ad Name = utm_content).
    gheader = google_rows[0] if google_rows else []
    gidx = header_index(
        gheader,
        {"day": ["day", "data"], "campaign": ["campaign name", "campaign", "campanha"],
         "adset": ["ad group name", "ad group", "grupo de anuncios"], "ad": ["ad name"],
         "spent": ["cost", "custo", "amount spent"], "impr": ["impressions", "impress"],
         "clicks": ["clicks", "cliques"]},
        {"day": 0, "campaign": 1, "adset": 2, "ad": 3, "spent": 4, "impr": 5, "clicks": 6},
    )
    gads = []
    gad_map = {}
    for row in (google_rows or [])[1:]:
        if not any((c or "").strip() for c in row):
            continue
        if is_test_row(" ".join(str(c) for c in row)):
            continue
        camp = cell(row, gidx["campaign"]) or "(sem campanha)"
        adset = cell(row, gidx["adset"]) or "(sem grupo)"
        ad = cell(row, gidx["ad"]) or "(sem anúncio)"
        gkey = (norm(camp), norm(ad))
        if gkey not in gad_map:
            gad_map[gkey] = (camp, adset)
        gads.append({
            "d": parse_date(cell(row, gidx["day"])),
            "camp": camp, "adset": adset, "ad": ad,
            "sp": round(to_float(cell(row, gidx["spent"])), 4),
            "im": to_float(cell(row, gidx["impr"])),
            "cl": to_float(cell(row, gidx["clicks"])),
            # Sem Page Views/Checkouts/vídeo nesta aba (em branco por enquanto).
            "pv": 0, "ck": 0, "vv3": 0, "vv50": 0, "vv95": 0,
            "cs": None, "as": None, "ds": None,
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
         # Coluna alternativa de faturamento EM REAIS (opcional, ver
         # REVENUE_BRL_ALIASES em config.py) — correção manual do cliente
         # sobre a coluna de faturamento quebrada. Quando presente, tem
         # prioridade sobre "val" acima, mas precisa ser convertida BRL->USD
         # (feito abaixo, com fx_rate) antes de virar o "val" de cada venda.
         "val_brl": REVENUE_BRL_ALIASES,
         "utm_content": ["utm content", "utm_content"],
         "utm_campaign": ["utm campaign", "utm_campaign"],
         "utm_medium": ["utm medium", "utm_medium"],
         # Fallback p/ planilhas sem colunas UTM próprias: 1 campo concatenado
         # (ver split_utm_detail acima).
         "utm_detail": ["detalhe utm", "utm detail", "detalhe do utm"],
         "status": ["status"],
         # usados só p/ casar com a lista de reembolsos e p/ as análises da aba
         # Reembolsos (taxa por forma de pagamento/parcelas/origem)
         "code": ["cod transacao", "cod. transacao", "codigo transacao"],
         "orig": ["valor compra (orig"],
         "pay": ["metodo pagto", "metodo de pagamento"], "parc": ["parcelas"],
         "origem": ["origem"]},
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
        # Só tenta o Google se não casou com o Meta (Meta tem prioridade).
        gads_hit = None if meta_hit is not None else gad_map.get(meta_key)
        val_brl_raw = cell(row, sidx["val_brl"]) if sidx.get("val_brl") is not None else ""
        if val_brl_raw:
            # Coluna de correção do cliente vem em REAIS -> converte pra USD
            # (todo o resto do funil, Gasto do Meta incluso, é nativo em
            # dólar por baixo; ver REVENUE_BRL_ALIASES/fetch_usd_brl_rate acima).
            val = to_float(val_brl_raw) / fx_rate
            # Guarda também o valor EXATO em reais (sem passar pela cotação)
            # pra exibição em modo BRL no navegador: converter BRL->USD no build
            # (cotação do momento do build) e depois USD->BRL de novo na tela
            # (cotação do momento em que o visitante abriu a página, cacheada
            # até 6h) faz um round-trip com DUAS cotações diferentes — o total
            # exibido nunca bate exatamente com a soma de "Faturamento Fixo" da
            # planilha. Guardando o valor original em reais, o navegador usa
            # ele direto (sem reconverter) sempre que a moeda selecionada for
            # BRL, batendo 1:1 com a planilha.
            val_brl_exact = to_float(val_brl_raw)
        else:
            val = to_float(cell(row, sidx["val"]))
            val_brl_exact = None
        det_term = _det_term if use_utm_detail else ""
        raw_rows.append({
            "d": parse_date(cell(row, sidx["created"])),
            "code": cell(row, sidx["code"]), "orig": to_float(cell(row, sidx["orig"])),
            "pl": det_term or "(sem posicionamento)",
            "pay": cell(row, sidx["pay"]) or "(n/d)", "parc": cell(row, sidx["parc"]) or "(n/d)",
            "org": norm_origin(cell(row, sidx["origem"])),
            "prod": prod, "main": main, "upsell": upsell,
            "sale_camp": sale_camp, "ad": ad, "adset_own": adset_own, "meta_hit": meta_hit, "gads_hit": gads_hit,
            "email_n": norm(cell(row, sidx["email"])),
            "val": val,
            "val_brl_exact": val_brl_exact,
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
                camp, adset, ch = r["meta_hit"][0], r["meta_hit"][1], "meta"
            elif r["gads_hit"] is not None:
                camp, adset, ch = r["gads_hit"][0], r["gads_hit"][1], "gads"
            else:
                camp, adset, ch = r["sale_camp"], r["adset_own"], None
            email_attr[r["email_n"]] = (camp, adset, r["ad"], ch, r["pl"])

    # ---------------- Lista de REEMBOLSOS ----------------
    # Casa cada reembolso com a venda correspondente: 1º pelo código da transação;
    # sem código na venda (vendas antigas da planilha não têm), por e-mail + produto,
    # escolhendo a de valor/data mais próximos. A venda casada SAI de sales[] (vira
    # refunds[]), então Vendas/CAC/Faturamento/ROAS de TODAS as abas já saem líquidos.
    refund_recs = parse_refunds(refund_rows)
    by_code = {r["code"]: r for r in raw_rows if r["code"]}
    by_email = {}
    for r in raw_rows:
        if not r["code"] and r["email_n"]:
            by_email.setdefault((r["email_n"], norm(r["prod"])), []).append(r)
    n_matched = 0
    for rec in refund_recs:
        hit = by_code.get(rec["code"]) if rec["code"] else None
        if hit is not None and hit.get("refund") is not None:
            hit = None
        if hit is None and rec["email_n"]:
            cands = [x for x in by_email.get((rec["email_n"], norm(rec["prod"])), []) if x.get("refund") is None]
            if cands:
                rd = parse_date_ord(rec["d"])
                hit = min(cands, key=lambda x: (abs(x["orig"] - rec["orig"]), abs(parse_date_ord(x["d"]) - rd)))
        rec["hit"] = hit
        if hit is not None:
            hit["refund"] = rec
            n_matched += 1

    def attribution(r):
        if r["meta_hit"] is not None:
            return r["meta_hit"][0], r["meta_hit"][1], r["ad"], r["pl"], "meta"
        if r["gads_hit"] is not None:
            return r["gads_hit"][0], r["gads_hit"][1], r["ad"], r["pl"], "gads"
        if r["upsell"] and r["email_n"] in email_attr:
            c, a, ad_, ch_, pl_ = email_attr[r["email_n"]]
            return c, a, ad_, pl_, ch_
        return r["sale_camp"], r["adset_own"], r["ad"], r["pl"], None

    sales = []
    refunds = []
    for r in raw_rows:
        camp, adset, ad_out, pl_out, ch = attribution(r)
        val = r["val"]
        prod_out = r["prod"] or "—"
        if r["upsell"]:
            # As 2 ofertas (upsell caro / downsell barato) vêm com o MESMO texto de
            # produto na planilha — só o valor da venda diferencia qual foi aceita.
            prod_out = UPSELL_USL_LABEL if val >= UPSELL_SPLIT_VALUE else UPSELL_DSL_LABEL
        rec_out = {
            "d": r["d"],
            "camp": camp, "adset": adset, "ad": ad_out, "pl": pl_out,
            "prod": prod_out,
            "val": round(val, 2),
            # Valor original EM REAIS (sem round-trip de cotação) quando a venda
            # veio de REVENUE_BRL_ALIASES ("Faturamento Fixo") — usado pelo
            # navegador pra exibir o Faturamento/Ticket em BRL batendo 1:1 com a
            # planilha, em vez de reconverter "val" (USD) por uma cotação diferente
            # da usada aqui no build. None quando a venda usou o fallback em USD.
            "val_brl": round(r["val_brl_exact"], 2) if r["val_brl_exact"] is not None else None,
            # Vendas/CAC/ConvCHK/Ticket são só do produto principal — upsell/downsell
            # entram no Faturamento/ROAS (val acima) mas não em "main".
            "main": 1 if r["main"] else 0,
            # meta=1 quando a venda (ou, p/ upsell/downsell, a compra do produto
            # principal do mesmo comprador) casa com campanha+anúncio real do Meta.
            "meta": 1 if ch == "meta" else 0,
            # gads=1 quando casa (campanha+anúncio) com a aba Google Ads — mesma
            # lógica do flag meta (mutuamente exclusivos; Meta tem prioridade).
            "gads": 1 if ch == "gads" else 0,
            "org": r["org"], "pay": r["pay"], "parc": r["parc"],
            "nm": r["nm"], "em": r["em"],
        }
        if r.get("refund") is None:
            sales.append(rec_out)
        else:
            rec_out.update(refund_extra(r["refund"], funnel=1))
            refunds.append(rec_out)

    # Reembolsos sem venda do funil correspondente (outros produtos do cliente —
    # a planilha é de vários funis — ou vendas fora do período lido): entram só
    # na aba Reembolsos, com a UTM da própria linha da lista.
    for rec in refund_recs:
        if rec["hit"] is not None:
            continue
        prod = rec["prod"]
        main = is_main_product(prod)
        upsell = (not main) and is_upsell_product(prod)
        if use_utm_detail or rec["utm_detail"]:
            mdm, cmp_, term, content = split_utm_detail(rec["utm_detail"])
        else:
            mdm = cmp_ = term = content = ""
        meta_hit = ad_map.get((norm(cmp_), norm(content)))
        gads_hit = None if meta_hit is not None else gad_map.get((norm(cmp_), norm(content)))
        camp = (meta_hit or gads_hit or (cmp_, mdm))[0] or "(sem campanha)"
        adset = (meta_hit or gads_hit or (cmp_, mdm))[1] or "(sem conjunto)"
        if rec["email_n"] in email_attr and not cmp_:
            camp, adset, content, ch_, term = (email_attr[rec["email_n"]][0], email_attr[rec["email_n"]][1],
                                              email_attr[rec["email_n"]][2], email_attr[rec["email_n"]][3],
                                              email_attr[rec["email_n"]][4])
            meta_hit = True if ch_ == "meta" else None
            gads_hit = True if ch_ == "gads" else None
        if rec["val_brl_raw"]:
            val_brl = to_float(rec["val_brl_raw"]); val = val_brl / fx_rate
        else:
            val = to_float(rec["val_usd_raw"]); val_brl = None
        prod_out = prod or "—"
        if upsell:
            prod_out = UPSELL_USL_LABEL if val >= UPSELL_SPLIT_VALUE else UPSELL_DSL_LABEL
        refunds.append(dict({
            "d": rec["d"], "camp": camp, "adset": adset, "ad": content or "(sem anúncio)",
            "pl": term or "(sem posicionamento)", "prod": prod_out,
            "val": round(val, 2), "val_brl": round(val_brl, 2) if val_brl is not None else None,
            "main": 1 if main else 0,
            "meta": 1 if meta_hit else 0, "gads": 1 if gads_hit else 0,
            "org": norm_origin(rec["origem"]), "pay": rec["pay"] or "(n/d)", "parc": rec["parc"] or "(n/d)",
            "nm": first_last_initial(rec["name"]), "em": mask_email(rec["email"]),
        }, **refund_extra(rec, funnel=1 if (main or upsell) else 0)))

    dates = sorted({d for d in ([m["d"] for m in meta + gads if m["d"]] + [s["d"] for s in sales + refunds if s["d"]])})
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
            "upsell_usl_label": UPSELL_USL_LABEL,
            "upsell_dsl_label": UPSELL_DSL_LABEL,
            "ia_worker_url": IA_WORKER_URL,
            # Metas da aba Relatórios (código de cor de CAC/ROAS)
            "cac_target": CAC_TARGET,
            "roas_target": ROAS_TARGET,
            "report_band_low": REPORT_BAND_LOW,
            "report_band_high": REPORT_BAND_HIGH,
            # Cotação USD/BRL usada no build para converter a coluna de
            # faturamento em reais (REVENUE_BRL_ALIASES) de volta pra dólar —
            # só informativo (auditoria); não usado no navegador. is_live=False
            # quando a busca falhou e caiu no fallback fixo de config.py.
            "fx_rate_build": fx_rate,
            "fx_rate_build_is_live": fx_rate_live,
        },
        "meta": meta,
        "gads": gads,
        "sales": sales,
        "refunds": refunds,
        "has_refunds": bool(refund_rows),
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


def load_refund_rows(local=None):
    """Lista de reembolsos (planilha própria). Falha aqui NÃO derruba o build, mas
    avisa alto: sem a lista, os reembolsos voltam a contar como venda."""
    if not local and not (REFUNDS_SPREADSHEET_ID and GID_REFUNDS):
        return None
    try:
        return load_rows(EXPORT_URL.format(sid=REFUNDS_SPREADSHEET_ID, gid=GID_REFUNDS), local)
    except Exception as e:
        print(f"AVISO: falha ao ler a lista de reembolsos ({e}); reembolsos NÃO descontados neste build.",
              file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta-file")
    ap.add_argument("--sales-file")
    ap.add_argument("--google-file")
    ap.add_argument("--refunds-file")
    ap.add_argument("--template", default="build/template.html")
    ap.add_argument("--out", default="dist/index.html")
    args = ap.parse_args()

    meta_rows = load_rows(EXPORT_URL.format(sid=SPREADSHEET_ID, gid=GID_META), args.meta_file)
    sales_rows = load_rows(EXPORT_URL.format(sid=SPREADSHEET_ID, gid=GID_SALES), args.sales_file)
    google_rows = None
    if args.google_file or GID_GOOGLE:
        try:
            google_rows = load_rows(EXPORT_URL.format(sid=SPREADSHEET_ID, gid=GID_GOOGLE), args.google_file)
        except Exception as e:  # aba do Google não pode derrubar o build inteiro
            print(f"AVISO: falha ao ler a aba Google Ads ({e}); seguindo sem ela.", file=sys.stderr)

    refund_rows = load_refund_rows(args.refunds_file)

    # Só busca cotação (rede externa) se o cliente configurou uma coluna de
    # faturamento em reais (ver REVENUE_BRL_ALIASES) — clientes sem isso não
    # precisam da conversão e o build segue 100% offline como antes.
    if REVENUE_BRL_ALIASES:
        fx_rate, fx_rate_live = fetch_usd_brl_rate(FX_RATE_FALLBACK)
        print(f"  cotacao : 1 USD = {fx_rate:.4f} BRL ({'ao vivo' if fx_rate_live else 'fallback fixo'})", file=sys.stderr)
    else:
        fx_rate, fx_rate_live = FX_RATE_FALLBACK, False

    data = process(meta_rows, sales_rows, fx_rate, fx_rate_live, google_rows, refund_rows)

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
    print(f"  google  : {len(data['gads'])} linhas · vendas atribuídas: {sum(s['gads'] for s in data['sales'])}", file=sys.stderr)
    print(f"  sales   : {len(data['sales'])} linhas (funil) · Vendas(principal): {vendas} · Fat: US$ {fat:,.2f}", file=sys.stderr)
    rf = data["refunds"]
    print(f"  reembolsos: {len(rf)} ({sum(r['funnel'] for r in rf)} do funil) · descontados de sales[]", file=sys.stderr)
    print(f"  out     : {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
