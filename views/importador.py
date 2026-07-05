# -*- coding: utf-8 -*-
"""Página: Importador de Extratos (OFX/CSV)."""
import streamlit as st

from database import (
    db_query, listar_categorias_principais, listar_subcategorias,
    subcategoria_pertence, NATUREZAS,
)
from finance import (
    ContaDestinoObrigatoriaError,
    listar_staging, inserir_upload_no_staging, atualizar_linha_staging,
    excluir_staging, analisar_staging, contabilizar_staging,
)
from import_parser import parse_arquivo_extrato

st.subheader("📥 Importador de Extratos")

_flash = st.session_state.pop("_flash_importador", None)
if _flash:
    st.success(_flash)

# --- Req. 8: atalhos para cadastros auxiliares ---
st.caption(
    "Precisa cadastrar beneficiários ou categorias? Abra **Gestão Geral** no menu lateral "
    "(disponível para administradores) e retorne aqui — o buffer de revisão é preservado."
)

# --- Req. 1: seletor de conta obrigatório ---
fontes = [f[0] for f in db_query("SELECT nome FROM fontes ORDER BY nome")]
if not fontes:
    st.warning(
        "⚠️ Nenhuma conta cadastrada. Peça a um administrador para criar em **Gestão Geral**."
    )
    st.stop()

conta_sel = st.selectbox(
    "Conta de Destino (obrigatória)",
    [""] + fontes,
    key="import_conta_destino",
    placeholder="Selecione a conta antes do upload",
)

st.divider()

# --- Upload com trava reativa (Req. 1) ---
arquivo = st.file_uploader(
    "Arquivo de extrato (.OFX ou .CSV)",
    type=["ofx", "csv"],
    key="import_arquivo",
)

if arquivo is not None:
    if not conta_sel:
        st.error("⚠️ Selecione a conta de destino antes de importar o arquivo.")
    else:
        cache_key = f"_import_done_{arquivo.name}_{arquivo.size}"
        if not st.session_state.get(cache_key):
            try:
                conteudo = arquivo.getvalue()
                linhas = parse_arquivo_extrato(arquivo.name, conteudo)
                n = inserir_upload_no_staging(
                    linhas, conta_sel, usuario=st.session_state.get("user"),
                )
                st.session_state[cache_key] = True
                st.session_state["_flash_importador"] = (
                    f"✅ {n} transação(ões) carregada(s) no buffer de revisão."
                )
                st.rerun()
            except ContaDestinoObrigatoriaError as e:
                st.error(f"⚠️ {e}")
            except ValueError as e:
                st.error(f"⚠️ Erro ao ler o arquivo: {e}")

# --- Buffer de validação (Req. 2 e 3) ---
linhas_staging = listar_staging(conta_sel) if conta_sel else []

if conta_sel and not linhas_staging:
    st.info("Nenhuma transação pendente no buffer para esta conta. Faça upload de um extrato.")
