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

# --- INICIALIZAÇÃO ESTRUTURAL ---
def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, email TEXT, nome_exibicao TEXT, senha_trocada INTEGER DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS transacoes (id INTEGER PRIMARY KEY, data TEXT, categoria TEXT, beneficiario TEXT, fonte TEXT, valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS beneficiarios (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS fontes (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    conn.commit()
    conn.close()

init_db()

# --- FLUXO DE SEGURANÇA (2FA & LOGIN) ---
if 'logado' not in st.session_state: st.session_state.logado = False
if 'auth_2fa' not in st.session_state: st.session_state.auth_2fa = False

if not st.session_state.logado:
    st.title("🔐 Login: ERP Familiar")
    u_in = st.text_input("Usuário")
    p_in = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        conn = get_conn()
        user = conn.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u_in, hash_password(p_in))).fetchone()
        conn.close()
        if user:
            st.session_state.tmp_user = user
            codigo = str(random.randint(100000, 999999))
            st.session_state.verif_code = codigo
            if enviar_email_2fa(user[3], codigo):
                st.session_state.logado = True
                st.rerun()
            else: st.error("Erro no envio do e-mail. Verifique os Secrets.")
    st.stop()

if not st.session_state.auth_2fa:
    st.title("🛡️ Verificação de Segurança")
    c_in = st.text_input("Digite o código enviado para seu e-mail")
    if st.button("Validar"):
        if c_in == st.session_state.verif_code:
            st.session_state.auth_2fa = True
            u = st.session_state.tmp_user
            st.session_state.user_id, st.session_state.display_name, st.session_state.precisa_trocar = u[0], u[4], (u[5] == 0)
            st.rerun()
        else: st.error("Código incorreto.")
    st.stop()

if st.session_state.precisa_trocar:
    st.title("🔑 Troca de Senha Obrigatória")
    nova = st.text_input("Nova Senha", type="password")
    if st.button("Atualizar"):
        if len(nova) >= 6:
            conn = get_conn()
            conn.execute("UPDATE usuarios SET password=?, senha_trocada=1 WHERE id=?", (hash_password(nova), st.session_state.user_id))
            conn.commit()
            conn.close()
            st.session_state.precisa_trocar = False
            st.rerun()
        else: st.error("Mínimo 6 caracteres.")
    st.stop()

# --- INTERFACE PRINCIPAL ---
conn = get_conn()
lista_cat = pd.read_sql_query("SELECT nome FROM categorias", conn)['nome'].tolist()
lista_ben = pd.read_sql_query("SELECT nome FROM beneficiarios", conn)['nome'].tolist()
lista_fon = pd.read_sql_query("SELECT nome FROM fontes", conn)['nome'].tolist()

st.sidebar.title(f"👤 {st.session_state.display_name}")
if st.sidebar.button("Sair"):
    st.session_state.clear()
    st.rerun()

tab1, tab2, tab3 = st.tabs(["➕ Lançar", "📊 Ver Dados", "⚙️ Gestão Familiar"])

with tab1:
    st.subheader("Novo Lançamento")
    with st.form("form_l", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        val = col1.number_input("Valor", min_value=0.0)
        moe = col2.selectbox("Moeda", ["EUR", "BRL"])
        fon = col3.selectbox("Fonte (Conta/Cartão)", lista_fon)
        cat = st.selectbox("Categoria", lista_cat)
        ben = st.selectbox("Beneficiário", lista_ben)
        tip = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        if st.form_submit_button("Salvar"):
            v_eur = val * 0.16 if moe == "BRL" else val
            conn.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, usuario) VALUES (?,?,?,?,?,?,?)",
                         (datetime.now().strftime("%d/%m/%Y"), cat, ben, fon, v_eur, tip, st.session_state.display_name))
            conn.commit()
            st.success("✅ Salvo!")

with tab3:
    st.subheader("🛠️ Gestão de Listas (Fontes, Categorias e Membros)")
    c1, c2, c3 = st.columns(3)
    
    # Exemplo para FONTES (Repita a lógica para Categorias e Beneficiários)
    with c1:
        st.write("**💳 Fontes (Contas/Cartões)**")
        nf = st.text_input("Nova Fonte")
        if st.button("Adicionar Fonte"):
            conn.execute("INSERT OR IGNORE INTO fontes (nome) VALUES (?)", (nf,))
            conn.commit()
            st.rerun()
        df = st.selectbox("Excluir Fonte", [""] + lista_fon)
        if st.button("Remover"):
            conn.execute("DELETE FROM fontes WHERE nome=?", (df,))
            conn.commit()
            st.rerun()
            
    # [A lógica para Membros e Categorias segue o mesmo padrão aqui]

conn.close()
