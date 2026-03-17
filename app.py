import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import smtplib
import random
import plotly.express as px
import os
from email.mime.text import MIMEText
from datetime import datetime

# --- TRUQUE DE LIMPEZA (REMOVER APÓS CRIAR O NOVO ADMIN) ---
if os.path.exists('finance.db'):
    os.remove('finance.db')

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="ERP Familiar Seguro", layout="wide")

# --- FUNÇÕES DE SEGURANÇA ---
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def enviar_email(destino, assunto, corpo):
    try:
        msg = MIMEText(corpo)
        msg['Subject'] = assunto
        msg['From'] = st.secrets["email"]["smtp_user"]
        msg['To'] = destino
        with smtplib.SMTP(st.secrets["email"]["smtp_server"], st.secrets["email"]["smtp_port"]) as server:
            server.starttls()
            server.login(st.secrets["email"]["smtp_user"], st.secrets["email"]["smtp_pass"])
            server.sendmail(st.secrets["email"]["smtp_user"], destino, msg.as_string())
        return True
    except Exception as e:
        st.error(f"Erro ao enviar e-mail: {e}")
        return False

# --- BANCO DE DADOS ---
def get_conn():
    return sqlite3.connect('finance.db', check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, email TEXT, nome_exibicao TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transacoes 
                 (id INTEGER PRIMARY KEY, data TEXT, categoria TEXT, beneficiario TEXT, 
                  valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- CONTROLE DE SESSÃO ---
if 'logado' not in st.session_state: st.session_state.logado = False
if 'fase_2fa' not in st.session_state: st.session_state.fase_2fa = False

# --- VERIFICAR SE EXISTE ADMIN ---
conn = get_conn()
c = conn.cursor()
c.execute("SELECT * FROM usuarios")
if not c.fetchone():
    st.title("🏠 Configuração Inicial: Criar Admin")
    with st.form("admin_form"):
        nome_ex = st.text_input("Seu Nome (Como quer ser chamado)", placeholder="Ex: Ivan Barros")
        u = st.text_input("Usuário de Login (Sem espaços)", placeholder="Ex: ivan123")
        e = st.text_input("E-mail para 2FA")
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Criar Conta"):
            if u and e and p and nome_ex:
                c.execute("INSERT INTO usuarios (username, password, email, nome_exibicao) VALUES (?,?,?,?)", 
                          (u, hash_password(p), e, nome_ex))
                conn.commit()
                st.success("Admin criado! Faça login.")
                st.rerun()
            else: st.warning("Preencha todos os campos.")
    st.stop()

# --- TELA DE LOGIN ---
if not st.session_state.logado:
    st.title("🔐 Acesso Restrito: ERP Familiar")
    if not st.session_state.fase_2fa:
        user = st.text_input("Usuário")
        pwd = st.text_input("Senha", type="password")
        if st.button("Login"):
            c.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (user, hash_password(pwd)))
            user_data = c.fetchone()
            if user_data:
                codigo = str(random.randint(100000, 999999))
                st.session_state.code = codigo
                st.session_state.temp_user = user
                st.session_state.display_name = user_data[4]
                st.session_state.temp_email = user_data[3]
                if enviar_email(user_data[3], "Código de Acesso ERP", f"Olá {user_data[4]}, seu código 2FA é: {codigo}"):
                    st.session_state.fase_2fa = True
                    st.rerun()
            else: st.error("Usuário ou senha incorretos.")
    else:
        st.info(f"Código enviado para {st.session_state.temp_email}")
        code_input = st.text_input("Insira o código de 6 dígitos")
        if st.button("Verificar Código"):
            if code_input == st.session_state.code:
                st.session_state.logado = True
                st.session_state.fase_2fa = False
                st.rerun()
            else: st.error("Código inválido.")
    st.stop()

# --- ÁREA PROTEGIDA ---
st.sidebar.title(f"👤 {st.session_state.display_name}")
if st.sidebar.button("Sair (Logout)"):
    st.session_state.logado = False
    st.rerun()

df = pd.read_sql_query("SELECT * FROM transacoes", conn)

st.title(f"🚗 Painel de {st.session_state.display_name}")

if not df.empty:
    total_gasto = df[df['tipo'] == 'Despesa']['valor_eur'].sum()
    total_receita = df[df['tipo'] == 'Receita']['valor_eur'].sum()
    saldo_atual = total_receita - total_gasto
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Saldo Disponível", f"€ {saldo_atual:,.2f}")
    col2.metric("Total de Receitas", f"€ {total_receita:,.2f}")
    col3.metric("Total de Despesas", f"€ {total_gasto:,.2f}")
    st.divider()

tab1, tab2, tab3 = st.tabs(["➕ Lançamentos", "📊 Análises", "⚙️ Configurações"])

with tab1:
    with st.form("form_transacao", clear_on_submit=True):
        col_v, col_m = st.columns(2)
        v_raw = col_v.number_input("Valor", min_value=0.0)
        moeda = col_m.selectbox("Moeda Original", ["EUR", "BRL"])
        v_eur = v_raw * 0.16 if moeda == "BRL" else v_raw
        
        benef = st.selectbox("Beneficiário", ["Pai", "Mãe", "Filho", "Cão", "Carro", "Família"])
        cat = st.selectbox("Categoria", ["Alimentação", "Moradia
