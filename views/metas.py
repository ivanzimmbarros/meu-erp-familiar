# -*- coding: utf-8 -*-
"""Página: Metas / Orçamento."""
import streamlit as st
from datetime import date

from database import (
    db_query, db_execute, db_df,
    listar_categorias_principais, listar_subcategorias, subcategoria_pertence,
)
import finance
from ui_state import limpar_campos_sessao

st.subheader("🎯 Orçamento e Metas")

# Pós-commit: exibe sucesso e RESETA os seletores reativos (Natureza/Categoria/
# Subcategoria) que ficam fora do st.form. O mês de referência é preservado.
_flash_meta = st.session_state.pop("_flash_meta", None)
if _flash_meta:
    st.success(_flash_meta)
if st.session_state.pop("_reset_meta", False):
    limpar_campos_sessao(st.session_state, prefixos=("p_meta_", "f_meta_"), chaves=("hier_t_meta_final",))

meses_db = db_query("SELECT DISTINCT substr(data, 1, 7) FROM transacoes")
lista_m = sorted(list(set([m[0] for m in meses_db] + [date.today().strftime("%Y-%m")])), reverse=True)
c_mes, c_roll = st.columns([2, 2])
m_ref = c_mes.selectbox("Mês de Referência", lista_m, key="sel_mes_metas_final")

# Toggle de Rollover (modelo de envelopes / YNAB). O estado é persistido em
# `configuracoes` para que a preferência valha em toda a navegação.
rollover_on = c_roll.checkbox(
    "🔄 Acumular saldo do mês anterior (Rollover)",
    value=finance.rollover_esta_ativo(),
    key="rollover_toggle",
    help="Soma à meta deste mês a sobra (ou estouro) acumulada dos meses anteriores.",
)
if rollover_on != finance.rollover_esta_ativo():
    finance.definir_rollover_ativo(rollover_on)

with st.expander("➕ Definir Nova Meta / Teto"):
    # NÍVEL 1 — Natureza (obrigatória).
    t_m_sel = st.radio("Natureza da Meta", ["Despesa", "Receita"], horizontal=True, key="hier_t_meta_final")

    # NÍVEL 2 — Categoria Principal, filtrada pela Natureza.
    pais_db = listar_categorias_principais(t_m_sel)
    if not pais_db:
        st.warning(
            f"⚠️ Nenhuma Categoria Principal de **{t_m_sel}** cadastrada. "
            "Crie-a em **Gestão Geral** antes de definir metas."
        )
    dict_pais = {p[1]: p[0] for p in pais_db}
    c_p_sel = st.selectbox(
        "Categoria Principal",
        list(dict_pais.keys()),
        key=f"p_meta_{t_m_sel}",
        index=0 if dict_pais else None,
        placeholder="Selecione a categoria",
    )

    # NÍVEL 3 — Subcategoria obrigatória, estritamente filhos da categoria.
    id_p_sel = dict_pais.get(c_p_sel)
    filhos_db = listar_subcategorias(id_p_sel)
    c_f_sel = st.selectbox(
        "Subcategoria / Detalhe (obrigatória)",
        [f[1] for f in filhos_db],
        key=f"f_meta_{t_m_sel}_{id_p_sel}",
        index=0 if filhos_db else None,
        placeholder="Selecione a subcategoria",
    )
    if c_p_sel and not filhos_db:
        st.info(
            f"ℹ️ A categoria **{c_p_sel}** não possui subcategorias. "
            "Cadastre ao menos uma em **Gestão Geral** para definir metas."
        )

    with st.form("form_metas_hierarquico_v3", clear_on_submit=True):
        v_m = st.number_input("Valor Planejado (€)", min_value=0.0, step=50.0)
        if st.form_submit_button("💾 SALVAR PLANEJAMENTO"):
            if not (c_p_sel and c_f_sel):
                st.error("⚠️ Selecione Natureza, Categoria Principal e Subcategoria (todas obrigatórias).")
            elif not subcategoria_pertence(id_p_sel, c_f_sel):
                st.error("⚠️ A Subcategoria não pertence à Categoria Principal escolhida.")
            else:
                db_execute("""
                    INSERT OR REPLACE INTO orcamentos (mes_ano, categoria_pai, categoria_filho, valor_previsto, tipo_meta)
                    VALUES (?,?,?,?,?)""", (m_ref, c_p_sel, c_f_sel, v_m, t_m_sel))
                st.session_state["_flash_meta"] = "✅ Meta salva com sucesso!"
                st.session_state["_reset_meta"] = True
                st.rerun()

