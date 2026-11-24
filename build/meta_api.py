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

import json
import os
import sys
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


class MetaApiError(RuntimeError):
    pass


def _get(url: str, params: dict | None = None, token: str = "", retries: int = 4) -> dict:
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
            if code in (1, 2, 4, 17, 32, 613) or e.code >= 500:
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
                    attribution_windows: list[str] | None = None) -> list[list[str]]:
    token = os.environ.get("META_ACCESS_TOKEN", "").strip()
    if not token:
        raise MetaApiError("META_ACCESS_TOKEN não definido (cadastre como Secret do GitHub Actions).")
    act = account_id if account_id.startswith("act_") else f"act_{account_id}"
    until = until or date.today().isoformat()

    # --- 1) metadados por anúncio: status (anúncio/conjunto/campanha) + permalink ---
    meta_by_ad: dict[str, dict] = {}
    for ad in _paginate(f"{act}/ads", {
        "fields": "id,effective_status,adset{effective_status},campaign{effective_status},"
                  "creative{instagram_permalink_url}",
        "limit": 200,
    }, token):
        meta_by_ad[ad["id"]] = {
            "ds": (ad.get("effective_status") or ""),
            "as": ((ad.get("adset") or {}).get("effective_status") or ""),
            "cs": ((ad.get("campaign") or {}).get("effective_status") or ""),
            "link": ((ad.get("creative") or {}).get("instagram_permalink_url") or ""),
        }

    # --- 2) insights diários por anúncio (em janelas de 90 dias p/ respostas menores) ---
    params_base = {
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
        d_end = min(d0 + timedelta(days=89), d1)
        p = dict(params_base)
        p["time_range"] = json.dumps({"since": d0.isoformat(), "until": d_end.isoformat()})
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
        d0 = d_end + timedelta(days=1)

    rows.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    print(f"  meta api: {len(rows)} linhas ({since}..{until}), {len(meta_by_ad)} anuncios", file=sys.stderr)
    return [HEADER] + rows
