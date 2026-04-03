import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import hashlib
import io
import logging
import smtplib, random, hashlib
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from email.mime.text import MIMEText

# --- 1. CONFIGURAÇÃO GLOBAL E CSS MOBILE-FIRST ---
st.set_page_config(page_title="ERP Familiar", page_icon="🏠", layout="wide")

import streamlit as st

st.markdown("""
<style>
    /* 1. FUNDO GERAL E CONTAINER (Journal Paper Style) */
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
        background-color: #D5D5D5 !important;
        color: #2F2F2F !important;
    }

    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 1rem !important;
        padding-left: 3rem !important;
        padding-right: 3rem !important;
    }

    /* 2. SIDEBAR (Overcast Style) */
    [data-testid="stSidebar"] {
        background-color: #9099A2 !important;
        border-right: 1px solid rgba(0,0,0,0.1);
    }
    
    [data-testid="stSidebar"] .stMarkdown, [data-testid="stSidebar"] p, [data-testid="stSidebar"] span {
        color: #FFFFFF !important;
    }

    /* 3. ABAS (TABS) CUSTOMIZADAS */
    .stTabs [data-baseweb="tab-list"] {
        background-color: #9099A2;
        padding: 8px 8px 0px 8px;
        border-radius: 10px 10px 0 0;
        gap: 5px;
    }

    .stTabs [data-baseweb="tab"] {
        height: 45px;
        background-color: transparent;
        color: #F0F0F0 !important;
        font-weight: 500;
        border: none !important;
    }

    .stTabs [aria-selected="true"] {
        background-color: #6D7993 !important; /* Lavendar */
        color: #FFFFFF !important;
        border-radius: 5px 5px 0 0 !important;
    }

    /* 4. MÉTRICAS AVANÇADAS */
    [data-testid="stMetric"] {
        background-color: #FFFFFF;
        padding: 15px;
        border-radius: 4px;
        border-left: 4px solid #6D7993;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }

    [data-testid="stMetricLabel"] p {
        color: #9099A2 !important;
        font-size: 0.85rem !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    /* 5. BOTÕES (Dusty Style) */
    .stButton>button {
        background-color: #96858F !important;
        color: #FFFFFF !important;
        border-radius: 4px !important;
        border: none !important;
        font-weight: 600 !important;
        text-transform: uppercase;
        letter-spacing: 1px;
        transition: 0.3s ease;
    }

    .stButton>button:hover {
        background-color: #6D7993 !important;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }

    /* 6. INPUTS, SELECTS E DATA EDITORS */
    div[data-baseweb="input"], div[data-baseweb="select"], .stNumberInput input {
        background-color: #FFFFFF !important;
        color: #2F2F2F !important;
        border: 1px solid #9099A2 !important;
    }

    /* 7. CARDS E LISTAGENS */
    .card, .liquidar-row {
        background-color: #FFFFFF !important;
        border-left: 6px solid #6D7993 !important;
        border-radius: 4px;
        padding: 15px;
        margin-bottom: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }

    /* Scrollbar Journal Style */
    ::-webkit-scrollbar { width: 8px; }
    ::-webkit-scrollbar-track { background: #D5D5D5; }
    ::-webkit-scrollbar-thumb { background: #9099A2; border-radius: 10px; }

    header {visibility: hidden;}

    /* 8. PADRONIZAÇÃO ABSOLUTA DE FONTES (BASEADO NA GESTÃO GERAL) */
    /* Substitui a tipografia Serifada pela Sans-Serif moderna em todos os cabeçalhos */
    h1, h2, h3, h4, h5, h6, [data-testid="stHeaderElement"], .stMarkdown h4 {
        font-family: 'Inter', 'Source Sans Pro', 'Helvetica Neue', Helvetica, Arial, sans-serif !important;
        color: #2F2F2F !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em !important;
    }
    
    /* Ajuste de escala para manter st.subheader e Markdown proporcionais */
    h1 { font-size: 1.8rem !important; }
    h2 { font-size: 1.6rem !important; }
    h3 { font-size: 1.4rem !important; } /* st.subheader */
    h4 { font-size: 1.25rem !important; } /* Seções de Markdown #### */

    /* Remove qualquer resquício de cor ou fonte anterior de marcações Markdown h2 */
    .stMarkdown h2 {
        color: #2F2F2F !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 700 !important;
    }
</style>
""", unsafe_allow_html=True)

# --- 2. MOTOR DE BANCO DE DADOS E ESTADO DA SESSÃO ---
DB_PATH = 'finance.db'

def db_execute(sql, params=()):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON"); conn.execute(sql, params); conn.commit()

def db_query(sql, params=()):
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(sql, params).fetchall()

def db_df(sql, params=()):
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(sql, conn, params=params)

def db_execute_many(ops):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for sql, params in ops: conn.execute(sql, params)
        conn.commit()

def init_db():
    tables = [
        "CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, nome_exibicao TEXT, email TEXT, perfil TEXT DEFAULT 'Utilizador')",
        "CREATE TABLE IF NOT EXISTS fontes (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)",
        "CREATE TABLE IF NOT EXISTS saldos_iniciais (fonte TEXT PRIMARY KEY, valor_inicial REAL DEFAULT 0.0)",
        "CREATE TABLE IF NOT EXISTS beneficiarios (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)",
        "CREATE TABLE IF NOT EXISTS configuracoes (chave TEXT PRIMARY KEY, valor TEXT)",
        "CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE, pai_id INTEGER, tipo_categoria TEXT, FOREIGN KEY(pai_id) REFERENCES categorias(id) ON DELETE RESTRICT)",
        "CREATE TABLE IF NOT EXISTS cartoes (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE, limite REAL, dia_fechamento INTEGER, dia_vencimento INTEGER, conta_pagamento TEXT)",
        "CREATE TABLE IF NOT EXISTS orcamentos (id INTEGER PRIMARY KEY AUTOINCREMENT, mes_ano TEXT, categoria_pai TEXT, categoria_filho TEXT DEFAULT 'Geral', valor_previsto REAL, tipo_meta TEXT, UNIQUE(mes_ano, categoria_pai, categoria_filho, tipo_meta))",
        "CREATE TABLE IF NOT EXISTS transacoes (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT, categoria_pai TEXT, categoria_filho TEXT, beneficiario TEXT, fonte TEXT, valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT, forma_pagamento TEXT DEFAULT 'Dinheiro/Débito', cartao_id INTEGER, fatura_ref TEXT, status_cartao TEXT DEFAULT 'pendente', status_liquidacao TEXT DEFAULT 'PAGO', data_liquidacao TEXT, parcela_id TEXT, parcela_numero INTEGER DEFAULT 1, total_parcelas INTEGER DEFAULT 1)"
    ]
    for sql in tables: db_execute(sql)
    for t, c, s in [("orcamentos", "categoria_filho", "TEXT DEFAULT 'Geral'"), ("usuarios", "email", "TEXT"), ("usuarios", "perfil", "TEXT DEFAULT 'Utilizador'")]:
        try: db_execute(f"ALTER TABLE {t} ADD COLUMN {c} {s}")
        except: pass
    s = st.secrets["initial_setup"]
    pwd_h = hashlib.sha256(s["admin_password"].encode()).hexdigest()
    db_execute("INSERT OR IGNORE INTO usuarios (username, password, nome_exibicao, email, perfil) VALUES (?,?,?,?,'Administrador')", (s["admin_user"], pwd_h, "Administrador Mestre", s["admin_email"]))
    db_execute("INSERT OR IGNORE INTO configuracoes (chave, valor) VALUES ('taxa_brl_eur', '0.16')")

def enviar_email(assunto, conteudo, destino):
    msg = MIMEText(conteudo)
    msg['Subject'] = assunto
    msg['From'] = st.secrets["smtp"]["user"]
    msg['To'] = destino
    try:
        with smtplib.SMTP(st.secrets["smtp"]["server"], st.secrets["smtp"]["port"]) as server:
            server.starttls()
            server.login(st.secrets["smtp"]["user"], st.secrets["smtp"]["password"])
            server.sendmail(st.secrets["smtp"]["user"], destino, msg.as_string())
        return True
    except Exception as e:
        st.error(f"⚠️ Erro SMTP: {e}"); return False

