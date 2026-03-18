import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import smtplib
import random
from email.mime.text import MIMEText
from datetime import datetime

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="ERP Familiar Pro", layout="wide")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def enviar_email_2fa(destino, codigo):
    try:
        corpo = f"Seu código de verificação é: {codigo}"
        msg = MIMEText(corpo)
        msg['Subject'] = "🔒 Código 2FA - ERP Familiar"
        msg['From'] = st.secrets["email"]["smtp_user"]
        msg['To'] = destino
        with smtplib.SMTP(st.secrets["email"]["smtp_server"], st.secrets["email"]["smtp_port"]) as server:
            server.starttls()
            server.login(st.secrets["email"]["smtp_user"], st.secrets["email"]["smtp_pass"])
            server.sendmail(st.secrets["email"]["smtp_user"], destino, msg.as_string())
        return True
    except: return False

def get_conn():
    return sqlite3.connect('finance.db', check_same_thread=False)

# --- INICIALIZAÇÃO DO BANCO ---
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
    
    # Usuario admin inicial
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
    st.title("🔐 Acesso: ERP Familiar")
    u_in = st.text_input("Usuário", key="login_user")
    p_in = st.text_input("Senha", type="password", key="login_pass")
    if st.button("Entrar"):
        c.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u_in, hash_password(p_in)))
        user = c.fetchone()
        if user:
            st.session_state.logado = True
            st.session_state.display_name = user[4]
            st.rerun()
    st.stop()

# --- INTERFACE ---
st.sidebar.title(f"👤 {st.session_state.display_name}")
if st.sidebar.button("Sair"):
    st.session_state.clear()
    st.rerun()

# Listas para os selects
lista_cat = pd.read_sql_query("SELECT nome FROM categorias ORDER BY nome", conn)['nome'].tolist()
lista_ben = pd.read_sql_query("SELECT nome FROM beneficiarios ORDER BY nome", conn)['nome'].tolist()
lista_fon = pd.read_sql_query("SELECT nome FROM fontes ORDER BY nome", conn)['nome'].tolist()

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "➕ Lançar", "📊 Ver Dados", "⚙️ Gestão Familiar", "💰 Saldos e Ajustes", "👤 Gestão de Usuários"
])

with tab1:
    st.subheader("Novo Lançamento")
    with st.form("f_lanca", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        valor = c1.number_input("Valor", min_value=0.0, step=0.01, key="v_lanca")
        moeda = c2.selectbox("Moeda", ["EUR", "BRL"])
        fonte = c3.selectbox("Fonte", lista_fon if lista_fon else ["Padrão"])
        cat = st.selectbox("Categoria", lista_cat if lista_cat else ["Geral"])
        ben = st.selectbox("Beneficiário", lista_ben if lista_ben else ["Família"])
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        nota = st.text_input("Nota/Observação", key="n_lanca")
        
        if st.form_submit_button("Salvar Registro"):
            if valor > 0: # PROTEÇÃO CONTRA VALOR ZERO
                v_eur = valor * 0.16 if moeda == "BRL" else valor
                c.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, nota, usuario) VALUES (?,?,?,?,?,?,?,?)",
                          (datetime.now().strftime("%d/%m/%Y"), cat, ben, fonte, v_eur, tipo, nota, st.session_state.display_name))
                conn.commit()
                st.toast(f"✅ Lançamento de €{v_eur:,.2f} guardado!", icon='💰')
                st.rerun()
            else:
                st.error("O valor deve ser superior a zero para evitar registos vazios.")

with tab2:
    st.subheader("📑 Histórico Geral")
    # Tabela limpa, sem poluição de valores zero se a trava do Tab 1 for respeitada
    df_hist = pd.read_sql_query("SELECT id, data, categoria, beneficiario, fonte, valor_eur, tipo, nota, usuario FROM transacoes ORDER BY id DESC", conn)
    st.dataframe(df_hist, use_container_width=True, hide_index=True)

