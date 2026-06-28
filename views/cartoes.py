# -*- coding: utf-8 -*-
"""Página: Cartões / Gestão de Crédito."""
import streamlit as st
from datetime import date

from database import db_query, db_execute, db_df, db_execute_many, criar_cartao, DuplicadoError
from finance import calcular_saldo_real

st.subheader("💳 Gestão de Crédito")

with st.expander("➕ Cadastrar Novo Cartão"):
    fnts_c = [f[0] for f in db_query("SELECT nome FROM fontes")]
    with st.form("f_cartao", clear_on_submit=True):
        c_nc = st.text_input("Nome do Cartão")
        c_lim = st.number_input("Limite Total (€)", min_value=0.0, step=100.0)
        c_cnt = st.selectbox("Conta para Pagamento", fnts_c if fnts_c else ["Sem contas cadastradas"])
        c_df = st.number_input("Dia Fechamento", 1, 31, 25)
        c_dv = st.number_input("Dia Vencimento", 1, 31, 10)
        if st.form_submit_button("Salvar Cartão") and c_nc and fnts_c:
            try:
                criar_cartao(c_nc, c_lim, c_cnt, c_df, c_dv)
                st.success(f"Cartão '{c_nc.strip()}' cadastrado!")
            except DuplicadoError as e:
                st.error(f"❌ {e}")
            except ValueError as e:
                st.warning(f"⚠️ {e}")

st.divider()
cts = db_df("SELECT * FROM cartoes ORDER BY nome")
if cts.empty:
    st.info("Nenhum cartão cadastrado.")
for _, c in cts.iterrows():
    usd = db_query("SELECT SUM(valor_eur) FROM transacoes WHERE cartao_id=? AND status_cartao='pendente'", (c['id'],))[0][0] or 0.0
    st.markdown(f'<div class="card"><b>💳 {c["nome"]}</b><br>Limite: €{c["limite"]:,.2f} | Usado: €{usd:,.2f}</div>', unsafe_allow_html=True)
    fats = db_df("SELECT fatura_ref, SUM(valor_eur) as tot, status_cartao FROM transacoes WHERE cartao_id=? GROUP BY fatura_ref ORDER BY fatura_ref ASC", (c['id'],))
    for _, f in fats.iterrows():
        with st.expander(f"📅 Fatura {f['fatura_ref']} | €{f['tot']:,.2f} ({f['status_cartao']})"):
            comp = db_df("SELECT data, categoria_pai, valor_eur, nota FROM transacoes WHERE cartao_id=? AND fatura_ref=?", (c['id'], f['fatura_ref']))
            st.dataframe(comp, hide_index=True, width="stretch")
            if f['status_cartao'] == 'pendente':
                if st.button(f"Pagar Fatura {f['fatura_ref']}", key=f"p_{c['id']}_{f['fatura_ref']}", type="primary"):
                    if calcular_saldo_real(c['conta_pagamento']) >= f['tot']:
                        ops = [("UPDATE transacoes SET status_cartao='pago', status_liquidacao='PAGO' WHERE cartao_id=? AND fatura_ref=?", (c['id'], f['fatura_ref'])),
                               ("INSERT INTO transacoes (data, categoria_pai, fonte, valor_eur, tipo, nota, status_liquidacao) VALUES (?,?,?,?,?,?,?)", (date.today().strftime("%Y-%m-%d"), "Cartão", c['conta_pagamento'], f['tot'], "Despesa", f"Pgto {c['nome']}", "PAGO"))]
                        db_execute_many(ops); st.rerun()
                    else:
                        st.error("Saldo insuficiente na conta de débito.")
