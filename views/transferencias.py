# -*- coding: utf-8 -*-
"""Página: Transferências Entre Bancos."""
import streamlit as st
from datetime import date

from database import db_query, db_execute, db_df
from finance import realizar_transferencia

st.subheader("🔄 Transferência Entre Bancos")

res_fontes = db_query("SELECT nome FROM fontes ORDER BY nome")
fontes_t = [f[0] for f in res_fontes]

if len(fontes_t) < 2:
    st.error("❗ **Ação Necessária:** Cadastre pelo menos 2 contas na aba Gestão.")
else:
    with st.expander("➕ Executar Nova Transferência", expanded=True):
        with st.form("form_transf_bi", clear_on_submit=True):
            c1, c2 = st.columns(2)
            c_origem = c1.selectbox("Conta de Origem (Saída)", fontes_t)
            c_destino = c2.selectbox("Conta de Destino (Entrada)", [f for f in fontes_t if f != c_origem])

            v_col, d_col = st.columns(2)
            valor_transf = v_col.number_input("Valor (€)", min_value=0.01, step=10.0, format="%.2f")
            data_transf = d_col.date_input("Data da Operação", date.today())

            nota_transf = st.text_input("Nota / Motivo da Movimentação")

            if st.form_submit_button("🔁 CONFIRMAR MOVIMENTAÇÃO"):
                try:
                    realizar_transferencia(c_origem, c_destino, valor_transf, data_transf.strftime("%Y-%m-%d"), st.session_state.user, nota_transf)
                    st.success("Transferência realizada!")
                except ValueError as e:
                    st.error(f"⚠️ {e}")

st.divider()
st.markdown("#### 📜 Histórico de Movimentações Internas")

df_trans_hist = db_df("""
    SELECT
        GROUP_CONCAT(id) as ids_grupo,
        data as Data,
        MAX(CASE WHEN beneficiario LIKE 'Para %' THEN fonte END) as "Conta Origem",
        MAX(CASE WHEN beneficiario LIKE 'De %' THEN fonte END) as "Conta Destino",
        valor_eur as "Valor (€)",
        nota as "Descrição"
    FROM transacoes
    WHERE categoria_pai = 'Transferência'
    GROUP BY data, valor_eur, nota
    ORDER BY data DESC
""")

if df_trans_hist.empty:
    st.info("Nenhuma transferência registrada no histórico.")
else:
    df_trans_view = df_trans_hist.copy()
    df_trans_view.insert(0, "🗑️", False)

    st.caption("Abaixo, cada linha representa uma operação completa entre duas contas.")
    ed_trans = st.data_editor(
        df_trans_view,
        hide_index=True,
        width="stretch",
        key="editor_transf_consolidado"
    )

    if st.button("🗑️ Estornar Movimentações Selecionadas", type="secondary"):
        strings_ids = df_trans_view.loc[ed_trans["🗑️"] == True, "ids_grupo"].tolist()

        if strings_ids:
            todos_ids = []
            for s in strings_ids:
                todos_ids.extend(s.split(','))

            placeholder = ",".join(["?"] * len(todos_ids))
            db_execute(f"DELETE FROM transacoes WHERE id IN ({placeholder})", tuple(todos_ids))
            st.success(f"✅ Sucesso! {len(strings_ids)} operação(ões) de transferência estornada(s).")
            st.rerun()
