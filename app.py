import streamlit as st
import sqlite3
import pandas as pd
import hashlib
from datetime import datetime
from streamlit.column_config import SelectboxColumn, ColumnConf

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
    "➕ Lançar", "📊 Lançamentos", "💰 Saldos e Ajustes", "🏷️ Gestão Familiar", "👤 Gestão de Usuários"
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
        nota = st.text_input("Nota/Observação")
        
        if st.form_submit_button("Salvar Registro"):
            if valor > 0:
                v_eur = valor * 0.16 if moeda == "BRL" else valor
                c.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, nota, usuario) VALUES (?,?,?,?,?,?,?,?)",
                          (datetime.now().strftime("%d/%m/%Y"), cat, ben, fonte, v_eur, tipo, nota, st.session_state.display_name))
                conn.commit()
                st.toast(f"✅ Registado: €{v_eur:,.2f}")
                limpar_campos(); st.rerun()

with tab2:
    st.subheader("📑 Controle Geral")
    st.info("💡 **Dica:** Passe o mouse sobre o cabeçalho das colunas para ver as setas de ordenação e a lupa de filtro.")
    
    df_h = pd.read_sql_query("SELECT * FROM transacoes ORDER BY id DESC", conn)
    
    # Editor configurado para habilitar lixeira, filtros e ordenação
    edited_df = st.data_editor(
        df_h, 
        key=f"editor_hist_{v}", 
        num_rows="dynamic", # Habilita a lixeira nativa ao selecionar linhas
        use_container_width=True,
        hide_index=True,
        disabled=["id", "usuario"],
        column_config={
            "id": st.column_config.NumberColumn("ID", help="ID único do registro"),
            "data": st.column_config.TextColumn("Data", required=True),
            "categoria": SelectboxColumn("Categoria", options=lista_cat, required=True),
            "beneficiario": SelectboxColumn("Beneficiário", options=lista_ben, required=True),
            "fonte": SelectboxColumn("Fonte", options=lista_fon, required=True),
            "valor_eur": st.column_config.NumberColumn("Valor (€)", format="€ %.2f", required=True),
            "tipo": SelectboxColumn("Tipo", options=["Despesa", "Receita"], required=True),
        }
    )

    with st.expander("🔐 Painel de Confirmação", expanded=True):
        confirmar = st.checkbox("Confirmo que revisei os dados filtrados/ordenados.", key=f"chk_conf_{v}")
        if st.button("💾 Executar Alterações", type="primary", key=f"save_edit_{v}"):
            if confirmar:
                try:
                    c.execute("DELETE FROM transacoes")
                    edited_df.to_sql("transacoes", conn, if_exists="append", index=False)
                    conn.commit()
                    st.toast("🔄 Base de dados atualizada!")
                    limpar_campos(); st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")
            else:
                st.error("A confirmação é obrigatória.")

with tab3:
    st.header("💰 Saldos e Ajustes")
    # ... (Restante do código de saldos permanece igual ao solicitado anteriormente)
    c_f, c_v = st.columns([2, 1])
    f_alvo = c_f.selectbox("Selecionar Conta", lista_fon, key=f"f_aj_{v}")
    v_ini = c_v.number_input("Novo Saldo Inicial (€)", min_value=0.0, step=0.01, key=f"v_aj_{v}")
    
    if st.button("Gravar Ajuste", key=f"btn_aj_{v}"):
        if f_alvo:
            c.execute("INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)", (f_alvo, v_ini))
            conn.commit()
            st.toast(f"📈 Saldo de {f_alvo} atualizado!")
            limpar_campos(); st.rerun()

    st.divider()
    df_t = pd.read_sql_query("SELECT fonte, valor_eur, tipo FROM transacoes", conn)
    df_s = pd.read_sql_query("SELECT * FROM saldos_iniciais", conn)
    
    if lista_fon:
        for i in range(0, len(lista_fon), 4):
            batch = lista_fon[i:i+4]
            cols_grid = st.columns(4)
            for j, f in enumerate(batch):
                ini = df_s[df_s['fonte'] == f]['valor_inicial'].sum()
                rec = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Receita')]['valor_eur'].sum()
                des = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Despesa')]['valor_eur'].sum()
                cols_grid[j].metric(f, f"€ {ini+rec-des:,.2f}", f"Inicial: € {ini:,.2f}")

with tab4:
    st.header("🏷️ Gestão Familiar")
    # ... (Código de gestão de listas sem alterações)
    cols = st.columns(3)
    def ui_gestao(col, tit, tab, lst, k):
        with col:
            st.subheader(tit)
            nv = st.text_input(f"Novo {tit}", key=f"add_{k}_{v}")
            if st.button(f"Add {tit}", key=f"btn_add_{k}_{v}"):
                if nv:
                    c.execute(f"INSERT OR IGNORE INTO {tab} (nome) VALUES (?)", (nv,))
                    conn.commit(); st.toast("✅ Adicionado!"); limpar_campos(); st.rerun()
            sel = st.selectbox(f"Modificar {tit}", [""] + lst, key=f"sel_{k}_{v}")
            if sel:
                nn = st.text_input("Novo nome", key=f"new_{k}_{v}")
                if st.button("Salvar Edição", key=f"sv_{k}_{v}"):
                    c.execute(f"UPDATE {tab} SET nome=? WHERE nome=?", (nn, sel))
                    conn.commit(); st.toast("✅ Nome alterado!"); limpar_campos(); st.rerun()
                if st.button("Excluir Item", key=f"rm_{k}_{v}"):
                    c.execute(f"DELETE FROM {tab} WHERE nome=?", (sel,))
                    conn.commit(); st.toast("🗑️ Removido!"); limpar_campos(); st.rerun()

    ui_gestao(cols[0], "Categoria", "categorias", lista_cat, "c")
    ui_gestao(cols[1], "Beneficiário", "beneficiarios", lista_ben, "b")
    ui_gestao(cols[2], "Fonte", "fontes", lista_fon, "f")

with tab5:
    st.header("👤 Gestão de Usuários")
    st.dataframe(pd.read_sql_query("SELECT nome_exibicao, username, email FROM usuarios", conn), use_container_width=True, hide_index=True)
    with st.expander("➕ Cadastrar Novo Membro", expanded=False):
        n_nom = st.text_input("Nome Completo", key=f"cad_n_{v}")
        n_usr = st.text_input("Login", key=f"cad_u_{v}")
        n_eml = st.text_input("E-mail", key=f"cad_e_{v}")
        n_sen = st.text_input("Senha Provisória", type="password", key=f"cad_s_{v}")
        if st.button("Confirmar Cadastro", key=f"btn_cad_{v}"):
            if n_usr and n_sen:
                try:
                    c.execute("INSERT INTO usuarios (username, password, email, nome_exibicao) VALUES (?,?,?,?)", 
                              (n_usr, hash_password(n_sen), n_eml, n_nom))
                    conn.commit(); st.toast("👤 Usuário cadastrado!"); limpar_campos(); st.rerun()
                except: st.error("Erro: Usuário já existe.")

conn.close()
