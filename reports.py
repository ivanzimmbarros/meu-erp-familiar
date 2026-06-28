# -*- coding: utf-8 -*-
"""
============================================================================
 RELATÓRIOS / EXPORTAÇÃO — ERP FAMILIAR (reports.py)
============================================================================
Geração de relatórios exportáveis. Mantido SEM Streamlit para permitir
testes diretos (os bytes do Excel são validados com pandas/openpyxl).

O relatório gerencial possui EXATAMENTE 3 abas:
  1. Transacoes      — base bruta de todos os lançamentos.
  2. Metas           — orçamentos/tetos configurados.
  3. Resumo_Saldos   — consolidação por conta (real, comprometido, disponível).
"""
import io

import pandas as pd

from database import db_df, db_query
from finance import calcular_saldo_real, calcular_comprometido

SHEETS = ("Transacoes", "Metas", "Resumo_Saldos")


def _resumo_saldos_df() -> pd.DataFrame:
    """Monta o quadro consolidado por conta. Sempre devolve as colunas
    esperadas, mesmo sem contas cadastradas (planilha com cabeçalho)."""
    colunas = ["Conta", "Saldo Real (EUR)", "Comprometido (EUR)", "Disponivel (EUR)"]
    fontes = [f[0] for f in db_query("SELECT nome FROM fontes ORDER BY nome")]
    linhas = []
    for f in fontes:
        sr = calcular_saldo_real(f)
        sc = calcular_comprometido(f)
        linhas.append({
            "Conta": f,
            "Saldo Real (EUR)": sr,
            "Comprometido (EUR)": sc,
            "Disponivel (EUR)": round(sr - sc, 2),
        })
    return pd.DataFrame(linhas, columns=colunas)


def gerar_relatorio_excel_bytes() -> bytes:
    """Gera o relatório gerencial (.xlsx) com 3 abas e devolve os bytes.

    Robusto a banco vazio: cada aba é escrita com seu cabeçalho mesmo sem
    linhas, evitando o erro 'At least one sheet must be visible'."""
    transacoes = db_df("SELECT * FROM transacoes")
    metas = db_df("SELECT * FROM orcamentos")
    resumo = _resumo_saldos_df()

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        transacoes.to_excel(writer, index=False, sheet_name="Transacoes")
        metas.to_excel(writer, index=False, sheet_name="Metas")
        resumo.to_excel(writer, index=False, sheet_name="Resumo_Saldos")
    return output.getvalue()