st.divider()
metas_df = db_df("SELECT * FROM orcamentos WHERE mes_ano=? ORDER BY categoria_pai ASC", (m_ref,))

if metas_df.empty:
    st.info("Nenhuma meta definida para este mês.")
else:
    for pai in metas_df['categoria_pai'].unique():
        st.markdown(f"#### 📁 {pai}")

        filhos_da_categoria = metas_df[metas_df['categoria_pai'] == pai]

        for _, r in filhos_da_categoria.iterrows():
            real_val = finance.realizado_mes(
                r['categoria_pai'], r['categoria_filho'], r['tipo_meta'], m_ref
            )
            base = r['valor_previsto'] or 0.0

            if rollover_on:
                # (a) Rollover herdado dos meses anteriores.
                roll = finance.calcular_rollover_categoria(
                    r['categoria_pai'], r['categoria_filho'], r['tipo_meta'], m_ref
                )
                # (b) Orçamento ajustado = meta base + rollover herdado.
                ajustado = finance.calcular_orcamento_ajustado(base, roll)
                # (d) Barra robusta contra orçamento ajustado <= 0.
                p_val = finance.fracao_progresso(real_val, ajustado)
                is_over = (r['tipo_meta'] == "Despesa" and real_val > ajustado) or (ajustado <= 0 and real_val > 0)
                cor_barra = "🔴" if is_over else "🟢"

                # (c) Selo de rollover colorido (verde positivo / vermelho negativo).
                if roll > 0:
                    selo = f"<span style='color:#2E7D32;font-weight:700;'>➕ €{roll:,.2f}</span>"
                elif roll < 0:
                    selo = f"<span style='color:#C62828;font-weight:700;'>➖ €{abs(roll):,.2f}</span>"
                else:
                    selo = "<span style='color:#9099A2;'>sem saldo herdado</span>"

                with st.container():
                    st.markdown(
                        f"&nbsp;&nbsp;&nbsp;&nbsp;{cor_barra} **{r['categoria_filho']}** "
                        f"<small>({r['tipo_meta']})</small>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"&nbsp;&nbsp;&nbsp;&nbsp;<small>Meta base €{base:,.2f} &nbsp;|&nbsp; "
                        f"Rollover {selo} &nbsp;|&nbsp; <b>Ajustado €{ajustado:,.2f}</b></small>",
                        unsafe_allow_html=True,
                    )
                    st.progress(p_val, text=f"€{real_val:,.2f} de €{ajustado:,.2f} (ajustado)")
            else:
                # Rollover INATIVO: comportamento original (vs. meta base).
                p_val = finance.fracao_progresso(real_val, base)
                is_over = (r['tipo_meta'] == "Despesa" and real_val > base)
                cor_barra = "🔴" if is_over else "🟢"

                with st.container():
                    st.markdown(
                        f"&nbsp;&nbsp;&nbsp;&nbsp;{cor_barra} **{r['categoria_filho']}** "
                        f"<small>({r['tipo_meta']})</small>",
                        unsafe_allow_html=True,
                    )
                    st.progress(p_val, text=f"€{real_val:,.2f} de €{base:,.2f}")
        st.markdown("<br>", unsafe_allow_html=True)
