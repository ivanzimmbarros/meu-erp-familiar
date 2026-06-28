# -*- coding: utf-8 -*-
"""Página: Dashboards / Business Intelligence."""
import streamlit as st
import pandas as pd
import plotly.express as px

from database import db_df
from reports import gerar_relatorio_excel_bytes

st.subheader("📊 Business Intelligence: Saúde e Tendências")

df_dashboard_base = db_df("SELECT * FROM transacoes")

if df_dashboard_base.empty:
    st.warning("⚠️ O banco de dados está vazio. Registre lançamentos para visualizar os gráficos.")
else:
    with st.expander("🔍 Filtros Avançados de BI", expanded=False):
        df_dashboard_base['dt'] = pd.to_datetime(df_dashboard_base['data'])
        df_dashboard_base['beneficiario'] = df_dashboard_base['beneficiario'].fillna("N/A").replace("", "N/A")
        df_dashboard_base['categoria_filho'] = df_dashboard_base['categoria_filho'].fillna("Geral")

        c_an1, c_an2, c_an3 = st.columns(3)
        min_d = df_dashboard_base['dt'].min().date()
        max_d = df_dashboard_base['dt'].max().date()
        data_range = c_an1.date_input("Período de Análise", [min_d, max_d])

        f_contas = c_an2.multiselect("Filtrar Contas/Cartões", sorted(df_dashboard_base['fonte'].unique()))
        f_ben = c_an3.multiselect("Filtrar Beneficiários", sorted(df_dashboard_base['beneficiario'].unique()))

        c_an4, c_an5 = st.columns(2)
        f_cats = c_an4.multiselect("Filtrar Categorias Principais", sorted(df_dashboard_base['categoria_pai'].unique()))

        if f_cats:
            sub_options = sorted(df_dashboard_base[df_dashboard_base['categoria_pai'].isin(f_cats)]['categoria_filho'].unique())
        else:
            sub_options = sorted(df_dashboard_base['categoria_filho'].unique())

        f_subcats = c_an5.multiselect("Filtrar Subcategorias / Detalhes", sub_options)

    df_bi = df_dashboard_base.copy()
    if len(data_range) == 2:
        df_bi = df_bi[(df_bi['dt'].dt.date >= data_range[0]) & (df_bi['dt'].dt.date <= data_range[1])]
    if f_contas:
        df_bi = df_bi[df_bi['fonte'].isin(f_contas)]
    if f_cats:
        df_bi = df_bi[df_bi['categoria_pai'].isin(f_cats)]
    if f_subcats:
        df_bi = df_bi[df_bi['categoria_filho'].isin(f_subcats)]
    if f_ben:
        df_bi = df_bi[df_bi['beneficiario'].isin(f_ben)]

    if df_bi.empty:
        st.info("Ajuste os filtros acima. Nenhum dado encontrado para esta seleção.")
    else:
        st.markdown("---")
        rec_total = df_bi[df_bi['tipo'] == 'Receita']['valor_eur'].sum()
        des_total = df_bi[df_bi['tipo'] == 'Despesa']['valor_eur'].sum()
        des_paga = df_bi[(df_bi['tipo'] == 'Despesa') & (df_bi['status_liquidacao'] == 'PAGO')]['valor_eur'].sum()
        total_comp = df_bi[df_bi['status_liquidacao'].isin(['PENDENTE', 'PREVISTO'])]['valor_eur'].sum()

        balanco_projetado = round(rec_total - des_total, 2)
        margem_pct = (balanco_projetado / rec_total * 100) if rec_total > 0 else (0.0 if balanco_projetado >= 0 else -100.0)

        status_color = "#10b981" if balanco_projetado >= 0 else "#ef4444"
        st.markdown(f"""
            <style>
            [data-testid="stMetricValue"] {{ font-size: 1.8rem !important; }}
            [data-testid="stHorizontalBlock"] > div:nth-of-type(4) [data-testid="stMetricValue"] {{ color: {status_color} !important; }}
            </style>
        """, unsafe_allow_html=True)

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("💰 Receita Total", f"€{rec_total:,.2f}")
        k2.metric("💸 Despesa Paga", f"€{des_paga:,.2f}")
        k3.metric("⚠️ Comprometido", f"€{total_comp:,.2f}")
        k4.metric("⚖️ Balanço Líquido", f"€{balanco_projetado:,.2f}")

        if balanco_projetado < 0:
            st.error(f"**Déficit Detectado:** Suas obrigações superam as receitas. Margem: `{margem_pct:.1f}%`")
        else:
            st.success(f"**Superávit Projetado:** Margem de segurança: `{margem_pct:.1f}%`")

        st.markdown("---")

        visao_t = st.radio("Selecione a Perspectiva do Fluxo Temporal:",
                           ["Receita x Despesa", "Execução de Despesa", "Despesa por Categoria"],
                           horizontal=True, key="visao_temporal_bi_final_v2")

        col_g1, col_g2 = st.columns([2, 1])

        with col_g1:
            paleta_journal = {"Receita": "#6D7993", "Despesa": "#96858F",
                              "Realizado (Pago)": "#9099A2", "Comprometido (Pendente)": "#96858F",
                              "Total Geral": "#4A4A4A"}

            if visao_t == "Receita x Despesa":
                df_trend = df_bi.groupby(['dt', 'tipo'])['valor_eur'].sum().unstack(fill_value=0).reset_index()
                df_melt = df_trend.melt(id_vars='dt', var_name='Tipo', value_name='Valor')
                fig_trend = px.line(df_melt, x='dt', y='Valor', color='Tipo',
                                    line_dash='Tipo',
                                    title="Tendência: Receita vs Despesa",
                                    color_discrete_map=paleta_journal,
                                    markers=True, template="simple_white")

            elif visao_t == "Execução de Despesa":
                df_exec = df_bi[df_bi['tipo'] == 'Despesa'].copy()
                df_exec['Status_Exec'] = df_exec['status_liquidacao'].apply(lambda x: 'Realizado (Pago)' if x == 'PAGO' else 'Comprometido (Pendente)')
                df_trend = df_exec.groupby(['dt', 'Status_Exec'])['valor_eur'].sum().unstack(fill_value=0).reset_index()

                for col in ['Realizado (Pago)', 'Comprometido (Pendente)']:
                    if col not in df_trend.columns:
                        df_trend[col] = 0

                df_trend['Total Geral'] = df_trend['Realizado (Pago)'] + df_trend['Comprometido (Pendente)']
                df_melt = df_trend.melt(id_vars='dt', var_name='Status', value_name='Valor')

                fig_trend = px.line(df_melt, x='dt', y='Valor', color='Status',
                                    line_dash='Status',
                                    title="Execução: Realizado vs Comprometido",
                                    color_discrete_map=paleta_journal,
                                    markers=True, template="simple_white")

            else:
                df_cat_t = df_bi[df_bi['tipo'] == 'Despesa'].groupby(['dt', 'categoria_pai'])['valor_eur'].sum().unstack(fill_value=0).reset_index()
                if len(df_cat_t.columns) > 1:
                    fig_trend = px.area(df_cat_t, x='dt', y=df_cat_t.columns[1:],
                                        title="Peso Temporal por Categoria",
                                        template="simple_white", color_discrete_sequence=px.colors.qualitative.Pastel)
                else:
                    fig_trend = None

            if fig_trend is not None:
                fig_trend.update_layout(hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                st.plotly_chart(fig_trend, width="stretch")
            else:
                st.info("Sem dados de despesa no período/filtros para este gráfico.")

        with col_g2:
            df_desp_tree = df_bi[df_bi['tipo'] == 'Despesa']
            if not df_desp_tree.empty:
                fig_tree = px.treemap(df_desp_tree,
                                      path=['categoria_pai', 'beneficiario'],
                                      values='valor_eur',
                                      title="Estrutura de Gastos",
                                      color_discrete_sequence=['#6D7993', '#96858F', '#9099A2'])
                fig_tree.update_layout(margin=dict(t=30, l=10, r=10, b=10))
                st.plotly_chart(fig_tree, width="stretch")
            else:
                st.info("Sem despesas para montar a estrutura de gastos.")

        st.markdown("---")
        col_g3, col_g4 = st.columns(2)

        with col_g3:
            df_pareto = df_bi[df_bi['tipo'] == 'Despesa'].groupby('beneficiario')['valor_eur'].sum().sort_values(ascending=False).head(10).reset_index()
            if not df_pareto.empty:
                fig_pareto = px.bar(df_pareto, x='valor_eur', y='beneficiario', orientation='h',
                                    title="Top 10 Beneficiários",
                                    color='valor_eur', color_continuous_scale='Purples')
                fig_pareto.update_layout(yaxis={'categoryorder': 'total ascending'})
                st.plotly_chart(fig_pareto, width="stretch")
            else:
                st.info("Sem despesas para ranquear beneficiários.")

        with col_g4:
            df_src = df_bi.groupby(['fonte', 'tipo'])['valor_eur'].sum().reset_index()
            if not df_src.empty:
                fig_sun = px.sunburst(df_src, path=['fonte', 'tipo'], values='valor_eur',
                                      title="Concentração de Volume por Fonte",
                                      color_discrete_sequence=['#9099A2', '#6D7993', '#96858F', '#D5D5D5'])
                st.plotly_chart(fig_sun, width="stretch")
            else:
                st.info("Sem dados para concentração por fonte.")

st.markdown("---")
st.caption("O relatório gera 3 abas: Transações, Metas e Resumo de Saldos por conta.")
st.download_button(
    "📊 Baixar Relatório Excel (3 Abas)",
    data=gerar_relatorio_excel_bytes(),
    file_name="Relatorio_BI_Gerencial.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    width="stretch",
    type="primary",
)
