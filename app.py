import streamlit as st
import sqlite3
import pandas as pd
import hashlib
from datetime import datetime

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="ERP Familiar Pro", layout="wide")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

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
    
    # Admin Inicial (senha: 123456)
    senha_adm = hash_password("123456")
    c.execute("INSERT OR IGNORE INTO usuarios (username, password, email, nome_exibicao, senha_trocada) VALUES (?,?,?,?,?)",
              ("admin", senha_adm, "admin@teste.com", "Administrador", 1))
    conn.commit()
    conn.close()

init_db()

# --- SEGURANÇA ---
if 'logado' not in st.session_state: st.session_state.logado = False
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
            st.session_state.logado = True
            st.session_state.display_name = user[4]
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

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "➕ Lançar", "📊 Ver Dados", "🏷️ Gestão Familiar", "💰 Saldos e Ajustes", "👤 Gestão de Usuários"
])

with tab1:
    st.subheader("Novo Lançamento")
    with st.form("f_lanca", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        valor = c1.number_input("Valor", min_value=0.0, step=0.01, key="val_lan")
        moeda = c2.selectbox("Moeda", ["EUR", "BRL"])
        fonte = c3.selectbox("Fonte", lista_fon if lista_fon else ["Padrão"])
        cat = st.selectbox("Categoria", lista_cat if lista_cat else ["Geral"])
        ben = st.selectbox("Beneficiário", lista_ben if lista_ben else ["Família"])
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        nota = st.text_input("Nota/Observação", key="not_lan")
        
        if st.form_submit_button("Salvar Registro"):
            if valor > 0: # Proteção contra poluição
                v_eur = valor * 0.16 if moeda == "BRL" else valor
                c.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, nota, usuario) VALUES (?,?,?,?,?,?,?,?)",
                          (datetime.now().strftime("%d/%m/%Y"), cat, ben, fonte, v_eur, tipo, nota, st.session_state.display_name))
                conn.commit()
                st.toast(f"✅ Registado: €{v_eur:,.2f}", icon='💰')
                st.rerun() # Limpa campos
            else:
                st.error("Insira um valor maior que zero.")

with tab2:
    st.subheader("📑 Histórico")
    df_h = pd.read_sql_query("SELECT id, data, categoria, beneficiario, fonte, valor_eur, tipo, nota, usuario FROM transacoes ORDER BY id DESC", conn)
    st.dataframe(df_h, use_container_width=True, hide_index=True)

with tab3: # Gestão de Listas
    st.header("⚙️ Gestão de Listas")
    col_a, col_b, col_c = st.columns(3)
    
    def ui_lista(titulo, tabela, lista, k):
        st.subheader(titulo)
        nv = st.text_input(f"Adicionar {titulo}", key=f"add_{k}")
        if st.button(f"Confirmar", key=f"btn_{k}"):
            if nv:
                c.execute(f"INSERT OR IGNORE INTO {tabela} (nome) VALUES (?)", (nv,))
                conn.commit()
                st.toast(f"✅ {nv} adicionado!")
                st.rerun()
        
        sel = st.selectbox(f"Editar/Remover", [""] + lista, key=f"sel_{k}")
        if sel:
            novo_n = st.text_input(f"Novo nome para {sel}", key=f"ed_{k}")
            b1, b2 = st.columns(2)
            if b1.button("Salvar", key=f"ok_{k}"):
                c.execute(f"UPDATE {tabela} SET nome=? WHERE nome=?", (novo_n, sel))
                conn.commit()
                st.toast("✅ Atualizado!")
                st.rerun()
            if b2.button("Apagar", key=f"del_{k}"):
                c.execute(f"DELETE FROM {tabela} WHERE nome=?", (sel,))
                conn.commit()
                st.toast("🗑️ Removido.")
                st.rerun()
        st.dataframe(pd.DataFrame(lista, columns=["Atual"]), hide_index=True, use_container_width=True)

    with col_a: ui_lista("Categoria", "categorias", lista_cat, "c")
    with col_b: ui_lista("Beneficiário", "beneficiarios", lista_ben, "b")
    with col_c: ui_lista("Fonte", "fontes", lista_fon, "f")

with tab4: # Saldos e Ajustes
    st.header("💰 Saldos e Ajustes")
    c_f, c_v = st.columns([2, 1])
    f_alvo = c_f.selectbox("Conta", lista_fon, key="f_aj")
    v_ini = c_v.number_input("Saldo de Abertura (€)", min_value=0.0, step=0.01, key="v_aj")
    if st.button("Gravar Saldo"):
        if f_alvo:
            c.execute("INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)", (f_alvo, v_ini))
            conn.commit()
            st.toast(f"✅ Saldo de {f_alvo} atualizado!", icon='📈')
            st.rerun() # Limpa o valor de entrada

    st.divider()
    df_t = pd.read_sql_query("SELECT fonte, valor_eur, tipo FROM transacoes", conn)
    df_s = pd.read_sql_query("SELECT * FROM saldos_iniciais", conn)
    for f in lista_fon:
        ini = df_s[df_s['fonte'] == f]['valor_inicial'].sum()
        rec = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Receita')]['valor_eur'].sum()
        des = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Despesa')]['valor_eur'].sum()
        st.metric(f, f"€ {ini+rec-des:,.2f}", f"Inicial: € {ini:,.2f}")

with tab5: # Gestão de Usuários
    st.header("👤 Gestão de Utilizadores")
    st.table(pd.read_sql_query("SELECT nome_exibicao, username, email FROM usuarios", conn))
    with st.expander("➕ Cadastrar Novo Membro"):
        n_nom = st.text_input("Nome", key="u_n")
        n_usr = st.text_input("Login", key="u_u")
        n_eml = st.text_input("Email", key="u_e")
        n_sen = st.text_input("Senha", type="password", key="u_p")
        if st.button("Finalizar Cadastro"):
            if n_usr and n_sen:
                try:
                    c.execute("INSERT INTO usuarios (username, password, email, nome_exibicao) VALUES (?,?,?,?)", 
                              (n_usr, hash_password(n_sen), n_eml, n_nom))
                    conn.commit()
                    st.toast("👤 Membro cadastrado!")
                    st.rerun() # Limpa expander
                except: st.error("Usuário já existe.")

conn.close()
