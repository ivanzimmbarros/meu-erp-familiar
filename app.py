import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import smtplib
import random
from email.mime.text import MIMEText
from datetime import datetime

# --- CONFIGURAÇÃO E SEGURANÇA ---
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

# --- INICIALIZAÇÃO ---
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
    
    # Admin Inicial
    senha_adm = hash_password("123456")
    c.execute("INSERT OR IGNORE INTO usuarios (username, password, email, nome_exibicao, senha_trocada) VALUES (?,?,?,?,?)",
              ("admin", senha_adm, "admin@teste.com", "Administrador", 1))
    conn.commit()
    conn.close()

init_db()

# --- FLUXO DE ACESSO ---
if 'logado' not in st.session_state: st.session_state.logado = False
if 'auth_2fa' not in st.session_state: st.session_state.auth_2fa = False

conn = get_conn()
c = conn.cursor()

if not st.session_state.logado:
    st.title("🔐 ERP Familiar")
    u_in = st.text_input("Usuário")
    p_in = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        c.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u_in, hash_password(p_in)))
        user = c.fetchone()
        if user:
            st.session_state.tmp_user = user
            if u_in == "admin":
                st.session_state.logado = True
                st.session_state.auth_2fa = True
                st.session_state.display_name = user[4]
                st.rerun()
            else:
                codigo = str(random.randint(100000, 999999))
                st.session_state.verif_code = codigo
                if enviar_email_2fa(user[3], codigo):
                    st.session_state.logado = True
                    st.rerun()
    st.stop()

# --- INTERFACE PRINCIPAL ---
st.sidebar.title(f"👤 {st.session_state.display_name}")
if st.sidebar.button("Sair"):
    st.session_state.clear()
    st.rerun()

lista_cat = pd.read_sql_query("SELECT nome FROM categorias ORDER BY nome", conn)['nome'].tolist()
lista_ben = pd.read_sql_query("SELECT nome FROM beneficiarios ORDER BY nome", conn)['nome'].tolist()
lista_fon = pd.read_sql_query("SELECT nome FROM fontes ORDER BY nome", conn)['nome'].tolist()

# 5 ABAS PARA ORGANIZAÇÃO TOTAL
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "➕ Lançar", "📊 Ver Dados", "🏷️ Gestão Familiar", "💰 Saldos e Ajustes", "👤 Gestão de Usuários"
])

with tab1:
    st.subheader("Novo Lançamento")
    with st.form("f_lanca", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        valor = c1.number_input("Valor", min_value=0.0)
        moeda = c2.selectbox("Moeda", ["EUR", "BRL"])
        fonte = c3.selectbox("Fonte", lista_fon if lista_fon else ["Padrão"])
        cat = st.selectbox("Categoria", lista_cat if lista_cat else ["Geral"])
        ben = st.selectbox("Beneficiário", lista_ben if lista_ben else ["Casa"])
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        if st.form_submit_button("Salvar Registro"):
            v_eur = valor * 0.16 if moeda == "BRL" else valor
            c.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, usuario) VALUES (?,?,?,?,?,?,?)",
                      (datetime.now().strftime("%d/%m/%Y"), cat, ben, fonte, v_eur, tipo, st.session_state.display_name))
            conn.commit()
            st.toast("✅ Lançamento realizado!", icon='💰')
            st.rerun()

with tab2:
    st.subheader("Histórico Geral")
    df = pd.read_sql_query("SELECT * FROM transacoes ORDER BY id DESC", conn)
    st.dataframe(df, use_container_width=True)

