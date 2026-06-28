# -*- coding: utf-8 -*-
"""Página: Gestão Geral (somente Administrador) + Backup/Restauração."""
import streamlit as st
import sqlite3
from datetime import date, datetime

from database import (
    db_query, db_execute, db_df,
    export_db_bytes, restaurar_db, validar_backup,
    criar_fonte, criar_beneficiario, criar_categoria_principal, criar_subcategoria,
    DuplicadoError,
)
from auth import criar_usuario
from finance import verificar_bloqueio_delecao

# Trava de segurança: mesmo que a rota seja acessada diretamente, só admin entra.
if st.session_state.get("perfil") != "Administrador":
    st.error("🚫 Acesso restrito a administradores.")
    st.stop()

st.subheader("⚙️ Gestão e Configurações do Sistema")

# --- SEÇÃO DE BACKUP E RESTAURAÇÃO ---
st.markdown("#### 💾 Backup e Restauração de Dados")
col_bkp, col_rst = st.columns(2)

with col_bkp:
    st.caption("Baixe uma cópia completa e consistente do banco de dados.")
    nome_arq = f"finance_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    st.download_button(
        "⬇️ Baixar Backup (.db)",
        data=export_db_bytes(),
        file_name=nome_arq,
        mime="application/x-sqlite3",
        width="stretch",
    )

with col_rst:
    st.caption("Restaure o sistema a partir de um arquivo de backup `.db`.")
    arquivo_up = st.file_uploader("Selecione o arquivo de backup", type=["db"], key="upload_backup")
    if arquivo_up is not None:
        dados = arquivo_up.getvalue()
        ok_valid, msg_valid = validar_backup(dados)
        if not ok_valid:
            st.error(f"❌ Arquivo rejeitado: {msg_valid}")
        else:
            st.success("✅ Arquivo validado (SQLite íntegro e com tabelas essenciais).")
            confirma = st.checkbox("Confirmo a substituição do banco ATUAL por este backup.", key="confirma_restore")
            if st.button("♻️ RESTAURAR AGORA", type="primary", width="stretch", disabled=not confirma):
                ok_rest, msg_rest = restaurar_db(dados)
                if ok_rest:
                    st.success(f"✅ {msg_rest} A sessão será reiniciada.")
                    st.session_state.clear()
                    st.rerun()
                else:
                    st.error(f"❌ {msg_rest}")

st.divider()

# Seção 0: Câmbio
st.markdown("#### 💱 Seção 0 - Taxa de Câmbio")
ntax = st.number_input("Taxa BRL/EUR", value=st.session_state.taxa, format="%.4f")
if st.button("💾 Salvar Nova Taxa"):
    db_execute("UPDATE configuracoes SET valor=? WHERE chave='taxa_brl_eur'", (str(ntax),))
    st.session_state.taxa = ntax
    st.success("Taxa atualizada com sucesso!")
    st.rerun()

st.divider()

# Seção 1: Contas
st.markdown("#### 🏦 Seção 1 - Contas Bancárias (Fontes)")
with st.form("form_nova_conta", clear_on_submit=True):
    n_font = st.text_input("Nome da Nova Conta (Ex: Banco X, Carteira)")
    if st.form_submit_button("➕ Adicionar Conta"):
        if n_font:
            try:
                criar_fonte(n_font)
                st.success(f"Conta '{n_font.strip()}' adicionada!")
            except DuplicadoError as e:
                st.error(f"❌ {e}")
            except ValueError as e:
                st.warning(f"⚠️ {e}")
        else:
            st.warning("⚠️ Informe um nome para a conta.")

df_f = db_df("SELECT id, nome FROM fontes")
if not df_f.empty:
    df_f.insert(0, "Remover", False)
    ed_f = st.data_editor(df_f, hide_index=True, width="stretch", key="ed_font_gest")
    if st.button("🗑️ Excluir Contas Selecionadas"):
        for _, r in df_f[ed_f["Remover"] == True].iterrows():
            if not verificar_bloqueio_delecao("fontes", r['id']):
                db_execute("DELETE FROM fontes WHERE id=?", (r['id'],))
            else:
                st.error(f"Bloqueado: A conta '{r['nome']}' possui lançamentos vinculados.")
        st.rerun()

st.divider()

# Seção 2: Categorias
st.markdown("#### 📂 Seção 2 - Árvore de Categorias")
c1, c2 = st.columns(2)
with c1:
    st.caption("Criar Categoria Principal (sempre vinculada a uma Natureza)")
    with st.form("form_categoria_principal", clear_on_submit=True):
        tc = st.radio("Natureza", ["Despesa", "Receita"], horizontal=True, key="tc_gest_final")
        nc = st.text_input("Nome da Categoria")
        if st.form_submit_button("➕ Criar Categoria Principal"):
            if nc:
                try:
                    criar_categoria_principal(nc, tc)
                    st.success(f"Categoria '{nc.strip()}' ({tc}) criada!")
                except DuplicadoError as e:
                    st.error(f"❌ {e}")
                except ValueError as e:
                    st.warning(f"⚠️ {e}")
            else:
                st.warning("⚠️ Informe o nome da categoria.")
