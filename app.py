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
        ben = st.selectbox("Beneficiário", lista_ben if lista_ben else ["Família"])
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        nota = st.text_input("Nota")
        
        if st.form_submit_button("Salvar"):
            if valor > 0:
                v_eur = valor * 0.16 if moeda == "BRL" else valor
                c.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, nota, usuario) VALUES (?,?,?,?,?,?,?,?)",
                          (datetime.now().strftime("%d/%m/%Y"), cat, ben, fonte, v_eur, tipo, nota, st.session_state.display_name))
                conn.commit()
                st.toast(f"✅ Registado: €{v_eur:,.2f}")
                limpar_campos(); st.rerun()

with tab2:
    st.subheader("📊 Filtros e Histórico")
    
    # BUSCA DE DADOS
    df_full = pd.read_sql_query("SELECT * FROM transacoes ORDER BY id DESC", conn)
    
    # BARRA DE FILTROS (Solução para a falta de ícones nativos)
    col_f1, col_f2, col_f3 = st.columns(3)
    f_cat = col_f1.multiselect("Filtrar Categoria", options=lista_cat)
    f_fon = col_f2.multiselect("Filtrar Fonte", options=lista_fon)
    f_tipo = col_f3.multiselect("Filtrar Tipo", options=["Despesa", "Receita"])

    # APLICAÇÃO DOS FILTROS NO DATAFRAME
    df_filtered = df_full.copy()
    if f_cat: df_filtered = df_filtered[df_filtered['categoria'].isin(f_cat)]
    if f_fon: df_filtered = df_filtered[df_filtered['fonte'].isin(f_fon)]
    if f_tipo: df_filtered = df_filtered[df_filtered['tipo'].isin(f_tipo)]

    # TABELA EDITÁVEL
    edited_df = st.data_editor(
        df_filtered,
        key=f"editor_hist_{v}",
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "categoria": st.column_config.SelectboxColumn("Categoria", options=lista_cat),
            "beneficiario": st.column_config.SelectboxColumn("Beneficiário", options=lista_ben),
            "fonte": st.column_config.SelectboxColumn("Fonte", options=lista_fon),
            "valor_eur": st.column_config.NumberColumn("Valor (€)", format="€ %.2f")
        }
    )

    if st.button("💾 Salvar Alterações", type="primary"):
        # Lógica para atualizar apenas as linhas modificadas ou a tabela toda
        try:
            # Para simplificar e garantir integridade:
            ids_na_tabela = edited_df['id'].tolist()
            # 1. Remove do DB o que não está mais no DF filtrado (se deletou linhas)
            # 2. Atualiza o restante. 
            # (Nota: Em apps reais, usaríamos loops de UPDATE por ID)
            st.warning("Funcionalidade de salvamento em lote processando...")
            # Re-inserção simples para este exemplo:
            c.execute("DELETE FROM transacoes WHERE id IN ({})".format(','.join(['?']*len(df_filtered))) if len(df_filtered)>0 else "SELECT 1", tuple(df_filtered['id'].tolist()))
            edited_df.to_sql("transacoes", conn, if_exists="append", index=False)
            conn.commit()
            st.success("✅ Histórico atualizado!")
            limpar_campos(); st.rerun()
        except Exception as e:
            st.error(f"Erro ao salvar: {e}")

# --- RESTANTE DAS ABAS (Saldos, Gestão, Usuários) ---
with tab3:
    st.header("💰 Saldos e Ajustes")
    c_f, c_v = st.columns([2, 1])
    f_alvo = c_f.selectbox("Conta", lista_fon, key=f"f_aj_{v}")
    v_ini = c_v.number_input("Novo Saldo Inicial (€)", min_value=0.0, step=0.01)
    
    if st.button("Gravar Saldo Inicial"):
        c.execute("INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)", (f_alvo, v_ini))
        conn.commit(); st.toast("✅ Saldo Atualizado!"); limpar_campos(); st.rerun()

    st.divider()
    df_t = pd.read_sql_query("SELECT fonte, valor_eur, tipo FROM transacoes", conn)
    df_s = pd.read_sql_query("SELECT * FROM saldos_iniciais", conn)
    
    if lista_fon:
        cols_grid = st.columns(4)
        for i, f in enumerate(lista_fon):
            ini = df_s[df_s['fonte'] == f]['valor_inicial'].sum()
            rec = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Receita')]['valor_eur'].sum()
            des = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Despesa')]['valor_eur'].sum()
            cols_grid[i % 4].metric(f, f"€ {ini+rec-des:,.2f}", f"Inicial: € {ini:,.2f}")

with tab4:
    st.header("🏷️ Gestão de Listas")
    cols = st.columns(3)
    def ui_gestao(col, tit, tab, lst, k):
        with col:
            st.subheader(tit)
            nv = st.text_input(f"Novo {tit}", key=f"add_{k}_{v}")
            if st.button(f"Adicionar", key=f"btn_add_{k}_{v}"):
                c.execute(f"INSERT OR IGNORE INTO {tab} (nome) VALUES (?)", (nv,))
                conn.commit(); limpar_campos(); st.rerun()
            sel = st.selectbox(f"Eliminar {tit}", [""] + lst, key=f"sel_{k}_{v}")
            if st.button(f"Remover", key=f"rm_{k}_{v}"):
                c.execute(f"DELETE FROM {tab} WHERE nome=?", (sel,))
                conn.commit(); limpar_campos(); st.rerun()

    ui_gestao(cols[0], "Categoria", "categorias", lista_cat, "c")
    ui_gestao(cols[1], "Beneficiário", "beneficiarios", lista_ben, "b")
    ui_gestao(cols[2], "Fonte", "fontes", lista_fon, "f")

with tab5:
    st.header("👤 Usuários")
    st.dataframe(pd.read_sql_query("SELECT nome_exibicao, username, email FROM usuarios", conn), use_container_width=True)

conn.close()
