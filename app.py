import streamlit as st
import sqlite3
import pandas as pd
import hashlib
from datetime import datetime

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="ERP Familiar Pro", layout="wide")

if 'ver' not in st.session_state: st.session_state.ver = 0
if 'logado' not in st.session_state: st.session_state.logado = False

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
    
    # Dados Iniciais
    senha_adm = hash_password("123456")
    c.execute("INSERT OR IGNORE INTO usuarios (username, password, email, nome_exibicao, senha_trocada) VALUES (?,?,?,?,?)",
              ("admin", senha_adm, "admin@teste.com", "Administrador", 1))
    conn.commit()
    conn.close()

init_db()

# --- LOGIN ---
if not st.session_state.logado:
    st.title("🔐 Acesso ERP Familiar")
    u = st.text_input("Usuário")
    p = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        conn = get_conn()
        user = conn.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u, hash_password(p))).fetchone()
        if user:
            st.session_state.logado = True
            st.session_state.display_name = user[4]
            st.rerun()
        else: st.error("Incorreto")
    st.stop()

# --- CARREGAMENTO DE LISTAS ---
conn = get_conn()
def load_list(query, default):
    res = pd.read_sql_query(query, conn)['nome'].tolist()
    return res if res else default

lista_cat = load_list("SELECT nome FROM categorias ORDER BY nome", ["Geral"])
lista_ben = load_list("SELECT nome FROM beneficiarios ORDER BY nome", ["Geral"])
lista_fon = load_list("SELECT nome FROM fontes ORDER BY nome", ["Padrão"])

# --- INTERFACE ---
tab1, tab2, tab3, tab4, tab5 = st.tabs(["➕ Lançar", "📊 Lançamentos", "💰 Saldos", "⚙️ Gestão", "👤 Usuários"])
v = st.session_state.ver

with tab1:
    st.subheader("Novo Registro")
    with st.form(key=f"f_lanca_{v}", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        valor = c1.number_input("Valor", min_value=0.0)
        moeda = c2.selectbox("Moeda", ["EUR", "BRL"])
        fonte = c3.selectbox("Fonte", lista_fon)
        cat = st.selectbox("Categoria", lista_cat)
        ben = st.selectbox("Beneficiário", lista_ben)
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        nota = st.text_input("Nota")
        if st.form_submit_button("Salvar"):
            v_eur = valor * 0.16 if moeda == "BRL" else valor
            conn.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, nota, usuario) VALUES (?,?,?,?,?,?,?,?)",
                         (datetime.now().strftime("%d/%m/%Y"), cat, ben, fonte, v_eur, tipo, nota, st.session_state.display_name))
            conn.commit()
            st.success("Lançado!")
            limpar_campos(); st.rerun()

with tab2:
    st.subheader("📊 Histórico e Edição")
    
    # 1. Carregamento de dados (sempre fresco do banco)
    df_h = pd.read_sql_query("SELECT * FROM transacoes ORDER BY id DESC", conn)
    
    # Adicionamos uma coluna virtual de seleção para deleção
    df_h.insert(0, "Selecionar", False)

    # 2. Configuração do Editor
    st.write("Marque a caixa 'Selecionar' e clique no botão vermelho para excluir registros.")
    edited_df = st.data_editor(
        df_h, 
        key=f"editor_final_v{st.session_state.ver}", 
        use_container_width=True, 
        hide_index=True,
        column_config={
            "Selecionar": st.column_config.CheckboxColumn("🗑️", default=False),
            "id": st.column_config.Column(disabled=True),
            "usuario": st.column_config.Column(disabled=True)
        }
    )

    st.divider()
    c_save, c_del = st.columns(2)

    # 3. Lógica de Salvar Edições
    if c_save.button("💾 Salvar Alterações de Texto", use_container_width=True):
        # Filtra apenas as linhas que não foram marcadas para seleção
        df_para_salvar = edited_df.drop(columns=["Selecionar"])
        df_para_salvar.to_sql("transacoes", conn, if_exists="replace", index=False)
        conn.commit()
        st.success("Alterações salvas!")
        st.rerun()

    # 4. Lógica de Remoção Segura
    if c_del.button("🗑️ Remover Registros Marcados", type="primary", use_container_width=True):
        # Identifica os IDs onde o checkbox "Selecionar" é True
        ids_para_excluir = edited_df[edited_df["Selecionar"] == True]["id"].tolist()
        
        if ids_para_excluir:
            st.session_state.temp_ids = ids_para_excluir
            st.session_state.confirmar_agora = True
        else:
            st.warning("Nenhuma linha foi marcada no checkbox.")

    # 5. Modal de Confirmação
    if st.session_state.get('confirmar_agora', False):
        st.error(f"Deseja excluir permanentemente {len(st.session_state.temp_ids)} registro(s)?")
        col_s, col_n = st.columns(2)
        
        if col_s.button("SIM, EXCLUIR AGORA", use_container_width=True):
            ids = st.session_state.temp_ids
            query = f"DELETE FROM transacoes WHERE id IN ({','.join(['?']*len(ids))})"
            conn.execute(query, tuple(ids))
            conn.commit()
            
            # Força o reset completo
            st.session_state.confirmar_agora = False
            st.session_state.ver += 1 
            st.success("Excluído com sucesso e saldos atualizados!")
            st.rerun()
            
        if col_n.button("CANCELAR", use_container_width=True):
            st.session_state.confirmar_agora = False
            st.rerun()

