import streamlit as st
import sqlite3
import pandas as pd
import hashlib
from datetime import datetime

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="ERP Familiar Pro", layout="wide")

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
    u_in = st.text_input("Usuário", key=f"login_u_{st.session_state.ver}")
    p_in = st.text_input("Senha", type="password", key=f"login_p_{st.session_state.ver}")
    if st.button("Entrar"):
        c.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u_in, hash_password(p_in)))
        user = c.fetchone()
        if user:
            st.session_state.logado = True
            st.session_state.display_name = user[4]
            st.rerun()
    st.stop()

# --- CARREGAMENTO DE LISTAS ---
lista_cat = pd.read_sql_query("SELECT nome FROM categorias ORDER BY nome", conn)['nome'].tolist()
lista_ben = pd.read_sql_query("SELECT nome FROM beneficiarios ORDER BY nome", conn)['nome'].tolist()
lista_fon = pd.read_sql_query("SELECT nome FROM fontes ORDER BY nome", conn)['nome'].tolist()

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
        fonte = c3.selectbox("Fonte", lista_fon if lista_fon else ["Padrão"])
        cat = st.selectbox("Categoria", lista_cat if lista_cat else ["Geral"])
        ben = st.selectbox("Beneficiário", lista_ben if lista_ben else ["Geral"])
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        nota = st.text_input("Nota")
        
        if st.form_submit_button("Salvar Registro"):
            if valor > 0:
                v_eur = valor * 0.16 if moeda == "BRL" else valor
                c.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, nota, usuario) VALUES (?,?,?,?,?,?,?,?)",
                          (datetime.now().strftime("%d/%m/%Y"), cat, ben, fonte, v_eur, tipo, nota, st.session_state.display_name))
                conn.commit()
                st.toast("✅ Registado!")
                limpar_campos(); st.rerun()

with tab2:
    st.subheader("📊 Controle Geral")
    df_h = pd.read_sql_query("SELECT * FROM transacoes ORDER BY id DESC", conn)
    
    # BARRA DE FILTROS
    f1, f2, f3, f4 = st.columns(4)
    sel_cat = f1.multiselect("Filtrar Categoria", lista_cat)
    sel_ben = f2.multiselect("Filtrar Beneficiário", lista_ben)
    sel_fon = f3.multiselect("Filtrar Fonte", lista_fon)
    sel_tipo = f4.multiselect("Filtrar Tipo", ["Despesa", "Receita"])

    df_f = df_h.copy()
    if sel_cat: df_f = df_f[df_f['categoria'].isin(sel_cat)]
    if sel_ben: df_f = df_f[df_f['beneficiario'].isin(sel_ben)]
    if sel_fon: df_f = df_f[df_f['fonte'].isin(sel_fon)]
    if sel_tipo: df_f = df_f[df_f['tipo'].isin(sel_tipo)]

    # TABELA EDITÁVEL
    edited_df = st.data_editor(
        df_f, 
        key=f"edit_hist_{v}", 
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": st.column_config.Column(disabled=True),
            "categoria": st.column_config.SelectboxColumn("Categoria", options=lista_cat),
            "beneficiario": st.column_config.SelectboxColumn("Beneficiário", options=lista_ben),
            "fonte": st.column_config.SelectboxColumn("Fonte", options=lista_fon),
            "valor_eur": st.column_config.NumberColumn("Valor (€)", format="%.2f"),
            "tipo": st.column_config.SelectboxColumn("Tipo", options=["Despesa", "Receita"]),
            "usuario": st.column_config.Column(disabled=True)
        }
    )

    # PAINEL DE CONFIRMAÇÃO
    with st.expander("🔐 Painel de Confirmação", expanded=True):
        confirmar = st.checkbox("Confirmo que as alterações refletem a realidade financeira.", key=f"chk_{v}")
        if st.button("💾 Executar Alterações", type="primary"):
            if confirmar:
                try:
                    ids_originais = df_f['id'].tolist()
                    if ids_originais:
                        placeholders = ','.join(['?'] * len(ids_originais))
                        query = f"DELETE FROM transacoes WHERE id IN ({placeholders})"
                        c.execute(query, tuple(ids_originais))
                    
                    edited_df.to_sql("transacoes", conn, if_exists="append", index=False)
                    conn.commit()
                    st.success("🔄 Dados atualizados!")
                    limpar_campos(); st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")

with tab3:
    st.header("💰 Saldos e Ajustes")
    c_f, c_v = st.columns([2, 1])
    f_alvo = c_f.selectbox("Escolha a Conta", lista_fon, key=f"
