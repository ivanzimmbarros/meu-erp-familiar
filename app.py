import streamlit as st
import sqlite3
import pandas as pd
import hashlib
from datetime import datetime

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="ERP Familiar", layout="wide")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_conn():
    return sqlite3.connect('finance.db', check_same_thread=False)

# --- INICIALIZAÇÃO DO BANCO (Tabelas e Dados Padrão) ---
def init_db():
    conn = get_conn()
    c = conn.cursor()
    # Tabelas base
    c.execute('CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, email TEXT, nome_exibicao TEXT, senha_trocada INTEGER DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS transacoes (id INTEGER PRIMARY KEY, data TEXT, categoria TEXT, beneficiario TEXT, fonte TEXT, valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT)')
    
    # Tabelas de listas dinâmicas
    c.execute('CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS beneficiarios (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS fontes (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    
    # 3) Popula tabelas vazias com dados padrão para corrigir erro de image_16
    for table, defaults in {
        "categorias": ["Alimentação", "Transporte", "Moradia", "Lazer"],
        "beneficiarios": ["Pai", "Mãe", "Filho", "Geral"],
        "fontes": ["Dinheiro Vivo", "Conta Principal"]
    }.items():
        c.execute(f"SELECT COUNT(*) FROM {table}")
        if c.fetchone()[0] == 0:
            for item in defaults:
                c.execute(f"INSERT OR IGNORE INTO {table} (nome) VALUES (?)", (item,))
    conn.commit()
    conn.close()

init_db()

# --- CONTROLE DE ACESSO (Omitido login por brevidade, assumindo logado) ---
if 'display_name' not in st.session_state: st.session_state.display_name = "Ivan Zimmermann"

st.title(f"🚗 Painel Financeiro")

tab1, tab2, tab3 = st.tabs(["➕ Lançar", "📊 Ver Dados", "⚙️ Gestão Familiar"])

# --- TAB 1: CORRIGINDO FORMULÁRIO QUEBRADO (Erro 1 - image_14) ---
with tab1:
    conn = get_conn()
    # Carrega listas reais do banco para popular os selectboxes
    lc = pd.read_sql_query("SELECT nome FROM categorias", conn)['nome'].tolist()
    lb = pd.read_sql_query("SELECT nome FROM beneficiarios", conn)['nome'].tolist()
    lf = pd.read_sql_query("SELECT nome FROM fontes", conn)['nome'].tolist()
    conn.close()

    st.subheader("Novo Lançamento")
    with st.form("form_novo_registro", clear_on_submit=True):
        col1, col2 = st.columns(2)
        valor = col1.number_input("Valor", min_value=0.0, step=0.01)
        moeda = col2.selectbox("Moeda", ["EUR", "BRL"])
        # Conversão simples
        v_eur = valor * 0.16 if moeda == "BRL" else valor
        
        cat = st.selectbox("Categoria", lc) # Usa listalc
        ben = st.selectbox("Beneficiário", lb) # Usa listalb
        fon = st.selectbox("Fonte (Conta/Cartão)", lf) # Usa listalf
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        
        if st.form_submit_button("Salvar Registro"):
            conn = get_conn()
            conn.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, usuario) VALUES (?,?,?,?,?,?,?)",
                      (datetime.now().strftime("%d/%m/%Y"), cat, ben, fon, v_eur, tipo, st.session_state.display_name))
            conn.commit()
            conn.close()
            st.success("✅ Lançado com sucesso!")
            st.rerun()

# --- TAB 3: CORRIGINDO CADASTRO E DADOS (Erros 2 e 3 - image_15/16) ---
with tab3:
    st.subheader("👥 Controle Administrativo")
    
    # 3) Mostra as listas atuais (agora populadas)
    conn = get_conn()
    colc1, colc2, colc3 = st.columns(3)
    colc1.write("**Fontes Ativas**")
    colc1.dataframe(pd.read_sql_query("SELECT nome FROM fontes", conn), use_container_width=True, hide_index=True)
    
    colc2.write("**Categorias**")
    colc2.dataframe(pd.read_sql_query("SELECT nome FROM categorias", conn), use_container_width=True, hide_index=True)

    colc3.write("**Beneficiários**")
    colc3.dataframe(pd.read_sql_query("SELECT nome FROM beneficiarios", conn), use_container_width=True, hide_index=True)
    conn.close()
    st.divider()

    # 2) Reativando o formulário de cadastro de usuário
    st.subheader("➕ Cadastrar Novo Membro (Admin)")
    with st.form("form_novo_usuario", clear_on_submit=True):
        n_ex = st.text_input("Nome Completo")
        u_lo = st.text_input("Nome de Usuário (Login)")
        u_em = st.text_input("E-mail")
        u_ps = st.text_input("Senha Inicial", type="password")
        if st.form_submit_button("Cadastrar Membro"):
            if n_ex and u_lo and u_ps:
                conn = get_conn()
                try:
                    conn.execute("INSERT INTO usuarios (username, password, email, nome_exibicao, senha_trocada) VALUES (?,?,?,?,0)",
                               (u_lo, hash_password(u_ps), u_em, n_ex))
                    conn.commit()
                    st.success(f"Acesso criado para {n_ex}!")
                except: st.error("Erro: Usuário já existe.")
                finally: conn.close()
            else: st.warning("Preencha todos os campos.")
