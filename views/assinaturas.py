# -*- coding: utf-8 -*-
"""Página: Calendário de Assinaturas e Contas Fixas (estilo Rocket Money)."""
import streamlit as st
from datetime import date

from database import (
    db_query,
    listar_categorias_principais, listar_subcategorias, subcategoria_pertence,
    DuplicadoError,
)
from finance import (
    criar_assinatura, listar_assinaturas, assinatura_tem_pagamento_no_mes,
    registrar_pagamento_assinatura, registrar_pagamentos_assinaturas,
    definir_status_assinatura, excluir_assinatura,
)
from ui_state import limpar_campos_sessao

st.subheader("📅 Calendário de Assinaturas e Contas Fixas")

mes_corrente = date.today().strftime("%Y-%m")

# Pós-commit: exibe sucesso e RESETA os seletores reativos (Natureza/Categoria/
# Subcategoria) que ficam fora do st.form, devolvendo-os ao valor padrão.
_flash = st.session_state.pop("_flash_assin", None)
if _flash:
    st.success(_flash)
if st.session_state.pop("_reset_assin", False):
    limpar_campos_sessao(
        st.session_state, prefixos=("pai_assin_", "sub_assin_"), chaves=("t_assin_final",)
    )

# ---------------------------------------------------------------------------
# (a) FORMULÁRIO DE CADASTRO — hierarquia estrita de 3 níveis obrigatórios
# ---------------------------------------------------------------------------
with st.expander("➕ Cadastrar Nova Assinatura / Conta Fixa"):
    # NÍVEL 1 — Natureza (assinaturas são despesas recorrentes, mas mantemos a
    # mesma trava hierárquica de 3 níveis do restante do sistema).
    tipo_sel = st.radio(
        "Natureza", ["Despesa", "Receita"], horizontal=True, key="t_assin_final"
    )

    # NÍVEL 2 — Categoria Principal, filtrada estritamente pela Natureza.
    pais = listar_categorias_principais(tipo_sel)
    if not pais:
        st.warning(
            f"⚠️ Nenhuma Categoria Principal de **{tipo_sel}** cadastrada. "
            "Crie-a em **Gestão Geral** antes de cadastrar assinaturas."
        )
    dict_pais = {p[1]: p[0] for p in pais}
    pai_sel = st.selectbox(
        "Categoria Principal",
        list(dict_pais.keys()),
        key=f"pai_assin_{tipo_sel}",
        index=0 if dict_pais else None,
        placeholder="Selecione a categoria",
    )

    # NÍVEL 3 — Subcategoria obrigatória, estritamente filhos da categoria.
    id_p = dict_pais.get(pai_sel)
    filhos = listar_subcategorias(id_p)
    filho_sel = st.selectbox(
        "Subcategoria / Detalhe (obrigatória)",
        [f[1] for f in filhos],
        key=f"sub_assin_{tipo_sel}_{id_p}",
        index=0 if filhos else None,
        placeholder="Selecione a subcategoria",
    )
    if pai_sel and not filhos:
        st.info(
            f"ℹ️ A categoria **{pai_sel}** ainda não possui subcategorias. "
            "Cadastre ao menos uma em **Gestão Geral** antes de continuar."
        )

    with st.form("f_assinatura", clear_on_submit=True):
        nome_in = st.text_input("Nome da Assinatura (ex.: Netflix, Aluguel)")
        c1, c2 = st.columns(2)
        valor_in = c1.number_input("Valor Mensal (€)", min_value=0.01, format="%.2f")
        dia_in = c2.number_input("Dia de Vencimento", 1, 31, 1)
        contas = [f[0] for f in db_query("SELECT nome FROM fontes ORDER BY nome")]
        conta_sel = st.selectbox(
            "Conta de Débito Padrão", contas if contas else ["Sem contas cadastradas"]
        )

        if st.form_submit_button("💾 SALVAR ASSINATURA"):
            campos_invalidos = []
            if not nome_in or not nome_in.strip():
                campos_invalidos.append("Nome")
            if not pai_sel:
                campos_invalidos.append("Categoria Principal")
            if not filho_sel:
                campos_invalidos.append("Subcategoria / Detalhe")
            if not contas:
                campos_invalidos.append("Conta de Débito (cadastre uma conta)")

            hierarquia_ok = bool(
                pai_sel and filho_sel and subcategoria_pertence(id_p, filho_sel)
            )

            if campos_invalidos:
                st.error(
                    "⚠️ **Erro de Preenchimento:** Os seguintes campos são "
                    f"obrigatórios: {', '.join(campos_invalidos)}."
                )
            elif not hierarquia_ok:
                st.error(
                    "⚠️ A Subcategoria selecionada não pertence à Categoria "
                    "Principal escolhida."
                )
            else:
                try:
                    criar_assinatura(
                        nome_in, valor_in, dia_in, conta_sel, pai_sel, filho_sel
                    )
                    st.session_state["_flash_assin"] = (
                        f"✅ Assinatura '{nome_in.strip()}' cadastrada com sucesso!"
                    )
                    st.session_state["_reset_assin"] = True
                    st.rerun()
                except DuplicadoError as e:
                    st.error(f"❌ {e}")
                except ValueError as e:
                    st.warning(f"⚠️ {e}")

