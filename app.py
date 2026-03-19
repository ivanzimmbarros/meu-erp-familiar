import streamlit as st
import sqlite3
import pandas as pd
import hashlib
from datetime import datetime

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="ERP Familiar Pro", layout="wide")

# Inicialização do estado de versão para limpeza de campos
if 'ver' not in st.session_state:
    st.session_state.ver = 0

def limpar_campos():
    st.session_state.ver += 1

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_conn():
    return sqlite3.connect('finance.db', check_same_thread=False)

# --- INICIALIZAÇÃO DB ---
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
    
    # Usuário Admin Padrão
    senha_adm = hash_password("123456")
    c.execute("INSERT OR IGNORE INTO usuarios (username, password, email, nome_exibicao, senha_trocada) VALUES (?,?,?,?,?)",
              ("admin", senha_adm, "admin@teste.com", "Administrador", 1))
    
    # Inserção de dados iniciais para evitar abas vazias no primeiro acesso
    c.execute("INSERT OR IGNORE INTO categorias (nome) VALUES ('Alimentação'), ('Moradia'), ('Lazer')")
    c.execute("INSERT OR IGNORE INTO fontes (nome) VALUES ('Banco'), ('Dinheiro Vivo')")
    c.execute("INSERT OR IGNORE INTO beneficiarios (nome) VALUES ('Geral')")
    
    conn.commit()
    conn.close()

init_db()

# --- SEGURANÇA E SESSÃO ---
if 'logado' not in st.session_state: st.session_state.logado = False
conn = get_conn()

if not st.session_state.logado:
    st.title("🔐 ERP Familiar - Acesso")
    u_in = st.text_input("Usuário", key=f"login_u_{st.session_state.ver}")
    p_in = st.text_input("Senha", type="password", key=f"login_p_{st.session_state.ver}")
    if st.button("Entrar"):
        c = conn.cursor()
        c.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u_in, hash_password(p_in)))
        user = c.fetchone()
        if user:
            st.session_state.logado = True
            st.session_state.display_name = user[4]
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")
    st.stop()

# --- CARREGAMENTO DE LISTAS COM TRATAMENTO DE ERRO (ABAS BLINDADAS) ---
def carregar_lista(query, default):
    try:
        res = pd.read_sql_query(query, conn)['nome'].tolist()
        return res if res else default
    except:
        return default

lista_cat = carregar_lista("SELECT nome FROM categorias ORDER BY nome", ["Geral"])
lista_ben = carregar_lista("SELECT nome FROM beneficiarios ORDER BY nome", ["Geral"])
lista_fon = carregar_lista("SELECT nome FROM fontes ORDER BY nome", ["Padrão"])

# --- NAVEGAÇÃO ---
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "➕ Lançar", "📊 Lançamentos", "💰 Saldos", "🏷️ Gestão", "👤 Usuários"
])

v = st.session_state.ver

with tab1:
    st.subheader("Novo Lançamento")
    with st.form(key=f"f_lanca_{v}", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        valor = c1.number_input("Valor", min_value=0.0, step=0.01)
        moeda = c2.selectbox("Moeda", ["EUR", "BRL"])
        fonte = c3.selectbox("Fonte", lista_fon)
        cat = st.selectbox("Categoria", lista_cat)
        ben = st.selectbox("Beneficiário", lista_ben)
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        nota = st.text_input("Nota")
        
        if st.form_submit_button("Salvar Registro"):
            if valor > 0:
                v_eur = valor * 0.16 if moeda == "BRL" else valor
                conn.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, nota, usuario) VALUES (?,?,?,?,?,?,?,?)",
                          (datetime.now().strftime("%d/%m/%Y"), cat, ben, fonte, v_eur, tipo, nota, st.session_state.display_name))
                conn.commit()
                st.toast("✅ Registado com sucesso!")
                limpar_campos()
                st.rerun()

with tab2:
    st.subheader("📊 Controle Geral")
    df_h = pd.read_sql_query("SELECT * FROM transacoes ORDER BY id DESC", conn)
    
    if not df_h.empty:
        f1, f2, f3 = st.columns(3)
        sel_cat = f1.multiselect("Filtrar Categoria", lista_cat)
        sel_fon = f2.multiselect("Filtrar Fonte", lista_fon)
        sel_tipo = f3.multiselect("Filtrar Tipo", ["Despesa", "Receita"])

        df_f = df_h.copy()
        if sel_cat: df_f = df_f[df_f['categoria'].isin(sel_cat)]
        if sel_fon: df_f = df_f[df_f['fonte'].isin(sel_fon)]
        if sel_tipo: df_f = df_f[df_f['tipo'].isin(sel_tipo)]

        st.data_editor(df_f, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum lançamento encontrado no histórico.")

with tab3:
    st.header("💰 Patrimônio e Saldos")
    df_t = pd.read_sql_query("SELECT fonte, valor_eur, tipo FROM transacoes", conn)
    df_s = pd.read_sql_query("SELECT * FROM saldos_iniciais", conn)
    
    cols_grid = st.columns(4)
    for i, f in enumerate(lista_fon):
        ini = df_s[df_s['fonte'] == f]['valor_inicial'].sum()
        rec = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Receita')]['valor_eur'].sum()
        des = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Despesa')]['valor_eur'].sum()
        saldo_total = ini + rec - des
        
        with cols_grid[i % 4]:
            st.metric(f, f"€ {saldo_total:,.2f}", f"Inicial: € {ini:,.2f}")

with tab4:
    st.header("🏷️ Gestão de Parâmetros")
    cols = st.columns(3)
    
    def ui_gestao(col, tit, tab, lst, k):
        with col:
            st.subheader(tit)
            nv = st.text_input(f"Adicionar {tit}", key=f"add_{k}_{v}")
            if st.button(f"Confirmar {tit}", key=f"btn_add_{k}_{v}"):
                if nv:
                    conn.execute(f"INSERT OR IGNORE INTO {tab} (nome) VALUES (?)", (nv,))
                    conn.commit()
                    limpar_campos()
                    st.rerun()
            sel = st.selectbox(f"Remover {tit}", [""] + lst, key=f"sel_{k}_{v}")
            if st.button(f"Excluir Item", key=f"rm_{k}_{v}"):
                if sel:
                    conn.execute(f"DELETE FROM {tab} WHERE nome=?", (sel,))
                    conn.commit()
                    limpar_campos()
                    st.rerun()

    ui_gestao(cols[0], "Categoria", "categorias", lista_cat, "c")
    ui_gestao(cols[1], "Beneficiário", "beneficiarios", lista_ben, "b")
    ui_gestao(cols[2], "Fonte", "fontes", lista_fon, "f")

with tab5:
    st.header("👤 Gestão de Usuários")
    st.dataframe(pd.read_sql_query("SELECT nome_exibicao, username, email FROM usuarios", conn), use_container_width=True, hide_index=True)
    if st.sidebar.button("Sair"):
        st.session_state.logado = False
        st.rerun()

conn.close()