with c2:
    st.caption("Criar Detalhamento (Subcategoria) — exclusiva da categoria pai")
    pais_list = db_query("SELECT id, nome FROM categorias WHERE pai_id IS NULL ORDER BY nome")
    if pais_list:
        with st.form("form_subcategoria", clear_on_submit=True):
            p_sel_g = st.selectbox("Vincular ao Pai", [p[1] for p in pais_list])
            ns = st.text_input("Nome do Detalhe")
            if st.form_submit_button("➕ Criar Subcategoria"):
                if ns:
                    id_p_g = [p[0] for p in pais_list if p[1] == p_sel_g][0]
                    try:
                        criar_subcategoria(ns, id_p_g)
                        st.success(f"Subcategoria '{ns.strip()}' vinculada a '{p_sel_g}'!")
                    except DuplicadoError as e:
                        st.error(f"❌ {e}")
                    except ValueError as e:
                        st.warning(f"⚠️ {e}")
                else:
                    st.warning("⚠️ Informe o nome da subcategoria.")
    else:
        st.info("Crie ao menos uma Categoria Principal antes de detalhar subcategorias.")

df_c = db_df("SELECT id, nome, tipo_categoria FROM categorias")
if not df_c.empty:
    df_c.insert(0, "Remover", False)
    ed_c = st.data_editor(df_c, hide_index=True, width="stretch", key="ed_cat_gest")
    if st.button("🗑️ Excluir Categorias Selecionadas"):
        for _, r in df_c[ed_c["Remover"] == True].iterrows():
            if not verificar_bloqueio_delecao("categorias", r['id']):
                db_execute("DELETE FROM categorias WHERE id=?", (r['id'],))
            else:
                st.error(f"Bloqueado: Categoria '{r['nome']}' possui dependências.")
        st.rerun()

# Seção 3: Beneficiários
st.divider()
st.markdown("#### 👤 Seção 3 - Gestão de Beneficiários")
with st.form("form_novo_beneficiario", clear_on_submit=True):
    nb = st.text_input("Novo Beneficiário", placeholder="Ex: Nome da Pessoa ou Empresa")
    if st.form_submit_button("➕ Adicionar Beneficiário"):
        if nb:
            try:
                criar_beneficiario(nb)
                st.success(f"Beneficiário '{nb.strip()}' adicionado!")
            except DuplicadoError as e:
                st.error(f"❌ {e}")
            except ValueError as e:
                st.warning(f"⚠️ {e}")
        else:
            st.warning("⚠️ Informe um nome para o beneficiário.")

df_b = db_df("SELECT id, nome FROM beneficiarios ORDER BY nome")
if not df_b.empty:
    df_b.insert(0, "Remover", False)
    ed_b = st.data_editor(df_b, hide_index=True, width="stretch", key="ed_ben_gestao")
    if st.button("🗑️ Excluir Beneficiários Selecionados"):
        for _, r in df_b[ed_b["Remover"] == True].iterrows():
            if not verificar_bloqueio_delecao("beneficiarios", r['id']):
                db_execute("DELETE FROM beneficiarios WHERE id=?", (r['id'],))
            else:
                st.error(f"Bloqueado: '{r['nome']}' possui transações vinculadas.")
        st.rerun()

# Seção 4: Usuários e Segurança
st.divider()
st.markdown("#### 👥 Seção 4 - Controle de Usuários e Perfis")
st.caption("Cadastre membros da família e defina o nível de acesso (Admin ou Utilizador).")

with st.form("form_novo_usuario", clear_on_submit=True):
    u_col1, u_col2 = st.columns(2)
    u_col3, u_col4 = st.columns(2)

    with u_col1:
        unome = st.text_input("Nome de Exibição")
    with u_col2:
        ulog = st.text_input("Login (Username)")
    with u_col3:
        umail = st.text_input("E-mail (Para 2FA)")
    with u_col4:
        uprof = st.selectbox("Perfil", ["Utilizador", "Administrador"])

    usenh = st.text_input("Senha Inicial", type="password")

    if st.form_submit_button("👤 CRIAR CONTA", width="stretch"):
        if unome and ulog and umail and usenh:
            try:
                # force_reset=1 (padrão): novo usuário troca a senha no 1º login.
                criar_usuario(ulog.strip(), usenh, unome.strip(), umail.strip(), uprof)
                st.success(f"✅ Usuário '{ulog}' criado! (Deverá trocar a senha no primeiro acesso.)")
            except DuplicadoError as e:
                st.error(f"❌ {e}")
            except sqlite3.IntegrityError:
                st.error("❌ Erro: Este Login (Username) já está em uso por outro membro.")
            except Exception as e:
                st.error(f"❌ Erro inesperado: {e}")
        else:
            st.warning("⚠️ Preencha todos os campos obrigatórios.")

st.markdown("##### Usuários Cadastrados")
df_users = db_df("SELECT id, username as Login, nome_exibicao as Nome, email as Email, perfil as Perfil FROM usuarios")
if not df_users.empty:
    df_users.insert(0, "Remover", False)
    ed_u = st.data_editor(df_users, hide_index=True, width="stretch", key="ed_usuarios_gestao")
    if st.button("🗑️ Remover Acesso Selecionado"):
        for _, r in df_users[ed_u["Remover"] == True].iterrows():
            if r['Login'] == st.session_state.user:
                st.error("Você não pode remover seu próprio acesso.")
            else:
                db_execute("DELETE FROM usuarios WHERE id=?", (r['id'],))
        st.rerun()
