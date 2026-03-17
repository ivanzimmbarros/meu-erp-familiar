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
    except: return False

def get_conn():
    return sqlite3.connect('finance.db', check_same_thread=False)

# --- INICIALIZAÇÃO DO BANCO ---
conn = get_conn()
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS usuarios 
             (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, 
              email TEXT, nome_exibicao TEXT, senha_trocada INTEGER DEFAULT 0)''')
conn.commit()

# --- CONTROLE DE SESSÃO ---
if 'logado' not in st.session_state: st.session_state.logado = False
if 'auth_2fa' not in st.session_state: st.session_state.auth_2fa = False
if 'precisa_trocar' not in st.session_state: st.session_state.precisa_trocar = False

# --- FLUXO DE ACESSO ---
if not st.session_state.logado:
    st.title("🔐 Login: ERP Familiar")
    u_in = st.text_input("Usuário")
    p_in = st.text_input("Senha", type="password")
    
    if st.button("Entrar"):
        c.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u_in, hash_password(p_in)))
        user = c.fetchone()
        if user:
            st.session_state.user_id = user[0]
            st.session_state.username = user[1]
            st.session_state.user_email = user[3]
            st.session_state.display_name = user[4]
            st.session_state.precisa_trocar = (user[5] == 0)
            
            # Gerar e enviar 2FA
            codigo = str(random.randint(100000, 999999))
            st.session_state.verif_code = codigo
            if enviar_email(user[3], "Seu Código de Acesso", f"Olá, seu código é: {codigo}"):
                st.session_state.logado = True
                st.rerun()
            else: st.error("Erro ao enviar e-mail. Verifique os Secrets.")
    st.stop()

# --- VERIFICAÇÃO 2FA MANDATÓRIA ---
if not st.session_state.auth_2fa:
    st.title("🛡️ Verificação de Segurança")
    st.info(f"Enviamos um código para {st.session_state.user_email}")
    c_in = st.text_input("Digite o código de 6 dígitos")
    if st.button("Confirmar"):
        if c_in == st.session_state.verif_code:
            st.session_state.auth_2fa = True
            st.rerun()
        else: st.error("Código incorreto.")
    st.stop()

# --- TROCA DE SENHA MANDATÓRIA ---
if st.session_state.precisa_trocar:
    st.title("🔑 Troca de Senha Obrigatória")
    st.warning("Para sua segurança, você deve alterar sua senha inicial antes de prosseguir.")
    nova_s = st.text_input("Nova Senha", type="password")
    conf_s = st.text_input("Confirme a Nova Senha", type="password")
    
    if st.button("Atualizar Senha"):
        if nova_s == conf_s and len(nova_s) >= 6:
            c.execute("UPDATE usuarios SET password=?, senha_trocada=1 WHERE id=?", 
                      (hash_password(nova_s), st.session_state.user_id))
            conn.commit()
            st.session_state.precisa_trocar = False
            st.success("Senha atualizada! Acessando painel...")
            st.rerun()
        else: st.error("As senhas não coincidem ou são muito curtas.")
    st.stop()

# --- PAINEL PRINCIPAL ---
st.sidebar.title(f"👤 {st.session_state.display_name}")
if st.sidebar.button("Sair"):
    for key in list(st.session_state.keys()): del st.session_state[key]
    st.rerun()

st.title(f"🚗 Painel Financeiro: {st.session_state.display_name}")

# Abas e funcionalidades (Lançamentos, Ver Dados, Gestão Familiar)
tab1, tab2, tab3 = st.tabs(["➕ Lançar", "📊 Ver Dados", "⚙️ Gestão Familiar"])

with tab1:
    st.write("Formulário de lançamentos aqui...") # Reutilize o código de formulário anterior

with tab2:
    st.write("Gráficos aqui...") # Reutilize o código de gráficos anterior

with tab3:
    st.subheader("👥 Quadro de Controle")
    users = pd.read_sql_query("SELECT nome_exibicao, username, CASE WHEN senha_trocada=1 THEN '✅ Alterada' ELSE '⚠️ Inicial' END as Status FROM usuarios", conn)
    st.table(users)
    
    st.divider()
    st.subheader("➕ Novo Membro")
    with st.form("add_user"):
        n = st.text_input("Nome")
        u = st.text_input("Login")
        e = st.text_input("E-mail")
        s = st.text_input("Senha Inicial", type="password")
        if st.form_submit_button("Criar"):
            c.execute("INSERT INTO usuarios (username, password, email, nome_exibicao, senha_trocada) VALUES (?,?,?,?,?)",
                      (u, hash_password(s), e, n, 0))
            conn.commit()
            st.success(f"Usuário {u} criado com senha inicial.")
            st.rerun()
