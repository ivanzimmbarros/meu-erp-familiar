import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import smtplib
import random
from email.mime.text import MIMEText
from datetime import datetime

st.set_page_config(page_title="ERP Seguro", layout="wide")

# --- FUNÇÕES DE SEGURANÇA E EMAIL ---
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
    except Exception as e:
        st.error(f"Erro ao enviar e-mail: {e}")

# --- BANCO DE DADOS ---
conn = sqlite3.connect('finance.db', check_same_thread=False)
def init_db():
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY, username TEXT, password TEXT, email TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transacoes (id INTEGER PRIMARY KEY, valor_eur REAL, beneficiario TEXT, usuario TEXT)''')
    conn.commit()

init_db()

# --- FLUXO DE AUTENTICAÇÃO ---
if 'logado' not in st.session_state: st.session_state.logado = False
if 'fase_2fa' not in st.session_state: st.session_state.fase_2fa = False

# Verificar se existe administrador
c = conn.cursor()
c.execute("SELECT * FROM usuarios")
if not c.fetchone():
    st.title("Configuração Inicial: Criar Admin")
    with st.form("admin_form"):
        u = st.text_input("Usuário Admin")
        e = st.text_input("E-mail")
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Criar"):
            c.execute("INSERT INTO usuarios (username, password, email) VALUES (?,?,?)", (u, hash_password(p), e))
            conn.commit()
            st.rerun()
    st.stop()

# TELA DE LOGIN
if not st.session_state.logado:
    st.title("🔐 Acesso Restrito")
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
                enviar_email(user_data[3], "Seu código 2FA", f"Seu código é: {codigo}")
                st.session_state.fase_2fa = True
                st.rerun()
            else: st.error("Credenciais inválidas")
    else:
        code_input = st.text_input("Insira o código de 6 dígitos enviado ao e-mail")
        if st.button("Verificar"):
            if code_input == st.session_state.code:
                st.session_state.logado = True
                st.session_state.fase_2fa = False
                st.rerun()
            else: st.error("Código incorreto")
    st.stop()

# --- DASHBOARD (ÁREA PROTEGIDA) ---
st.sidebar.write(f"Bem-vindo, {st.session_state.temp_user}")
if st.sidebar.button("Logout"):
    st.session_state.logado = False
    st.rerun()

st.title("🚗 Painel de Controle Financeiro")
# (O restante da lógica de transações e gráficos entra aqui, 
# rodando apenas dentro deste bloco protegido)