with tab3: # ABA EXCLUSIVA PARA LISTAS
    st.header("🏷️ Gestão de Categorias, Beneficiários e Fontes")
    col_a, col_b, col_c = st.columns(3)
    
    def gerenciar_listas(titulo, tabela, lista, key):
        st.subheader(titulo)
        # Inserção
        novo = st.text_input(f"Adicionar {titulo}", key=f"n_{key}", value="")
        if st.button(f"Confirmar {titulo}", key=f"bn_{key}"):
            if novo:
                c.execute(f"INSERT OR IGNORE INTO {tabela} (nome) VALUES (?)", (novo,))
                conn.commit()
                st.toast(f"✅ {titulo} adicionado!", icon='🎉')
                st.rerun()
        
        # Edição/Exclusão
        alvo = st.selectbox(f"Selecionar para Alterar", [""] + lista, key=f"s_{key}")
        if alvo:
            ed_nome = st.text_input(f"Novo nome para {alvo}", key=f"e_{key}")
            ce1, ce2 = st.columns(2)
            if ce1.button("Renomear", key=f"br_{key}"):
                c.execute(f"UPDATE {tabela} SET nome=? WHERE nome=?", (ed_nome, alvo))
                conn.commit()
                st.toast("✅ Alterado com sucesso!")
                st.rerun()
            if ce2.button("Excluir", key=f"be_{key}"):
                c.execute(f"DELETE FROM {tabela} WHERE nome=?", (alvo,))
                conn.commit()
                st.toast("🗑️ Removido!")
                st.rerun()
        
        # Tabela Atual
        st.write(f"**Lista de {titulo}s:**")
        st.dataframe(pd.DataFrame(lista, columns=["Nome"]), hide_index=True, use_container_width=True)

    with col_a: gerenciar_listas("Categoria", "categorias", lista_cat, "cat")
    with col_b: gerenciar_listas("Beneficiário", "beneficiarios", lista_ben, "ben")
    with col_c: gerenciar_listas("Fonte", "fontes", lista_fon, "fon")

with tab4: # ABA DE SALDOS
    st.header("💰 Saldos de Abertura")
    col_f, col_v = st.columns([2, 1])
    f_alvo = col_f.selectbox("Conta", lista_fon, key="f_aj")
    v_ini = col_v.number_input("Valor Inicial (€)", min_value=0.0, key="v_aj")
    if st.button("Definir Saldo"):
        c.execute("INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)", (f_alvo, v_ini))
        conn.commit()
        st.toast("📈 Saldo de abertura gravado!")
        st.rerun()
    
    st.divider()
    df_t = pd.read_sql_query("SELECT fonte, valor_eur, tipo FROM transacoes", conn)
    df_s = pd.read_sql_query("SELECT * FROM saldos_iniciais", conn)
    cols = st.columns(len(lista_fon)) if lista_fon else st.columns(1)
    for i, f in enumerate(lista_fon):
        ini = df_s[df_s['fonte'] == f]['valor_inicial'].sum()
        rec = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Receita')]['valor_eur'].sum()
        des = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Despesa')]['valor_eur'].sum()
        cols[i].metric(f, f"€ {ini+rec-des:,.2f}", f"Inicial: € {ini:,.2f}")

with tab5: # ABA EXCLUSIVA DE USUÁRIOS
    st.header("👤 Controle de Acessos")
    st.subheader("Membros Cadastrados")
    u_df = pd.read_sql_query("SELECT nome_exibicao, username, email, senha_trocada FROM usuarios", conn)
    st.table(u_df)
    
    # Fechamento correto de aspas para evitar o erro da linha 186
    with st.expander("➕ Cadastrar Novo Membro"):
        n_nome = st.text_input("Nome Completo", key="reg_n")
        n_user = st.text_input("Login (Usuário)", key="reg_u")
        n_mail = st.text_input("E-mail para 2FA", key="reg_e")
        n_pass = st.text_input("Senha Inicial", type="password", key="reg_p")
        if st.button("Salvar Novo Usuário"):
            if n_user and n_pass:
                try:
                    c.execute("INSERT INTO usuarios (username, password, email, nome_exibicao, senha_trocada) VALUES (?,?,?,?,0)", 
                              (n_user, hash_password(n_pass), n_mail, n_nome))
                    conn.commit()
                    st.toast("👤 Usuário criado com sucesso!")
                    st.rerun()
                except: st.error("Este login já existe.")

conn.close()
