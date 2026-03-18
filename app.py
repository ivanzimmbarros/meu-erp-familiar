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
        smtp_user = st.secrets["email"]["smtp_user"]
        smtp_pass = st.secrets["email"]["smtp_pass"]
        smtp_server = st.secrets["email"]["smtp_server"]
        smtp_port = st.secrets["email"]["smtp_port"]

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
        st.error(f"Erro ao enviar e-mail: {e}")
        return False

# --- INICIALIZAÇÃO DO BANCO DE DADOS ---
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
    c.execute('CREATE TABLE IF NOT EXISTS saldos_iniciais (fonte TEXT PRIMARY KEY, valor_inicial REAL DEFAULT 0.0)')
    
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
                    st.session_state.auth_step = "2fa"
                    st.rerun()
                else:
                    st.session_state.auth_step = "2fa"
                    st.rerun()
            else:
                st.error("Credenciais inválidas.")
    elif st.session_state.auth_step == "2fa":
        st.info("Código enviado ao e-mail.")
        cod_in = st.text_input("Código de 6 dígitos")
        if st.button("Verificar"):
            if cod_in == st.session_state.codigo_gerado or cod_in == st.secrets.get("seguranca", {}).get("chave_mestra", "999888"):
                st.session_state.logado = True
                st.session_state.display_name = st.session_state.temp_user[4]
                st.session_state.is_admin = (st.session_state.temp_user[1] == 'admin')
                st.rerun()
            else: st.error("Incorreto.")
    st.stop()

# --- CARREGAMENTO DE LISTAS (PREVENÇÃO DE ERRO DE TELA VAZIA) ---
def carregar_listas():
    try:
        cats = pd.read_sql_query("SELECT nome FROM categorias ORDER BY nome", conn)['nome'].tolist()
        fons = pd.read_sql_query("SELECT nome FROM fontes ORDER BY nome", conn)['nome'].tolist()
        bens = pd.read_sql_query("SELECT nome FROM beneficiarios ORDER BY nome", conn)['nome'].tolist()
    except:
        cats, fons, bens = [], [], []

    # Se estiver vazio no banco, injeta valores para a tela não quebrar
    if not cats: cats = ["Alimentação", "Moradia", "Lazer", "Outros"]
    if not fons: fons = ["Dinheiro", "Banco", "Cartão"]
    if not bens: bens = ["Geral"]
    return cats, fons, bens

lista_cat, lista_fon, lista_ben = carregar_listas()

# --- INTERFACE PRINCIPAL ---
st.title(f"🏠 Bem-vindo, {st.session_state.display_name}")
tab1, tab2, tab3, tab4, tab5 = st.tabs(["➕ Lançar", "📊 Lançamentos", "💰 Saldos", "🏷️ Gestão", "👤 Usuários"])

with tab1:
    with st.form(key=f"form_l_{st.session_state.ver}", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        valor = col1.number_input("Valor", min_value=0.0, step=0.01)
        fonte = col2.selectbox("Fonte", lista_fon)
        cat = col3.selectbox("Categoria", lista_cat)
        
        col4, col5 = st.columns(2)
        ben = col4.selectbox("Beneficiário", lista_ben)
        tipo = col5.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        
        nota = st.text_input("Descrição")
        data = st.date_input("Data", datetime.now())
        
        if st.form_submit_button("Salvar"):
            c = conn.cursor()
            c.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, nota, usuario) VALUES (?,?,?,?,?,?,?,?)",
                      (data.strftime('%Y-%m-%d'), cat, ben, fonte, valor, tipo, nota, st.session_state.display_name))
            conn.commit()
            st.success("Salvo!")
            limpar_campos()
            st.rerun()

with tab2:
    st.subheader("Histórico")
    df = pd.read_sql_query("SELECT data, categoria, beneficiario, fonte, valor_eur, tipo, nota FROM transacoes ORDER BY data DESC", conn)
    st.dataframe(df, use_container_width=True) if not df.empty else st.info("Sem dados.")

with tab3:
    st.subheader("Saldos Atuais")
    for f in lista_fon:
        c_s = conn.cursor()
        c_s.execute("SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo='Receita'", (f,))
        r = c_s.fetchone()[0] or 0
        c_s.execute("SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo='Despesa'", (f,))
        d = c_s.fetchone()[0] or 0
        st.metric(label=f, value=f"€ {r - d:,.2f}")

with tab4:
    st.subheader("Gestão de Itens")
    tipo_g = st.radio("O que deseja adicionar?", ["Categoria", "Fonte", "Beneficiário"], horizontal=True)
    novo_item = st.text_input(f"Nome da nova {tipo_g}")
    if st.button("Cadastrar"):
        tabela = "categorias" if tipo_g == "Categoria" else "fontes" if tipo_g == "Fonte" else "beneficiarios"
        conn.execute(f"INSERT OR IGNORE INTO {tabela} (nome) VALUES (?)", (novo_item,))
        conn.commit()
        st.success("Adicionado!")
        st.rerun()

with tab5:
    if st.session_state.is_admin:
        st.dataframe(pd.read_sql_query("SELECT id, username, email, nome_exibicao FROM usuarios", conn), use_container_width=True)
    else: st.warning("Acesso restrito.")

if st.sidebar.button("Sair"):
    st.session_state.logado = False
    st.rerun()
