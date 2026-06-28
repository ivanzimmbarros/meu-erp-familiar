# -*- coding: utf-8 -*-
"""Página: Novos Lançamentos."""
import streamlit as st
from datetime import date

from database import (
    db_query, db_execute_many,
    listar_categorias_principais, listar_subcategorias, subcategoria_pertence,
)
from finance import determinar_status_operacao, calcular_parcelas, calcular_fatura_ref
from ui_state import limpar_campos_sessao

st.subheader("➕ Registro de Movimentação")

# Pós-commit: exibe o sucesso e RESETA os seletores reativos (que ficam fora do
# st.form e, por isso, não são limpos pelo clear_on_submit). Feito ANTES de
# instanciar os widgets para que voltem ao valor padrão.
_flash = st.session_state.pop("_flash_lancamento", None)
if _flash:
    st.success(_flash)
if st.session_state.pop("_reset_lancamento", False):
    limpar_campos_sessao(st.session_state, prefixos=("pai_", "sub_"), chaves=("t_reg_final", "forma_reg"))

c_t1, c_t2 = st.columns(2)
# NÍVEL 1 — Natureza (obrigatória). Ao mudar, recarrega categorias e subcategorias.
tipo_sel = c_t1.radio("Natureza", ["Despesa", "Receita"], horizontal=True, key="t_reg_final")
forma_sel = c_t2.radio("Meio de Pagamento", ["Dinheiro/Débito", "Cartão de Crédito"], horizontal=True, key="forma_reg")

# NÍVEL 2 — Categoria Principal, filtrada estritamente pela Natureza.
pais = listar_categorias_principais(tipo_sel)
if not pais:
    st.warning(
        f"⚠️ Nenhuma Categoria Principal de **{tipo_sel}** cadastrada. "
        "Peça a um administrador para criar em **Gestão Geral → Árvore de Categorias**."
    )
pai_sel = st.selectbox(
    "Categoria Principal",
    [p[1] for p in pais],
    key=f"pai_{tipo_sel}",
    placeholder="Selecione a categoria",
    index=0 if pais else None,
)

# NÍVEL 3 — Subcategoria, filtrada estritamente pela Categoria selecionada.
# A key inclui o pai => trocar a categoria zera a seleção (sem vazamento).
id_p = next((p[0] for p in pais if p[1] == pai_sel), None)
filhos = listar_subcategorias(id_p)
filho_sel = st.selectbox(
    "Subcategoria / Detalhe (obrigatória)",
    [f[1] for f in filhos],
    key=f"sub_{tipo_sel}_{id_p}",
    placeholder="Selecione a subcategoria",
    index=0 if filhos else None,
)
if pai_sel and not filhos:
    st.info(
        f"ℹ️ A categoria **{pai_sel}** ainda não possui subcategorias. "
        "Cadastre ao menos uma em **Gestão Geral** antes de lançar."
    )

with st.form("f_novo_final", clear_on_submit=True):
    f_data = db_query("SELECT nome FROM cartoes") if forma_sel == "Cartão de Crédito" else db_query("SELECT nome FROM fontes")
    fonte_sel = st.selectbox("Origem / Destino", [f[0] for f in f_data])

    col_v, col_p = st.columns(2)
    data_in = col_v.date_input("Data da Compra/Recebimento", date.today())
    valor_in = col_v.number_input("Valor Total (€)", min_value=0.01, format="%.2f")
    parc_in = col_p.number_input("Quantidade de Parcelas", 1, 48, 1)

    benef_list = [b[0] for b in db_query("SELECT nome FROM beneficiarios ORDER BY nome")]
    benef_sel = st.selectbox("Beneficiário", [""] + benef_list)
    nota_in = st.text_input("Observação Adicional")

    if st.form_submit_button("💾 SALVAR REGISTRO"):
        campos_invalidos = []
        # Hierarquia obrigatória: Natureza -> Categoria Principal -> Subcategoria.
        if not tipo_sel:
            campos_invalidos.append("Natureza")
        if not pai_sel:
            campos_invalidos.append("Categoria Principal")
        if not filho_sel:
            campos_invalidos.append("Subcategoria / Detalhe")
        if not fonte_sel:
            campos_invalidos.append("Origem / Destino (Conta ou Cartão)")
        if not benef_sel or benef_sel == "":
            campos_invalidos.append("Beneficiário")
        if not nota_in or nota_in.strip() == "":
            campos_invalidos.append("Observação / Descrição")
        if valor_in <= 0:
            campos_invalidos.append("Valor (deve ser maior que zero)")

        # Trava de hierarquia: a subcategoria precisa pertencer de fato ao pai.
        hierarquia_ok = bool(pai_sel and filho_sel and subcategoria_pertence(id_p, filho_sel))

        if campos_invalidos:
            st.error(f"⚠️ **Erro de Preenchimento:** Os seguintes campos são obrigatórios: {', '.join(campos_invalidos)}.")
        elif not hierarquia_ok:
            st.error("⚠️ A Subcategoria selecionada não pertence à Categoria Principal escolhida. Reabra as seleções e tente novamente.")
        else:
            try:
                is_cc = (forma_sel == "Cartão de Crédito")
                c_inf_res = db_query("SELECT id, dia_fechamento, dia_vencimento FROM cartoes WHERE nome=?", (fonte_sel,))
                c_inf = c_inf_res[0] if c_inf_res else (None, 0, 0)

                parcs = calcular_parcelas(data_in.strftime("%Y-%m-%d"), c_inf[1], c_inf[2], valor_in, parc_in, is_cc)

                ops = []
                for i, (p_d, p_v, p_n) in enumerate(parcs):
                    if is_cc:
                        st_liq = "PENDENTE"
                    else:
                        st_liq = determinar_status_operacao(tipo_sel, eh_primeira_parcela=(i == 0))

                    f_ref = calcular_fatura_ref(p_d, c_inf[1]) if is_cc else None

                    ops.append(("INSERT INTO transacoes (data, categoria_pai, categoria_filho, beneficiario, fonte, valor_eur, tipo, nota, usuario, forma_pagamento, cartao_id, fatura_ref, status_liquidacao) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (p_d, pai_sel, filho_sel, benef_sel, fonte_sel, p_v, tipo_sel, f"{nota_in} ({p_n}/{parc_in})" if parc_in > 1 else nota_in, st.session_state.user, forma_sel, c_inf[0], f_ref, st_liq)))

                db_execute_many(ops)
                # Sinaliza sucesso + reset dos seletores reativos no próximo run.
                st.session_state["_flash_lancamento"] = f"✅ Sucesso! {parc_in} lançamento(s) registrado(s) corretamente."
                st.session_state["_reset_lancamento"] = True
                st.rerun()
            except Exception as e:
                st.error(f"Erro Crítico ao Salvar: {e}")
