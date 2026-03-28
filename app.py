import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import hashlib
import io
import logging
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

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
        "CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, nome_exibicao TEXT)",
        "CREATE TABLE IF NOT EXISTS fontes (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)",
        "CREATE TABLE IF NOT EXISTS saldos_iniciais (fonte TEXT PRIMARY KEY, valor_inicial REAL DEFAULT 0.0)",
        "CREATE TABLE IF NOT EXISTS beneficiarios (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)",
        "CREATE TABLE IF NOT EXISTS configuracoes (chave TEXT PRIMARY KEY, valor TEXT)",
        "CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE, pai_id INTEGER, tipo_categoria TEXT, FOREIGN KEY(pai_id) REFERENCES categorias(id) ON DELETE RESTRICT)",
        "CREATE TABLE IF NOT EXISTS cartoes (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE, limite REAL, dia_fechamento INTEGER, dia_vencimento INTEGER, conta_pagamento TEXT)",
        "CREATE TABLE IF NOT EXISTS orcamentos (id INTEGER PRIMARY KEY AUTOINCREMENT, mes_ano TEXT, categoria_pai TEXT, valor_previsto REAL, tipo_meta TEXT, UNIQUE(mes_ano, categoria_pai, tipo_meta))",
        "CREATE TABLE IF NOT EXISTS transacoes (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT, categoria_pai TEXT, categoria_filho TEXT, beneficiario TEXT, fonte TEXT, valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT, forma_pagamento TEXT DEFAULT 'Dinheiro/Débito', cartao_id INTEGER, fatura_ref TEXT, status_cartao TEXT DEFAULT 'pendente', status_liquidacao TEXT DEFAULT 'PAGO', data_liquidacao TEXT, parcela_id TEXT, parcela_numero INTEGER DEFAULT 1, total_parcelas INTEGER DEFAULT 1)"
    ]
    for sql in tables: db_execute(sql)
    db_execute("INSERT OR IGNORE INTO configuracoes (chave, valor) VALUES ('taxa_brl_eur', '0.16')")
    admin_pw = hashlib.sha256("123456".encode()).hexdigest()
    db_execute("INSERT OR IGNORE INTO usuarios (username, password, nome_exibicao) VALUES ('admin', ?, 'Administrador')", (admin_pw,))

init_db()

if 'ver' not in st.session_state:
    taxa_db = db_query("SELECT valor FROM configuracoes WHERE chave='taxa_brl_eur'")
    st.session_state.update({'ver': 0, 'logado': False, 'user': None, 'display_name': None, 'taxa': float(taxa_db[0][0]) if taxa_db else 0.16})

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
    res_ini = db_query("SELECT valor_inicial FROM saldos_iniciais WHERE fonte=?", (fonte,))
    ini = res_ini[0][0] if res_ini else 0.0
    rec = db_query("SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo='Receita' AND status_liquidacao='RECEBIDO'", (fonte,))[0][0] or 0.0
    des = db_query("SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo='Despesa' AND status_liquidacao='PAGO'", (fonte,))[0][0] or 0.0
    return round(ini + rec - des, 2)

def calcular_comprometido(fonte):
    sql = "SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo=? AND status_liquidacao IN ('PENDENTE','PREVISTO')"
    desp = db_query(sql, (fonte, "Despesa"))[0][0] or 0.0
    rec = db_query(sql, (fonte, "Receita"))[0][0] or 0.0
    fat = db_query("SELECT SUM(t.valor_eur) FROM transacoes t JOIN cartoes c ON t.cartao_id=c.id WHERE c.conta_pagamento=? AND t.status_cartao='pendente'", (fonte,))[0][0] or 0.0
    return round(desp - rec + fat, 2)

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

# --- 4. AUTENTICAÇÃO E SIDEBAR ---
if not st.session_state.logado:
    _, col_login, _ = st.columns([1, 1.5, 1])
    with col_login:
        st.markdown("<br>## 🏠 ERP Familiar", unsafe_allow_html=True)
        u_in = st.text_input("Usuário")
        p_in = st.text_input("Senha", type="password")
        if st.button("Entrar", use_container_width=True, type="primary"):
            pwd_hash = hashlib.sha256(p_in.encode()).hexdigest()
            res = db_query("SELECT nome_exibicao FROM usuarios WHERE username=? AND password=?", (u_in, pwd_hash))
            if res: st.session_state.update({'logado': True, 'user': u_in, 'display_name': res[0][0]}); st.rerun()
            else: st.error("Erro de login.")
    st.stop()

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

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs(["➕ Novos Lançamentos", "📋 Histórico de Lançamentos", "💰 Saldos", "💳 Cartões", "🎯 Metas", "📊 Dashboards", "⚙️ Gestão Geral", "🔄 Transferências"])

