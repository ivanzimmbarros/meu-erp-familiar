# -*- coding: utf-8 -*-
"""Página: Revisão Familiar (atribuição cooperativa estilo Monarch Money)."""
import streamlit as st

from database import listar_categorias_principais, listar_subcategorias
from finance import listar_transacoes_pendentes_revisao, concluir_revisao_transacao

st.subheader("🔍 Revisão Familiar")

_flash = st.session_state.pop("_flash_revisao", None)
if _flash:
    st.success(_flash)

usuario = st.session_state.get("user")
pendentes = listar_transacoes_pendentes_revisao(usuario)

st.metric("⚠️ Pendentes de revisão", len(pendentes))

if not pendentes:
    st.info("🎉 Você está em dia! Nenhuma transação aguardando sua revisão.")
    st.stop()

st.caption("Classifique cada lançamento atribuído a você e conclua a revisão.")
st.divider()

for t in pendentes:
    tid = t["id"]
    with st.container():
        st.markdown(
            f"""
            <div class="card">
                <b>📅 {t['data']} — €{(t['valor_eur'] or 0.0):,.2f}</b>
                &nbsp;<span style="float:right;font-weight:700;">{t['tipo']}</span><br>
                👤 Lançado por: <b>{t['usuario'] or '—'}</b><br>
                🏦 Conta/Cartão: {t['fonte'] or '—'} &nbsp;|&nbsp; 🧾 {t['forma_pagamento'] or '—'}<br>
                📝 Nota original: <i>{t['nota'] or '—'}</i>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Categorias filtradas estritamente pela Natureza da transação.
        pais = listar_categorias_principais(t["tipo"])
        if not pais:
            st.warning(
                f"⚠️ Não há Categoria Principal de **{t['tipo']}** cadastrada. "
                "Peça a um administrador para criar em **Gestão Geral**."
            )
            continue
        dict_pais = {p[1]: p[0] for p in pais}

        # Pré-seleciona a categoria atual da transação, se ainda existir.
        nomes_pais = list(dict_pais.keys())
        idx_pai = nomes_pais.index(t["categoria_pai"]) if t["categoria_pai"] in nomes_pais else 0

        c1, c2 = st.columns(2)
        pai_sel = c1.selectbox(
            "Categoria Principal", nomes_pais, index=idx_pai, key=f"rev_pai_{tid}"
        )
        id_pai = dict_pais.get(pai_sel)

        # Cascata reativa: subcategorias estritamente filhas do pai escolhido.
        filhos = listar_subcategorias(id_pai)
        nomes_filhos = [f[1] for f in filhos]
        idx_filho = nomes_filhos.index(t["categoria_filho"]) if t["categoria_filho"] in nomes_filhos else 0
        filho_sel = c2.selectbox(
            "Subcategoria (obrigatória)",
            nomes_filhos,
            index=idx_filho if nomes_filhos else None,
            key=f"rev_filho_{tid}_{id_pai}",
            placeholder="Selecione a subcategoria",
        )
        if not nomes_filhos:
            st.info(
                f"ℹ️ A categoria **{pai_sel}** ainda não possui subcategorias. "
                "Cadastre ao menos uma em **Gestão Geral** para concluir."
            )

        nota_sel = st.text_input(
            "Nota revisada", value=t["nota"] or "", key=f"rev_nota_{tid}"
        )

        if st.button("✅ Concluir Revisão", key=f"rev_btn_{tid}", type="primary"):
            try:
                concluir_revisao_transacao(
                    tid, pai_sel, filho_sel, nota_sel, usuario_revisor=usuario
                )
                st.session_state["_flash_revisao"] = "✅ Revisão concluída com sucesso!"
                st.rerun()
            except ValueError as e:
                st.error(f"⚠️ {e}")
        st.divider()
