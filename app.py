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

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="ERP Familiar", layout="wide")

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
tem_usuario = c.fetchone()[0] > 0

if not tem_usuario:
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
                st.success("Conta criada! Recarregando...")
                st.rerun()
    st.stop()

# --- LOGIN ---
if not st.session_state.logado:
    st.title("🔐 Login")
    user_in = st.text_input("Usuário")
    pass_in = st.text_input("Senha", type="password")
    
    if st.button("Entrar"):
        c.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (user_in, hash_password(pass_in)))
        res = c.fetchone()
        if res:
            st.session_state.logado = True
            st.session_state.display_name = res[4]
            st.session_state.temp_user = res[1]
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")
    st.stop()

# --- APP PRINCIPAL ---
st.sidebar.title(f"Olá, {st.session_state.display_name}")
if st.sidebar.button("Sair"):
    st.session_state.logado = False
    st.rerun()

st.title("📊 Painel Financeiro")
st.write("Bem-vindo ao seu novo sistema!")

# Aba de Gestão para criar novos membros
tab1, tab2 = st.tabs(["Lançamentos", "Configurações"])

with tab2:
    st.subheader("👨‍👩‍👧‍👦 Adicionar Familiar")
    with st.form("add_family"):
        f_nom = st.text_input("Nome do Familiar")
        f_log = st.text_input("Login do Familiar")
        f_ema = st.text_input("E-mail do Familiar")
        f_sen = st.text_input("Senha Inicial", type="password")
        if st.form_submit_button("Cadastrar"):
            try:
                c.execute("INSERT INTO usuarios (username, password, email, nome_exibicao) VALUES (?,?,?,?)",
                          (f_log, hash_password(f_sen), f_ema, f_nom))
                conn.commit()
                st.success(f"{f_nom} cadastrado!")
            except:
                st.error("Erro ao cadastrar.")
