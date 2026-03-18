import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import smtplib
import random
import plotly.express as px
from email.mime.text import MIMEText
from datetime import datetime

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="ERP Familiar Pro", layout="wide")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def enviar_email_2fa(destino, codigo):
    try:
        corpo = f"Seu código de verificação é: {codigo}"
        msg = MIMEText(corpo)
        msg['Subject'] = "🔒 Código 2FA - ERP Familiar"
        msg['From'] = st.secrets["email"]["smtp_user"]
        msg['To'] = destino
        with smtplib.SMTP(st.secrets["email"]["smtp_server"], st.secrets["email"]["smtp_port"]) as server:
            server.starttls()
            server.login(st.secrets["email"]["smtp_user"], st.secrets["email"]["smtp_pass"])
            server.sendmail(st.secrets["email"]["smtp_user"], destino, msg.as_string())
        return True
    except: return False

def get_conn():
    return sqlite3.connect('finance.db', check_same_thread=False)

# --- INICIALIZAÇÃO DO BANCO ---
def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, email TEXT, nome_exibicao TEXT, senha_trocada INTEGER DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS transacoes (id INTEGER PRIMARY KEY, data TEXT, categoria TEXT, beneficiario TEXT, fonte TEXT, valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS beneficiarios (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS fontes (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS saldos_iniciais (fonte TEXT PRIMARY KEY, valor_inicial REAL DEFAULT 0.0)')
    
    for tabela, itens in {"categorias": ["Alimentação", "Moradia"], "beneficiarios": ["Ivan", "Geral"], "fontes": ["Dinheiro Vivo", "Banco Principal"]}.items():
        c.execute(f"SELECT COUNT(*) FROM {tabela}")
        if c.fetchone()[0] == 0:
            for i in itens: c.execute(f"INSERT OR IGNORE INTO {tabela} (nome) VALUES (?)", (i,))
    conn.commit()
    conn.close()

# Executa a inicialização
init_db()

# --- BLOCO DE EMERGÊNCIA (Garante o usuário admin) ---
conn_emergencia = get_conn()
cursor_e = conn_emergencia.cursor()
senha_reset = hashlib.sha256("123456".encode()).hexdigest()
cursor_e.execute("""
    INSERT OR IGNORE INTO usuarios (username, password, email, nome_exibicao, senha_trocada) 
    VALUES (?, ?, ?, ?, ?)
""", ("admin", senha_reset, "seuemail@exemplo.com", "Administrador", 0))
conn_emergencia.commit()
conn_emergencia.close()

# --- SEGURANÇA (2FA E ACESSO) ---
if 'logado' not in st.session_state: st.session_state.logado = False
if 'auth_2fa' not in st.session_state: st.session_state.auth_2fa = False

conn = get_conn()
c = conn.cursor()

if not st.session_state.logado:
    st.title("🔐 Acesso: ERP Familiar")
    u_in = st.text_input("Usuário")
    p_in = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        c.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u_in, hash_password(p_in)))
        user = c.fetchone()
        if user:
            st.session_state.tmp_user = user
            # Bypass do 2FA apenas para o admin de emergência entrar
            if u_in == "admin":
                st.session_state.logado = True
                st.session_state.auth_2fa = True
                st.session_state.user_id = user[0]
                st.session_state.display_name = user[4]
                st.session_state.precisa_trocar = (user[5] == 0)
                st.rerun()
            else:
                codigo = str(random.randint(100000, 999999))
                st.session_state.verif_code = codigo
                if enviar_email_2fa(user[3], codigo):
                    st.session_state.logado = True
                    st.rerun()
                else: st.error("Erro no 2FA. Verifique os Secrets.")
        else:
            st.error("Usuário ou senha incorretos.")
    st.stop()

# --- LOGICA DE TROCA DE SENHA E PAINEL CONTINUA IGUAL ---
# (O restante do seu código a partir daqui...)
