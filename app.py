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
    
    # Garantir dados padrão para evitar menus vazios
    for tabela, itens in {"categorias": ["Alimentação", "Moradia"], "beneficiarios": ["Ivan", "Geral"], "fontes": ["Dinheiro Vivo", "Banco Principal"]}.items():
        c.execute(f"SELECT COUNT(*) FROM {tabela}")
        if c.fetchone()[0] == 0:
            for i in itens: c.execute(f"INSERT OR IGNORE INTO {tabela} (nome) VALUES (?)", (i,))
    conn.commit()
    conn.close()

init_db()

# ... (código anterior das funções e init_db)

init_db()

# --- COLE O BLOCO ABAIXO AQUI ---
conn_emergencia = get_conn()
cursor_e = conn_emergencia.cursor()
# Criamos o utilizador 'admin' com a senha '123456'
senha_reset = hashlib.sha256("123456".encode()).hexdigest()
cursor_e.execute("""
    INSERT OR IGNORE INTO usuarios (username, password, email, nome_exibicao, senha_trocada) 
    VALUES (?, ?, ?, ?, ?)
""", ("admin", senha_reset, "seuemail@exemplo.com", "Administrador", 0))
conn_emergencia.commit()
conn_emergencia.close()
# --- FIM DO BLOCO DE EMERGÊNCIA ---

# --- SEGURANÇA (O resto do código continua abaixo) ---
if 'logado' not in st.session_state: st.session_state.logado = False
# ...

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
        else: st.error("Código inválido.")
    st.stop()

if st.session_state.precisa_trocar:
    st.title("🔑 Troca de Senha Obrigatória")
    nova_s = st.text_input("Nova Senha", type="password")
    if st.button("Atualizar"):
        if len(nova_s) >= 6:
            c.execute("UPDATE usuarios SET password=?, senha_trocada=1 WHERE id=?", (hash_password(nova_s), st.session_state.user_id))
            conn.commit()
            st.session_state.precisa_trocar = False
            st.rerun()
        else: st.error("Mínimo 6 caracteres.")
    st.stop()

# --- PAINEL PRINCIPAL ---
st.sidebar.title(f"👤 {st.session_state.display_name}")
if st.sidebar.button("Sair"):
    st.session_state.clear()
    st.rerun()

# Listas para menus
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
        fonte_sel = c3.selectbox("Fonte (Conta/Cartão)", lista_fon)
        cat_sel = st.selectbox("Categoria", lista_cat)
        ben_sel = st.selectbox("Beneficiário", lista_ben)
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        nota = st.text_input("Nota/Descrição")
        if st.form_submit_button("Salvar Registro"):
            v_eur = valor * 0.16 if moeda == "BRL" else valor
            c.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, nota, usuario) VALUES (?,?,?,?,?,?,?,?)",
                      (datetime.now().strftime("%d/%m/%Y"), cat_sel, ben_sel, fonte_sel, v_eur, tipo, nota, st.session_state.display_name))
            conn.commit()
            st.success("✅ Salvo!")
            st.rerun()

with tab2:
    st.subheader("💰 Resumo de Património")
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
    df_all = pd.read_sql_query("SELECT * FROM transacoes ORDER BY id DESC", conn)
    st.dataframe(df_all, use_container_width=True)

with tab3:
    st.header("⚙️ Gestão Administrativa")
    
    # SALDOS INICIAIS
    st.subheader("🎯 Saldos de Abertura")
    cs1, cs2 = st.columns([2, 1])
    f_alvo = cs1.selectbox("Escolha a Conta", lista_fon, key="f_s_base")
    v_ini = cs2.number_input("Saldo na Data de Início (€)", min_value=0.0, key="v_s_base")
    if st.button("Gravar Saldo Inicial", key="btn_s_base"):
        c.execute("INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)", (f_alvo, v_ini))
        conn.commit()
        st.success(f"Saldo inicial de {f_alvo} definido!")
        st.rerun()

    st.divider()

    # GESTÃO DE LISTAS (RECUPERADO)
    col1, col2, col3 = st.columns(3)
    def gerir(tit, tab, lista, k):
        st.markdown(f"**{tit}**")
        st.dataframe(pd.DataFrame(lista, columns=["Nome"]), hide_index=True)
        novo = st.text_input(f"Novo {tit}", key=f"n_{k}")
        if st.button(f"Adicionar", key=f"ba_{k}"):
            if novo: c.execute(f"INSERT OR IGNORE INTO {tab} (nome) VALUES (?)", (novo,)); conn.commit(); st.rerun()
        alvo = st.selectbox(f"Excluir", [""] + lista, key=f"se_{k}")
        if alvo and st.button(f"🗑️ Remover", key=f"be_{k}"):
            c.execute(f"DELETE FROM {tab} WHERE nome=?", (alvo,)); conn.commit(); st.rerun()

    with col1: gerir("💳 Fontes", "fontes", lista_fon, "fon")
    with col2: gerir("🏷️ Categorias", "categorias", lista_cat, "cat")
    with col3: gerir("👤 Beneficiários", "beneficiarios", lista_ben, "ben")

    st.divider()

    # USUÁRIOS (RECUPERADO)
    st.subheader("👥 Gestão de Membros")
    u_df = pd.read_sql_query("SELECT nome_exibicao, username, CASE WHEN senha_trocada=1 THEN '✅ OK' ELSE '⚠️ Inicial' END as Status FROM usuarios", conn)
    st.table(u_df)
    
    with st.expander("➕ Cadastrar Novo Membro"):
        n_n = st.text_input("Nome")
        n_u = st.text_input("Login")
        n_e = st.text_input("E-mail")
        n_s = st.text_input("Senha Inicial", type="password")
        if st.button("Confirmar Cadastro"):
            c.execute("INSERT INTO usuarios (username, password, email, nome_exibicao) VALUES (?,?,?,?)", (n_u, hash_password(n_s), n_e, n_n))
            conn.commit(); st.rerun()

conn.close()
