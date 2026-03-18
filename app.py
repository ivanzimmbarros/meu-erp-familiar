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
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, 
                  email TEXT, nome_exibicao TEXT, senha_trocada INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transacoes 
                 (id INTEGER PRIMARY KEY, data TEXT, categoria TEXT, beneficiario TEXT, 
                  fonte TEXT, valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT)''')
    c.execute('CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS beneficiarios (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS fontes (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    
    # NOVA TABELA PARA SALDOS INICIAIS
    c.execute('CREATE TABLE IF NOT EXISTS saldos_iniciais (fonte TEXT PRIMARY KEY, valor_inicial REAL DEFAULT 0.0)')
    
    # GARANTIR USUÁRIO ADMIN (Recuperação)
    senha_adm = hash_password("123456")
    c.execute("INSERT OR IGNORE INTO usuarios (username, password, email, nome_exibicao, senha_trocada) VALUES (?,?,?,?,?)",
              ("admin", senha_adm, "admin@teste.com", "Administrador", 1))
    
    # Preencher se estiver vazio
    for table, defaults in {"categorias": ["Geral"], "beneficiarios": ["Família"], "fontes": ["Banco"]}.items():
        c.execute(f"SELECT COUNT(*) FROM {table}")
        if c.fetchone()[0] == 0:
            for item in defaults: c.execute(f"INSERT OR IGNORE INTO {table} (nome) VALUES (?)", (item,))
    conn.commit()
    conn.close()

init_db()

# --- LOGIN E SEGURANÇA (Versão Base) ---
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
            if u_in == "admin": # Bypass para Admin não depender de e-mail inexistente
                st.session_state.logado = True
                st.session_state.auth_2fa = True
                st.session_state.user_id = user[0]
                st.session_state.display_name = user[4]
                st.rerun()
            else:
                codigo = str(random.randint(100000, 999999))
                st.session_state.verif_code = codigo
                if enviar_email_2fa(user[3], codigo):
                    st.session_state.logado = True
                    st.rerun()
                else: st.error("Verifique os Secrets de e-mail.")
    st.stop()

# --- PAINEL PRINCIPAL ---
st.sidebar.title(f"👤 {st.session_state.display_name}")
if st.sidebar.button("Sair"):
    st.session_state.clear()
    st.rerun()

lista_cat = pd.read_sql_query("SELECT nome FROM categorias", conn)['nome'].tolist()
lista_ben = pd.read_sql_query("SELECT nome FROM beneficiarios", conn)['nome'].tolist()
lista_fon = pd.read_sql_query("SELECT nome FROM fontes", conn)['nome'].tolist()

# ADICIONADA TAB4 PARA NÃO MEXER NAS EXISTENTES
tab1, tab2, tab3, tab4 = st.tabs(["➕ Lançar", "📊 Ver Dados", "⚙️ Gestão Familiar", "💰 Saldos e Ajustes"])

with tab1: # CÓDIGO DA VERSÃO BASE
    st.subheader("Novo Lançamento")
    with st.form("form_financeiro", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        valor = col1.number_input("Valor", min_value=0.0)
        moeda = col2.selectbox("Moeda", ["EUR", "BRL"])
        fonte_sel = col3.selectbox("Fonte", lista_fon)
        cat_sel = st.selectbox("Categoria", lista_cat)
        ben_sel = st.selectbox("Beneficiário", lista_ben)
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        if st.form_submit_button("Salvar"):
            v_eur = valor * 0.16 if moeda == "BRL" else valor
            c.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, usuario) VALUES (?,?,?,?,?,?,?)",
                      (datetime.now().strftime("%d/%m/%Y"), cat_sel, ben_sel, fonte_sel, v_eur, tipo, st.session_state.display_name))
            conn.commit(); st.success("Salvo!"); st.rerun()

with tab2: # CÓDIGO DA VERSÃO BASE
    st.subheader("Histórico")
    df = pd.read_sql_query("SELECT * FROM transacoes ORDER BY id DESC", conn)
    st.dataframe(df, use_container_width=True)

with tab3: # CÓDIGO DA VERSÃO BASE
    st.header("⚙️ Gestão de Listas e Usuários")
    col_cat, col_ben, col_fon = st.columns(3)
    def gerenciar_secao(titulo, tabela, lista_atual, key):
        st.subheader(titulo)
        novo = st.text_input(f"Novo {titulo}", key=f"add_{key}")
        if st.button(f"Adicionar", key=f"btn_add_{key}"):
            if novo: c.execute(f"INSERT OR IGNORE INTO {tabela} (nome) VALUES (?)", (novo,)); conn.commit(); st.rerun()
        alvo = st.selectbox(f"Editar/Excluir", [""] + lista_atual, key=f"sel_{key}")
        if alvo:
            novo_n = st.text_input(f"Renomear {alvo}", key=f"edit_{key}")
            if st.button("OK", key=f"btn_ed_{key}"):
                c.execute(f"UPDATE {tabela} SET nome=? WHERE nome=?", (novo_n, alvo)); conn.commit(); st.rerun()
            if st.button("Remover", key=f"btn_del_{key}"):
                c.execute(f"DELETE FROM {tabela} WHERE nome=?", (alvo,)); conn.commit(); st.rerun()

    with col_cat: gerenciar_secao("Categoria", "categorias", lista_cat, "c")
    with col_ben: gerenciar_secao("Beneficiário", "beneficiarios", lista_ben, "b")
    with col_fon: gerenciar_secao("Fonte", "fontes", lista_fon, "f")

    st.divider()
    st.subheader("👥 Usuários")
    st.table(pd.read_sql_query("SELECT nome_exibicao, username FROM usuarios", conn))

with tab4: # NOVA ABA: SALDOS E AJUSTES
    st.header("💰 Ajuste de Inventário e Saldos")
    st.info("Defina aqui quanto você já tem em cada conta antes de começar os lançamentos.")
    
    col_f, col_v = st.columns([2, 1])
    f_alvo = col_f.selectbox("Selecione a Conta", lista_fon, key="f_ajuste")
    v_inicial = col_v.number_input("Saldo Inicial Atual (€)", min_value=0.0, key="v_ajuste")
    
    if st.button("Gravar Saldo Inicial"):
        c.execute("INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)", (f_alvo, v_inicial))
        conn.commit()
        st.success(f"Saldo de abertura para {f_alvo} definido com sucesso!")
        st.rerun()
    
    st.divider()
    st.subheader("📈 Patrimônio Líquido Atual")
    df_t = pd.read_sql_query("SELECT fonte, valor_eur, tipo FROM transacoes", conn)
    df_s = pd.read_sql_query("SELECT * FROM saldos_iniciais", conn)
    
    for f in lista_fon:
        ini = df_s[df_s['fonte'] == f]['valor_inicial'].sum()
        rec = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Receita')]['valor_eur'].sum()
        des = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Despesa')]['valor_eur'].sum()
        st.metric(f, f"€ {ini + rec - des:,.2f}", f"Inicial: € {ini:,.2f}")

conn.close()