# --- TAB 1: NOVO LANÇAMENTO ---

with tab1:
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

        if st.form_submit_button("💾 SALVAR REGISTRO"):
            try:
                is_cc = (forma_sel == "Cartão de Crédito")
                c_inf = db_query("SELECT id, dia_fechamento, dia_vencimento FROM cartoes WHERE nome=?", (fonte_sel,))[0] if is_cc else (None, 0, 0)
                
                # Gera o cronograma de parcelas
                parcs = calcular_parcelas(data_in.strftime("%Y-%m-%d"), c_inf[1], c_inf[2], valor_in, parc_in, is_cc)
                
                ops = []
                for i, (p_d, p_v, p_n) in enumerate(parcs):
                    # --- APLICAÇÃO DA NOVA REGRA DE OURO ---
                    if is_cc:
                        # Se for cartão, NADA é pago agora. Tudo entra como PENDENTE.
                        st_liq = "PENDENTE"
                    else:
                        # Se for Dinheiro/Débito, segue a regra: 1ª Paga, demais Pendentes.
                        st_liq = determinar_status_operacao(tipo_sel, eh_primeira_parcela=(i==0))
                    
                    f_ref = calcular_fatura_ref(p_d, c_inf[1]) if is_cc else None
                    
                    ops.append(("INSERT INTO transacoes (data, categoria_pai, categoria_filho, beneficiario, fonte, valor_eur, tipo, nota, usuario, forma_pagamento, cartao_id, fatura_ref, status_liquidacao) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (p_d, pai_sel, filho_sel, benef_sel, fonte_sel, p_v, tipo_sel, f"{nota_in} ({p_n}/{parc_in})" if parc_in>1 else nota_in, st.session_state.user, forma_sel, c_inf[0], f_ref, st_liq)))
                
                db_execute_many(ops)
                st.success(f"✅ Sucesso! {parc_in} lançamento(s) registrado(s) como {st_liq if not is_cc or i>0 else 'PENDENTE (Cartão)'}")
                st.rerun()
            except Exception as e:
                st.error(f"Erro Crítico: {e}")

# --- TAB 2: HISTÓRICO ---

with tab2:
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
        meses_uniquos = df_raw.sort_values('dt', ascending=False)['mes_ref'].unique()

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

        # 5. TABELA TÉCNICA DE REMOÇÃO
        st.divider()
        st.caption("🛠️ Remoção e Auditoria Técnica")
        df_audit = df_raw.copy()
        df_audit.insert(0, "Remover", False)
        editor_df = st.data_editor(df_audit[["Remover", "id", "data", "categoria_pai", "valor_eur", "nota"]], 
                                     hide_index=True, use_container_width=True, key=f"ed_v_final")
        
        if st.button("🗑️ Excluir Selecionados", type="secondary"):
            ids_rm = df_audit.loc[editor_df["Remover"] == True, "id"].tolist()
            if ids_rm:
                ph = ",".join(["?"] * len(ids_rm))
                db_execute(f"DELETE FROM transacoes WHERE id IN ({ph})", tuple(ids_rm))
                st.rerun()
    else:
        st.info("Nenhum registro encontrado para os filtros aplicados.")
        
# --- TAB 3 E 4: SALDOS E CARTÕES ---
with tab3:
    st.subheader("💰 Patrimônio e Liquidez")
    fnts = [f[0] for f in db_query("SELECT nome FROM fontes ORDER BY nome")]
    if not fnts:
        st.info("💡 Vá até a aba ⚙️ Gestão e cadastre suas Contas Bancárias.")
    else:
        tr, tl = 0.0, 0.0
        cols = st.columns(3)
        for i, f in enumerate(fnts):
            sr = calcular_saldo_real(f); sc = calcular_comprometido(f); sl = sr - sc
            tr += sr; tl += sl
            with cols[i%3]: 
                st.markdown(f'<div class="card"><b>🏦 {f}</b><br>Real: €{sr:,.2f}<br>Livre: <b style="color:{"#10b981" if sl>=0 else "#ef4444"};">€{sl:,.2f}</b></div>', unsafe_allow_html=True)
        st.divider()
        c_t1, c_t2 = st.columns(2)
        c_t1.metric("SALDO REAL TOTAL", f"€ {tr:,.2f}")
        c_t2.metric("DISPONIBILIDADE REAL", f"€ {tl:,.2f}", delta_color="normal" if tl>=0 else "inverse")
        if tl < 0: st.error("🚨 RISCO DE INSOLVÊNCIA PATRIMONIAL!")
        
        st.divider()
        col_aj, col_ini = st.columns(2)
        with col_aj:
            st.markdown("#### ⚖️ Bater Saldo (Ajuste)")
            f_aj = st.selectbox("Conta", fnts, key="f_aj")
            v_banco = st.number_input("Valor no Extrato (€)", step=0.01, format="%.2f")
            if st.button("Sincronizar Banco"):
                sr_atual = calcular_saldo_real(f_aj)
                diff = round(v_banco - sr_atual, 2)
                if abs(diff) > 0.01:
                    t_aj, st_aj = ("Receita", "RECEBIDO") if diff > 0 else ("Despesa", "PAGO")
                    db_execute("INSERT INTO transacoes (data, categoria_pai, fonte, valor_eur, tipo, nota, status_liquidacao, usuario) VALUES (?,?,?,?,?,?,?,?)",
                               (date.today().strftime("%Y-%m-%d"), "Ajuste de Saldo", f_aj, abs(diff), t_aj, f"Ajuste automático (diff {diff})", st_aj, st.session_state.user))
                    st.success("Ajuste realizado!"); st.rerun()
                else: st.info("Saldo já coincide.")
        with col_ini:
            st.markdown("#### 🔧 Configurar Saldo Inicial")
            f_ini = st.selectbox("Conta Inicial", fnts, key="f_ini")
            n_ini = st.number_input("Valor Inicial (€)", step=10.0, format="%.2f")
            if st.button("Salvar Inicial"):
                db_execute("INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)", (f_ini, n_ini))
                st.success("Salvo!"); st.rerun()

# --- TAB 4: CARTÕES (COMPLETA) ---
with tab4:
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
        fats = db_df("SELECT fatura_ref, SUM(valor_eur) as tot, status_cartao FROM transacoes WHERE cartao_id=? GROUP BY fatura_ref ORDER BY fatura_ref DESC", (c['id'],))
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
with tab5:
    st.subheader("🎯 Orçamento e Metas")
    m_ref_list = sorted(list(set([d[0][:7] for d in db_query("SELECT data FROM transacoes")] + [date.today().strftime("%Y-%m")])), reverse=True)
    m_ref = st.selectbox("Mês de Referência", m_ref_list, key="m_ref_metas")
    
    with st.expander("➕ Definir Nova Meta / Teto"):
        with st.form("f_metas"):
            t_m = st.radio("Tipo de Meta", ["Despesa", "Receita"], horizontal=True)
            cats_p = db_query("SELECT nome FROM categorias WHERE pai_id IS NULL AND tipo_categoria=?", (t_m,))
            c_m = st.selectbox("Categoria Principal", [c[0] for c in cats_p] if cats_p else ["Sem categorias"])
            v_m = st.number_input("Valor Planejado (€)", min_value=0.0, step=50.0)
            if st.form_submit_button("Salvar Planejamento") and cats_p:
                db_execute("INSERT OR REPLACE INTO orcamentos (mes_ano, categoria_pai, valor_previsto, tipo_meta) VALUES (?,?,?,?)", (m_ref, c_m, v_m, t_m)); st.rerun()

    st.divider()
    metas = db_df("SELECT * FROM orcamentos WHERE mes_ano=?", (m_ref,))
    if metas.empty: st.info("Nenhuma meta para este mês.")
    for _, r in metas.iterrows():
        real = db_query("SELECT SUM(valor_eur) FROM transacoes WHERE categoria_pai=? AND data LIKE ? AND tipo=?", (r['categoria_pai'], f"{m_ref}%", r['tipo_meta']))[0][0] or 0.0
        p = min(real / r['valor_previsto'], 1.0) if r['valor_previsto'] > 0 else 0.0
        st.write(f"**{r['categoria_pai']}** ({r['tipo_meta']})"); st.progress(p, text=f"€{real:,.2f} / €{r['valor_previsto']:,.2f}")

# --- TAB 6: DASHBOARD E EXCEL (COMPLETA) ---
# --- TAB 6: DASHBOARD DE INTELIGÊNCIA FINANCEIRA (BI EDITION V2) ---
with tab6:
    st.subheader("📊 Business Intelligence: Saúde e Tendências")
    
    # 1. MOTOR DE FILTROS AVANÇADOS (AGORA COM BENEFICIÁRIOS)
    with st.expander("🔍 Filtros Avançados de BI", expanded=False):
        # Carregamento base para os filtros
        df_all = db_df("SELECT * FROM transacoes")
        if df_all.empty:
            st.warning("O banco de dados está vazio. Registre lançamentos para ativar o BI.")
            st.stop()
            
        df_all['dt'] = pd.to_datetime(df_all['data'])
        df_all['beneficiario'] = df_all['beneficiario'].fillna("N/A").replace("", "N/A")
        
        c_an1, c_an2 = st.columns(2)
        c_an3, c_an4 = st.columns(2)
        
        # Filtro 1: Datas (Range)
        min_d = df_all['dt'].min().date()
        max_d = df_all['dt'].max().date()
        data_range = c_an1.date_input("Período de Análise", [min_d, max_d])
        
        # Filtro 2: Contas/Cartões
        f_contas = c_an2.multiselect("Filtrar Contas/Cartões", sorted(df_all['fonte'].unique()))
        
        # Filtro 3: Categorias
        f_cats = c_an3.multiselect("Filtrar Categorias", sorted(df_all['categoria_pai'].unique()))
        
        # Filtro 4: Beneficiários (NOVO)
        f_ben = c_an4.multiselect("Filtrar Beneficiários", sorted(df_all['beneficiario'].unique()))

    # --- PROCESSAMENTO DOS DADOS COM TRAVA DE SEGURANÇA ---
    df_bi = df_all.copy()
    
    # Correção do Erro de Atributo: Uso de .dt.date
    if len(data_range) == 2:
        df_bi = df_bi[(df_bi['dt'].dt.date >= data_range[0]) & (df_bi['dt'].dt.date <= data_range[1])]
    
    if f_contas: df_bi = df_bi[df_bi['fonte'].isin(f_contas)]
    if f_cats:   df_bi = df_bi[df_bi['categoria_pai'].isin(f_cats)]
    if f_ben:    df_bi = df_bi[df_bi['beneficiario'].isin(f_ben)]

    if df_bi.empty:
        st.info("Ajuste os filtros para visualizar a análise. Nenhum dado encontrado para esta seleção.")
    else:
        # 2. KPIs EXECUTIVOS
        st.markdown("---")
        rec_real = df_bi[(df_bi['tipo'] == 'Receita') & (df_bi['status_liquidacao'] == 'RECEBIDO')]['valor_eur'].sum()
        des_real = df_bi[(df_bi['tipo'] == 'Despesa') & (df_bi['status_liquidacao'] == 'PAGO')]['valor_eur'].sum()
        pendente = df_bi[df_bi['status_liquidacao'].isin(['PENDENTE', 'PREVISTO'])]['valor_eur'].sum()
        
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("💰 Receita Realizada", f"€{rec_real:,.2f}")
        k2.metric("💸 Despesa Realizada", f"€{des_real:,.2f}")
        k3.metric("⚠️ Total Comprometido", f"€{pendente:,.2f}")
        balanco = rec_real - des_real
        k4.metric("⚖️ Balanço Líquido", f"€{balanco:,.2f}", delta=f"{((balanco/rec_real)*100 if rec_real > 0 else 0):.1f}% Margem")

        # 3. GRÁFICOS ANALÍTICOS
        st.markdown("---")
        col_g1, col_g2 = st.columns([2, 1])

        with col_g1:
            # FLUXO DE CAIXA NO TEMPO
            df_trend = df_bi.groupby(['dt', 'tipo'])['valor_eur'].sum().unstack(fill_value=0).reset_index()
            fig_trend = px.line(df_trend, x='dt', y=df_trend.columns[1:], 
                                title="Tendência Temporal: Receita vs Despesa",
                                color_discrete_map={'Receita': '#6D7993', 'Despesa': '#96858F'},
                                markers=True, template="simple_white")
            st.plotly_chart(fig_trend, use_container_width=True)

        with col_g2:
            # COMPOSIÇÃO HIERÁRQUICA
            fig_tree = px.treemap(df_bi[df_bi['tipo']=='Despesa'], 
                                  path=['categoria_pai', 'beneficiario'], 
                                  values='valor_eur',
                                  title="Gastos: Categoria > Beneficiário",
                                  color_discrete_sequence=['#6D7993', '#96858F', '#9099A2'])
            st.plotly_chart(fig_tree, use_container_width=True)

        st.markdown("---")
        col_g3, col_g4 = st.columns(2)

        with col_g3:
            # ANÁLISE DE PARETO (RANKING)
            df_pareto = df_bi[df_bi['tipo']=='Despesa'].groupby('beneficiario')['valor_eur'].sum().sort_values(ascending=False).head(10).reset_index()
            fig_pareto = px.bar(df_pareto, x='valor_eur', y='beneficiario', orientation='h',
                                title="Pareto: Top 10 Gastos por Beneficiário",
                                color='valor_eur', color_continuous_scale='Blues')
            fig_pareto.update_layout(yaxis={'categoryorder':'total ascending'})
            st.plotly_chart(fig_pareto, use_container_width=True)

        with col_g4:
            # CONCENTRAÇÃO POR FONTE
            df_src = df_bi.groupby(['fonte', 'tipo'])['valor_eur'].sum().reset_index()
            fig_sun = px.sunburst(df_src, path=['fonte', 'tipo'], values='valor_eur',
                                  title="Onde o dinheiro está circulando?",
                                  color='tipo', color_discrete_map={'Receita': '#6D7993', 'Despesa': '#96858F'})
            st.plotly_chart(fig_sun, use_container_width=True)

    # Botão de Exportação Gerencial
    st.markdown("---")
    if st.button("📊 Gerar Exportação para Auditoria Externa", use_container_width=True):
        m_ref_backup = date.today().strftime("%Y-%m")
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_bi.to_excel(writer, index=False, sheet_name='Dados_Filtrados_BI')
            db_df("SELECT * FROM transacoes").to_excel(writer, index=False, sheet_name='Backup_Completo')
        st.download_button("⬇️ Baixar Dados Analíticos", output.getvalue(), f"BI_Audit_{m_ref_backup}.xlsx")

# --- TAB 7: GESTÃO (TOTALMENTE CORRIGIDA E FUNCIONAL) ---
with tab7:
    st.markdown("#### 🏦 Seção 1 - Contas Bancárias (Fontes)")
    n_font = st.text_input("Nome da Nova Conta")
    if st.button("➕ Adicionar Conta"):
        if n_font: db_execute("INSERT INTO fontes (nome) VALUES (?)", (n_font,)); st.rerun()
    df_f = db_df("SELECT id, nome FROM fontes")
    if not df_f.empty:
        df_f.insert(0, "Remover", False) # Coluna booleana explícita para o checkbox
        ed_f = st.data_editor(df_f, hide_index=True, use_container_width=True, key="ed_font")
        if st.button("🗑️ Excluir Conta Selecionada"):
            for _, r in df_f[ed_f["Remover"] == True].iterrows():
                if not verificar_bloqueio_delecao("fontes", r['id']): db_execute("DELETE FROM fontes WHERE id=?", (r['id'],)); st.rerun()
                else: st.error(f"Bloqueado: Conta {r['nome']} possui lançamentos.")

    st.divider()
    st.markdown("#### 📂 Seção 2 - Categorias")
    c1, c2 = st.columns(2)
    with c1:
        st.caption("Adicionar Categoria Principal")
        tc = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True, key="tc_gest")
        nc = st.text_input("Nome da Categoria Principal")
        if st.button("➕ Adicionar Pai"):
            if nc: db_execute("INSERT INTO categorias (nome, tipo_categoria) VALUES (?,?)", (nc, tc)); st.rerun()
    with c2:
        st.caption("Adicionar Detalhamento (Filho)")
        pais_list = db_query("SELECT id, nome FROM categorias WHERE pai_id IS NULL")
        if pais_list:
            p_sel_g = st.selectbox("Vincular com a Categoria Principal", [p[1] for p in pais_list])
            ns = st.text_input("Nome do Detalhe")
            if st.button("➕ Adicionar Filho"):
                id_p_g = [p[0] for p in pais_list if p[1] == p_sel_g][0]
                db_execute("INSERT INTO categorias (nome, pai_id) VALUES (?,?)", (ns, id_p_g)); st.rerun()

    df_c = db_df("SELECT id, nome, tipo_categoria FROM categorias")
    if not df_c.empty:
        df_c.insert(0, "Remover", False)
        ed_c = st.data_editor(df_c, hide_index=True, use_container_width=True, key="ed_cat")
        if st.button("🗑️ Excluir Categoria Selecionada"):
            for _, r in df_c[ed_c["Remover"] == True].iterrows():
                if not verificar_bloqueio_delecao("categorias", r['id']): db_execute("DELETE FROM categorias WHERE id=?", (r['id'],)); st.rerun()
                else: st.error(f"Bloqueado: Categoria {r['nome']} possui lançamentos.")

    st.divider()
    st.markdown("#### 👤 Seção 3 - Beneficiários")
    nb = st.text_input("Novo Beneficiário")
    if st.button("➕ Adicionar Beneficiário"):
        if nb: db_execute("INSERT OR IGNORE INTO beneficiarios (nome) VALUES (?)", (nb,)); st.rerun()
    df_b = db_df("SELECT id, nome FROM beneficiarios")
    if not df_b.empty:
        df_b.insert(0, "Remover", False)
        ed_b = st.data_editor(df_b, hide_index=True, use_container_width=True, key="ed_ben")
        if st.button("🗑️ Excluir Beneficiário"):
            for _, r in df_b[ed_b["Remover"] == True].iterrows():
                if not verificar_bloqueio_delecao("beneficiarios", r['id']): db_execute("DELETE FROM beneficiarios WHERE id=?", (r['id'],)); st.rerun()

    st.divider()
    st.markdown("#### 👥 Seção 4 - Acesso e Usuários")
    u1, u2, u3 = st.columns(3)
    unome = u1.text_input("Nome de Exibição")
    ulog = u2.text_input("Login")
    usenh = u3.text_input("Senha", type="password")
    if st.button("👤 Criar Novo Usuário", type="primary"):
        if unome and ulog and usenh:
            db_execute("INSERT INTO usuarios (username, password, nome_exibicao) VALUES (?,?,?)", 
                       (ulog, hashlib.sha256(usenh.encode()).hexdigest(), unome)); st.success("Usuário Criado!")

# --- TAB 8: TRANSFERÊNCIAS (IDENTIDADE VISUAL MENTA/AZUL) ---
with tab8:
    st.subheader("🔄 Transferência Entre Bancos")
    
    # Busca contas cadastradas
    res_fontes = db_query("SELECT nome FROM fontes ORDER BY nome")
    fontes_t = [f[0] for f in res_fontes]

    if len(fontes_t) < 2:
        st.error("❗ **Ação Necessária:** Você precisa de pelo menos **2 CONTAS** (ex: Banco e Carteira) para habilitar transferências.")
        st.info("Vá na aba **⚙️ Gestão** para cadastrar suas contas bancárias.")
    else:
        st.markdown('<div class="card">Mova valores entre suas contas mantendo a integridade do saldo geral.</div>', unsafe_allow_html=True)
        
        with st.form("form_transf_final"):
            c1, c2 = st.columns(2)
            c_origem = c1.selectbox("De onde sai o dinheiro?", fontes_t)
            # Destinos excluindo a origem
            c_destino = c2.selectbox("Para onde vai o dinheiro?", [f for f in fontes_t if f != c_origem])
            
            v_col, d_col = st.columns(2)
            valor_transf = v_col.number_input("Valor (€)", min_value=0.01, step=10.0, format="%.2f")
            data_transf = d_col.date_input("Data da Transferência", date.today())
            
            nota_transf = st.text_input("Nota / Observação")
            
            if st.form_submit_button("🔁 EXECUTAR TRANSFERÊNCIA"):
                try:
                    realizar_transferencia(
                        c_origem, 
                        c_destino, 
                        valor_transf, 
                        data_transf.strftime("%Y-%m-%d"), 
                        st.session_state.user, 
                        nota_transf
                    )
                    st.balloons()
                    st.success(f"Transferência de €{valor_transf} concluída com sucesso!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro no processamento: {e}")