with tab3:
    st.header("⚙️ Gestão de Listas")
    col_a, col_b, col_c = st.columns(3)
    
    def ui_gestao(titulo, tabela, lista, key_prefix):
        st.subheader(titulo)
        novo = st.text_input(f"Novo {titulo}", key=f"add_{key_prefix}")
        if st.button(f"Adicionar {titulo}", key=f"btn_{key_prefix}"):
            if novo:
                c.execute(f"INSERT OR IGNORE INTO {tabela} (nome) VALUES (?)", (novo,))
                conn.commit()
                st.toast(f"✅ {novo} adicionado!", icon='✨')
                st.rerun()
        
        item_sel = st.selectbox(f"Editar/Remover {titulo}", [""] + lista, key=f"sel_{key_prefix}")
        if item_sel:
            novo_nome = st.text_input(f"Renomear {item_sel}", key=f"ren_{key_prefix}")
            b1, b2 = st.columns(2)
            if b1.button("Confirmar", key=f"ok_{key_prefix}"):
                c.execute(f"UPDATE {tabela} SET nome=? WHERE nome=?", (novo_nome, item_sel))
                conn.commit()
                st.toast("✅ Nome atualizado!")
                st.rerun()
            if b2.button("Eliminar", key=f"del_{key_prefix}"):
                c.execute(f"DELETE FROM {tabela} WHERE nome=?", (item_sel,))
                conn.commit()
                st.toast("🗑️ Item removido.")
                st.rerun()
        st.write(f"**{titulo}s Atuais:**")
        st.dataframe(pd.DataFrame(lista, columns=["Nome"]), hide_index=True, use_container_width=True)

    with col_a: ui_gestao("Categoria", "categorias", lista_cat, "cat")
    with col_b: ui_gestao("Beneficiário", "beneficiarios", lista_ben, "ben")
    with col_c: ui_gestao("Fonte", "fontes", lista_fon, "fon")

with tab4:
    st.header("💰 Saldos e Ajustes")
    # LIMPEZA E CONFIRMAÇÃO PARA SALDOS
    col_f, col_v = st.columns([2, 1])
    f_alvo = col_f.selectbox("Selecione a Conta", lista_fon, key="f_aj_saldo")
    v_ajuste = col_v.number_input("Novo Saldo Inicial (€)", min_value=0.0, step=0.01, key="v_aj_saldo")
    
    if st.button("Gravar Ajuste de Saldo"):
        if f_alvo:
            c.execute("INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)", (f_alvo, v_ajuste))
            conn.commit()
            st.toast(f"✅ Saldo inicial de {f_alvo} ajustado para €{v_ajuste:,.2f}!", icon='📈')
            st.rerun() # Limpa o campo automaticamente ao recarregar
        else:
            st.warning("Crie uma Fonte primeiro na aba Gestão Familiar.")

    st.divider()
    st.subheader("📊 Património por Conta")
    df_t = pd.read_sql_query("SELECT fonte, valor_eur, tipo FROM transacoes", conn)
    df_s = pd.read_sql_query("SELECT * FROM saldos_iniciais", conn)
    
    if lista_fon:
        m_cols = st.columns(len(lista_fon))
        for i, f in enumerate(lista_fon):
            ini = df_s[df_s['fonte'] == f]['valor_inicial'].sum()
            rec = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Receita')]['valor_eur'].sum()
            des = df_t[(df_t['fonte'] == f) & (df_t['tipo'] == 'Despesa')]['valor_eur'].sum()
            m_cols[i].metric(f, f"€ {ini+rec-des:,.2f}", f"Inicial: € {ini:,.2f}")

with tab5:
    st.header("👤 Gestão de Utilizadores")
    # TABELA DE UTILIZADORES
    u_df = pd.read_sql_query("SELECT nome_exibicao, username, email FROM usuarios", conn)
    st.table(u_df)
    
    with st.expander("➕ Registar Novo Membro"):
        n_nome = st.text_input("Nome Completo", key="reg_nome")
        n_user = st.text_input("Login", key="reg_user")
        n_mail = st.text_input("Email", key="reg_mail")
        n_pass = st.text_input("Senha Inicial", type="password", key="reg_pass")
        if st.button("Criar Conta"):
            if n_user and n_pass:
                try:
                    c.execute("INSERT INTO usuarios (username, password, email, nome_exibicao, senha_trocada) VALUES (?,?,?,?,0)", 
                              (n_user, hash_password(n_pass), n_mail, n_nome))
                    conn.commit()
                    st.toast(f"👤 {n_nome} cadastrado com sucesso!")
                    st.rerun()
                except: st.error("Este nome de utilizador já existe.")

conn.close()
