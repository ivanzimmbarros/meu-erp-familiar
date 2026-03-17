import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import plotly.express as px
from datetime import datetime

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="ERP Familiar Pro", layout="wide")

# --- FUNÇÕES DE SEGURANÇA ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_conn():
    return sqlite3.connect('finance.db', check_same_thread=False)

# --- INICIALIZAÇÃO E ATUALIZAÇÃO DO BANCO ---
def init_db():
    conn = get_conn()
    c = conn.cursor()
    # Criação das tabelas base
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, 
                  email TEXT, nome_exibicao TEXT, senha_trocada INTEGER DEFAULT 0)''')
    
    # Atualização: Adiciona coluna de status de senha se ela não existir
    try:
        c.execute("ALTER TABLE usuarios ADD COLUMN senha_trocada INTEGER DEFAULT 0")
    except:
        pass 
        
    c.execute('''CREATE TABLE IF NOT EXISTS transacoes 
                 (id INTEGER PRIMARY KEY, data TEXT, categoria TEXT, beneficiario TEXT, 
                  valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- CONTROLE DE SESSÃO ---
if 'logado' not in st.session_state:
    st.session_state.logado = False

# --- LOGIN ---
if not st.session_state.logado:
    conn = get_conn()
    c = conn.cursor()
    
    # Verifica se existe algum usuário, se não, força criação do Admin
    c.execute("SELECT COUNT(*) FROM usuarios")
    if c.fetchone()[0] == 0:
        st.title("🏠 Configuração Inicial: Criar Admin")
        with st.form("admin_form"):
            n_ex = st.text_input("Seu Nome (Exibição)")
            u_log = st.text_input("Usuário de Login")
            u_em = st.text_input("E-mail")
            u_ps = st.text_input("Senha", type="password")
            if st.form_submit_button("Criar Conta"):
                if n_ex and u_log and u_ps:
                    c.execute("INSERT INTO usuarios (username, password, email, nome_exibicao, senha_trocada) VALUES (?,?,?,?,?)",
                              (u_log, hash_password(u_ps), u_em, n_ex, 1)) # Admin já nasce com senha "trocada"
                    conn.commit()
                    st.success("Admin criado! Faça login.")
                    st.rerun()
        st.stop()

    st.title("🔐 Acesso: ERP Familiar")
    user_in = st.text_input("Usuário")
    pass_in = st.text_input("Senha", type="password")
    
    if st.button("Entrar"):
        c.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (user_in, hash_password(pass_in)))
        res = c.fetchone()
        if res:
            st.session_state.logado = True
            st.session_state.user_id = res[0]
            st.session_state.username = res[1]
            st.session_state.display_name = res[4]
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")
    conn.close()
    st.stop()

# --- APP PRINCIPAL ---
conn = get_conn()
c = conn.cursor()

st.sidebar.title(f"👤 {st.session_state.display_name}")
if st.sidebar.button("Sair (Logout)"):
    st.session_state.logado = False
    st.rerun()

# Carregar Dados Globalmente
df = pd.read_sql_query("SELECT * FROM transacoes", conn)

st.title(f"🚗 Painel de Controle: {st.session_state.display_name}")

# KPIs
if not df.empty:
    rec = df[df['tipo'] == 'Receita']['valor_eur'].sum()
    des = df[df['tipo'] == 'Despesa']['valor_eur'].sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("Saldo Geral", f"€ {rec - des:,.2f}")
    c2.metric("Total Receitas", f"€ {rec:,.2f}")
    c3.metric("Total Despesas", f"€ {des:,.2f}")
    st.divider()

tab1, tab2, tab3 = st.tabs(["➕ Lançamentos", "📊 Análises", "⚙️ Gestão Familiar"])

with tab1:
    with st.form("novo_lancamento", clear_on_submit=True):
        col_v, col_m = st.columns(2)
        valor = col_v.number_input("Valor", min_value=0.0)
        moeda = col_m.selectbox("Moeda", ["EUR", "BRL"])
        v_eur = valor * 0.16 if moeda == "BRL" else valor
        
        cat = st.selectbox("Categoria", ["Alimentação", "Moradia", "Transporte", "Saúde", "Lazer", "Outros"])
        benef = st.selectbox("Beneficiário", ["Pai", "
