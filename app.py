import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import smtplib
import random
import plotly.express as px
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

# --- INICIALIZAÇÃO ---
conn = get_conn()
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS usuarios 
             (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, 
              email TEXT, nome_exibicao TEXT, senha_trocada INTEGER DEFAULT 0)''')
c.execute('''CREATE TABLE IF NOT EXISTS transacoes 
             (id INTEGER PRIMARY KEY, data TEXT, categoria TEXT, beneficiario TEXT, 
              valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT)''')
conn.commit()

# --- SESSÃO E LOGIN (2FA E TROCA DE SENHA) ---
if 'logado' not in st.session_state: st.session_state.logado = False
if 'auth_2fa' not in st.session_state: st.session_state.auth_2fa = False

if not st.session_state.logado:
    st.title("🔐 Acesso: ERP Familiar")
    u_in = st.text_input("Usuário")
    p_in = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        c.execute("SELECT * FROM usuarios WHERE username=? AND password=?", (u_in, hash_password(p_in)))
        user = c.fetchone()
        if user:
            st.session_state.tmp_user = user
            codigo = str(random.randint(100000, 999999))
            st.session_state.verif_code = codigo
            if enviar_email_2fa(user[3], codigo):
                st.session_state.logado = True
                st.rerun()
            else: st.error("Erro ao enviar e-mail. Verifique os Secrets.")
    st.stop()

if not st.session_state.auth_2fa:
    st.title("🛡️ Verificação 2FA")
    c_in = st.text_input("Código de 6 dígitos enviado por e-mail")
    if st.button("Confirmar"):
        if c_in == st.session_state.verif_code:
            st.session_state.auth_2fa = True
            st.session_state.user_id = st.session_state.tmp_user[0]
            st.session_state.display_name = st.session_state.tmp_user[4]
            st.session_state.precisa_trocar = (st.session_state.tmp_user[5] == 0)
            st.rerun()
        else: st.error("Código inválido.")
    st.stop()

if st.session_state.precisa_trocar:
    st.title("🔑 Troca de Senha Obrigatória")
    nova_s = st.text_input("Nova Senha", type="password")
    if st.button("Salvar Nova Senha"):
        if len(nova_s) >= 6:
            c.execute("UPDATE usuarios SET password=?, senha_trocada=1 WHERE id=?", (hash_password(nova_s), st.session_state.user_id))
            conn.commit()
            st.session_state.precisa_trocar = False
            st.rerun()
        else: st.error("Mínimo 6 caracteres.")
    st.stop()

# --- PAINEL PRINCIPAL ---
st.sidebar.title(f"👤 {st.session_state.display_name}")
if st.sidebar.button("Sair"):
    st.session_state.clear()
    st.rerun()

df = pd.read_sql_query("SELECT * FROM transacoes", conn)

st.title(f"🚗 Painel: {st.session_state.display_name}")
tab1, tab2, tab3 = st.tabs(["➕ Lançar", "📊 Ver Dados", "⚙️ Gestão Familiar"])

with tab1:
    st.subheader("Novo Lançamento")
    with st.form("form_financeiro", clear_on_submit=True):
        col1, col2 = st.columns(2)
        valor = col1.number_input("Valor", min_value=0.0)
        moeda = col2.selectbox("Moeda", ["EUR", "BRL"])
        # Conversão simples (fixa para teste, pode ser via API depois)
        v_eur = valor * 0.16 if moeda == "BRL" else valor
        
        cat = st.selectbox("Categoria", ["Alimentação", "Moradia", "Transporte", "Saúde", "Lazer", "Outros"])
        ben = st.selectbox("Beneficiário", ["Ivan", "Larissa", "Geral"])
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        nota = st.text_input("Nota/Descrição")
        
        if st.form_submit_button("Salvar Registro"):
            c.execute("INSERT INTO transacoes (data, categoria, beneficiario, valor_eur, tipo, nota, usuario) VALUES (?,?,?,?,?,?,?)",
                      (datetime.now().strftime("%d/%m/%Y"), cat, ben, v_eur, tipo, nota, st.session_state.display_name))
            conn.commit()
            st.success("Lançamento salvo com sucesso!")
            st.rerun()

with tab2:
    st.subheader("Histórico e Análises")
    if not df.empty:
        col_m1, col_m2 = st.columns(2)
        fig_pizza = px.pie(df[df['tipo'] == 'Despesa'], values='valor_eur', names='categoria', title="Gastos por Categoria")
        col_m1.plotly_chart(fig_pizza, use_container_width=True)
        
        fig_bar = px.bar(df, x='data', y='valor_eur', color='tipo', title="Fluxo de Caixa")
        col_m2.plotly_chart(fig_bar, use_container_width=True)
        
        st.dataframe(df.sort_index(ascending=False), use_container_width=True)
    else:
        st.info("Nenhum dado cadastrado ainda.")

with tab3:
    st.subheader("Membros Cadastrados")
    u_df = pd.read_sql_query("SELECT nome_exibicao, username, CASE WHEN senha_trocada=1 THEN '✅ Alterada' ELSE '⚠️ Inicial' END as Status FROM usuarios", conn)
    st.table(u_df)
    
    st.divider()
    st.subheader("Cadastrar Novo Membro")
    with st.form("novo_u"):
        n = st.text_input("Nome")
        u = st.text_input("Login")
        e = st.text_input("E-mail")
        s = st.text_input("Senha Inicial", type="password")
        if st.form_submit_button("Criar"):
            try:
                c.execute("INSERT INTO usuarios (username, password, email, nome_exibicao, senha_trocada) VALUES (?,?,?,?,0)", (u, hash_password(s), e, n))
                conn.commit()
                st.success("Criado!")
                st.rerun()
            except: st.error("Usuário já existe.")

conn.close()
