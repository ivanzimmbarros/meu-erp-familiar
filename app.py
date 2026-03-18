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
    
    # Barra de Filtros
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

    # Edição de Dados - Sintaxe revisada
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

    with st.expander("🔐 Painel de Confirmação", expanded=True):
        confirmar = st.checkbox("Confirmo que as alterações refletem a realidade financeira.", key=f"chk_{v}")
        if st.button("💾 Executar Alterações", type="primary"):
            if confirmar:
                try:
                    ids_originais = df_f['id'].tolist()
                    if ids_originais:
                        # Correção Sintaxe DELETE
                        ph = ','.join(['?'] * len(ids_originais))
                        c.execute(f"DELETE FROM transacoes WHERE id IN ({ph})", tuple(ids_originais))
                    
                    edited_df.to_sql("transacoes", conn, if_exists="append", index=False)
                    conn.commit()
                    st.success("🔄 Dados atualizados!")
                    limpar_campos(); st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")

with tab3:
    st.header("💰 Saldos e Ajustes")
    c_f, c_v = st.columns([2, 1])
    # Correção Sintaxe Selectbox
    f_alvo = c_f.selectbox("Escolha a Conta", lista_fon, key=f"f_aj_sel_{v}")
    v_ini = c_v.number_input("Saldo de Abertura (€)", step=0.01, key=f"v_ini_aj_{v}")
    
    if st.button("Gravar Saldo Inicial"):
        c.execute("INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)", (f_alvo, v_ini))
        conn.commit()
        st.toast("✅ Saldo Atualizado!")
        limpar_campos(); st.rerun()

    st.divider()
    df_t = pd.read_sql_query("SELECT fonte, valor_eur, tipo FROM transacoes", conn)
    df_s = pd.read_sql_query("SELECT * FROM saldos_iniciais", conn)
    
    st.subheader("Património por Conta")
    cols_grid = st.columns(4)
    for i, f in enumerate(lista_fon):
        ini = df_s[df_s['fonte'] == f]['valor_inicial'].sum()
        rec = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Receita')]['valor_eur'].sum()
        des = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Despesa')]['valor_eur'].sum()
        saldo_total = ini + rec - des
        
        with cols_grid[i % 4]:
            # Lógica de Cor para Saldo Negativo
            if saldo_total < 0:
                st.metric(f, f"€ {saldo_total:,.2f}", delta="ALERTA: NEGATIVO", delta_color="inverse")
            else:
                st.metric(f, f"€ {saldo_total:,.2f}", f"Inicial: € {ini:,.2f}")

with tab4:
    st.header("🏷️ Gestão Familiar")
    cols = st.columns(3)
    def ui_gestao(col, tit, tab, lst, k):
        with col:
            st.subheader(tit)
            nv = st.text_input(f"Novo {tit}", key=f"add_{k}_{v}")
            if st.button(f"Adicionar", key=f"btn_add_{k}_{v}"):
                if nv:
                    c.execute(f"INSERT OR IGNORE INTO {tab} (nome) VALUES (?)", (nv,))
                    conn.commit(); limpar_campos(); st.rerun()
            sel = st.selectbox(f"Remover {tit}", [""] + lst, key=f"sel_{k}_{v}")
            if st.button(f"Excluir Item", key=f"rm_{k}_{v}"):
                if sel:
                    c.execute(f"DELETE FROM {tab} WHERE nome=?", (sel,))
                    conn.commit(); limpar_campos(); st.rerun()

    ui_gestao(cols[0], "Categoria", "categorias", lista_cat, "c")
    ui_gestao(cols[1], "Beneficiário", "beneficiarios", lista_ben, "b")
    # Correção Sintaxe ui_gestao
    ui_gestao(cols[2], "Fonte", "fontes", lista_fon, "f")

with tab5:
    st.header("👤 Gestão de Usuários")
    # Reinstalação do Módulo de Cadastro
    with st.expander("➕ Adicionar Novo Membro"):
        with st.form("f_novo_u", clear_on_submit=True):
            n_n = st.text_input("Nome Completo")
            n_u = st.text_input("Username")
            n_e = st.text_input("Email")
            n_p = st.text_input("Senha", type="password")
            if st.form_submit_button("Cadastrar"):
                if n_u and n_p:
                    try:
                        c.execute("INSERT INTO usuarios (username, password, email, nome_exibicao) VALUES (?,?,?,?)",
                                  (n_u, hash_password(n_p), n_e, n_n))
                        conn.commit()
                        st.success("Conta criada com sucesso!")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("Este nome de usuário já está em uso.")
    
    st.subheader("Contas Ativas")
    # Visualização da tabela de usuários
    st.dataframe(pd.read_sql_query("SELECT nome_exibicao, username, email FROM usuarios", conn), use_container_width=True, hide_index=True)

conn.close()
