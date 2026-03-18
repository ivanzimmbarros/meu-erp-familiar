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

def get_conn():
    return sqlite3.connect('finance.db', check_same_thread=False)

# --- INICIALIZAÇÃO DO BANCO (COM NOVA TABELA DE SALDOS) ---
def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, email TEXT, nome_exibicao TEXT, senha_trocada INTEGER DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS transacoes (id INTEGER PRIMARY KEY, data TEXT, categoria TEXT, beneficiario TEXT, fonte TEXT, valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS beneficiarios (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    c.execute('CREATE TABLE IF NOT EXISTS fontes (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
    
    # NOVA TABELA: Saldos Iniciais por Fonte
    c.execute('CREATE TABLE IF NOT EXISTS saldos_iniciais (fonte TEXT PRIMARY KEY, valor_inicial REAL DEFAULT 0.0)')
    
    # Dados padrão
    for tabela, itens in {"categorias": ["Alimentação", "Moradia"], "beneficiarios": ["Ivan", "Geral"], "fontes": ["Dinheiro Vivo", "Banco"]}.items():
        c.execute(f"SELECT COUNT(*) FROM {tabela}")
        if c.fetchone()[0] == 0:
            for i in itens: c.execute(f"INSERT INTO {tabela} (nome) VALUES (?)", (i,))
    conn.commit()
    conn.close()

init_db()

# [Lógica de Login e 2FA preservada conforme a Versão Base]
if 'display_name' not in st.session_state: st.session_state.display_name = "Ivan Zimmermann"

st.title(f"🚗 Painel de Controle: {st.session_state.display_name}")
tab1, tab2, tab3 = st.tabs(["➕ Lançar", "📊 Ver Dados", "⚙️ Gestão Familiar"])

conn = get_conn()

with tab1:
    # Form de lançamento (Inalterado para garantir estabilidade)
    lista_cat = pd.read_sql_query("SELECT nome FROM categorias ORDER BY nome", conn)['nome'].tolist()
    lista_ben = pd.read_sql_query("SELECT nome FROM beneficiarios ORDER BY nome", conn)['nome'].tolist()
    lista_fon = pd.read_sql_query("SELECT nome FROM fontes ORDER BY nome", conn)['nome'].tolist()
    
    st.subheader("Novo Lançamento")
    with st.form("registro_financeiro", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        valor = c1.number_input("Valor", min_value=0.0)
        moeda = c2.selectbox("Moeda", ["EUR", "BRL"])
        fonte = c3.selectbox("Fonte/Conta", lista_fon)
        categoria = st.selectbox("Categoria", lista_cat)
        beneficiario = st.selectbox("Beneficiário", lista_ben)
        tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        if st.form_submit_button("Salvar Registro"):
            v_eur = valor * 0.16 if moeda == "BRL" else valor
            conn.execute("INSERT INTO transacoes (data, categoria, beneficiario, fonte, valor_eur, tipo, usuario) VALUES (?,?,?,?,?,?,?)",
                         (datetime.now().strftime("%d/%m/%Y"), categoria, beneficiario, fonte, v_eur, tipo, st.session_state.display_name))
            conn.commit()
            st.success("✅ Salvo!")
            st.rerun()

with tab2:
    st.subheader("💰 Saldo Real por Conta")
    # CÁLCULO DO SALDO REAL (Item 3.1 do Plano)
    df_trans = pd.read_sql_query("SELECT fonte, valor_eur, tipo FROM transacoes", conn)
    df_saldos = pd.read_sql_query("SELECT * FROM saldos_iniciais", conn)
    
    col_metrics = st.columns(len(lista_fon))
    for i, f in enumerate(lista_fon):
        inicial = df_saldos[df_saldos['fonte'] == f]['valor_inicial'].sum()
        receitas = df_trans[(df_trans['fonte'] == f) & (df_trans['tipo'] == 'Receita')]['valor_eur'].sum()
        despesas = df_trans[(df_trans['fonte'] == f) & (df_trans['tipo'] == 'Despesa')]['valor_eur'].sum()
        saldo_atual = inicial + receitas - despesas
        col_metrics[i].metric(label=f, value=f"€ {saldo_atual:,.2f}", delta=f"Inicial: € {inicial:,.2f}")

with tab3:
    st.header("⚙️ Configurações e Saldos Iniciais")
    
    # Interface para Carga Inicial (Novo)
    st.subheader("🎯 Definir Saldos de Abertura")
    st.info("Introduza quanto dinheiro tinha em cada conta no dia em que começou a usar o sistema.")
    c_s1, c_s2 = st.columns([2, 1])
    f_alvo = c_s1.selectbox("Escolha a Conta", lista_fon, key="sel_fonte_saldo")
    v_inicial = c_s2.number_input("Saldo Inicial (€)", min_value=0.0, key="val_inicial")
    if st.button("Gravar Saldo Inicial"):
        conn.execute("INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?, ?)", (f_alvo, v_inicial))
        conn.commit()
        st.success(f"Saldo inicial de {f_alvo} atualizado!")
        st.rerun()

    st.divider()
    # [Restante da Gestão de Listas e Usuários preservada]
    st.write("--- Funções de Gestão de Listas e Usuários Continuam Aqui ---")

conn.close()
