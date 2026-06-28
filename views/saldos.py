# -*- coding: utf-8 -*-
"""Página: Saldos / Patrimônio e Liquidez."""
import streamlit as st

from database import db_query, db_df
from finance import calcular_saldo_real, calcular_comprometido, liquidar_transacao

st.subheader("💰 Patrimônio e Liquidez")
fnts = [f[0] for f in db_query("SELECT nome FROM fontes ORDER BY nome")]

if not fnts:
    st.info("💡 Cadastre suas contas na aba Gestão.")
else:
    t_real, t_livre = 0.0, 0.0
    cols = st.columns(len(fnts) if len(fnts) <= 3 else 3)

    for i, f in enumerate(fnts):
        sr = calcular_saldo_real(f)
        sc = calcular_comprometido(f)
        sl = round(sr - sc, 2)
        t_real += sr
        t_livre += sl

        with cols[i % 3]:
            cor_livre = "#10b981" if sl >= 0 else "#ef4444"
            st.markdown(f"""
                <div class="card">
                    <h4 style="margin:0; color:#2F2F2F;">🏦 {f}</h4>
                    <div style="display:flex; justify-content:space-between; margin-top:10px; color:#2F2F2F;">
                        <span>Saldo Real:</span> <b>€{sr:,.2f}</b>
                    </div>
                    <div style="display:flex; justify-content:space-between; color:#6D7993; font-size:0.9rem;">
                        <span>Comprometido:</span> <span>-€{sc:,.2f}</span>
                    </div>
                    <hr style="margin:8px 0; border:0; border-top:1px solid #eee;">
                    <div style="display:flex; justify-content:space-between; color:#2F2F2F;">
                        <span>Disponível:</span> <b style="color:{cor_livre};">€{sl:,.2f}</b>
                    </div>
                </div>
            """, unsafe_allow_html=True)

    st.divider()

    status_color_livre = "#10b981" if t_livre >= 0 else "#ef4444"
    pct_comprometido = (abs(t_real - t_livre) / t_real * 100) if t_real > 0 else 0

    st.markdown(f"""
        <style>
            [data-testid="stMetricValue"] {{ font-size: 1.8rem !important; }}
            [data-testid="stHorizontalBlock"] > div:nth-of-type(2) [data-testid="stMetricValue"] {{
                color: {status_color_livre} !important;
            }}
        </style>
    """, unsafe_allow_html=True)

    c_t1, c_t2 = st.columns(2)
    c_t1.metric("SALDO REAL TOTAL", f"€ {t_real:,.2f}")
    c_t2.metric("DISPONIBILIDADE REAL", f"€ {t_livre:,.2f}")

    if t_livre < 0:
        st.error(f"""
            🚨 **ALERTA DE INSOLVÊNCIA PATRIMONIAL**
            Suas obrigações futuras (contas pendentes + faturas) superam o seu dinheiro disponível em conta.
            📌 **Déficit Estimado:** `€{abs(t_livre):,.2f}`
            📊 **Pressão sobre o Patrimônio:** Suas dívidas representam `{pct_comprometido:.1f}%` acima do seu saldo atual.
        """)
    else:
        st.success(f"""
            ✅ **DISPONIBILIDADE POSITIVA**
            Seu patrimônio atual é suficiente para cobrir todos os compromissos futuros registrados.
            📌 **Margem de Segurança Livre:** `€{t_livre:,.2f}`
            📊 **Nível de Comprometimento:** Você já empenhou `{pct_comprometido:.1f}%` do seu saldo real.
        """)

# --- PAINEL DE LIQUIDAÇÃO DE PENDENTES ---
st.divider()
st.markdown("#### 🧾 Contas a Liquidar (Pendentes / Previstas)")
st.caption("Dê baixa em pagamentos/recebimentos. A liquidação efetiva o valor no saldo real da conta.")

df_pend = db_df(
    "SELECT id, data, tipo, categoria_pai, beneficiario, fonte, valor_eur, status_liquidacao "
    "FROM transacoes WHERE status_liquidacao IN ('PENDENTE','PREVISTO') "
    "AND forma_pagamento != 'Cartão de Crédito' ORDER BY data ASC, id ASC"
)

if df_pend.empty:
    st.info("✅ Nenhuma conta pendente ou prevista para liquidar.")
else:
    df_pend_view = df_pend.copy()
    df_pend_view.insert(0, "✅ Liquidar", False)
    ed_pend = st.data_editor(
        df_pend_view,
        hide_index=True,
        width="stretch",
        key="editor_liquidacao",
        disabled=[c for c in df_pend.columns],
    )
    if st.button("✅ LIQUIDAR SELECIONADAS", type="primary"):
        sel = df_pend_view.loc[ed_pend["✅ Liquidar"] == True]
        if sel.empty:
            st.warning("⚠️ Selecione ao menos uma conta para liquidar.")
        else:
            for _, r in sel.iterrows():
                liquidar_transacao(int(r["id"]), r["tipo"], st.session_state.get("user"))
            st.success(f"✅ {len(sel)} lançamento(s) liquidado(s) com sucesso!")
            st.rerun()