if 'ver' not in st.session_state:
    try:
        taxa_db = db_query("SELECT valor FROM configuracoes WHERE chave='taxa_brl_eur'")
        t_init = float(taxa_db[0][0]) if taxa_db else 0.16
    except: t_init = 0.16
    st.session_state.update({
        'ver': 0, 'logado': False, 'user': None, 'display_name': None, 
        'perfil': None, # Novo campo obrigatório
        'taxa': t_init
    })    

# --- 3. CORE FINANCEIRO E REGRAS DE NEGÓCIO ---
def determinar_status_operacao(tipo, eh_primeira_parcela=True):
    if not eh_primeira_parcela: return "PENDENTE"
    return "RECEBIDO" if tipo == "Receita" else "PAGO"

def calcular_parcelas(data_str, dia_fech, dia_venc, valor_total, total_parc, is_cartao=False):
    parcelas = []
    d = datetime.strptime(data_str, "%Y-%m-%d")
    v_parc = round(valor_total / total_parc, 2)
    v_ult = round(valor_total - (v_parc * (total_parc - 1)), 2)
    offset = 1 if (is_cartao and d.day > dia_fech) else 0
    for i in range(total_parc):
        num = i + 1
        data_v = d + relativedelta(months=offset + i, day=dia_venc if is_cartao else d.day)
        val = v_ult if num == total_parc else v_parc
        parcelas.append((data_v.strftime("%Y-%m-%d"), val, num))
    return parcelas

def calcular_fatura_ref(data_str, dia_fech):
    d = datetime.strptime(data_str, "%Y-%m-%d")
    if d.day > dia_fech: d += relativedelta(months=1)
    return d.strftime("%Y-%m")

def calcular_saldo_real(fonte):
    """Calcula o dinheiro que REALMENTE existe na conta agora."""
    res_ini = db_query("SELECT valor_inicial FROM saldos_iniciais WHERE fonte=?", (fonte,))
    ini = res_ini[0][0] if res_ini else 0.0
    # Soma apenas o que entrou (RECEBIDO) e saiu (PAGO) via Dinheiro/Débito nesta conta
    rec = db_query("SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo='Receita' AND status_liquidacao='RECEBIDO' AND forma_pagamento != 'Cartão de Crédito'", (fonte,))[0][0] or 0.0
    des = db_query("SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo='Despesa' AND status_liquidacao='PAGO' AND forma_pagamento != 'Cartão de Crédito'", (fonte,))[0][0] or 0.0
    return round(ini + rec - des, 2)

def calcular_comprometido(fonte):
    """Calcula tudo que vai sair da conta no futuro (Boletos Pendentes + Faturas)."""
    # 1. Boletos e Receitas agendadas diretamente nesta conta (excluindo cartão)
    sql_pend = "SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo=? AND status_liquidacao IN ('PENDENTE','PREVISTO') AND forma_pagamento != 'Cartão de Crédito'"
    desp_p = db_query(sql_pend, (fonte, "Despesa"))[0][0] or 0.0
    rec_p = db_query(sql_pend, (fonte, "Receita"))[0][0] or 0.0
    
    # 2. Total de faturas de todos os cartões que debitam nesta conta
    fat = db_query("""
        SELECT SUM(t.valor_eur) 
        FROM transacoes t 
        JOIN cartoes c ON t.cartao_id = c.id 
        WHERE c.conta_pagamento=? AND t.status_cartao='pendente'
    """, (fonte,))[0][0] or 0.0
    
    return round(desp_p - rec_p + fat, 2)

def realizar_transferencia(origem, destino, valor, data_str, usuario, nota):
    nota_f = f"Transferência: {origem} ➔ {destino} | {nota}"
    ops = [
        ("INSERT INTO transacoes (data, categoria_pai, beneficiario, fonte, valor_eur, tipo, nota, usuario, status_liquidacao) VALUES (?,?,?,?,?,?,?,?,?)",
         (data_str, "Transferência", f"Para {destino}", origem, valor, "Despesa", nota_f, usuario, "PAGO")),
        ("INSERT INTO transacoes (data, categoria_pai, beneficiario, fonte, valor_eur, tipo, nota, usuario, status_liquidacao) VALUES (?,?,?,?,?,?,?,?,?)",
         (data_str, "Transferência", f"De {origem}", destino, valor, "Receita", nota_f, usuario, "RECEBIDO"))
    ]
    db_execute_many(ops)

def verificar_bloqueio_delecao(tabela, id_item):
    if tabela == "categorias":
        res = db_query("SELECT nome FROM categorias WHERE id=?", (id_item,))
        if not res: return False
        n = res[0][0]
        return len(db_query("SELECT id FROM categorias WHERE pai_id=?", (id_item,))) > 0 or \
               len(db_query("SELECT id FROM transacoes WHERE categoria_pai=? OR categoria_filho=?", (n, n))) > 0
    if tabela == "fontes":
        res = db_query("SELECT nome FROM fontes WHERE id=?", (id_item,))
        if not res: return False
        n = res[0][0]
        return len(db_query("SELECT id FROM transacoes WHERE fonte=?", (n,))) > 0 or \
               len(db_query("SELECT fonte FROM saldos_iniciais WHERE fonte=?", (n,))) > 0
    if tabela == "beneficiarios":
        res = db_query("SELECT nome FROM beneficiarios WHERE id=?", (id_item,))
        if not res: return False
        return len(db_query("SELECT id FROM transacoes WHERE beneficiario=?", (res[0][0],))) > 0
    return False

# --- 4. NOVO MOTOR DE ACESSO (LOGIN / 2FA / RECUPERAÇÃO) ---
if 'auth_step' not in st.session_state: st.session_state.auth_step = 'login'

if not st.session_state.logado:
    _, col_auth, _ = st.columns([1, 1.5, 1])
    with col_auth:
        st.markdown("<br><h2 style='text-align: center;'>🔒 Portal de Acesso</h2>", unsafe_allow_html=True)
        if st.session_state.auth_step == 'login':
            u_in = st.text_input("Usuário", key="u_login")
            p_in = st.text_input("Senha", type="password", key="p_login")
            if st.button("Entrar", use_container_width=True, type="primary"):
                pwd_h = hashlib.sha256(p_in.encode()).hexdigest()
                res = db_query("SELECT email, perfil, nome_exibicao FROM usuarios WHERE username=? AND password=?", (u_in, pwd_h))
                if res:
                    u_email, u_perfil, u_nome = res[0]
                    otp = str(random.randint(100000, 999999))
                    if enviar_email("🔑 Código 2FA", f"Seu código é: {otp}", u_email):
                        st.session_state.update({'temp_user': u_in, 'temp_perfil': u_perfil, 'temp_display': u_nome, 'correct_otp': otp, 'auth_step': '2fa'})
                        st.rerun()
                else: st.error("Acesso negado.")
            if st.button("Esqueci a Senha"): st.session_state.auth_step = 'recovery'; st.rerun()
        elif st.session_state.auth_step == '2fa':
            otp_in = st.text_input("Código de 6 dígitos", max_chars=6)
            if st.button("Verificar e Entrar"):
                if otp_in == st.session_state.correct_otp:
                    st.session_state.update({'logado': True, 'user': st.session_state.temp_user, 'perfil': st.session_state.temp_perfil, 'display_name': st.session_state.temp_display})
                    st.rerun()
                else: st.error("Incorreto.")
        elif st.session_state.auth_step == 'recovery':
            email_rec = st.text_input("Email cadastrado")
            if st.button("Resetar"):
                user_check = db_query("SELECT id FROM usuarios WHERE email=?", (email_rec,))
                if user_check:
                    nova = str(random.randint(10000000, 99999999))
                    db_execute("UPDATE usuarios SET password=? WHERE email=?", (hashlib.sha256(nova.encode()).hexdigest(), email_rec))
                    enviar_email("Nova Senha", f"Senha temporária: {nova}", email_rec)
                    st.success("Enviado!"); st.session_state.auth_step = 'login'; st.rerun()