elif linhas_staging:
    st.markdown(f"#### 📋 Buffer de Revisão — **{conta_sel}** ({len(linhas_staging)} linha(s))")

    benef_lista = [""] + [b[0] for b in db_query(
        "SELECT nome FROM beneficiarios ORDER BY nome"
    )]

    # Ações em lote
    col_a, col_b, col_c = st.columns(3)
    if col_a.button("🔍 Analisar", type="secondary", use_container_width=True):
        n = analisar_staging(conta_sel, usuario=st.session_state.get("user"))
        st.session_state["_flash_importador"] = (
            f"✅ Análise concluída: {n} linha(s) classificada(s) automaticamente."
        )
        st.rerun()

    selecionados = []
    for row in linhas_staging:
        sid = row[0]
        if st.session_state.get(f"imp_sel_{sid}", True):
            selecionados.append(sid)

    if col_b.button("💾 Contabilizar Selecionados", type="primary", use_container_width=True):
        try:
            # Sincroniza edições dos widgets antes de contabilizar.
            for row in linhas_staging:
                sid = row[0]
                if not st.session_state.get(f"imp_sel_{sid}", True):
                    continue
                atualizar_linha_staging(
                    sid,
                    st.session_state.get(f"imp_raw_{sid}", row[1]),
                    st.session_state.get(f"imp_data_{sid}", row[2]),
                    st.session_state.get(f"imp_valor_{sid}", row[3]),
                    st.session_state.get(f"imp_nat_{sid}", row[4]),
                    st.session_state.get(f"imp_pai_{sid}", row[5]),
                    st.session_state.get(f"imp_filho_{sid}", row[6]),
                    st.session_state.get(f"imp_benef_{sid}", row[7]),
                    st.session_state.get(f"imp_nota_{sid}", row[8]),
                )
            ids_contab = [
                r[0] for r in linhas_staging
                if st.session_state.get(f"imp_sel_{r[0]}", True)
            ]
            n = contabilizar_staging(
                ids_contab, st.session_state.get("user"), fonte_destino=conta_sel,
            )
            st.session_state["_flash_importador"] = (
                f"✅ {n} transação(ões) contabilizada(s) com sucesso!"
            )
            st.rerun()
        except ValueError as e:
            st.error(f"⚠️ {e}")

    if col_c.button("🗑️ Excluir Selecionados", use_container_width=True):
        ids_del = [
            r[0] for r in linhas_staging
            if st.session_state.get(f"imp_sel_{r[0]}", True)
        ]
        if ids_del:
            excluir_staging(ids_del, usuario=st.session_state.get("user"))
            st.session_state["_flash_importador"] = (
                f"✅ {len(ids_del)} linha(s) removida(s) do buffer."
            )
            st.rerun()

    st.divider()

    for row in linhas_staging:
        sid, raw, data, valor, natureza, pai, filho, benef, nota, fonte = row

        with st.container():
            st.checkbox(
                "Selecionar para ação em lote",
                value=True,
                key=f"imp_sel_{sid}",
            )
            st.markdown(
                f'<div class="card"><b>#{sid}</b> — {data} — €{valor:,.2f}</div>',
                unsafe_allow_html=True,
            )

            c1, c2, c3 = st.columns(3)
            raw_edit = c1.text_input(
                "Descrição bruta", value=raw or "", key=f"imp_raw_{sid}",
            )
            data_edit = c2.text_input(
                "Data (AAAA-MM-DD)", value=data or "", key=f"imp_data_{sid}",
            )
            valor_edit = c3.number_input(
                "Valor (€)", min_value=0.01, value=float(valor or 0.01),
                format="%.2f", key=f"imp_valor_{sid}",
            )

            # Req. 8: cascata Natureza → Categoria → Subcategoria → Beneficiário
            nat_opts = list(NATUREZAS)
            idx_nat = nat_opts.index(natureza) if natureza in nat_opts else 0
            nat_sel = st.selectbox(
                "Natureza", nat_opts, index=idx_nat, key=f"imp_nat_{sid}",
            )

            pais = listar_categorias_principais(nat_sel)
            nomes_pais = [p[1] for p in pais]
            dict_pais = {p[1]: p[0] for p in pais}
            idx_pai = nomes_pais.index(pai) if pai in nomes_pais else 0
            pai_sel = st.selectbox(
                "Categoria Principal",
                nomes_pais if nomes_pais else [""],
                index=idx_pai if nomes_pais else None,
                key=f"imp_pai_{sid}",
                placeholder="Selecione a categoria",
            )
            id_p = dict_pais.get(pai_sel)
            filhos = listar_subcategorias(id_p)
            nomes_filhos = [f[1] for f in filhos]
            idx_filho = nomes_filhos.index(filho) if filho in nomes_filhos else 0
            filho_sel = st.selectbox(
                "Subcategoria",
                nomes_filhos if nomes_filhos else [""],
                index=idx_filho if nomes_filhos else None,
                key=f"imp_filho_{sid}_{id_p}",
                placeholder="Selecione a subcategoria",
            )

            c_b, c_n = st.columns(2)
            idx_benef = benef_lista.index(benef) if benef in benef_lista else 0
            benef_sel = c_b.selectbox(
                "Beneficiário", benef_lista, index=idx_benef, key=f"imp_benef_{sid}",
            )
            nota_edit = c_n.text_input(
                "Nota adicional", value=nota or "", key=f"imp_nota_{sid}",
            )

            if st.button("💾 Salvar linha", key=f"imp_save_{sid}"):
                if pai_sel and filho_sel and not subcategoria_pertence(id_p, filho_sel):
                    st.error("⚠️ A Subcategoria não pertence à Categoria Principal.")
                else:
                    atualizar_linha_staging(
                        sid, raw_edit, data_edit, valor_edit, nat_sel,
                        pai_sel, filho_sel, benef_sel, nota_edit,
                    )
                    st.session_state["_flash_importador"] = f"✅ Linha #{sid} atualizada."
                    st.rerun()

            if st.button("🗑️ Excluir linha", key=f"imp_del_{sid}"):
                excluir_staging([sid], usuario=st.session_state.get("user"))
                st.session_state["_flash_importador"] = f"✅ Linha #{sid} removida."
                st.rerun()

            st.divider()