with tab3:
    st.header("💰 Saldos e Abertura")
    # Área de ajuste de saldos iniciais
    c_f, c_v = st.columns([2, 1])
    f_alvo = c_f.selectbox("Fonte para Ajuste", lista_fon, key=f"f_adj_{v}")
    v_ini = c_v.number_input("Saldo Inicial (€)", step=0.01, key=f"v_adj_{v}")
    if st.button("Definir Saldo Inicial"):
        conn.execute("INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)", (f_alvo, v_ini))
        conn.commit(); st.rerun()

    st.divider()
    df_t = pd.read_sql_query("SELECT fonte, valor_eur, tipo FROM transacoes", conn)
    df_s = pd.read_sql_query("SELECT * FROM saldos_iniciais", conn)
    cols = st.columns(4)
    for i, f in enumerate(lista_fon):
        ini = df_s[df_s['fonte'] == f]['valor_inicial'].sum()
        rec = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Receita')]['valor_eur'].sum()
        des = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Despesa')]['valor_eur'].sum()
        total = ini + rec - des
        with cols[i % 4]:
            color = "normal" if total >= 0 else "inverse"
            st.metric(f, f"€ {total:,.2f}", f"Inicial: {ini}", delta_color=color)

with tab4:
    st.header("⚙️ Controle de Registros")
    st.write("Gerencie e visualize as listas de parâmetros do sistema.")
    st.divider()

    # Função Mestre para Layout em Colunas com Tabela
    def render_controle_completo(titulo, tabela, lista, icone, key_prefix):
        st.subheader(f"{icone} {titulo}")
        
        # Layout de 3 Colunas: Adicionar | Editar | Visualizar (Tabela)
        col_add, col_edit, col_tab = st.columns([1, 1.2, 0.8])
        
        with col_add:
            st.markdown(f"**➕ Adicionar**")
            n_val = st.text_input(f"Novo {titulo.lower()}", key=f"add_txt_{key_prefix}_{v}", label_visibility="collapsed", placeholder=f"Nome do {titulo.lower()}...")
            if st.button(f"Salvar {titulo}", key=f"btn_add_{key_prefix}_{v}", use_container_width=True):
                if n_val:
                    conn.execute(f"INSERT OR IGNORE INTO {tabela} (nome) VALUES (?)", (n_val,))
                    conn.commit()
                    st.success("Salvo!")
                    limpar_campos(); st.rerun()

        with col_edit:
            st.markdown(f"**📝 Editar/Remover**")
            item_sel = st.selectbox(f"Selecionar {titulo}", [""] + lista, key=f"sel_{key_prefix}_{v}", label_visibility="collapsed")
            
            if item_sel:
                novo_nome = st.text_input(f"Novo nome para {item_sel}", key=f"ren_txt_{key_prefix}_{v}", placeholder="Novo nome...")
                c1, c2 = st.columns(2)
                if c1.button("Renomear", key=f"btn_ren_{key_prefix}_{v}", use_container_width=True):
                    if novo_nome:
                        conn.execute(f"UPDATE {tabela} SET nome=? WHERE nome=?", (novo_nome, item_sel))
                        col_ref = tabela[:-1] if tabela != 'fontes' else 'fonte'
                        conn.execute(f"UPDATE transacoes SET {col_ref}=? WHERE {col_ref}=?", (novo_nome, item_sel))
                        conn.commit(); st.rerun()
                
                if c2.button("Excluir", key=f"btn_del_{key_prefix}_{v}", use_container_width=True, type="secondary"):
                    conn.execute(f"DELETE FROM {tabela} WHERE nome=?", (item_sel,))
                    conn.commit(); st.rerun()

        with col_tab:
            st.markdown(f"**📋 {titulo}s Atuais**")
            # Tabela simples para visualização rápida
            if lista:
                df_temp = pd.DataFrame(lista, columns=["Existentes"])
                st.dataframe(df_temp, hide_index=True, use_container_width=True, height=150)
            else:
                st.info("Lista vazia")

        st.divider()

    # Renderização alinhada e organizada
    render_controle_completo("Categoria", "categorias", lista_cat, "🏷️", "ct")
    render_controle_completo("Beneficiário", "beneficiarios", lista_ben, "👤", "bn")
    render_controle_completo("Fonte", "fontes", lista_fon, "🏦", "fn")

with tab5:
    st.header("👤 Gestão de Usuários")
    with st.expander("➕ Cadastrar Novo Usuário"):
        with st.form("f_usu"):
            n_n = st.text_input("Nome")
            n_u = st.text_input("Username")
            n_e = st.text_input("Email")
            n_p = st.text_input("Senha", type="password")
            if st.form_submit_button("Criar"):
                conn.execute("INSERT INTO usuarios (username, password, email, nome_exibicao) VALUES (?,?,?,?)",
                             (n_u, hash_password(n_p), n_e, n_n))
                conn.commit(); st.rerun()
    st.dataframe(pd.read_sql_query("SELECT username, email, nome_exibicao FROM usuarios", conn), use_container_width=True)

if st.sidebar.button("Sair"):
    st.session_state.clear(); st.rerun()
conn.close()
