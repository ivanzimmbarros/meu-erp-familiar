# -*- coding: utf-8 -*-
"""Página: Histórico / Auditoria de Lançamentos."""
import streamlit as st
import pandas as pd

from database import db_query, db_execute, db_df

st.subheader("📋 Auditoria de Lançamentos")

# 1. Recuperação da Base de Dados (Híbrida)
df_comuns = db_df("SELECT * FROM transacoes WHERE forma_pagamento != 'Cartão de Crédito'")
df_faturas = db_df("""
    SELECT MIN(t.id) as id, t.fatura_ref || '-01' as data, 'Cartão de Crédito' as categoria_pai,
           'Geral' as categoria_filho, 'Fatura' as beneficiario, c.nome as fonte,
           SUM(t.valor_eur) as valor_eur, 'Despesa' as tipo,
           'Fatura Consolidada: ' || c.nome || ' (Ref: ' || t.fatura_ref || ')' as nota,
           MAX(t.status_liquidacao) as status_liquidacao, 'Cartão de Crédito' as forma_pagamento
    FROM transacoes t JOIN cartoes c ON t.cartao_id = c.id
    WHERE t.forma_pagamento = 'Cartão de Crédito' GROUP BY t.fatura_ref, c.nome
""")
df_raw = pd.concat([df_comuns, df_faturas], ignore_index=True)
df_raw['fonte'] = df_raw['fonte'].fillna("Não Especificado").astype(str)

# 2. MATRIZ DE FILTROS (REATIVIDADE DE CATEGORIAS)
c_f1, c_f2, c_f3 = st.columns([1, 1, 2])
f_tipo = c_f1.selectbox("Tipo de Lançamento", ["Todos", "Despesa", "Receita"], key="f_tipo_final")
f_fonte = c_f2.selectbox("Conta/Cartão", ["Todas"] + sorted(df_raw['fonte'].unique().tolist()))
f_busca = c_f3.text_input("🔍 Busca Livre", placeholder="Nota ou Beneficiário...", key="f_busca_final")

c_f4, f_f5 = st.columns(2)
sql_pai = "SELECT id, nome FROM categorias WHERE pai_id IS NULL"
if f_tipo != "Todos":
    sql_pai += " AND tipo_categoria = ?"
    pais_filt = db_query(sql_pai, (f_tipo,))
else:
    pais_filt = db_query(sql_pai)
lista_pais = ["Todas"] + [p[1] for p in pais_filt]
f_pai = c_f4.selectbox("Filtrar Categoria Principal", lista_pais, key="f_pai_hist")

if f_pai != "Todas":
    id_p_filt = [p[0] for p in pais_filt if p[1] == f_pai][0]
    filhos_filt = db_query("SELECT nome FROM categorias WHERE pai_id = ?", (id_p_filt,))
    lista_filhos = ["Todos"] + [f[0] for f in filhos_filt]
else:
    lista_filhos = ["Todos"]
f_filho = f_f5.selectbox("Filtrar Subcategoria", lista_filhos, key="f_filho_hist")

# 3. APLICAÇÃO DOS FILTROS NO DATAFRAME
if f_tipo != "Todos":
    df_raw = df_raw[df_raw['tipo'] == f_tipo]
if f_fonte != "Todas":
    df_raw = df_raw[df_raw['fonte'] == f_fonte]
if f_pai != "Todas":
    df_raw = df_raw[df_raw['categoria_pai'] == f_pai]
if f_filho != "Todos":
    df_raw = df_raw[df_raw['categoria_filho'] == f_filho]
if f_busca:
    mask = df_raw.apply(lambda r: f_busca.lower() in str(r).lower(), axis=1)
    df_raw = df_raw[mask]

# 4. RESULTADOS FILTRADOS
st.caption(f"{len(df_raw)} lançamento(s) correspondem aos filtros.")
st.dataframe(df_raw, hide_index=True, width="stretch")

# 5. TABELA TÉCNICA DE REMOÇÃO E AUDITORIA (COM COLUNA STATUS)
st.divider()
st.markdown("#### 🛠️ Auditoria Técnica e Controle de Registros")
st.caption("Esta visão mostra os dados originais do banco para exclusão precisa e conferência de status.")

df_audit_raw = db_df("SELECT * FROM transacoes ORDER BY data DESC, id DESC")

if not df_audit_raw.empty:
    def formatar_nota_bi(row):
        nota_base = row['nota'] or ""
        if row['total_parcelas'] > 1:
            nota_limpa = nota_base.split(" (")[0]
            return f"📦 Parcela {row['parcela_numero']}/{row['total_parcelas']} | {nota_limpa}"
        return nota_base

    df_audit_raw['informacao_detalhada'] = df_audit_raw.apply(formatar_nota_bi, axis=1)

    df_audit_view = df_audit_raw.copy()
    df_audit_view.insert(0, "🗑️", False)

    df_audit_final = df_audit_view[[
        "🗑️", "id", "data", "status_liquidacao", "tipo", "forma_pagamento",
        "categoria_pai", "categoria_filho", "beneficiario",
        "valor_eur", "informacao_detalhada"
    ]].rename(columns={
        "data": "Data",
        "status_liquidacao": "Status",
        "tipo": "Operação",
        "forma_pagamento": "Meio de Pagamento",
        "categoria_pai": "Categoria",
        "categoria_filho": "Subcategoria",
        "beneficiario": "Beneficiário",
        "valor_eur": "Valor (€)",
        "informacao_detalhada": "Estrutura de Notas / Parcelamento"
    })

    editor_audit = st.data_editor(
        df_audit_final,
        hide_index=True,
        width="stretch",
        key="audit_final_v5"
    )

    if st.button("🗑️ EXCLUIR REGISTROS SELECIONADOS", type="secondary", key="btn_del_audit"):
        ids_para_excluir = df_audit_final.loc[editor_audit["🗑️"] == True, "id"].tolist()
        if ids_para_excluir:
            ph = ",".join(["?"] * len(ids_para_excluir))
            db_execute(f"DELETE FROM transacoes WHERE id IN ({ph})", tuple(ids_para_excluir))
            st.success(f"✅ {len(ids_para_excluir)} registro(s) removido(s).")
            st.rerun()