st.divider()

# ---------------------------------------------------------------------------
# Carrega assinaturas ativas e calcula o status de pagamento do mês corrente.
# ---------------------------------------------------------------------------
assinaturas = listar_assinaturas(apenas_ativas=True)
itens = []
for (aid, nome, valor, dia, conta, cat_pai, cat_filho, _ativa) in assinaturas:
    pago = assinatura_tem_pagamento_no_mes(aid, mes_corrente)
    itens.append(
        {
            "id": aid, "nome": nome, "valor": valor or 0.0, "dia": dia,
            "conta": conta, "cat_pai": cat_pai, "cat_filho": cat_filho, "pago": pago,
        }
    )

# ---------------------------------------------------------------------------
# (b) MÉTRICAS DO MÊS
# ---------------------------------------------------------------------------
total_previsto = sum(i["valor"] for i in itens)
total_pago = sum(i["valor"] for i in itens if i["pago"])
total_pendente = sum(i["valor"] for i in itens if not i["pago"])

m1, m2, m3 = st.columns(3)
m1.metric("📦 Previsto no mês", f"€{total_previsto:,.2f}")
m2.metric("✅ Já pago", f"€{total_pago:,.2f}")
m3.metric("⏳ Pendente a pagar", f"€{total_pendente:,.2f}")

if not itens:
    st.info("Nenhuma assinatura ativa cadastrada. Cadastre a primeira acima. ☝️")
    st.stop()

# Ação em lote: dar baixa em todas as assinaturas pendentes de uma vez.
pendentes_ids = [i["id"] for i in itens if not i["pago"]]
if pendentes_ids:
    if st.button(
        f"⚡ Dar baixa em TODAS as {len(pendentes_ids)} pendentes",
        key="baixa_lote", type="primary",
    ):
        n = registrar_pagamentos_assinaturas(
            pendentes_ids, usuario=st.session_state.get("user")
        )
        st.session_state["_flash_assin"] = f"✅ {n} pagamento(s) registrado(s) em lote!"
        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# (c) CRONOGRAMA VISUAL — ordenado cronologicamente por dia de vencimento
# (d) LANÇAMENTO EM 1-CLIQUE — botão "Dar Baixa" por item pendente
# ---------------------------------------------------------------------------
st.markdown("#### 🗓️ Cronograma de Vencimentos")

for i in itens:
    if i["pago"]:
        selo, borda = "✅ PAGO", "#2E7D32"
    else:
        selo, borda = "⏳ PENDENTE", "#C62828"

    col_card, col_btn = st.columns([5, 1])
    with col_card:
        st.markdown(
            f"""
            <div class="card" style="border-left: 6px solid {borda} !important;">
                <b>📌 Dia {i['dia']:02d} — {i['nome']}</b>
                &nbsp;<span style="float:right;font-weight:700;">{selo}</span><br>
                🏷️ {i['cat_pai']} › {i['cat_filho']}<br>
                💶 €{i['valor']:,.2f} &nbsp;|&nbsp; 🏦 {i['conta']}
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_btn:
        if not i["pago"]:
            if st.button("💸 Dar Baixa", key=f"baixa_{i['id']}"):
                registrar_pagamento_assinatura(
                    i["id"], usuario=st.session_state.get("user")
                )
                st.session_state["_flash_assin"] = (
                    f"✅ Pagamento de '{i['nome']}' registrado!"
                )
                st.rerun()
        else:
            st.button("✔️ Quitada", key=f"ok_{i['id']}", disabled=True)

    with st.expander("⚙️ Gerir"):
        cg1, cg2 = st.columns(2)
        if cg1.button("⏸️ Pausar", key=f"pausa_{i['id']}"):
            definir_status_assinatura(i["id"], ativa=0)
            st.session_state["_flash_assin"] = f"Assinatura '{i['nome']}' pausada."
            st.rerun()
        if cg2.button("🗑️ Excluir", key=f"del_{i['id']}"):
            excluir_assinatura(i["id"])
            st.session_state["_flash_assin"] = f"Assinatura '{i['nome']}' excluída."
            st.rerun()
