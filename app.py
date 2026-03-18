import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import smtplib
import random
from email.mime.text import MIMEText
from datetime import datetime

# --- CONFIGURAÇÃO E SEGREDOS ---
st.set_page_config(page_title="ERP Familiar Pro - V1.1", layout="wide")

# Garantia de estados de sessão
if 'ver' not in st.session_state: st.session_state.ver = 0
if 'logado' not in st.session_state: st.session_state.logado = False
if 'auth_step' not in st.session_state: st.session_state.auth_step = "login" # login, 2fa, reset

def limpar_campos():
    st.session_state.ver += 1

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_conn():
    return sqlite3.connect('finance.db', check_same_thread=False)

# --- FUNÇÃO DE E-MAIL (COM TRATAMENTO DE ERRO) ---
def enviar_email(destino, assunto, mensagem):
    try:
        # Tenta usar segredos do Streamlit. Se não existirem, loga no console para não travar o app
        smtp_user = st.secrets.get("email", {}).get("smtp_user")
        smtp_pass = st.secrets.get("email", {}).get("smtp_pass")
        
        if not smtp_user or not smtp_pass:
            st.warning(f"⚠️ SMTP não configurado. Código para {destino}: {mensagem}")
            return True # Simula sucesso para desenvolvimento

        msg = MIMEText(mensagem)
        msg['Subject'] = assunto
        msg['From'] = smtp_user
        msg['To'] = destino
        
        with smtplib.SMTP(st.secrets["email"]["smtp_server"], st.secrets["email"]["smtp_port"]) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, destino, msg.as_string())
        return True
    except Exception as e:
        st.error(f"Erro no servidor de e-mail: {e}")
        return False

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
    
    # Garante Admin sem apagar outros
    senha_adm = hash_password("123456")
    c.execute("INSERT OR IGNORE INTO usuarios (username, password, email, nome_exibicao, senha_trocada) VALUES (?,?,?,?,?)",
              ("admin", senha_adm, "admin@teste.com", "Administrador", 1))
    conn.commit()
    conn.close()

init_db()
conn = get_conn()
c = conn.cursor()

# --- MÓDULO DE AUTENTICAÇÃO (CONTINGÊNCIA) ---
if not st.session_state.logado:
    st.title("🔐 Segurança ERP Familiar")
    
    # ETAPA 1: LOGIN
    if st.session_state.auth_step == "login":
        u_in = st.text_input("Usuário")
        p_in = st.text_input("Senha", type="password")
        col1, col2 = st.columns(2)
        if col1.button("Entrar"):
            c.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u_in, hash_password(p_in)))
            user = c.fetchone()
            if user:
                st.session_state.temp_user = user
                # Gera código 2FA
                st.session_state.codigo_gerado = str(random.randint(100000, 999999))
                enviar_email(user[3], "Seu Código de Acesso", f"Código: {st.session_state.codigo_gerado}")
                st.session_state.auth_step = "2fa"
                st.rerun()
            else:
                st.error("Credenciais inválidas.")
        if col2.button("Esqueci a Senha"):
            st.session_state.auth_step = "reset"
            st.rerun()

    # ETAPA 2: 2FA
    elif st.session_state.auth_step == "2fa":
        st.info(f"Enviamos um código para o e-mail cadastrado de {st.session_state.temp_user[4]}.")
        cod_in = st.text_input("Digite o código de 6 dígitos")
        bypass = st.secrets.get("seguranca", {}).get("chave_mestra", "999888") # Chave de emergência
        
        col1, col2 = st.columns(2)
        if col1.button("Verificar"):
            if cod_in == st.session_state.codigo_gerado or cod_in == bypass:
                user = st.session_state.temp_user
                st.session_state.logado = True
                st.session_state.display_name = user[4]
                st.session_state.is_admin = (user[1] == 'admin')
                st.success("Acesso autorizado!")
                st.rerun()
            else:
                st.error("Código incorreto.")
        if col2.button("Voltar"):
            st.session_state.auth_step = "login"
            st.rerun()

    # ETAPA 3: RESET DE SENHA
    elif st.session_state.auth_step == "reset":
        st.subheader("Recuperação de Acesso")
        email_reset = st.text_input("Confirme o seu e-mail cadastrado")
        if st.button("Solicitar Nova Senha"):
            c.execute("SELECT * FROM usuarios WHERE email=?", (email_reset,))
            user = c.fetchone()
            if user:
                nova_provisoria = "".join(random.choices("ABCDEF123456", k=8))
                if enviar_email(email_reset, "Recuperação de Senha", f"Sua senha temporária é: {nova_provisoria}"):
                    c.execute("UPDATE usuarios SET password=?, senha_trocada=0 WHERE email=?", 
                              (hash_password(nova_provisoria), email_reset))
                    conn.commit()
                    st.success("Senha temporária enviada! Verifique o seu e-mail.")
                    st.session_state.auth_step = "login"
            else:
                st.error("E-mail não encontrado.")
        if st.button("Cancelar"):
            st.session_state.auth_step = "login"
            st.rerun()
    st.stop()

# --- CÓDIGO DO SISTEMA (ABAS) ---
# (As listas são carregadas aqui para garantir que o banco já foi validado)
lista_cat = pd.read_sql_query("SELECT nome FROM categorias ORDER BY nome", conn)['nome'].tolist()
lista_ben = pd.read_sql_query("SELECT nome FROM beneficiarios ORDER BY nome", conn)['nome'].tolist()
lista_fon = pd.read_sql_query("SELECT nome FROM fontes ORDER BY nome", conn)['nome'].tolist()

tab1, tab2, tab3, tab4, tab5 = st.tabs(["➕ Lançar", "📊 Lançamentos", "💰 Saldos", "🏷️ Gestão", "👤 Usuários"])

v = st.session_state.ver

# ABA 1: LANÇAMENTOS (Funcionalidade Íntegra)
with tab1:
    with st.form(key=f"f_lanca_{v}", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        valor = c1.number_input("Valor", min_value=0.0, step=0.01)
        moeda = c2.selectbox("Moeda", ["EUR", "BRL"])
        fonte = c3.selectbox("Fonte", lista_fon if lista_fon else ["Padrão"])
        cat = st.selectbox("Categoria", lista_cat if lista_cat else ["Geral"])
        ben = st.selectbox("Beneficiário", lista_ben if lista_ben else ["Geral"])
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        nota = st.text_input("Nota")
        if st.form_submit_button("Salvar"):
            v_eur = valor * 0.
