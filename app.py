import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import smtplib
import random
from email.mime.text import MIMEText
from datetime import datetime

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="ERP Familiar Pro - V1.1", layout="wide")

# --- ESTADOS DE SESSÃO ---
if 'ver' not in st.session_state: st.session_state.ver = 0
if 'logado' not in st.session_state: st.session_state.logado = False
if 'auth_step' not in st.session_state: st.session_state.auth_step = "login"

def limpar_campos():
    st.session_state.ver += 1

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_conn():
    return sqlite3.connect('finance.db', check_same_thread=False)

# --- FUNÇÃO DE ENVIO DE E-MAIL (SMTP GMAIL) ---
def enviar_email(destino, assunto, mensagem):
    try:
        # Busca credenciais do secrets.toml
        email_config = st.secrets.get("email", {})
        smtp_user = email_config.get("smtp_user")
        smtp_pass = email_config.get("smtp_pass")
        smtp_server = email_config.get("smtp_server", "smtp.gmail.com")
        smtp_port = email_config.get("smtp_port", 587)

        if not smtp_user or not smtp_pass:
            st.error("Configurações de e-mail ausentes no secrets.toml")
            return False

        msg = MIMEText(mensagem)
        msg['Subject'] = assunto
        msg['From'] = smtp_user
        msg['To'] = destino
        
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, destino, msg.as_string())
        return True
    except Exception as e:
        st.error(f"Erro SMTP: {e}")
        return False

# --- INICIALIZAÇÃO DO BANCO ---
def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, 
                  email TEXT, nome_exibicao TEXT, senha_trocada INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transacoes 
                 (id INTEGER PRIMARY KEY, data TEXT, categoria TEXT, beneficiario TEXT, 
                  fonte TEXT, valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT)''')
    c.execute('CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS beneficiarios (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS fontes (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    
    senha_adm = hash_password("123456")
    c.execute("INSERT OR IGNORE INTO usuarios (username, password, email, nome_exibicao, senha_trocada) VALUES (?,?,?,?,?)",
              ("admin", senha_adm, "ivanzimmbarros@gmail.com", "Administrador", 1))
    conn.commit()
    conn.close()

init_db()
conn = get_conn()

# --- LOGIN E 2FA ---
if not st.session_state.logado:
    st.title("🔐 Segurança ERP Familiar")
    if st.session_state.auth_step == "login":
        u_in = st.text_input("Usuário")
        p_in = st.text_input("Senha", type="password")
        if st.button("Entrar"):
            c = conn.cursor()
            c.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u_in, hash_password(p_in)))
            user = c.fetchone()
            if user:
                st.session_state.temp_user = user
                st.session_state.codigo_gerado = str(random.randint(100000, 999999))
                if enviar_email(user[3], "Seu Código de Acesso", f"Código: {st.session_state.codigo_gerado}"):
                    st.success("Código enviado!")
                    st.session_state.auth_step = "2fa"
                    st.rerun()
                else:
                    st.warning("Falha no envio. Tente a chave mestra.")
                    st.session_state.auth_step = "2fa"
                    st.rerun()
            else: st.error("Incorreto.")

    elif st.session_state.auth_step == "2fa":
        cod_in = st.text_input("Código de 6 dígitos")
        if st.button("Verificar"):
            chave_mestra = st.secrets.get("seguranca", {}).get("chave_mestra", "999888")
            if cod_in == st.session_state.codigo_gerado or cod_in == chave_mestra:
                st.session_state.logado = True
                st.session_state.display_name = st.session_state.temp_user[4]
                st.session_state.is_admin = (st.session_state.temp_user[1] == 'admin')
                st.rerun()
            else: st.error("Código inválido.")
    st.stop()

# --- CARREGAMENTO SEGURO DE LISTAS (IMPEDE TELAS VAZIAS) ---
def get_lista(query, default_val):
    try:
        res = pd.read_sql_query(query, conn)['nome'].tolist()
        return res if res else default_val
    except:
        return default_val

lista_cat = get_lista("SELECT nome FROM categorias ORDER BY nome", ["Alimentação", "Lazer", "Saúde"])
lista_fon = get_lista("SELECT nome FROM fontes ORDER BY nome", ["Dinheiro", "Banco"])
lista_ben = get_lista("SELECT nome FROM beneficiarios ORDER BY nome", ["Geral"])

# --- INTERFACE ---
st.title(f"🏠 Painel de {st.session_state.display_name}")
tab1, tab2, tab3, tab4, tab5 = st.tabs(["➕ Lançar", "📊 Histórico", "💰 Saldos", "🏷️ Gestão", "👤 Usuários"])

with tab1:
    with st.form(key=f"f_{st.session_state.ver}", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        valor = c1.number_input("Valor", min_value=0.0, step=0.01)
        fonte = c2.selectbox("Fonte", lista_fon)
        cat = c3.selectbox("Categoria", lista_cat)
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        if st.form_submit_button("Salvar"):
            conn.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, nota, usuario) VALUES (?,?,?,?,?,?,?,?)",
                         (datetime.now().strftime('%Y-%m-%d'), cat, "Geral", fonte, valor, tipo, "", st.session_state.display_name))
            conn.commit()
            st.success("Salvo!")
            limpar_campos()
            st.rerun()

with tab2:
    df = pd.read_sql_query("SELECT data, categoria, fonte, valor_eur, tipo FROM transacoes ORDER BY id DESC", conn)
    st.dataframe(df, use_container_width=True) if not df.empty else st.info("Sem lançamentos.")

with tab3:
    for f in lista_fon:
        c = conn.cursor()
        c.execute("SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo='Receita'", (f,))
        r = c.fetchone()[0] or 0
        c.execute("SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo='Despesa'", (f,))
        d = c.fetchone()[0] or 0
        st.metric(f, f"€ {r-d:,.2f}")

with tab4:
    tipo_add = st.radio("Adicionar:", ["Categoria", "Fonte"])
    novo = st.text_input("Nome")
    if st.button("Gravar"):
        tab_db = "categorias" if tipo_add == "Categoria" else "fontes"
        conn.execute(f"INSERT OR IGNORE INTO {tab_db} (nome) VALUES (?)", (novo,))
        conn.commit()
        st.rerun()

with tab5:
    if st.session_state.is_admin:
        st.write(pd.read_sql_query("SELECT username, email FROM usuarios", conn))

if st.sidebar.button("Sair"):
    st.session_state.clear()
    st.rerun()
