import streamlit as st
import sqlite3
import pandas as pd
import hashlib
from datetime import datetime

# --- CONFIGURAÇÃO E ESTADO ---
st.set_page_config(page_title="ERP Familiar Pro", layout="wide")

def init_session():
    defaults = {'ver': 0, 'logado': False, 'display_name': None}
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

init_session()

def get_conn(): return sqlite3.connect('finance.db', check_same_thread=False)

def hash_password(password): return hashlib.sha256(password.encode()).hexdigest()

# --- MIGRAÇÃO E INICIALIZAÇÃO ---
def init_db():
    conn = get_conn()
    c = conn.cursor()
    # Tabelas base
    c.execute('CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, nome_exibicao TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS fontes (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS saldos_iniciais (fonte TEXT PRIMARY KEY, valor_inicial REAL DEFAULT 0.0)')
    
    # Migração Hierárquica Segura
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='categorias'")
    if c.fetchone():
        c.execute("PRAGMA table_info(categorias)")
        cols = [col[1] for col in c.fetchall()]
        if 'pai_id' not in cols:
            c.execute("ALTER TABLE categorias RENAME TO categorias_old")
            c.execute('CREATE TABLE categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE, pai_id INTEGER, FOREIGN KEY(pai_id) REFERENCES categorias(id))')
            c.execute("INSERT INTO categorias (nome, pai_id) SELECT nome, NULL FROM categorias_old")
            c.execute("DROP TABLE categorias_old")
    else:
        c.execute('CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE, pai_id INTEGER, FOREIGN KEY(pai_id) REFERENCES categorias(id))')
    
    # Tabela Transações (9 colunas de inserção)
    c.execute('''CREATE TABLE IF NOT EXISTS transacoes 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT, categoria_pai TEXT, categoria_filho TEXT, 
                  beneficiario TEXT, fonte TEXT, valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT)''')
    
    c.execute("INSERT OR IGNORE INTO usuarios (username, password, nome_exibicao) VALUES (?,?,?)", ("admin", hash_password("123456"), "Administrador"))
    conn.commit()
    conn.close()

init_db()

# --- LOGIN ---
if not st.session_state.logado:
    st.title("🔐 Acesso ERP Familiar")
    u = st.text_input("Usuário"); p = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        user = get_conn().execute("SELECT nome_exibicao FROM usuarios WHERE username=? AND password=?", (u, hash_password(p))).fetchone()
        if user:
            st.session_state.update({'logado': True, 'display_name': user[0]}); st.rerun()
        else: st.error("Credenciais inválidas")
    st.stop()

# --- INTERFACE ---
conn = get_conn()
tab1, tab2, tab3, tab4 = st.tabs(["➕ Lançar", "📊 Lançamentos", "💰 Saldos", "⚙️ Gestão"])

with tab1:
    st.subheader("Novo Lançamento")
    cat_df = pd.read_sql_query("SELECT id, nome, pai_id FROM categorias", conn)
    pai_opts = cat_df[cat_df['pai_id'].isna()]['nome'].tolist()
    
    with st.form(key=f"f_lanca_{st.session_state.ver}", clear_on_submit=True):
        col1, col2 = st.columns(2)
        val = col1.number_input("Valor", min_value=0.0)
        moeda = col2.selectbox("Moeda", ["EUR", "BRL"])
        
        sel_pai = st.selectbox("Categoria Pai", pai_opts if pai_opts else ["Cadastre um Pai em Gestão"])
        
        filhos = []
        if sel_pai != "Cadastre um Pai em Gestão":
            pid = cat_df[cat_df['nome'] == sel_pai]['id'].iloc[0]
            filhos = cat_df[cat_df['pai_id'] == pid]['nome'].tolist()
        
        sel_filho = st.selectbox("Subcategoria", filhos if filhos else ["Geral"])
        fonte = st.selectbox("Fonte", pd.read_sql_query("SELECT nome FROM fontes", conn)['nome'].tolist() or ["Padrão"])
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        nota = st.text_input("Nota")
        
        if st.form_submit_button("Salvar"):
            v_eur = val * 0.16 if moeda == "BRL" else val
            conn.execute("INSERT INTO transacoes (data, categoria_pai, categoria_filho, beneficiario, fonte, valor_eur, tipo, nota, usuario) VALUES (?,?,?,?,?,?,?,?,?)",
                         (datetime.now().strftime("%d/%m/%Y"), sel_pai, sel_filho, "Geral", fonte, v_eur, tipo, nota, st.session_state.display_name))
            conn.commit(); st.session_state.ver += 1; st.rerun()

with tab2:
    df = pd.read_sql_query("SELECT * FROM transacoes ORDER BY id DESC", conn)
    df.insert(0, "Remover", False)
    editor = st.data_editor(df, key=f"ed_{st.session_state.ver}")
    if st.button("🗑️ Confirmar Remoção"):
        ids = editor[editor["Remover"] == True]["id"].tolist()
        if ids:
            conn.execute(f"DELETE FROM transacoes WHERE id IN ({','.join(['?']*len(ids))})", tuple(ids))
            conn.commit(); st.session_state.ver += 1; st.rerun()

with tab3:
    st.header("💰 Saldos Consolidados")
    fontes = pd.read_sql_query("SELECT nome FROM fontes", conn)['nome'].tolist() or ["Padrão"]
    for f in fontes:
        ini = conn.execute("SELECT valor_inicial FROM saldos_iniciais WHERE fonte=?", (f,)).fetchone()
        ini = ini[0] if ini else 0.0
        rec = conn.execute("SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo='Receita'", (f,)).fetchone()[0] or 0.0
        des = conn.execute("SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo='Despesa'", (f,)).fetchone()[0] or 0.0
        saldo = ini + rec - des
        st.metric(f"Fonte: {f}", f"€ {saldo:,.2f}")

with tab4:
    st.header("⚙️ Gestão Hierárquica")
    c1, c2 = st.columns(2)
    with c1:
        n_p = st.text_input("Novo Pai"); 
        if st.button("Adicionar Pai"): conn.execute("INSERT INTO categorias (nome) VALUES (?)", (n_p,)); st.rerun()
    with c2:
        pai_sel = st.selectbox("Vincular a qual Pai?", pai_opts)
        n_s = st.text_input("Nova Subcategoria")
        if st.button("Adicionar Subcategoria"):
            pid = cat_df[cat_df['nome'] == pai_sel]['id'].iloc[0]
            conn.execute("INSERT INTO categorias (nome, pai_id) VALUES (?,?)", (n_s, pid)); st.rerun()

if st.sidebar.button("Sair"): st.session_state.clear(); st.rerun()
conn.close()
