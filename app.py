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

# --- INICIALIZAÇÃO DO BANCO ---
def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, 
                  email TEXT, nome_exibicao TEXT, senha_trocada INTEGER DEFAULT 0)''')
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

# --- LÓGICA DE ACESSO ---
conn = get_conn()
c = conn.cursor()

# Verifica se precisa criar o primeiro Admin
c.execute("SELECT COUNT(*) FROM usuarios")
if c.fetchone()[0] == 0:
    st.title("🏠 Configuração Inicial")
    with st.form("admin_setup"):
        n_ex = st.text_input("Nome de Exibição")
        u_log = st.text_input("Usuário de Login")
        u_ps = st.text_input("Senha", type="password")
        if st.form_submit_button("Criar Conta"):
            if n_ex and u_log and u_ps:
                c.execute("INSERT INTO usuarios (username, password, nome_exibicao, senha_trocada) VALUES (?,?,?,?)",
                          (u_log, hash_password(u_ps), n_ex, 1))
                conn.commit()
                st.success("Admin criado! Recarregue a página.")
                st.rerun()
    st.stop()

# Tela de Login
if not st.session_state.logado:
    st.title("🔐 Login")
    u_in = st.text_input("Usuário")
    p_in = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        c.execute("SELECT id, username, nome_exibicao FROM usuarios WHERE username=? AND password=?", (u_in, hash_password(p_in)))
        user_data = c.fetchone()
        if user_data:
            st.session_state.logado = True
            st.session_state.user_id = user_data[0]
            st.session_state.display_name = user_data[2]
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")
    st.stop()

# --- SISTEMA LOGADO ---
st.sidebar.title(f"👤 {st.session_state.display_name}")
if st.sidebar.button("Sair"):
    st.session_state.logado = False
    st.rerun()

df = pd.read_sql_query("SELECT * FROM transacoes", conn)

st.title(f"🚗 Painel de Controle: {st.session_state.display_name}")

# Abas
tab1, tab2, tab3 = st.tabs(["➕ Lançar", "📊 Ver Dados", "⚙️ Gestão Familiar"])

with tab1:
    with st.form("lancamento", clear_on_submit=True):
        col1, col2 = st.columns(2)
        val = col1.number_input("Valor", min_value=0.0)
        moe = col2.selectbox("Moeda", ["EUR", "BRL"])
        v_eur = val * 0.16 if moe == "BRL" else val
        cat = st.selectbox("Categoria", ["Alimentação", "Moradia", "Transporte", "Saúde", "Lazer", "Outros"])
        ben = st.selectbox("Quem?", ["Pai", "Mãe", "Filho", "Geral"])
        tip = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        if st.form_submit_button("Salvar"):
            c.execute("INSERT INTO transacoes (data, categoria, beneficiario, valor_eur, tipo, usuario) VALUES (?,?,?,?,?,?)",
                      (datetime.now().strftime("%d/%m/%Y"), cat, ben, v_eur, tip, st.session_state.display_name))
            conn.commit()
            st.success("Salvo!")
            st.rerun()

with tab2:
    if not df.empty:
        st.plotly_chart(px.pie(df[df['tipo']=='Despesa'], values='valor_eur', names='categoria', title="Despesas"), use_container_width=True)
        st.dataframe(df.sort_index(ascending=False), use_container_width=True)
    else:
        st.info("Sem dados.")

with tab3:
    st.subheader("👥 Controle de Usuários")
    users = pd.read_sql_query("SELECT nome_exibicao, username, CASE WHEN senha_trocada=1 THEN '✅ Alterada' ELSE '⚠️ Inicial' END as Status FROM usuarios", conn)
    st.table(users)
    
    st.divider()
    st.subheader("➕ Novo Membro")
    with st.form("novo_membro"):
        n_m = st.text_input("Nome")
        u_m = st.text_input("Login")
        s_m = st.text_input("Senha Inicial", type="password")
        if st.form_submit_button("Cadastrar"):
            try:
                c.execute("INSERT INTO usuarios (username, password, nome_exibicao, senha_trocada) VALUES (?,?,?,?)", (u_m, hash_password(s_m), n_m, 0))
                conn.commit()
                st.success("Cadastrado!")
                st.rerun()
            except: st.error("Erro ao cadastrar.")

conn.close()
