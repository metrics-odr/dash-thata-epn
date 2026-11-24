# -*- coding: utf-8 -*-
"""
Leitura do Meta Ads direto da Marketing API (substitui a aba "Meta Ads" da planilha).

Devolve `list[list[str]]` com o MESMO cabeçalho/colunas da aba da planilha, então
`process()` em build.py não muda. Somente leitura (ads_read).

Credenciais (nunca no repositório):
  - META_ACCESS_TOKEN : variável de ambiente (Secret do GitHub Actions)
  - META_ACCOUNT_ID   : build/config.py (não é segredo)
"""
from __future__ import annotations

import base64
import html
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

API_VERSION = "v21.0"
BASE = f"https://graph.facebook.com/{API_VERSION}"

HEADER = [
    "Day", "Campaign Name", "Ad Set Name", "Ad Name", "Amount Spent", "Impressions",
    "Link Clicks", "Landing Page Views", "Checkouts Initiated",
    "3-Second Video Views", "Video Watches at 50%", "Video Watches at 95%",
    "Ad ID", "Ad Status", "Ad Set Status", "Campaign Status",
    "Creative Instagram Permalink",
]


# ad_id -> {"th": data-URI da miniatura, "sh": link oficial da prévia (fb.me),
#           "ig": permalink do Instagram, "pv": src do iframe da prévia}
# Preenchido por fetch_meta_rows(); build.py grava em data["ad_media"].
AD_MEDIA: dict[str, dict] = {}


class MetaApiError(RuntimeError):
    pass


def _get(url: str, params: dict | None = None, token: str = "", retries: int = 6) -> dict:
    if params is not None:
        q = dict(params)
        q["access_token"] = token
        url = f"{url}?{urllib.parse.urlencode(q)}"
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                err = json.loads(body).get("error", {})
            except Exception:
                err = {}
            code = err.get("code")
            # 190 = token inválido/expirado: erro claro, sem retry
            if code == 190:
                raise MetaApiError(
                    "META_ACCESS_TOKEN inválido ou expirado (erro 190). Gere um novo token do "
                    "System User no Business Manager e atualize o Secret META_ACCESS_TOKEN."
                ) from None
            last = f"HTTP {e.code} code={code} {err.get('message', body[:200])}"
            # 4/17/32/613 = rate limit; 1/2 = erro transitório
            if code in (4, 17, 32, 613, 80000, 80003, 80004, 80014):
                time.sleep(min(30 * (i + 1), 120))   # throttle da conta: espera e tenta de novo
                continue
            if code in (1, 2) or e.code >= 500:
                time.sleep(2 ** i * 3)
                continue
            raise MetaApiError(last) from None
        except Exception as e:  # rede
            last = str(e)
            time.sleep(2 ** i * 2)
    raise MetaApiError(f"falha após {retries} tentativas: {last}")


def _paginate(path: str, params: dict, token: str):
    page = _get(f"{BASE}/{path}", params, token)
    while True:
        for item in page.get("data", []):
            yield item
        nxt = (page.get("paging") or {}).get("next")
        if not nxt:
            return
        page = _get(nxt, None, token)


def _action(lst, *types) -> float:
    """Soma de `value` das ações cujo action_type está em `types` (1º tipo que existir)."""
    if not lst:
        return 0.0
    by = {a.get("action_type"): float(a.get("value", 0) or 0) for a in lst}
    for t in types:
        if t in by:
            return by[t]
    return 0.0


def _first(lst) -> float:
    return float(lst[0].get("value", 0) or 0) if lst else 0.0


def _status(s) -> str:
    # app.js/build.py só reconhecem "active"/"ativo"; qualquer outro vira pausado.
    return "Active" if s == "ACTIVE" else (s or "").title()


