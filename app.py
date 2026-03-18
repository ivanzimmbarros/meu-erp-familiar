import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import smtplib
import random
import plotly.express as px
from email.mime.text import MIMEText
from datetime import datetime

# --- 1. CONFIGURAÇÃO E UTILITÁRIOS ---
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

# --- 2. BANCO DE DADOS (Injeção da Versão 2.1) ---
def init_db():
    conn = get_conn()
    c = conn.cursor()
    # Tabelas Base
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios 
                 (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, 
                  email TEXT, nome_exibicao TEXT, senha_trocada INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transacoes 
                 (id INTEGER PRIMARY KEY, data TEXT, categoria TEXT, beneficiario TEXT, 
                  fonte TEXT, valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT)''')
    c.execute('CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS beneficiarios (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS fontes (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    
    # Nova Tabela: Saldos Iniciais
    c.execute('CREATE TABLE IF NOT EXISTS saldos_iniciais (fonte TEXT PRIMARY KEY, valor_inicial REAL DEFAULT 0.0)')
    
    # Inserção do Usuário de Recuperação
    senha_adm = hash_password("123456")
    c.execute("INSERT OR IGNORE INTO usuarios (username, password, email, nome_exibicao, senha_trocada) VALUES (?,?,?,?,?)",
              ("admin", senha_adm, "admin@teste.com", "Administrador", 1))
    
    # Dados Padrão para evitar tela branca
    defaults = {
        "categorias": ["Alimentação", "Moradia", "Lazer"],
        "beneficiarios": ["Geral", "Casa"],
        "fontes": ["Dinheiro Vivo", "Conta Principal"]
    }
    for table, items in defaults.items():
        c.execute(f"SELECT COUNT(*) FROM {table}")
        if c.fetchone()[0] == 0:
            for item in items:
                c.execute(f"INSERT OR IGNORE INTO {table} (nome) VALUES (?)", (item,))
    conn.commit()
    conn.close()

init_db()

# --- 3. SEGURANÇA E SESSÃO ---
if 'logado' not in st.session_state: st.session_state.logado = False
if 'auth_2fa' not in st.session_state: st.session_state.auth_2fa = False

conn = get_conn()
c = conn.cursor()

if not st.session_state.logado:
    st.title("🔐 Acesso: ERP Familiar")
    u_in = st.text_input("Usuário", key="login_u")
    p_in = st.text_input("Senha", type="password", key="login_p")
    if st.button("Entrar"):
        c.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u_in, hash_password(p_in)))
        user = c.fetchone()
        if user:
            st.session_state.tmp_user = user
            if u_in == "admin": # Bypass emergencial
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
                else: st.error("Erro no envio do e-mail de segurança.")
        else: st.error("Credenciais inválidas.")
    st.stop()

# --- 4. INTERFACE PRINCIPAL ---
st.sidebar.title(f"👤 {st.session_state.display_name}")
if st.sidebar.button("Sair"):
    st.session_state.clear()
    st.rerun()

# Carregar Listas
lista_cat = pd.read_sql_query("SELECT nome FROM categorias ORDER BY nome", conn)['nome'].tolist()
lista_ben = pd.read_sql_query("SELECT nome FROM beneficiarios ORDER BY nome", conn)['nome'].tolist()
lista_fon = pd.read_sql_query("SELECT nome FROM fontes ORDER BY nome", conn)['nome'].tolist()

tab1, tab2, tab3 = st.tabs(["➕ Lançar", "📊 Ver Dados", "⚙️ Gestão Familiar"])

with tab1:
    st.subheader("Novo Lançamento")
    with st.form("form_financeiro", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        valor = c1.number_input("Valor", min_value=0.0)
        moeda = c2.selectbox("Moeda", ["EUR", "BRL"])
        fonte_sel = c3.selectbox("Fonte", lista_fon if lista_fon else ["Padrão"])
        cat_sel = st.selectbox("Categoria", lista_cat if lista_cat else ["Geral"])
        ben_sel = st.selectbox("Beneficiário", lista_ben if lista_ben else ["Família"])
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        nota = st.text_input("Nota/Descrição")
        if st.form_submit_button("Salvar Registro"):
            v_eur = valor * 0.16 if moeda == "BRL" else valor
            c.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, nota, usuario) VALUES (?,?,?,?,?,?,?,?)",
                      (datetime.now().strftime("%d/%m/%Y"), cat_sel, ben_sel, fonte_sel, v_eur, tipo, nota, st.session_state.display_name))
            conn.commit()
            st.success("✅ Lançamento realizado!")
            st.rerun()

with tab2:
    st.subheader("💰 Resumo de Patrimônio Real")
    df_t = pd.read_sql_query("SELECT fonte, valor_eur, tipo FROM transacoes", conn)
    df_s = pd.read_sql_query("SELECT * FROM saldos_iniciais", conn)
    
    if lista_fon:
        cols = st.columns(len(lista_fon))
        for i, f in enumerate(lista_fon):
            # Cálculo: Saldo Inicial + Receitas - Despesas
            val_ini = df_s[df_s['fonte'] == f]['valor_inicial'].sum()
            receitas = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Receita')]['valor_eur'].sum()
            despesas = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Despesa')]['valor_eur'].sum()
            saldo_atual = val_ini + receitas - despesas
            cols[i].metric(f, f"€ {saldo_atual:,.2f}", f"Inicial: € {val_ini:,.2f}")
    
    st.divider()
    df_all = pd.read_sql_query("SELECT * FROM transacoes ORDER BY id DESC", conn)
    st.dataframe(df_all, use_container_width=True)

with tab3:
    st.header("⚙️ Gestão Administrativa")
    
    # Saldos de Abertura
    st.subheader("🎯 Saldos de Abertura")
    col_f, col_v = st.columns([2, 1])
    f_alvo = col_f.selectbox("Conta para Ajuste", lista_fon, key="f_ajuste")
    v_inicial = col_v.number_input("Saldo Inicial (€)", min_value=0.0, key="v_ajuste")
    if st.button("Gravar Saldo Inicial"):
        c.execute("INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)", (f_alvo, v_inicial))
        conn.commit()
        st.success(f"Saldo de {f_alvo} atualizado!")
        st.rerun()

    st.divider()
    
    # Gestão de Membros e Listas
    st.subheader("👥 Gestão de Membros")
    u_df = pd.read_sql_query("SELECT nome_exibicao, username FROM usuarios", conn)
    st.table(u_df)
    
    with st.expander("➕ Cadastrar Novo Membro"):
        n_nome = st.text_input("Nome Completo")
        n_user = st.text_input("Login (Usuário)")
        n_mail = st.text_input("E-mail para 2FA")
        n_pass = st.text_input("Senha Inicial", type="password")
        if st.button("Confirmar Cadastro"):
            if n_user and n_pass:
                try:
                    c.execute("INSERT INTO usuarios (username, password, email, nome_exibicao) VALUES (?,?,?,?)", 
                              (n_user, hash_password(n_pass), n_mail, n_nome))
                    conn.commit()
                    st.success("Membro adicionado!")
                    st.rerun()
                except: st.error("Erro: Usuário já existe.")

conn.close()