st.stop() # Bloqueia o app até o login ser completado

# --- 5. INTERFACE LOGADA (FORA DO BLOCO DE LOGIN) ---
with st.sidebar:
    st.markdown(f"### 👋 {st.session_state.display_name}")
    st.caption(date.today().strftime('%d/%m/%Y'))
    st.divider()
    hoje_iso = date.today().strftime("%Y-%m-%d")
    pend = db_query("SELECT id FROM transacoes WHERE status_liquidacao='PENDENTE' AND data <= ?", (hoje_iso,))
    if pend: st.warning(f"⚠️ {len(pend)} conta(s) vencida(s)!")
    st.divider()
    st.caption(f"💱 Câmbio BRL/EUR: **{st.session_state.taxa:.4f}**")
    if st.button("🚪 Sair", use_container_width=True): st.session_state.clear(); st.rerun()

# --- 5. DEFINIÇÃO DE ABAS POR PERFIL (LOGICA DINÂMICA) ---
is_admin = (st.session_state.perfil == "Administrador")

if is_admin:
    titulos = ["➕ Novos Lançamentos", "📋 Histórico", "💰 Saldos", "💳 Cartões", "🎯 Metas", "📊 Dashboards", "🔄 Transferências", "⚙️ Gestão Geral"]
else:
    titulos = ["➕ Novos Lançamentos", "📋 Histórico", "💰 Saldos", "💳 Cartões", "🎯 Metas", "📊 Dashboards", "🔄 Transferências"]

# Criação das abas usando a variável correta 'titulos'
tabs = st.tabs(titulos)

# Agora, em vez de tab1, tab2, usaremos o índice tabs[0], tabs[1]...
# --- TAB 1: NOVO LANÇAMENTO ---

