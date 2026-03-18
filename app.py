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
    c.execute('CREATE TABLE IF NOT EXISTS saldos_iniciais (fonte TEXT PRIMARY KEY, valor_inicial REAL DEFAULT 0.0)')
    
    # Garantir utilizador admin de emergência
    senha_admin = hash_password("123456")
    c.execute("INSERT OR IGNORE INTO usuarios (username, password, email, nome_exibicao, senha_trocada) VALUES (?,?,?,?,?)",
              ("admin", senha_admin, "admin@teste.com", "Administrador", 1))
    
    for table, defaults in {"categorias": ["Alimentação", "Moradia"], "beneficiarios": ["Geral"], "fontes": ["Dinheiro Vivo", "Banco"]}.items():
        c.execute(f"SELECT COUNT(*) FROM {table}")
        if c.fetchone()[0] == 0:
            for item in defaults: c.execute(f"INSERT OR IGNORE INTO {table} (nome) VALUES (?)", (item,))
    conn.commit()
    conn.close()

init_db()

# --- SEGURANÇA E ACESSO ---
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
            if u_in == "admin": # Bypass emergencial para admin
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
                else: st.error("Erro no 2FA. Verifique os Secrets.")
    st.stop()

if not st.session_state.auth_2fa:
    st.title("🛡️ Verificação 2FA")
    c_in = st.text_input("Código de 6 dígitos")
    if st.button("Confirmar"):
        if c_in == st.session_state.verif_code:
            st.session_state.auth_2fa = True
            st.session_state.user_id = st.session_state.tmp_user[0]
            st.session_state.display_name = st.session_state.tmp_user[4]
            st.session_state.precisa_trocar = (st.session_state.tmp_user[5] == 0)
            st.rerun()
    st.stop()

# --- PAINEL PRINCIPAL ---
st.sidebar.title(f"👤 {st.session_state.display_name}")
if st.sidebar.button("Sair"):
    st.session_state.clear()
    st.rerun()

# Carregar listas para evitar menus vazios (Causa da tela branca)
lista_cat = pd.read_sql_query("SELECT nome FROM categorias", conn)['nome'].tolist()
lista_ben = pd.read_sql_query("SELECT nome FROM beneficiarios", conn)['nome'].tolist()
lista_fon = pd.read_sql_query("SELECT nome FROM fontes", conn)['nome'].tolist()

tab1, tab2, tab3 = st.tabs(["➕ Lançar", "📊 Ver Dados", "⚙️ Gestão Familiar"])

with tab1:
    st.subheader("Novo Lançamento")
    with st.form("f_lanc", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        valor = c1.number_input("Valor", min_value=0.0)
        moeda = c2.selectbox("Moeda", ["EUR", "BRL"])
        fonte = c3.selectbox("Fonte", lista_fon if lista_fon else ["Padrão"])
        cat = st.selectbox("Categoria", lista_cat if lista_cat else ["Geral"])
        ben = st.selectbox("Beneficiário", lista_ben if lista_ben else ["Geral"])
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        if st.form_submit_button("Salvar"):
            v_eur = valor * 0.16 if moeda == "BRL" else valor
            c.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, usuario) VALUES (?,?,?,?,?,?,?)",
                      (datetime.now().strftime("%d/%m/%Y"), cat, ben, fonte, v_eur, tipo, st.session_state.display_name))
            conn.commit()
            st.success("Lançamento Registado!")
            st.rerun()

with tab2:
    st.subheader("💰 Resumo de Património Reais")
    df_t = pd.read_sql_query("SELECT fonte, valor_eur, tipo FROM transacoes", conn)
    df_s = pd.read_sql_query("SELECT * FROM saldos_iniciais", conn)
    if lista_fon:
        cols = st.columns(len(lista_fon))
        for i, f in enumerate(lista_fon):
            ini = df_s[df_s['fonte'] == f]['valor_inicial'].sum()
            rec = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Receita')]['valor_eur'].sum()
            des = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Despesa')]['valor_eur'].sum()
            cols[i].metric(f, f"€ {ini+rec-des:,.2f}", f"Inicial: € {ini:,.2f}")
    st.divider()
    st.dataframe(pd.read_sql_query("SELECT * FROM transacoes ORDER BY id DESC", conn), use_container_width=True)

with tab3:
    st.header("⚙️ Gestão Familiar")
    
    # 1. SALDOS INICIAIS (Item 3.1 do Prompt)
    st.subheader("🎯 Definir Saldos de Abertura")
    cs1, cs2 = st.columns([2, 1])
    f_alvo = cs1.selectbox("Conta", lista_fon, key="sel_f_base")
    v_ini = cs2.number_input("Saldo Inicial (€)", min_value=0.0, key="num_v_base")
    if st.button("Gravar Saldo Inicial"):
        c.execute("INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)", (f_alvo, v_ini))
        conn.commit(); st.rerun()

    st.divider()

    # 2. GESTÃO DE LISTAS (Recuperado da Versão Base)
    col_a, col_b, col_c = st.columns(3)
    def gerir(tit, tab, lista, k):
        st.write(f"**{tit}**")
        st.dataframe(pd.DataFrame(lista, columns=["Nome"]), hide_index=True)
        novo = st.text_input(f"Adicionar {tit}", key=f"add_{k}")
        if st.button(f"Salvar {k}", key=f"btn_{k}"):
            if novo: c.execute(f"INSERT OR IGNORE INTO {tab} (nome) VALUES (?)", (novo,)); conn.commit(); st.rerun()
        alvo = st.selectbox(f"Remover", [""] + lista, key=f"del_{k}")
        if alvo and st.button(f"🗑️ Excluir", key=f"btndel_{k}"):
            c.execute(f"DELETE FROM {tab} WHERE nome=?", (alvo,)); conn.commit(); st.rerun()

    with col_a: gerir("💳 Fontes", "fontes", lista_fon, "f")
    with col_b: gerir("🏷️ Categorias", "categorias", lista_cat, "c")
    with col_c: gerir("👤 Membros", "beneficiarios", lista_ben, "b")

    st.divider()
    
    # 3. USUÁRIOS (Recuperado da Versão Base)
    st.subheader("👥 Controle de Membros")
    st.table(pd.read_sql_query("SELECT nome_exibicao, username FROM usuarios", conn))
    with st.expander("➕ Cadastrar
