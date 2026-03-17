import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

# --- CONFIGURAÇÃO DO BANCO DE DADOS ---
def init_db():
    conn = sqlite3.connect('finance.db')
    c = conn.cursor()
    # Tabela de transações com suporte a recibos (texto)
    c.execute('''CREATE TABLE IF NOT EXISTS transacoes 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT, categoria TEXT, 
                  beneficiario TEXT, valor REAL, tipo TEXT, nota TEXT, status TEXT)''')
    # Tabela de saldos iniciais
    c.execute('''CREATE TABLE IF NOT EXISTS contas 
                 (nome TEXT PRIMARY KEY, saldo REAL)''')
    conn.commit()
    conn.close()

init_db()

# --- INTERFACE (UX) ---
st.set_page_config(page_title="ERP Doméstico", page_icon="💰", layout="centered")
st.title("🏠 ERP Doméstico Familiar")

conn = sqlite3.connect('finance.db')

# --- DASHBOARD ---
df = pd.read_sql_query("SELECT * FROM transacoes", conn)

col1, col2 = st.columns(2)
total_gastos = df['valor'].sum() if not df.empty else 0
with col1:
    st.metric("Saldo Real (Total)", f"€ {total_gastos:,.2f}")
with col2:
    st.metric("Patrimônio Líquido", "€ 0,00") # Evoluir conforme o módulo de ativos

# --- ENTRADA DE DADOS ---
with st.expander("➕ Novo Lançamento"):
    with st.form("lancamento_form", clear_on_submit=True):
        data = st.date_input("Data", datetime.now())
        valor = st.number_input("Valor (€)", min_value=0.0, step=0.01)
        beneficiario = st.selectbox("Beneficiário", ["Pai", "Mãe", "Filho", "Cão", "Carro", "Família"])
        categoria = st.selectbox("Categoria", ["Alimentação", "Moradia", "Transporte", "Lazer", "Saúde"])
        tipo = st.radio("Tipo", ["Despesa", "Receita"])
        nota = st.text_input("Nota / Descrição")
        
        submitted = st.form_submit_button("Salvar Transação")
        if submitted:
            c = conn.cursor()
            c.execute("INSERT INTO transacoes (data, categoria, beneficiario, valor, tipo, nota, status) VALUES (?,?,?,?,?,?,?)", 
                      (data, categoria, beneficiario, valor, tipo, nota, "Confirmado"))
            conn.commit()
            st.success("Salvo com sucesso!")
            st.rerun()

# --- RELATÓRIOS SIMPLES ---
st.subheader("📋 Extrato Recente")
if not df.empty:
    st.dataframe(df.tail(10))
else:
    st.write("Nenhum lançamento encontrado.")

# --- MÓDULO DE AJUSTE (NOVO) ---
with st.expander("⚙️ Ajuste de Saldo"):
    st.write("Use isto apenas se o saldo do sistema estiver diferente do saldo real.")
    novo_saldo = st.number_input("Saldo Real Atual (€)", min_value=0.0)
    if st.button("Confirmar Ajuste"):
        # Log de auditoria simples
        c = conn.cursor()
        c.execute("INSERT INTO transacoes (data, categoria, beneficiario, valor, tipo, nota, status) VALUES (?,?,?,?,?,?,?)", 
                  (datetime.now(), "Ajuste de Auditoria", "Sistema", (novo_saldo - total_gastos), "Ajuste", "Ajuste Manual de Saldo", "Auditado"))
        conn.commit()
        st.success("Saldo ajustado com sucesso!")
        st.rerun()

conn.close()