with tabs[0]:
    st.subheader("➕ Registro de Movimentação")
    
    # Grid de Escolha Inicial
    c_t1, c_t2 = st.columns(2)
    tipo_sel = c_t1.radio("Natureza", ["Despesa", "Receita"], horizontal=True, key="t_reg_final")
    forma_sel = c_t2.radio("Meio de Pagamento", ["Dinheiro/Débito", "Cartão de Crédito"], horizontal=True)
    
    # Filtro Reativo de Categorias (DNA da Nova Funcionalidade)
    pais = db_query("SELECT id, nome FROM categorias WHERE pai_id IS NULL AND tipo_categoria=?", (tipo_sel,))
    pai_sel = st.selectbox("Categoria Principal", [p[1] for p in pais], key=f"p_{tipo_sel}_final")
    
    id_p = next((p[0] for p in pais if p[1] == pai_sel), None)
    filhos = db_query("SELECT nome FROM categorias WHERE pai_id=?", (id_p,)) if id_p else []
    filho_sel = st.selectbox("Subcategoria / Detalhe", ["Geral"] + [f[0] for f in filhos])

    with st.form("f_novo_final", clear_on_submit=True):
        # Seleção de Fonte (Cartões vs Contas)
        f_data = db_query("SELECT nome FROM cartoes") if forma_sel == "Cartão de Crédito" else db_query("SELECT nome FROM fontes")
        fonte_sel = st.selectbox("Origem / Destino", [f[0] for f in f_data])
        
        col_v, col_p = st.columns(2)
        data_in = col_v.date_input("Data da Compra/Recebimento", date.today())
        valor_in = col_v.number_input("Valor Total (€)", min_value=0.01, format="%.2f")
        parc_in = col_p.number_input("Quantidade de Parcelas", 1, 48, 1)
        
        benef_list = [b[0] for b in db_query("SELECT nome FROM beneficiarios ORDER BY nome")]
        benef_sel = st.selectbox("Beneficiário", [""] + benef_list)
        nota_in = st.text_input("Observação Adicional")

        # --- BOTÃO DE SALVAMENTO COM VALIDAÇÃO DE CAMPOS ---
        if st.form_submit_button("💾 SALVAR REGISTRO"):
            if not pai_sel or not benef_sel or not nota_in:
                st.error("🚨 Todos os campos são obrigatórios.")
            elif valor_in <= 0:
                st.error("🚨 Valor deve ser maior que zero.")
            else:
            # 1. CHECKLIST DE OBRIGATORIEDADE
            campos_invalidos = []
            
            if not pai_sel or pai_sel == "Sem categorias": campos_invalidos.append("Categoria Principal")
            if not fonte_sel: campos_invalidos.append("Origem / Destino (Conta ou Cartão)")
            if not benef_sel or benef_sel == "": campos_invalidos.append("Beneficiário")
            if not nota_in or nota_in.strip() == "": campos_invalidos.append("Observação / Descrição")
            if valor_in <= 0: campos_invalidos.append("Valor (deve ser maior que zero)")

            # 2. BLOQUEIO DE SEGURANÇA
            if campos_invalidos:
                st.error(f"⚠️ **Erro de Preenchimento:** Os seguintes campos são obrigatórios: {', '.join(campos_invalidos)}.")
            else:
                # 3. PROCESSAMENTO SE TODOS OS CAMPOS ESTIVEREM OK
                try:
                    is_cc = (forma_sel == "Cartão de Crédito")
                    c_inf_res = db_query("SELECT id, dia_fechamento, dia_vencimento FROM cartoes WHERE nome=?", (fonte_sel,))
                    c_inf = c_inf_res[0] if c_inf_res else (None, 0, 0)
                    
                    parcs = calcular_parcelas(data_in.strftime("%Y-%m-%d"), c_inf[1], c_inf[2], valor_in, parc_in, is_cc)
                    
                    ops = []
                    for i, (p_d, p_v, p_n) in enumerate(parcs):
                        if is_cc:
                            st_liq = "PENDENTE"
                        else:
                            st_liq = determinar_status_operacao(tipo_sel, eh_primeira_parcela=(i==0))
                        
                        f_ref = calcular_fatura_ref(p_d, c_inf[1]) if is_cc else None
                        
                        ops.append(("INSERT INTO transacoes (data, categoria_pai, categoria_filho, beneficiario, fonte, valor_eur, tipo, nota, usuario, forma_pagamento, cartao_id, fatura_ref, status_liquidacao) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                    (p_d, pai_sel, filho_sel, benef_sel, fonte_sel, p_v, tipo_sel, f"{nota_in} ({p_n}/{parc_in})" if parc_in>1 else nota_in, st.session_state.user, forma_sel, c_inf[0], f_ref, st_liq)))
                    
                    db_execute_many(ops)
                    st.success(f"✅ Sucesso! {parc_in} lançamento(s) registrado(s) corretamente.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro Crítico ao Salvar: {e}")

# --- TAB 2: HISTÓRICO ---

with tabs[1]:
    st.subheader("📋 Auditoria de Lançamentos")

    # 1. Recuperação da Base de Dados (Híbrida)
    df_comuns = db_df("SELECT * FROM transacoes WHERE forma_pagamento != 'Cartão de Crédito'")
    df_faturas = db_df("""
        SELECT MIN(t.id) as id, t.fatura_ref || '-01' as data, 'Cartão de Crédito' as categoria_pai, 
               'Geral' as categoria_filho, 'Fatura' as beneficiario, c.nome as fonte, 
               SUM(t.valor_eur) as valor_eur, 'Despesa' as tipo, 
               'Fatura Consolidada: ' || c.nome || ' (Ref: ' || t.fatura_ref || ')' as nota, 
               MAX(t.status_liquidacao) as status_liquidacao, 'Cartão de Crédito' as forma_pagamento
        FROM transacoes t JOIN cartoes c ON t.cartao_id = c.id
        WHERE t.forma_pagamento = 'Cartão de Crédito' GROUP BY t.fatura_ref, c.nome
    """)
    df_raw = pd.concat([df_comuns, df_faturas], ignore_index=True)
    df_raw['fonte'] = df_raw['fonte'].fillna("Não Especificado").astype(str)

    # ---------------------------------------------------------
    # 2. MATRIZ DE FILTROS (REATIVIDADE DE CATEGORIAS)
    # ---------------------------------------------------------
    c_f1, c_f2, c_f3 = st.columns([1, 1, 2])
    f_tipo = c_f1.selectbox("Tipo de Lançamento", ["Todos", "Despesa", "Receita"], key="f_tipo_final")
    f_fonte = c_f2.selectbox("Conta/Cartão", ["Todas"] + sorted(df_raw['fonte'].unique().tolist()))
    f_busca = c_f3.text_input("🔍 Busca Livre", placeholder="Nota ou Beneficiário...", key="f_busca_final")

    c_f4, f_f5 = st.columns(2)
    # Lógica de Categorias Pai dependente do Tipo
    sql_pai = "SELECT id, nome FROM categorias WHERE pai_id IS NULL"
    if f_tipo != "Todos":
        sql_pai += f" AND tipo_categoria = '{f_tipo}'"
    
    pais_filt = db_query(sql_pai)
    lista_pais = ["Todas"] + [p[1] for p in pais_filt]
    f_pai = c_f4.selectbox("Filtrar Categoria Principal", lista_pais, key="f_pai_hist")

    # Lógica de Categorias Filho dependente da Pai selecionada
    if f_pai != "Todas":
        id_p_filt = [p[0] for p in pais_filt if p[1] == f_pai][0]
        filhos_filt = db_query("SELECT nome FROM categorias WHERE pai_id = ?", (id_p_filt,))
        lista_filhos = ["Todos"] + [f[0] for f in filhos_filt]
    else:
        lista_filhos = ["Todos"]
    f_filho = f_f5.selectbox("Filtrar Subcategoria", lista_filhos, key="f_filho_hist")

    # ---------------------------------------------------------
    # 3. APLICAÇÃO DOS FILTROS NO DATAFRAME
    # ---------------------------------------------------------
    if f_tipo != "Todos": df_raw = df_raw[df_raw['tipo'] == f_tipo]
    if f_fonte != "Todas": df_raw = df_raw[df_raw['fonte'] == f_fonte]
    if f_pai != "Todas": df_raw = df_raw[df_raw['categoria_pai'] == f_pai]
    if f_filho != "Todos": df_raw = df_raw[df_raw['categoria_filho'] == f_filho]
    if f_busca: 
        mask = df_raw.apply(lambda r: f_busca.lower() in str(r).lower(), axis=1)
        df_raw = df_raw[mask]

    # ---------------------------------------------------------
    # 4. RENDERIZAÇÃO DOS RESULTADOS (EXPANDERS)
    # ---------------------------------------------------------
    if not df_raw.empty:
        df_raw['dt'] = pd.to_datetime(df_raw['data'], errors='coerce')
        df_raw = df_raw.dropna(subset=['dt'])
        df_raw['mes_ref'] = df_raw['dt'].dt.strftime('%m/%Y - %B')
        meses_uniquos = df_raw.sort_values('dt', ascending=True)['mes_ref'].unique()

        st.markdown("---")
        for m in meses_uniquos:
            with st.expander(f"📅 {m}", expanded=(m == meses_uniquos[0])):
                itens = df_raw[df_raw['mes_ref'] == m]
                for _, r in itens.iterrows():
                    c_lin, c_btn = st.columns([5, 1])
                    with c_lin:
                        st_map = {"RECEBIDO": "badge-recebido", "PAGO": "badge-pago", "PENDENTE": "badge-pendente"}
                        badge = st_map.get(r['status_liquidacao'], "badge-pendente")
                        icon = "💳" if r['forma_pagamento'] == "Cartão de Crédito" else "🏦"
                        st.markdown(f'''
                            <div class="liquidar-row">
                                <div>
                                    <span class="{badge}">{r["status_liquidacao"]}</span> 
                                    <b>{r["dt"].strftime("%d/%m")}</b> | {icon} {r["fonte"]} | <b>€{r["valor_eur"]:,.2f}</b><br>
                                    <small>{r["categoria_pai"]} / {r["categoria_filho"]} ➔ {r["nota"]}</small>
                                </div>
                            </div>
                        ''', unsafe_allow_html=True)
                    with c_btn:
                        if r['status_liquidacao'] == 'PENDENTE' and r['forma_pagamento'] != 'Cartão de Crédito':
                            if st.button("✅", key=f"liq_h_f_{r['id']}"):
                                liquidar_transacao(r['id'], r['tipo'], st.session_state.user)
                                st.rerun()

        # 5. TABELA TÉCNICA DE REMOÇÃO E AUDITORIA (COM COLUNA STATUS)
        st.divider()
        st.markdown("#### 🛠️ Auditoria Técnica e Controle de Registros")
        st.caption("Esta visão mostra os dados originais do banco para exclusão precisa e conferência de status.")

        # Busca dados brutos para transparência total
        df_audit_raw = db_df("SELECT * FROM transacoes ORDER BY data DESC, id DESC")
        
        if not df_audit_raw.empty:
            # --- PROCESSAMENTO DE BI ---
            
            # Formatação da Nota Estruturada
            def formatar_nota_bi(row):
                nota_base = row['nota'] or ""
                if row['total_parcelas'] > 1:
                    nota_limpa = nota_base.split(" (")[0]
                    return f"📦 Parcela {row['parcela_numero']}/{row['total_parcelas']} | {nota_limpa}"
                return nota_base

            df_audit_raw['informacao_detalhada'] = df_audit_raw.apply(formatar_nota_bi, axis=1)

            # Seleção de Colunas Incluindo o STATUS
            df_audit_view = df_audit_raw.copy()
            df_audit_view.insert(0, "🗑️", False) 
            
            # Adicionado "status_liquidacao" na lista de exibição
            df_audit_final = df_audit_view[[
                "🗑️", "id", "data", "status_liquidacao", "tipo", "forma_pagamento", 
                "categoria_pai", "categoria_filho", "beneficiario", 
                "valor_eur", "informacao_detalhada"
            ]].rename(columns={
                "data": "Data",
                "status_liquidacao": "Status",
                "tipo": "Operação",
                "forma_pagamento": "Meio de Pagamento",
                "categoria_pai": "Categoria",
                "categoria_filho": "Subcategoria",
                "beneficiario": "Beneficiário",
                "valor_eur": "Valor (€)",
                "informacao_detalhada": "Estrutura de Notas / Parcelamento"
            })

            # Renderização da Tabela
            editor_audit = st.data_editor(
                df_audit_final, 
                hide_index=True, 
                use_container_width=True, 
                key=f"audit_final_v5"
            )
            
            # Ação de Exclusão
            if st.button("🗑️ EXCLUIR REGISTROS SELECIONADOS", type="secondary", key="btn_del_audit"):
                ids_para_excluir = df_audit_final.loc[editor_audit["🗑️"] == True, "id"].tolist()
                
                if ids_para_excluir:
                    ph = ",".join(["?"] * len(ids_para_excluir))
                    db_execute(f"DELETE FROM transacoes WHERE id IN ({ph})", tuple(ids_para_excluir))
                    st.success(f"✅ {len(ids_para_excluir)} registro(s) removido(s).")
                    st.rerun()
                    
# --- TAB 3: SALDOS ---
with tabs[2]:
    st.subheader("💰 Patrimônio e Liquidez")
    fnts = [f[0] for f in db_query("SELECT nome FROM fontes ORDER BY nome")]
    
    if not fnts:
        st.info("💡 Cadastre suas contas na aba Gestão.")
    else:
        t_real, t_livre = 0.0, 0.0
        cols = st.columns(len(fnts) if len(fnts) <= 3 else 3)
        
        for i, f in enumerate(fnts):
            sr = calcular_saldo_real(f)
            sc = calcular_comprometido(f)
            sl = round(sr - sc, 2)
            t_real += sr
            t_livre += sl
            
            with cols[i % 3]:
                cor_livre = "#10b981" if sl >= 0 else "#ef4444"
                st.markdown(f"""
                    <div class="card">
                        <h4 style="margin:0; color:#2F2F2F;">🏦 {f}</h4>
                        <div style="display:flex; justify-content:space-between; margin-top:10px; color:#2F2F2F;">
                            <span>Saldo Real:</span> <b>€{sr:,.2f}</b>
                        </div>
                        <div style="display:flex; justify-content:space-between; color:#6D7993; font-size:0.9rem;">
                            <span>Comprometido:</span> <span>-€{sc:,.2f}</span>
                        </div>
                        <hr style="margin:8px 0; border:0; border-top:1px solid #eee;">
                        <div style="display:flex; justify-content:space-between; color:#2F2F2F;">
                            <span>Disponível:</span> <b style="color:{cor_livre};">€{sl:,.2f}</b>
                        </div>
                    </div>
                """, unsafe_allow_html=True)

        st.divider()
        
        # 1. CÁLCULO DE INSIGHTS PARA A MENSAGEM
        status_color_livre = "#10b981" if t_livre >= 0 else "#ef4444"
        # Percentual de comprometimento do patrimônio total
        pct_comprometido = (abs(t_real - t_livre) / t_real * 100) if t_real > 0 else 0

        # 2. CSS PARA ALINHAMENTO E COR DINÂMICA
        # Nota: O seletor nth-of-type(2) foca na segunda métrica deste bloco horizontal
        st.markdown(f"""
            <style>
                [data-testid="stMetricValue"] {{ font-size: 1.8rem !important; }}
                [data-testid="stHorizontalBlock"] > div:nth-of-type(2) [data-testid="stMetricValue"] {{
                    color: {status_color_livre} !important;
                }}
            </style>
        """, unsafe_allow_html=True)

        # 3. GRID DE TOTAIS (SIMÉTRICO - SEM DELTA)
        c_t1, c_t2 = st.columns(2)
        c_t1.metric("SALDO REAL TOTAL", f"€ {t_real:,.2f}")
        c_t2.metric("DISPONIBILIDADE REAL", f"€ {t_livre:,.2f}")

        # 4. MENSAGEM COMPLEMENTAR INCREMENTADA (BI INSIGHT)
        if t_livre < 0:
            st.error(f"""
                🚨 **ALERTA DE INSOLVÊNCIA PATRIMONIAL**  
                Suas obrigações futuras (contas pendentes + faturas) superam o seu dinheiro disponível em conta.  
                📌 **Déficit Estimado:** `€{abs(t_livre):,.2f}`  
                📊 **Pressão sobre o Patrimônio:** Suas dívidas representam `{pct_comprometido:.1f}%` acima do seu saldo atual.
            """)
        else:
            st.success(f"""
                ✅ **DISPONIBILIDADE POSITIVA**  
                Seu patrimônio atual é suficiente para cobrir todos os compromissos futuros registrados.  
                📌 **Margem de Segurança Livre:** `€{t_livre:,.2f}`  
                📊 **Nível de Comprometimento:** Você já empenhou `{pct_comprometido:.1f}%` do seu saldo real.
            """)

# --- TAB 4: CARTÕES (COMPLETA) ---
with tabs[3]:
    st.subheader("💳 Gestão de Crédito")
    
    with st.expander("➕ Cadastrar Novo Cartão"):
        fnts_c = [f[0] for f in db_query("SELECT nome FROM fontes")]
        with st.form("f_cartao"):
            c_nc = st.text_input("Nome do Cartão")
            c_lim = st.number_input("Limite Total (€)", min_value=0.0, step=100.0)
            c_cnt = st.selectbox("Conta para Pagamento", fnts_c if fnts_c else ["Sem contas cadastradas"])
            c_df = st.number_input("Dia Fechamento", 1, 31, 25)
            c_dv = st.number_input("Dia Vencimento", 1, 31, 10)
            if st.form_submit_button("Salvar Cartão") and c_nc and fnts_c:
                db_execute("INSERT INTO cartoes (nome, limite, conta_pagamento, dia_fechamento, dia_vencimento) VALUES (?,?,?,?,?)", (c_nc, c_lim, c_cnt, c_df, c_dv))
                st.rerun()

    st.divider()
    cts = db_df("SELECT * FROM cartoes ORDER BY nome")
    if cts.empty: st.info("Nenhum cartão cadastrado.")
    for _, c in cts.iterrows():
        usd = db_query("SELECT SUM(valor_eur) FROM transacoes WHERE cartao_id=? AND status_cartao='pendente'", (c['id'],))[0][0] or 0.0
        st.markdown(f'<div class="card"><b>💳 {c["nome"]}</b><br>Limite: €{c["limite"]:,.2f} | Usado: €{usd:,.2f}</div>', unsafe_allow_html=True)
        fats = db_df("SELECT fatura_ref, SUM(valor_eur) as tot, status_cartao FROM transacoes WHERE cartao_id=? GROUP BY fatura_ref ORDER BY fatura_ref ASC", (c['id'],))
        for _, f in fats.iterrows():
            with st.expander(f"📅 Fatura {f['fatura_ref']} | €{f['tot']:,.2f} ({f['status_cartao']})"):
                comp = db_df("SELECT data, categoria_pai, valor_eur, nota FROM transacoes WHERE cartao_id=? AND fatura_ref=?", (c['id'], f['fatura_ref']))
                st.dataframe(comp, hide_index=True, use_container_width=True)
                if f['status_cartao'] == 'pendente':
                    if st.button(f"Pagar Fatura {f['fatura_ref']}", key=f"p_{c['id']}_{f['fatura_ref']}", type="primary"):
                        if calcular_saldo_real(c['conta_pagamento']) >= f['tot']:
                            ops = [("UPDATE transacoes SET status_cartao='pago', status_liquidacao='PAGO' WHERE cartao_id=? AND fatura_ref=?", (c['id'], f['fatura_ref'])),
                                   ("INSERT INTO transacoes (data, categoria_pai, fonte, valor_eur, tipo, nota, status_liquidacao) VALUES (?,?,?,?,?,?,?)", (date.today().strftime("%Y-%m-%d"), "Cartão", c['conta_pagamento'], f['tot'], "Despesa", f"Pgto {c['nome']}", "PAGO"))]
                            db_execute_many(ops); st.rerun()
                        else: st.error("Saldo insuficiente na conta de débito.")

# --- TAB 5: METAS (COMPLETA) ---

with tabs[4]:
    st.subheader("🎯 Orçamento e Metas")
    
    # 1. SELETOR DE MÊS
    meses_db = db_query("SELECT DISTINCT substr(data, 1, 7) FROM transacoes")
    lista_m = sorted(list(set([m[0] for m in meses_db] + [date.today().strftime("%Y-%m")])), reverse=True)
    m_ref = st.selectbox("Mês de Referência", lista_m, key="sel_mes_metas_final")
    
    with st.expander("➕ Definir Nova Meta / Teto"):
        t_m_sel = st.radio("Natureza da Meta", ["Despesa", "Receita"], horizontal=True, key="hier_t_meta_final")
        
        # Busca Pais
        pais_db = db_query("SELECT id, nome FROM categorias WHERE pai_id IS NULL AND tipo_categoria=?", (t_m_sel,))
        dict_pais = {p[1]: p[0] for p in pais_db}
        c_p_sel = st.selectbox("Categoria Principal", list(dict_pais.keys()) if dict_pais else ["Sem categorias"], key="p_meta_final")
        
        # Busca Filhos reativamente
        id_p_sel = dict_pais.get(c_p_sel)
        filhos_db = db_query("SELECT nome FROM categorias WHERE pai_id = ?", (id_p_sel,)) if id_p_sel else []
        lista_f = ["Geral"] + [f[0] for f in filhos_db]
        c_f_sel = st.selectbox("Subcategoria / Detalhe", lista_f, key="f_meta_final")

        with st.form("form_metas_hierarquico_v3", clear_on_submit=True):
            v_m = st.number_input("Valor Planejado (€)", min_value=0.0, step=50.0)
            if st.form_submit_button("💾 SALVAR PLANEJAMENTO"):
                if c_p_sel != "Sem categorias":
                    db_execute("""
                        INSERT OR REPLACE INTO orcamentos (mes_ano, categoria_pai, categoria_filho, valor_previsto, tipo_meta) 
                        VALUES (?,?,?,?,?)""", (m_ref, c_p_sel, c_f_sel, v_m, t_m_sel))
                    st.success("Meta salva com sucesso!")
                    st.rerun()

    st.divider()
    # 2. RENDERIZAÇÃO HIERÁRQUICA (AGRUPADA POR PAI)
    metas_df = db_df("SELECT * FROM orcamentos WHERE mes_ano=? ORDER BY categoria_pai ASC", (m_ref,))
    
    if metas_df.empty:
        st.info("Nenhuma meta definida para este mês.")
    else:
        # Loop por Categoria Pai Única
        for pai in metas_df['categoria_pai'].unique():
            st.markdown(f"#### 📁 {pai}") # Título da Categoria Principal
            
            # Filtra os orçamentos que pertencem a este pai
            filhos_da_categoria = metas_df[metas_df['categoria_pai'] == pai]
            
            for _, r in filhos_da_categoria.iterrows():
                # Cálculo do Realizado
                if r['categoria_filho'] == "Geral":
                    real_val = db_query("SELECT SUM(valor_eur) FROM transacoes WHERE categoria_pai=? AND data LIKE ? AND tipo=?", 
                                        (r['categoria_pai'], f"{m_ref}%", r['tipo_meta']))[0][0] or 0.0
                else:
                    real_val = db_query("SELECT SUM(valor_eur) FROM transacoes WHERE categoria_pai=? AND categoria_filho=? AND data LIKE ? AND tipo=?", 
                                        (r['categoria_pai'], r['categoria_filho'], f"{m_ref}%", r['tipo_meta']))[0][0] or 0.0

                p_val = min(real_val / r['valor_previsto'], 1.0) if r['valor_previsto'] > 0 else 0.0
                is_over = (r['tipo_meta'] == "Despesa" and real_val > r['valor_previsto'])
                cor_barra = "🔴" if is_over else "🟢"

                # Layout de Indentação (Uso de container para separar visualmente)
                with st.container():
                    # Espaçamento HTML para criar o efeito de "árvore"
                    st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{cor_barra} **{r['categoria_filho']}** <small>({r['tipo_meta']})</small>", unsafe_allow_html=True)
                    st.progress(p_val, text=f"€{real_val:,.2f} de €{r['valor_previsto']:,.2f}")
            st.markdown("<br>", unsafe_allow_html=True) # Espaço entre grupos

# --- TAB 6: DASHBOARD DE INTELIGÊNCIA FINANCEIRA (BI COMPLETO V2) ---
with tabs[5]:
    st.subheader("📊 Business Intelligence: Saúde e Tendências")
    
    # 1. CARREGAMENTO INICIAL DOS DADOS
    df_dashboard_base = db_df("SELECT * FROM transacoes")
    
    if df_dashboard_base.empty:
        st.warning("⚠️ O banco de dados está vazio. Registre lançamentos para visualizar os gráficos.")
    else:
        # 2. MOTOR DE FILTROS AVANÇADOS (COM SUBCATEGORIAS)
        with st.expander("🔍 Filtros Avançados de BI", expanded=False):
            df_dashboard_base['dt'] = pd.to_datetime(df_dashboard_base['data'])
            df_dashboard_base['beneficiario'] = df_dashboard_base['beneficiario'].fillna("N/A").replace("", "N/A")
            df_dashboard_base['categoria_filho'] = df_dashboard_base['categoria_filho'].fillna("Geral")
            
            c_an1, c_an2, c_an3 = st.columns(3)
            min_d = df_dashboard_base['dt'].min().date()
            max_d = df_dashboard_base['dt'].max().date()
            data_range = c_an1.date_input("Período de Análise", [min_d, max_d])
            
            f_contas = c_an2.multiselect("Filtrar Contas/Cartões", sorted(df_dashboard_base['fonte'].unique()))
            f_ben = c_an3.multiselect("Filtrar Beneficiários", sorted(df_dashboard_base['beneficiario'].unique()))

            c_an4, c_an5 = st.columns(2)
            f_cats = c_an4.multiselect("Filtrar Categorias Principais", sorted(df_dashboard_base['categoria_pai'].unique()))
            
            if f_cats:
                sub_options = sorted(df_dashboard_base[df_dashboard_base['categoria_pai'].isin(f_cats)]['categoria_filho'].unique())
            else:
                sub_options = sorted(df_dashboard_base['categoria_filho'].unique())
                
            f_subcats = c_an5.multiselect("Filtrar Subcategorias / Detalhes", sub_options)

        # 3. PROCESSAMENTO DOS DADOS FILTRADOS
        df_bi = df_dashboard_base.copy()
        if len(data_range) == 2:
            df_bi = df_bi[(df_bi['dt'].dt.date >= data_range[0]) & (df_bi['dt'].dt.date <= data_range[1])]
        if f_contas:  df_bi = df_bi[df_bi['fonte'].isin(f_contas)]
        if f_cats:    df_bi = df_bi[df_bi['categoria_pai'].isin(f_cats)]
        if f_subcats: df_bi = df_bi[df_bi['categoria_filho'].isin(f_subcats)]
        if f_ben:     df_bi = df_bi[df_bi['beneficiario'].isin(f_ben)]

        if df_bi.empty:
            st.info("Ajuste os filtros acima. Nenhum dado encontrado para esta seleção.")
        else:
            # 4. KPIs EXECUTIVOS E ALINHAMENTO VISUAL
            st.markdown("---")
            rec_total = df_bi[df_bi['tipo'] == 'Receita']['valor_eur'].sum()
            des_total = df_bi[df_bi['tipo'] == 'Despesa']['valor_eur'].sum()
            des_paga  = df_bi[(df_bi['tipo'] == 'Despesa') & (df_bi['status_liquidacao'] == 'PAGO')]['valor_eur'].sum()
            total_comp = df_bi[df_bi['status_liquidacao'].isin(['PENDENTE', 'PREVISTO'])]['valor_eur'].sum()
            
            balanco_projetado = round(rec_total - des_total, 2)
            margem_pct = (balanco_projetado / rec_total * 100) if rec_total > 0 else (0.0 if balanco_projetado >= 0 else -100.0)

            # CSS Dinâmico para Alinhamento e Cor do Balanço
            status_color = "#10b981" if balanco_projetado >= 0 else "#ef4444"
            st.markdown(f"""
                <style>
                [data-testid="stMetricValue"] {{ font-size: 1.8rem !important; }}
                [data-testid="stHorizontalBlock"] > div:nth-of-type(4) [data-testid="stMetricValue"] {{ color: {status_color} !important; }}
                </style>
            """, unsafe_allow_html=True)

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("💰 Receita Total", f"€{rec_total:,.2f}")
            k2.metric("💸 Despesa Paga", f"€{des_paga:,.2f}")
            k3.metric("⚠️ Comprometido", f"€{total_comp:,.2f}")
            k4.metric("⚖️ Balanço Líquido", f"€{balanco_projetado:,.2f}")

            if balanco_projetado < 0:
                st.error(f"**Déficit Detectado:** Suas obrigações superam as receitas. Margem: `{margem_pct:.1f}%`")
            else:
                st.success(f"**Superávit Projetado:** Margem de segurança: `{margem_pct:.1f}%`")

            # 5. MOTOR DE INTELIGÊNCIA GRÁFICA (EDITION: REFINED JOURNAL)
            st.markdown("---")
            
            visao_t = st.radio("Selecione a Perspectiva do Fluxo Temporal:", 
                               ["Receita x Despesa", "Execução de Despesa", "Despesa por Categoria"], 
                               horizontal=True, key="visao_temporal_bi_final_v2")

            col_g1, col_g2 = st.columns([2, 1])
            
            with col_g1:
                # Definimos a paleta Journal para consistência
                paleta_journal = {"Receita": "#6D7993", "Despesa": "#96858F", 
                                  "Realizado (Pago)": "#9099A2", "Comprometido (Pendente)": "#96858F", 
                                  "Total Geral": "#4A4A4A"}

                if visao_t == "Receita x Despesa":
                    df_trend = df_bi.groupby(['dt', 'tipo'])['valor_eur'].sum().unstack(fill_value=0).reset_index()
                    # Melt para controle fino de traços
                    df_melt = df_trend.melt(id_vars='dt', var_name='Tipo', value_name='Valor')
                    fig_trend = px.line(df_melt, x='dt', y='Valor', color='Tipo', 
                                        line_dash='Tipo', # Diferencia por estilo de linha
                                        title="Tendência: Receita vs Despesa",
                                        color_discrete_map=paleta_journal,
                                        markers=True, template="simple_white")

                elif visao_t == "Execução de Despesa":
                    df_exec = df_bi[df_bi['tipo'] == 'Despesa'].copy()
                    df_exec['Status_Exec'] = df_exec['status_liquidacao'].apply(lambda x: 'Realizado (Pago)' if x == 'PAGO' else 'Comprometido (Pendente)')
                    df_trend = df_exec.groupby(['dt', 'Status_Exec'])['valor_eur'].sum().unstack(fill_value=0).reset_index()
                    
                    # Garantir que todas as colunas existem para não quebrar o gráfico
                    for col in ['Realizado (Pago)', 'Comprometido (Pendente)']:
                        if col not in df_trend.columns: df_trend[col] = 0
                    
                    df_trend['Total Geral'] = df_trend['Realizado (Pago)'] + df_trend['Comprometido (Pendente)']
                    df_melt = df_trend.melt(id_vars='dt', var_name='Status', value_name='Valor')
                    
                    fig_trend = px.line(df_melt, x='dt', y='Valor', color='Status',
                                        line_dash='Status', # Total (Sólida), Realizado (Tracejada), Pendente (Pontilhada)
                                        title="Execução: Realizado vs Comprometido",
                                        color_discrete_map=paleta_journal,
                                        markers=True, template="simple_white")

                else: # Despesa por Categoria
                    df_cat_t = df_bi[df_bi['tipo'] == 'Despesa'].groupby(['dt', 'categoria_pai'])['valor_eur'].sum().unstack(fill_value=0).reset_index()
                    fig_trend = px.area(df_cat_t, x='dt', y=df_cat_t.columns[1:], 
                                        title="Peso Temporal por Categoria",
                                        template="simple_white", color_discrete_sequence=px.colors.qualitative.Pastel)

                fig_trend.update_layout(hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                st.plotly_chart(fig_trend, use_container_width=True)

            with col_g2:
                fig_tree = px.treemap(df_bi[df_bi['tipo']=='Despesa'], 
                                      path=['categoria_pai', 'beneficiario'], 
                                      values='valor_eur', 
                                      title="Estrutura de Gastos", 
                                      color_discrete_sequence=['#6D7993', '#96858F', '#9099A2'])
                fig_tree.update_layout(margin=dict(t=30, l=10, r=10, b=10))
                st.plotly_chart(fig_tree, use_container_width=True)

            st.markdown("---")
            col_g3, col_g4 = st.columns(2)
            
            with col_g3:
                df_pareto = df_bi[df_bi['tipo']=='Despesa'].groupby('beneficiario')['valor_eur'].sum().sort_values(ascending=False).head(10).reset_index()
                fig_pareto = px.bar(df_pareto, x='valor_eur', y='beneficiario', orientation='h', 
                                    title="Top 10 Beneficiários", 
                                    color='valor_eur', color_continuous_scale='Purples')
                fig_pareto.update_layout(yaxis={'categoryorder':'total ascending'})
                st.plotly_chart(fig_pareto, use_container_width=True)

            with col_g4:
                # SUNBURST REFINADO: Cores pastéis e neutras
                df_src = df_bi.groupby(['fonte', 'tipo'])['valor_eur'].sum().reset_index()
                fig_sun = px.sunburst(df_src, path=['fonte', 'tipo'], values='valor_eur', 
                                      title="Concentração de Volume por Fonte", 
                                      color_discrete_sequence=['#9099A2', '#6D7993', '#96858F', '#D5D5D5'])
                st.plotly_chart(fig_sun, use_container_width=True)
    
    # 6. EXPORTAÇÃO GERENCIAL
    st.markdown("---")
    if st.button("📊 Gerar Relatório Excel (3 Abas)", use_container_width=True, type="primary"):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            db_df("SELECT * FROM transacoes").to_excel(writer, index=False, sheet_name='Transacoes_Full')
            db_df("SELECT * FROM orcamentos").to_excel(writer, index=False, sheet_name='Metas_Configuradas')
        st.download_button("⬇️ Baixar Excel", output.getvalue(), "Relatorio_BI_Gerencial.xlsx")
        
# --- TAB 7: GESTÃO GERAL (TOTALMENTE RESTAURADA E RESILIENTE) ---
if is_admin:
    with tabs[6]:
        st.subheader("⚙️ Gestão e Configurações do Sistema")
        
        # Seção 0: Câmbio
        st.markdown("#### 💱 Seção 0 - Taxa de Câmbio")
        ntax = st.number_input("Taxa BRL/EUR", value=st.session_state.taxa, format="%.4f")
        if st.button("💾 Salvar Nova Taxa"):
            db_execute("UPDATE configuracoes SET valor=? WHERE chave='taxa_brl_eur'", (str(ntax),))
            st.session_state.taxa = ntax
            st.success("Taxa atualizada com sucesso!")
            st.rerun()
    
        st.divider()
        
        # Seção 1: Contas
        st.markdown("#### 🏦 Seção 1 - Contas Bancárias (Fontes)")
        n_font = st.text_input("Nome da Nova Conta (Ex: Banco X, Carteira)")
        if st.button("➕ Adicionar Conta"):
            if n_font: 
                db_execute("INSERT INTO fontes (nome) VALUES (?)", (n_font,))
                st.success(f"Conta '{n_font}' adicionada!")
                st.rerun()
        
        df_f = db_df("SELECT id, nome FROM fontes")
        if not df_f.empty:
            df_f.insert(0, "Remover", False)
            ed_f = st.data_editor(df_f, hide_index=True, use_container_width=True, key="ed_font_gest")
            if st.button("🗑️ Excluir Contas Selecionadas"):
                for _, r in df_f[ed_f["Remover"] == True].iterrows():
                    if not verificar_bloqueio_delecao("fontes", r['id']):
                        db_execute("DELETE FROM fontes WHERE id=?", (r['id'],))
                    else: st.error(f"Bloqueado: A conta '{r['nome']}' possui lançamentos vinculados.")
                st.rerun()
    
        st.divider()
        
        # Seção 2: Categorias
        st.markdown("#### 📂 Seção 2 - Árvore de Categorias")
        c1, c2 = st.columns(2)
        with c1:
            st.caption("Criar Categoria Principal")
            tc = st.radio("Natureza", ["Despesa", "Receita"], horizontal=True, key="tc_gest_final")
            nc = st.text_input("Nome da Categoria")
            if st.button("➕ Criar Categoria Principal"):
                if nc: db_execute("INSERT INTO categorias (nome, tipo_categoria) VALUES (?,?)", (nc, tc)); st.rerun()
        with c2:
            st.caption("Criar Detalhamento (Subcategoria)")
            pais_list = db_query("SELECT id, nome FROM categorias WHERE pai_id IS NULL")
            if pais_list:
                p_sel_g = st.selectbox("Vincular ao Pai", [p[1] for p in pais_list])
                ns = st.text_input("Nome do Detalhe")
                if st.button("➕ Criar Subcategoria"):
                    id_p_g = [p[0] for p in pais_list if p[1] == p_sel_g][0]
                    db_execute("INSERT INTO categorias (nome, pai_id) VALUES (?,?)", (ns, id_p_g)); st.rerun()
    
        df_c = db_df("SELECT id, nome, tipo_categoria FROM categorias")
        if not df_c.empty:
            df_c.insert(0, "Remover", False)
            ed_c = st.data_editor(df_c, hide_index=True, use_container_width=True, key="ed_cat_gest")
            if st.button("🗑️ Excluir Categorias Selecionadas"):
                for _, r in df_c[ed_c["Remover"] == True].iterrows():
                    if not verificar_bloqueio_delecao("categorias", r['id']):
                        db_execute("DELETE FROM categorias WHERE id=?", (r['id'],))
                    else: st.error(f"Bloqueado: Categoria '{r['nome']}' possui dependências.")
                st.rerun()
    
        # --- SEÇÃO 3: BENEFICIÁRIOS (MANTIDA E ORGANIZADA) ---
        st.divider()
        st.markdown("#### 👤 Seção 3 - Gestão de Beneficiários")
        nb = st.text_input("Novo Beneficiário", placeholder="Ex: Nome da Pessoa ou Empresa")
        if st.button("➕ Adicionar Beneficiário"):
            if nb: 
                db_execute("INSERT OR IGNORE INTO beneficiarios (nome) VALUES (?)", (nb.strip(),))
                st.rerun()
    
        df_b = db_df("SELECT id, nome FROM beneficiarios ORDER BY nome")
        if not df_b.empty:
            df_b.insert(0, "Remover", False)
            ed_b = st.data_editor(df_b, hide_index=True, use_container_width=True, key="ed_ben_gestao")
            if st.button("🗑️ Excluir Beneficiários Selecionados"):
                for _, r in df_b[ed_b["Remover"] == True].iterrows():
                    if not verificar_bloqueio_delecao("beneficiarios", r['id']):
                        db_execute("DELETE FROM beneficiarios WHERE id=?", (r['id'],))
                    else:
                        st.error(f"Bloqueado: '{r['nome']}' possui transações vinculadas.")
                st.rerun()
    
        # --- SEÇÃO 4: USUÁRIOS E SEGURANÇA (TOTALMENTE NOVA) ---
        st.divider()
        st.markdown("#### 👥 Seção 4 - Controle de Usuários e Perfis")
        st.caption("Cadastre membros da família e defina o nível de acesso (Admin ou Utilizador).")
        
        with st.form("form_novo_usuario", clear_on_submit=True):
            u_col1, u_col2 = st.columns(2)
            u_col3, u_col4 = st.columns(2)
            
            with u_col1: unome = st.text_input("Nome de Exibição")
            with u_col2: ulog = st.text_input("Login (Username)")
            with u_col3: umail = st.text_input("E-mail (Para 2FA)")
            with u_col4: uprof = st.selectbox("Perfil", ["Utilizador", "Administrador"])
            
            usenh = st.text_input("Senha Inicial", type="password")
            
            if st.form_submit_button("👤 CRIAR CONTA", use_container_width=True):
                if unome and ulog and umail and usenh:
                    pwd_h = hashlib.sha256(usenh.encode()).hexdigest()
                    try:
                        db_execute("INSERT INTO usuarios (username, password, nome_exibicao, email, perfil) VALUES (?,?,?,?,?)",
                                   (ulog.strip(), pwd_h, unome.strip(), umail.strip(), uprof))
                        st.success(f"✅ Usuário '{ulog}' criado como {uprof}!")
                        st.rerun()
                    except:
                        st.error("Erro: Este login já está em uso.")
                else:
                    st.warning("Preencha todos os campos.")
    
        # Tabela de Auditoria de Usuários (Apenas Admin vê)
        st.markdown("##### Usuários Cadastrados")
        df_users = db_df("SELECT id, username as Login, nome_exibicao as Nome, email as Email, perfil as Perfil FROM usuarios")
        if not df_users.empty:
            df_users.insert(0, "Remover", False)
            ed_u = st.data_editor(df_users, hide_index=True, use_container_width=True, key="ed_usuarios_gestao")
            if st.button("🗑️ Remover Acesso Selecionado"):
                for _, r in df_users[ed_u["Remover"] == True].iterrows():
                    # Proteção para não deletar a si mesmo ou o admin master por engano
                    if r['Login'] == st.session_state.user:
                        st.error("Você não pode remover seu próprio acesso.")
                    else:
                        db_execute("DELETE FROM usuarios WHERE id=?", (r['id'],))
                st.rerun()

# --- TAB 8: TRANSFERÊNCIAS (SOMA ZERO + HISTÓRICO DE AUDITORIA) ---
with tabs[7]:
    st.subheader("🔄 Transferência Entre Bancos")
    
    # 1. MOTOR DE ENTRADA (FORMULÁRIO)
    res_fontes = db_query("SELECT nome FROM fontes ORDER BY nome")
    fontes_t = [f[0] for f in res_fontes]

    if len(fontes_t) < 2:
        st.error("❗ **Ação Necessária:** Cadastre pelo menos 2 contas na aba Gestão.")
    else:
        with st.expander("➕ Executar Nova Transferência", expanded=True):
            with st.form("form_transf_bi"):
                c1, c2 = st.columns(2)
                c_origem = c1.selectbox("Conta de Origem (Saída)", fontes_t)
                c_destino = c2.selectbox("Conta de Destino (Entrada)", [f for f in fontes_t if f != c_origem])
                
                v_col, d_col = st.columns(2)
                valor_transf = v_col.number_input("Valor (€)", min_value=0.01, step=10.0, format="%.2f")
                data_transf = d_col.date_input("Data da Operação", date.today())
                
                nota_transf = st.text_input("Nota / Motivo da Movimentação")
                
                if st.form_submit_button("🔁 CONFIRMAR MOVIMENTAÇÃO"):
                    realizar_transferencia(c_origem, c_destino, valor_transf, data_transf.strftime("%Y-%m-%d"), st.session_state.user, nota_transf)
                    st.success("Transferência realizada!")
                    st.rerun()

    # 2. HISTÓRICO DE TRANSFERÊNCIAS (VISÃO CONSOLIDADA DE BI)
    st.divider()
    st.markdown("#### 📜 Histórico de Movimentações Internas")
    
    # Lógica de Agrupamento: Unimos as duas linhas (ID par/ímpar) em um único evento visual
    df_trans_hist = db_df("""
        SELECT 
            GROUP_CONCAT(id) as ids_grupo, -- Junta os IDs das duas pontas (ex: "13,14")
            data as Data,
            MAX(CASE WHEN beneficiario LIKE 'Para %' THEN fonte END) as "Conta Origem",
            MAX(CASE WHEN beneficiario LIKE 'De %' THEN fonte END) as "Conta Destino",
            valor_eur as "Valor (€)",
            nota as "Descrição"
        FROM transacoes 
        WHERE categoria_pai = 'Transferência' 
        GROUP BY data, valor_eur, nota -- Agrupa as pontas que compartilham os mesmos dados
        ORDER BY data DESC
    """)

    if df_trans_hist.empty:
        st.info("Nenhuma transferência registrada no histórico.")
    else:
        df_trans_view = df_trans_hist.copy()
        df_trans_view.insert(0, "🗑️", False)
        
        st.caption("Abaixo, cada linha representa uma operação completa entre duas contas.")
        ed_trans = st.data_editor(
            df_trans_view, 
            hide_index=True, 
            use_container_width=True, 
            key="editor_transf_consolidado"
        )

        # 3. LÓGICA DE EXCLUSÃO ATÔMICA (ESTORNA AS DUAS PONTAS)
        if st.button("🗑️ Estornar Movimentações Selecionadas", type="secondary"):
            # Coletamos as strings de IDs agrupados (ex: ["13,14", "15,16"])
            strings_ids = df_trans_view.loc[ed_trans["🗑️"] == True, "ids_grupo"].tolist()
            
            if strings_ids:
                # Transformamos ["13,14", "15,16"] em uma lista única de IDs [13, 14, 15, 16]
                todos_ids = []
                for s in strings_ids:
                    todos_ids.extend(s.split(','))
                
                placeholder = ",".join(["?"] * len(todos_ids))
                db_execute(f"DELETE FROM transacoes WHERE id IN ({placeholder})", tuple(todos_ids))
                st.success(f"✅ Sucesso! {len(strings_ids)} operação(ões) de transferência estornada(s).")
                st.rerun()
