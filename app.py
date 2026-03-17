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
    
    # Tabelas de listas dinâmicas
    c.execute('CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS beneficiarios (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS fontes (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    
    # Dados iniciais se estiverem vazias
    for table, defaults in {
        "categorias": ["Alimentação", "Moradia", "Transporte"],
        "beneficiarios": ["Ivan", "Larissa", "Geral"],
        "fontes": ["Dinheiro Vivo", "Banco Principal"]
    }.items():
        c.execute(f"SELECT COUNT(*) FROM {table}")
        if c.fetchone()[0] == 0:
            for item in defaults:
                c.execute(f"INSERT OR IGNORE INTO {table} (nome) VALUES (?)", (item,))
    conn.commit()
    conn.close()

init_db()

# --- LOGIN E SEGURANÇA ---
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
            else: st.error("Erro ao enviar e-mail. Verifique os Secrets.")
    st.stop()

if not st.session_state.auth_2fa:
    st.title("🛡️ Verificação 2FA")
    c_in = st.text_input("Código enviado por e-mail")
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
    if st.button("Salvar Nova Senha"):
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

# Carregar listas dinâmicas para os menus
lista_cat = pd.read_sql_query("SELECT nome FROM categorias", conn)['nome'].tolist()
lista_ben = pd.read_sql_query("SELECT nome FROM beneficiarios", conn)['nome'].tolist()
lista_fon = pd.read_sql_query("SELECT nome FROM fontes", conn)['nome'].tolist()

tab1, tab2, tab3 = st.tabs(["➕ Lançar", "📊 Ver Dados", "⚙️ Gestão Familiar"])

with tab1:
    st.subheader("Novo Lançamento")
    with st.form("form_financeiro", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        valor = col1.number_input("Valor", min_value=0.0)
        moeda = col2.selectbox("Moeda", ["EUR", "BRL"])
        fonte_sel = col3.selectbox("Fonte (Conta/Cartão)", lista_fon)
        
        cat_sel = st.selectbox("Categoria", lista_cat)
        ben_sel = st.selectbox("Beneficiário", lista_ben)
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        nota = st.text_input("Nota/Descrição")
        
        if st.form_submit_button("Salvar Registro"):
            v_eur = valor * 0.16 if moeda == "BRL" else valor
            c.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, nota, usuario) VALUES (?,?,?,?,?,?,?,?)",
                      (datetime.now().strftime("%d/%m/%Y"), cat_sel, ben_sel, fonte_sel, v_eur, tipo, nota, st.session_state.display_name))
            conn.commit()
            st.success("Lançamento salvo!")
            st.rerun()

with tab2:
    st.subheader("Histórico e Análises")
    df = pd.read_sql_query("SELECT * FROM transacoes", conn)
    if not df.empty:
        fig_pizza = px.pie(df[df['tipo'] == 'Despesa'], values='valor_eur', names='categoria', title="Gastos por Categoria")
        st.plotly_chart(fig_pizza, use_container_width=True)
        st.dataframe(df.sort_index(ascending=False), use_container_width=True)
    else: st.info("Sem dados.")

with tab3:
    st.header("⚙️ Gestão de Listas e Usuários")
    
    # --- GESTÃO DE LISTAS DINÂMICAS ---
    col_cat, col_ben, col_fon = st.columns(3)
    
    def gerenciar_secao(titulo, tabela, lista_atual, key):
        st.subheader(titulo)
        st.write("**Lista Atual:**")
        st.dataframe(pd.DataFrame(lista_atual, columns=["Nome"]), hide_index=True)
        
        novo = st.text_input(f"Novo {titulo}", key=f"add_{key}")
        if st.button(f"Adicionar {titulo}", key=f"btn_add_{key}"):
            if novo:
                conn.execute(f"INSERT OR IGNORE INTO {tabela} (nome) VALUES (?)", (novo,))
                conn.commit()
                st.rerun()
        
        alvo = st.selectbox(f"Selecionar {titulo}", [""] + lista_atual, key=f"sel_{key}")
        if alvo:
            novo_n = st.text_input(f"Novo nome para {alvo}", key=f"edit_{key}")
            if st.button("Renomear", key=f"btn_ed_{key}"):
                conn.execute(f"UPDATE {tabela} SET nome=? WHERE nome=?", (novo_n, alvo))
                conn.commit()
                st.rerun()
            if st.button("Excluir", key=f"btn_del_{key}"):
                conn.execute(f"DELETE FROM {tabela} WHERE nome=?", (alvo,))
                conn.commit()
                st.rerun()

    with col_cat: gerenciar_secao("🏷️ Categoria", "categorias", lista_cat, "cat")
    with col_ben: gerenciar_secao("👤 Beneficiário", "beneficiarios", lista_ben, "ben")
    with col_fon: gerenciar_secao("💳 Fonte/Conta", "fontes", lista_fon, "fon")

    st.divider()
    st.subheader("👥 Controle de Usuários")
    u_df = pd.read_sql_query("SELECT nome_exibicao, username, CASE WHEN senha_trocada=1 THEN '✅ Alterada' ELSE '⚠️ Inicial' END as Status FROM usuarios", conn)
    st.table(u_df) # Quadro restaurado
    
    with st.expander("➕ Cadastrar Novo Membro"):
        n = st.text_input("Nome")
        u = st.text_input("Login")
        e = st.text_input("E-mail")
        s = st.text_input("Senha Inicial", type="password")
        if st.button("Criar Usuário"):
            try:
                c.execute("INSERT INTO usuarios (username, password, email, nome_exibicao, senha_trocada) VALUES (?,?,?,?,0)", (u, hash_password(s), e, n))
                conn.commit()
                st.success("Usuário criado!")
                st.rerun()
            except: st.error("Erro: Login já existe.")

conn.close()
