# -*- coding: utf-8 -*-
"""
Configuração do cliente — preencha todos os campos abaixo.

Este é o ÚNICO arquivo que você precisa editar para colocar um cliente novo
no ar — nada mais no projeto precisa mudar. Depois de editar, teste
localmente:

    python build/build.py --meta-file meta.csv --sales-file sales.csv --out dist/index.html

`build/config.example.py` é uma cópia intacta deste arquivo, para consulta
ou para restaurar `config.py` caso precise começar do zero de novo.
"""
from __future__ import annotations

# ==========================================================================
# 1) PLANILHA DO CLIENTE (Google Sheets)
# ==========================================================================
# Meta Ads e Compradores ficam na MESMA planilha (mudam só os gids).
# SPREADSHEET_ID: o trecho entre /d/ e /edit na URL da planilha
#   (https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit#gid=...)
# GID_META / GID_SALES: o número depois de "gid=" na URL de cada aba.
# A planilha precisa estar com o link público em modo "Qualquer pessoa com
# o link pode visualizar" (o build lê via export CSV, somente leitura).
SPREADSHEET_ID = "1QX5QRvFzeyloDurQLxaXTO3c3h6bMr3wskHVe0CiyYM"
GID_META = "1195145852"          # aba Meta Ads
GID_SALES = "1836439885"         # aba Compradores

# ==========================================================================
# 2) REGRAS DE NEGÓCIO
# ==========================================================================
# Fator de imposto aplicado sobre o gasto do Meta Ads quando o toggle
# "Imposto Meta" estiver ligado na dashboard. Use 1.0 se o cliente não tiver
# imposto a considerar.
TAX_FACTOR = 1.0   # ex.: 1.13806 (equivale a +13,806%) — cliente não informou imposto

# Produto principal do funil (base de Vendas/CAC/ConvCHK/Ticket). Casamento
# por PREFIXO, sem acento e em minúsculas, sobre o nome do produto que
# aparece na coluna "Produto" da planilha de Compradores.
MAIN_PRODUCT_PREFIX = "efeito proximo nivel"   # produto "Efeito Próximo Nível"

# A planilha de Compradores tem uma coluna de status de pagamento confiável
# (ex.: "pago"/"aprovado" vs. "aberto"/"cancelado")? Se SIM, deixe False e o
# build filtra por is_paid(). Se a planilha é uma lista de COMPRADORES onde
# toda linha já é uma compra concretizada (sem coluna de status utilizável),
# deixe True para contar todas as linhas como venda paga.
COUNT_ALL_AS_PAID = False   # planilha tem coluna "Status" confiável (Completo/Aprovado/...)

# ==========================================================================
# 3) RÓTULOS EXIBIDOS NA INTERFACE
# ==========================================================================
CLIENT_NAME = "Thata Junqueira"       # aparece no topo do menu lateral
CLIENT_SUB = "Efeito Próximo Nível"   # subtítulo abaixo do nome
TAX_LABEL = "Imposto Meta"            # TAX_FACTOR=1.0 (sem imposto informado) -> toggle não altera valores
MAIN_PRODUCT = "Efeito Próximo Nível" # nome de exibição do produto principal

# ==========================================================================
# 4) METAS (aba Relatórios) — código de cor de CAC/ROAS
# ==========================================================================
#   • ROAS: quanto MAIOR, melhor  -> desempenho = roas / ROAS_TARGET
#   • CAC : quanto MENOR, melhor  -> desempenho = CAC_TARGET / cac
# Faixas de cor (sobre o desempenho): <REPORT_BAND_LOW vermelho ·
#   REPORT_BAND_LOW–0.99 amarelo · 1.00–REPORT_BAND_HIGH verde ·
#   ≥REPORT_BAND_HIGH azul-ciano.
CAC_TARGET = 0.0     # CAC alvo (R$ por venda do produto principal)
ROAS_TARGET = 0.0    # ROAS alvo (Faturamento / Gasto)
REPORT_BAND_LOW = 0.70
REPORT_BAND_HIGH = 1.30

# ==========================================================================
# 5) IA INSIGHTS (Cloudflare Worker) — ver SETUP-IA.md
# ==========================================================================
# URL pública do Worker (não é secreta — o navegador chama esse endereço
# para ler/gerar insights). Deixe em branco até publicar o Worker (passo 7-10
# do checklist em CLAUDE.md); a aba IA Insights simplesmente fica
# indisponível enquanto este campo estiver vazio.
IA_WORKER_URL = ""   # ex.: "https://SEU-WORKER.SEU-SUBDOMINIO.workers.dev"
