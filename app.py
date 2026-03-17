import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import smtplib
import random
import plotly.express as px
from email.mime.text import MIMEText
from datetime import datetime

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="ERP Familiar Pro", layout="wide")

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
    except:
        return False

# --- BANCO DE DADOS ---
def get_conn():
    return sqlite3.connect('finance.db', check_same_thread=False)

conn = get_conn()
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS usuarios 
             (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, email TEXT, nome_exibicao TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS transacoes 
             (id INTEGER PRIMARY KEY, data TEXT, categoria TEXT, beneficiario TEXT, 
              valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT)''')
conn.commit()

# --- CONTROLE DE SESSÃO ---
if 'logado' not in st.session_state: st.session_state.logado = False
if 'fase_2fa' not in st.session_state: st.session_state.fase_2fa = False

# --- VERIFICAÇÃO DE USUÁRIOS ---
c.execute("SELECT COUNT(*) FROM usuarios")
if c.fetchone()[0] == 0:
    st.title("🏠 Configuração Inicial")
    with st.form("setup_admin"):
        n_ex = st.text_input("Seu Nome (Exibição)")
        u_log = st.text_input("Usuário de Login")
        u_em = st.text_input("E-mail para 2FA")
        u_ps = st.text_input("Senha", type="password")
        if st.form_submit_button("Criar Conta Admin"):
            if n_ex and u_log and u_em and u_ps:
                c.execute("INSERT INTO usuarios (username, password, email, nome_exibicao) VALUES (?,?,?,?)",
                          (u_log, hash_password(u_ps), u_em, n_ex))
                conn.commit()
                st.success("Admin criado! Recarregando...")
                st.rerun()
    st.stop()

# --- LOGIN COM 2FA ---
if not st.session_state.logado:
    st.title("🔐 Acesso Restrito")
    if not st.session_state.fase_2fa:
        u_in = st.text_input("Usuário")
        p_in = st.text_input("Senha", type="password")
        if st.button("Entrar"):
            c.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u_in, hash_password(p_in)))
            user_data = c.fetchone()
            if user_data:
                codigo = str(random.randint(100000, 999999))
                st.session_state.code = codigo
                st.session_state.temp_email = user_data[3]
                st.session_state.temp_display = user_data[4]
                if enviar_email(user_data[3], "Código de Acesso", f"Olá {user_data[4]}, seu código é: {codigo}"):
                    st.session_state.fase_2fa = True
                    st.rerun()
                else: st.error("Erro ao enviar e-mail de segurança.")
            else: st.error("Credenciais incorretas.")
    else:
        st.info(f"Código enviado para {st.session_state.temp_email}")
        c_in = st.text_input("Código 2FA")
        if st.button("Verificar"):
            if c_in == st.session_state.code:
                st.session_state.logado = True
                st.session_state.display_name = st.session_state.temp_display
                st.rerun()
            else: st.error("Código inválido.")
    st.stop()

# --- PAINEL PRINCIPAL ---
st.sidebar.title(f"👤 {st.session_state.display_name}")
if st.sidebar.button("Sair"):
    st.session_state.logado = False
    st.session_state.fase_2fa = False
    st.rerun()

# Carregar Dados
df = pd.read_sql_query("SELECT * FROM transacoes", conn)

st.title(f"🚗 Painel de Controle: {st.session_state.display_name}")

# KPIs de Saldo
if not df.empty:
    receita = df
