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
    
    # Busca dados atualizados do banco
    df_h = pd.read_sql_query("SELECT * FROM transacoes ORDER BY id DESC", conn)
    
    # --- FILTROS DE VISUALIZAÇÃO ---
    f1, f2, f3, f4 = st.columns(4)
    s_cat = f1.multiselect("Filtrar Categoria", lista_cat, key=f"f_cat_{v}")
    s_ben = f2.multiselect("Filtrar Beneficiário", lista_ben, key=f"f_ben_{v}")
    s_fon = f3.multiselect("Filtrar Fonte", lista_fon, key=f"f_fon_{v}")
    s_tip = f4.multiselect("Filtrar Tipo", ["Despesa", "Receita"], key=f"f_tip_{v}")

    df_f = df_h.copy()
    if s_cat: df_f = df_f[df_f['categoria'].isin(s_cat)]
    if s_ben: df_f = df_f[df_f['beneficiario'].isin(s_ben)]
    if s_fon: df_f = df_f[df_f['fonte'].isin(s_fon)]
    if s_tip: df_f = df_f[df_f['tipo'].isin(s_tip)]

    # --- EDITOR DE DADOS (Edição e Seleção para Deleção) ---
    st.write("Selecione as linhas na lateral esquerda para editar ou excluir:")
    edited_df = st.data_editor(
        df_f, 
        key=f"editor_hist_{v}", 
        use_container_width=True, 
        hide_index=True,
        num_rows="dynamic", # Permite deletar linhas selecionando e apertando 'delete' ou pelo botão
        column_config={
            "id": st.column_config.Column(disabled=True),
            "data": st.column_config.Column(width="small"),
            "categoria": st.column_config.SelectboxColumn("Categoria", options=lista_cat, required=True),
            "beneficiario": st.column_config.SelectboxColumn("Beneficiário", options=lista_ben),
            "fonte": st.column_config.SelectboxColumn("Fonte", options=lista_fon, required=True),
            "valor_eur": st.column_config.NumberColumn("Valor (€)", format="%.2f"),
            "tipo": st.column_config.SelectboxColumn("Tipo", options=["Despesa", "Receita"]),
            "usuario": st.column_config.Column(disabled=True)
        }
    )
    
    # --- AÇÕES DE SALVAMENTO E EXCLUSÃO ---
    st.divider()
    col_btn1, col_btn2 = st.columns([1, 4])
    
    confirma = col_btn1.checkbox("⚠️ Confirmar Ação", key=f"check_del_{v}")
    
    if confirma:
        if st.button("💾 Salvar Alterações / Excluir Linhas", type="primary", use_container_width=True):
            try:
                # 1. Identifica o que foi removido comparando o DF original filtrado com o editado
                ids_originais = set(df_f['id'].tolist())
                ids_restantes = set(edited_df['id'].tolist())
                ids_para_deletar = list(ids_originais - ids_restantes)
                
                # 2. Executa a exclusão no Banco de Dados
                if ids_para_deletar:
                    placeholder = ','.join(['?'] * len(ids_para_deletar))
                    conn.execute(f"DELETE FROM transacoes WHERE id IN ({placeholder})", tuple(ids_para_deletar))
                
                # 3. Atualiza os registros existentes (Update via substituição da tabela filtrada)
                # Removemos os registros antigos do set filtrado e reinserimos os novos editados
                placeholder_del = ','.join(['?'] * len(list(ids_originais)))
                conn.execute(f"DELETE FROM transacoes WHERE id IN ({placeholder_del})", tuple(list(ids_originais)))
                edited_df.to_sql("transacoes", conn, if_exists="append", index=False)
                
                conn.commit()
                st.success("Banco de dados atualizado! Saldos recalculados automaticamente.")
                limpar_campos()
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao atualizar: {e}")

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
