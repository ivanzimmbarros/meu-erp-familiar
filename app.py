import streamlit as st
import sqlite3
import pandas as pd
import hashlib
from datetime import datetime

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="ERP Familiar Pro", layout="wide")

# Sistema de versão para resetar widgets globalmente
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

# --- INTERFACE PRINCIPAL ---
st.sidebar.title(f"👤 {st.session_state.display_name}")
if st.sidebar.button("Sair"):
    st.session_state.clear()
    st.rerun()

# Carregamento de Listas
lista_cat = pd.read_sql_query("SELECT nome FROM categorias ORDER BY nome", conn)['nome'].tolist()
lista_ben = pd.read_sql_query("SELECT nome FROM beneficiarios ORDER BY nome", conn)['nome'].tolist()
lista_fon = pd.read_sql_query("SELECT nome FROM fontes ORDER BY nome", conn)['nome'].tolist()

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "➕ Lançar", "📊 Ver Dados", "🏷️ Gestão Familiar", "💰 Saldos e Ajustes", "👤 Gestão de Usuários"
])

v = st.session_state.ver # Atalho para a versão atual

with tab1:
    st.subheader("Novo Lançamento")
    with st.form(key=f"form_lanca_{v}", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        valor = c1.number_input("Valor", min_value=0.0, step=0.01)
        moeda = c2.selectbox("Moeda", ["EUR", "BRL"])
        fonte = c3.selectbox("Fonte", lista_fon if lista_fon else ["Padrão"])
        cat = st.selectbox("Categoria", lista_cat if lista_cat else ["Geral"])
        ben = st.selectbox("Beneficiário", lista_ben if lista_ben else ["Família"])
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        nota = st.text_input("Nota/Observação")
        
        if st.form_submit_button("Salvar Registro"):
            if valor > 0:
                v_eur = valor * 0.16 if moeda == "BRL" else valor
                c.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, nota, usuario) VALUES (?,?,?,?,?,?,?,?)",
                          (datetime.now().strftime("%d/%m/%Y"), cat, ben, fonte, v_eur, tipo, nota, st.session_state.display_name))
                conn.commit()
                st.toast(f"✅ Registado: €{v_eur:,.2f}")
                limpar_campos()
                st.rerun()
            else:
                st.error("O valor deve ser maior que zero.")

with tab2:
    st.subheader("📑 Histórico")
    df_h = pd.read_sql_query("SELECT id, data, categoria, beneficiario, fonte, valor_eur, tipo, nota, usuario FROM transacoes ORDER BY id DESC", conn)
    st.dataframe(df_h, use_container_width=True, hide_index=True)

with tab3:
    st.header("⚙️ Gestão de Listas")
    cols = st.columns(3)
    
    def ui_gestao_lista(col, titulo, tabela, lista, k):
        with col:
            st.subheader(titulo)
            nv = st.text_input(f"Novo {titulo}", key=f"in_{k}_{v}")
            if st.button(f"Adicionar", key=f"bt_ad_{k}_{v}"):
                if nv:
                    c.execute(f"INSERT OR IGNORE INTO {tabela} (nome) VALUES (?)", (nv,))
                    conn.commit()
                    st.toast(f"✅ {titulo} criado!")
                    limpar_campos()
                    st.rerun()
            
            sel = st.selectbox(f"Editar {titulo}", [""] + lista, key=f"sl_{k}_{v}")
            if sel:
                ed_n = st.text_input(f"Novo nome", key=f"ed_{k}_{v}")
                b_ed, b_rm = st.columns(2)
                if b_ed.button("Salvar", key=f"ok_{k}_{v}"):
                    c.execute(f"UPDATE {tabela} SET nome=? WHERE nome=?", (ed_n, sel))
                    conn.commit(); st.toast("✅ Atualizado!"); limpar_campos(); st.rerun()
                if b_rm.button("Excluir", key=f"rm_{k}_{v}"):
                    c.execute(f"DELETE FROM {tabela} WHERE nome=?", (sel,))
                    conn.commit(); st.toast("🗑️ Removido!"); limpar_campos(); st.rerun()
            st.dataframe(pd.DataFrame(lista, columns=["Lista"]), hide_index=True)

    ui_gestao_lista(cols[0], "Categoria", "categorias", lista_cat, "ct")
    ui_gestao_lista(cols[1], "Beneficiário", "beneficiarios", lista_ben, "bn")
    ui_gestao_lista(cols[2], "Fonte", "fontes", lista_fon, "fn")

with tab4:
    st.header("💰 Saldos e Ajustes")
    c_f, c_v = st.columns([2, 1])
    f_alvo = c_f.selectbox("Conta", lista_fon, key=f"f_saldo_{v}")
    # Campo limpa automaticamente devido ao key dinâmico
    v_ini = c_v.number_input("Saldo de Abertura (€)", min_value=0.0, step=0.01, key=f"v_saldo_{v}")
    
    if st.button("Gravar Saldo Inicial", key=f"btn_saldo_{v}"):
        if f_alvo:
            c.execute("INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)", (f_alvo, v_ini))
            conn.commit()
            st.toast(f"✅ Saldo de {f_alvo} atualizado!", icon='📈')
            limpar_campos()
            st.rerun()

    st.divider()
    st.subheader("📊 Património por Conta")
    df_t = pd.read_sql_query("SELECT fonte, valor_eur, tipo FROM transacoes", conn)
    df_s = pd.read_sql_query("SELECT * FROM saldos_iniciais", conn)
    
    # Grid Dinâmico: Máximo 4 colunas por linha
    if lista_fon:
        for i in range(0, len(lista_fon), 4):
            batch = lista_fon[i:i+4]
            cols_grid = st.columns(4)
            for j, f in enumerate(batch):
                ini = df_s[df_s['fonte'] == f]['valor_inicial'].sum()
                rec = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Receita')]['valor_eur'].sum()
                des = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Despesa')]['valor_eur'].sum()
                cols_grid[j].metric(f, f"€ {ini+rec-des:,.2f}", f"Inicial: € {ini:,.2f}")

with tab5:
    st.header("👤 Gestão de Utilizadores")
    st.table(pd.read_sql_query("SELECT nome_exibicao, username, email FROM usuarios", conn))
    with st.expander("➕ Cadastrar Novo Membro"):
        n_n = st.text_input("Nome", key=f"un_{v}")
        n_u = st.text_input("Login", key=f"uu_{v}")
        n_e = st.text_input("Email", key=f"ue_{v}")
        n_s = st.text_input("Senha", type="password", key=f"up_{v}")
        if st.button("Finalizar Cadastro", key=f"ub_{v}"):
            if n_u and n_s:
                try:
                    c.execute("INSERT INTO usuarios (username, password, email, nome_exibicao) VALUES (?,?,?,?)", 
                              (n_u, hash_password(n_s), n_e, n_n))
                    conn.commit()
                    st.toast("👤 Membro cadastrado!")
                    limpar_campos()
                    st.rerun()
                except: st.error("Erro: Login já existe.")

conn.close()