def fetch_meta_rows(account_id: str, since: str, until: str | None = None,
                    checkout_action: str = "omni_initiated_checkout",
                    attribution_windows: list[str] | None = None,
                    campaign_contains: str = "", preview_limit: int = 0) -> list[list[str]]:
    token = os.environ.get("META_ACCESS_TOKEN", "").strip()
    if not token:
        raise MetaApiError("META_ACCESS_TOKEN não definido (cadastre como Secret do GitHub Actions).")
    act = account_id if account_id.startswith("act_") else f"act_{account_id}"
    until = until or date.today().isoformat()

    # --- 1) metadados por anúncio: status (anúncio/conjunto/campanha) + permalink ---
    meta_by_ad: dict[str, dict] = {}
    ads_params = {
        "fields": "id,effective_status,adset{effective_status},campaign{effective_status},"
                  "preview_shareable_link,creative{instagram_permalink_url,thumbnail_url}",
        "limit": 100,
    }
    if campaign_contains:  # a conta tem vários funis: não listar os anúncios dos outros
        ads_params["filtering"] = json.dumps([{"field": "campaign.name", "operator": "CONTAIN",
                                               "value": campaign_contains}])
    for ad in _paginate(f"{act}/ads", ads_params, token):
        meta_by_ad[ad["id"]] = {
            "ds": (ad.get("effective_status") or ""),
            "as": ((ad.get("adset") or {}).get("effective_status") or ""),
            "cs": ((ad.get("campaign") or {}).get("effective_status") or ""),
            "link": ((ad.get("creative") or {}).get("instagram_permalink_url") or ""),
            "sh": ad.get("preview_shareable_link") or "",
            "thumb": ((ad.get("creative") or {}).get("thumbnail_url") or ""),
        }

    # --- 2) insights diários por anúncio (em janelas de 90 dias p/ respostas menores) ---
    # Recorte por nome de campanha (a conta tem vários funis; o dashboard é de um só)
    flt = ({"filtering": json.dumps([{"field": "campaign.name", "operator": "CONTAIN",
                                      "value": campaign_contains}])}
           if campaign_contains else {})
    params_base = {
        **flt,
        "level": "ad", "time_increment": 1, "limit": 500,
        "fields": "date_start,campaign_name,adset_name,ad_name,ad_id,spend,impressions,"
                  "inline_link_clicks,actions,video_play_actions,"
                  "video_p50_watched_actions,video_p95_watched_actions",
    }
    if attribution_windows:
        params_base["action_attribution_windows"] = json.dumps(attribution_windows)

    rows: list[list[str]] = []
    d0 = date.fromisoformat(since)
    d1 = date.fromisoformat(until)
    while d0 <= d1:
        d_end = min(d0 + timedelta(days=29), d1)
        p = dict(params_base)
        p["time_range"] = json.dumps({"since": d0.isoformat(), "until": d_end.isoformat()})
        n0 = len(rows)
        for r in _paginate(f"{act}/insights", p, token):
            acts = r.get("actions")
            m = meta_by_ad.get(r.get("ad_id"), {})
            rows.append([
                r["date_start"], r.get("campaign_name", ""), r.get("adset_name", ""),
                r.get("ad_name", ""), r.get("spend", "0"), r.get("impressions", "0"),
                r.get("inline_link_clicks", "0"),
                str(_action(acts, "landing_page_view")),
                str(_action(acts, checkout_action, "initiate_checkout")),
                # "3-Second Video Views" = ação video_view (reproduções de 3s+)
                str(_action(acts, "video_view")),
                str(_first(r.get("video_p50_watched_actions"))),
                str(_first(r.get("video_p95_watched_actions"))),
                r.get("ad_id", ""), _status(m.get("ds")), _status(m.get("as")),
                _status(m.get("cs")), m.get("link", ""),
            ])
        print(f"  meta api: {d0}..{d_end} +{len(rows) - n0} linhas", file=sys.stderr, flush=True)
        d0 = d_end + timedelta(days=1)

    spend: dict[str, float] = {}
    for r in rows:
        if r[12]:
            spend[r[12]] = spend.get(r[12], 0.0) + float(r[4] or 0)
    _fetch_media(spend, meta_by_ad, token, preview_limit)
    rows.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    print(f"  meta api: {len(rows)} linhas ({since}..{until}), {len(meta_by_ad)} anuncios", file=sys.stderr)
    return [HEADER] + rows


def _fetch_media(spend: dict, meta_by_ad: dict, token: str, preview_limit: int) -> None:
    """Miniatura (embutida como data-URI: a URL do fbcdn expira; baixar a imagem
    NÃO conta na cota da API) + link oficial da prévia (já vem na listagem de
    anúncios). O iframe da prévia custa 1 chamada da API por anúncio, e apps em
    'development_access' têm cota baixa: só os `preview_limit` anúncios de maior
    gasto (0 = desligado). Falha por anúncio nunca derruba o build."""
    AD_MEDIA.clear()
    ad_ids = set(spend)
    with_preview = set(sorted(spend, key=spend.get, reverse=True)[:max(preview_limit, 0)])

    def one(ad_id: str):
        m = meta_by_ad.get(ad_id, {})
        out = {"sh": m.get("sh", ""), "ig": m.get("link", ""), "th": "", "pv": ""}
        if m.get("thumb"):
            try:
                with urllib.request.urlopen(urllib.request.Request(m["thumb"]), timeout=30) as r:
                    mime = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
                    out["th"] = f"data:{mime};base64," + base64.b64encode(r.read()).decode()
            except Exception:
                pass
        if ad_id in with_preview:
            try:
                p = _get(f"{BASE}/{ad_id}/previews", {"ad_format": "MOBILE_FEED_STANDARD"}, token, retries=2)
                mt = re.search(r'src="([^"]+)"', (p.get("data") or [{}])[0].get("body", ""))
                if mt:
                    out["pv"] = html.unescape(mt.group(1))
            except Exception:
                pass
        return ad_id, out

    with ThreadPoolExecutor(max_workers=4) as ex:
        for ad_id, out in ex.map(one, sorted(ad_ids)):
            AD_MEDIA[ad_id] = out
    got = sum(1 for v in AD_MEDIA.values() if v["th"])
    pv = sum(1 for v in AD_MEDIA.values() if v["pv"])
    print(f"  meta api: midia de {len(AD_MEDIA)} anuncios (miniaturas {got}, previas {pv})",
          file=sys.stderr, flush=True)
