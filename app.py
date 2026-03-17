import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import plotly.express as px
from datetime import datetime

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="ERP Familiar", layout="wide")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_conn():
    return sqlite3.connect('finance.db', check_same_thread=False)

# --- INICIALIZAÇÃO DO BANCO ---
conn = get_conn()
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS usuarios 
             (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, email TEXT, nome_exibicao TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS transacoes 
             (id INTEGER PRIMARY KEY, data TEXT, categoria TEXT, valor_eur REAL, tipo TEXT, usuario TEXT)''')
conn.commit()

# --- CONTROLE DE SESSÃO ---
if 'logado' not in st.session_state:
    st.session_state.logado = False

# --- TELA DE LOGIN ---
if not st.session_state.logado:
    st.title("🔐 Login: ERP Familiar")
    u = st.text_input("Usuário")
    p = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        c.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, hash_password(p)))
        res = c.fetchone()
        if res:
            st.session_state.logado = True
            st.session_state.display_name = res[4]
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")
    st.stop()

# --- PAINEL PRINCIPAL (APÓS LOGIN) ---
st.sidebar.title(f"👤 {st.session_state.display_name}")
if st.sidebar.button("Sair"):
    st.session_state.logado = False
    st.rerun()

# Carregar dados para os gráficos
df = pd.read_sql_query("SELECT * FROM transacoes", conn)

st.title(f"🚗 Painel de Controle: {st.session_state.display_name}")

# KPIs de Saldo
if not df.empty:
    rec = df[df['tipo'] == 'Receita']['valor_eur'].sum()
    des = df[df['tipo'] == 'Despesa']['valor_eur'].sum()
    col1, col2, col3 = st.columns(3)
    col1.metric("Saldo Geral", f"€ {rec - des:,.2f}")
    col2.metric("Total Receitas", f"€ {rec:,.2f}")
    col3.metric("Total Despesas", f"€ {des:,.2f}")
    st.divider()

# DEFINIÇÃO DAS ABAS
tab1, tab2, tab3 = st.tabs(["➕ Novo Lançamento", "📊 Visualizar Dados", "⚙️ Configurações"])

with tab1:
    with st.form("lancamento", clear_on_submit=True):
        col_v, col_m = st.columns(2)
        valor = col_v.number_input("Valor", min_value=0.0)
        moeda = col_m.selectbox("Moeda", ["EUR", "BRL"])
        v_eur = valor * 0.16 if moeda == "BRL" else valor
        
        cat = st.selectbox("Categoria", ["Alimentação", "Moradia", "Transporte", "Saúde", "Lazer", "Outros"])
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        
        if st.form_submit_button("Salvar Registro"):
            c.execute("INSERT INTO transacoes (data, categoria, valor_eur, tipo, usuario) VALUES (?,?,?,?,?)",
                      (datetime.now().strftime("%d/%m/%Y %H:%M"), cat, v_eur, tipo, st.session_state.display_name))
            conn.commit()
            st.success("Lançamento realizado com sucesso!")
            st.rerun()

with tab2:
    if not df.empty:
        fig = px.pie(df[df['tipo'] == 'Despesa'], values='valor_eur', names='categoria', title="Distribuição de Despesas")
        st.plotly_chart(fig, use_container_width=True)
        st.subheader("📜 Histórico de Transações")
        st.dataframe(df.sort_index(ascending=False), use_container_width=True)
    else:
        st.info("Ainda não existem dados para exibir os gráficos.")

with tab3:
    st.subheader("Gerenciar Usuários")
    st.write("Aqui você poderá adicionar novos membros da família futuramente.")
