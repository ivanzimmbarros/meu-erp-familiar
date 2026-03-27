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

st.markdown("""
<style>
    /* 1. FUNDO UNIFICADO - CONCEITO "SAND & STONE" */
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stSidebar"] {
        background-color: #DDD0C8 !important;
        color: #323232 !important;
    }

    /* 2. SIDEBAR E NAVEGAÇÃO */
    [data-testid="stSidebar"] {
        border-right: 1px solid rgba(50, 50, 50, 0.1);
        background-color: #d6c7be !important; /* Leve variação para profundidade */
    }

    /* 3. ABAS (TABS) MINIMALISTAS */
    .stTabs [data-baseweb="tab-list"] {
        background-color: transparent;
        border-bottom: 2px solid #323232;
        gap: 0px;
    }

    .stTabs [data-baseweb="tab"] {
        height: 60px;
        background-color: transparent;
        color: #323232 !important;
        font-family: 'Helvetica Neue', sans-serif;
        font-weight: 400;
        letter-spacing: 1px;
        text-transform: uppercase;
        border: none !important;
    }

    .stTabs [aria-selected="true"] {
        background-color: #323232 !important;
        color: #DDD0C8 !important;
        border-radius: 0px !important;
    }

    /* 4. CARDS E LINHAS (CLEAN LOOK) */
    .card, .liquidar-row {
        background-color: rgba(255, 255, 255, 0.4) !important; /* Branco translúcido sobre o bege */
        border: 1px solid rgba(50, 50, 50, 0.1) !important;
        border-radius: 0px !important; /* Bordas retas para estilo premium */
        color: #323232 !important;
        padding: 20px;
        margin-bottom: 15px;
        box-shadow: none !important;
    }

    /* 5. INPUTS E CAMPOS DE TEXTO */
    div[data-baseweb="input"], div[data-baseweb="select"], .stNumberInput input {
        background-color: #fcfcfc !important;
        color: #323232 !important;
        border: 1px solid #323232 !important;
        border-radius: 0px !important;
        font-size: 1rem !important;
    }

    /* 6. BOTÕES (WELLS STYLE - "SHOP NOW") */
    .stButton>button {
        background-color: #323232 !important;
        color: #DDD0C8 !important;
        font-weight: 400 !important;
        letter-spacing: 2px;
        text-transform: uppercase;
        border: none !important;
        border-radius: 50px !important; /* Botão pílula como na imagem */
        padding: 10px 30px !important;
        transition: 0.4s ease;
    }

    .stButton>button:hover {
        background-color: #4a4a4a !important;
        transform: translateY(-2px);
    }

    /* 7. TIPOGRAFIA GERAL */
    h1, h2, h3, h4, h5, h6 {
        color: #323232 !important;
        font-family: 'Times New Roman', serif; /* Serif para títulos como no Wells */
        font-weight: 300 !important;
        letter-spacing: -1px;
    }

    p, label, .stMarkdown {
        color: #323232 !important;
        font-family: 'Inter', sans-serif;
        font-weight: 400;
    }

    /* Badges de Status (Earthy Tones) */
    .badge-recebido { background: #323232 !important; color: #DDD0C8 !important; padding: 4px 12px; border-radius: 0px; font-weight: bold; }
    .badge-pendente { background: #b04a4a !important; color: white !important; padding: 4px 12px; border-radius: 0px; }
    
    /* Remove a barra branca superior do Streamlit */
    header {visibility: hidden;}
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

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs(["➕ Lançar", "📋 Histórico", "💰 Saldos", "💳 Cartões", "🎯 Metas", "📊 Dash", "⚙️ Gestão", "🔄 Transf"])

# --- TAB 1: NOVO LANÇAMENTO ---
with tab1:
    st.subheader("➕ Registro de Movimentação")
    c_t1, c_t2 = st.columns(2)
    tipo_sel = c_t1.radio("Tipo", ["Despesa", "Receita"], horizontal=True, key="t_reg")
    forma_sel = c_t2.radio("Forma", ["Dinheiro/Débito", "Cartão de Crédito"], horizontal=True)
    pais = db_query("SELECT id, nome FROM categorias WHERE pai_id IS NULL AND tipo_categoria=?", (tipo_sel,))
    pai_sel = st.selectbox("Categoria", [p[1] for p in pais], key=f"p_{tipo_sel}")
    id_p = next((p[0] for p in pais if p[1] == pai_sel), None)
    filhos = db_query("SELECT nome FROM categorias WHERE pai_id=?", (id_p,)) if id_p else []
    filho_sel = st.selectbox("Subcategoria", ["Geral"] + [f[0] for f in filhos])
    with st.form("f_novo", clear_on_submit=True):
        f_data = db_query("SELECT nome FROM cartoes") if forma_sel == "Cartão de Crédito" else db_query("SELECT nome FROM fontes")
        fonte_sel = st.selectbox("Conta/Cartão", [f[0] for f in f_data])
        col_v, col_p = st.columns(2)
        data_in = col_v.date_input("Data", date.today())
        valor_in = col_v.number_input("Valor (€)", min_value=0.01, format="%.2f")
        parc_in = col_p.number_input("Parcelas", 1, 48, 1)
        benef_list = [b[0] for b in db_query("SELECT nome FROM beneficiarios ORDER BY nome")]
        benef_sel = st.selectbox("Beneficiário", [""] + benef_list)
        nota_in = st.text_input("Observação")
        if st.form_submit_button("Salvar Registro", use_container_width=True, type="primary"):
            try:
                is_cc = (forma_sel == "Cartão de Crédito")
                c_inf = db_query("SELECT id, dia_fechamento, dia_vencimento FROM cartoes WHERE nome=?", (fonte_sel,))[0] if is_cc else (None, 0, 0)
                parcs = calcular_parcelas(data_in.strftime("%Y-%m-%d"), c_inf[1], c_inf[2], valor_in, parc_in, is_cc)
                ops = []
                for i, (p_d, p_v, p_n) in enumerate(parcs):
                    st_liq = determinar_status_operacao(tipo_sel, i==0)
                    f_ref = calcular_fatura_ref(p_d, c_inf[1]) if is_cc else None
                    ops.append(("INSERT INTO transacoes (data, categoria_pai, categoria_filho, beneficiario, fonte, valor_eur, tipo, nota, usuario, forma_pagamento, cartao_id, fatura_ref, status_liquidacao) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (p_d, pai_sel, filho_sel, benef_sel, fonte_sel, p_v, tipo_sel, f"{nota_in} ({p_n}/{parc_in})" if parc_in>1 else nota_in, st.session_state.user, forma_sel, c_inf[0], f_ref, st_liq)))
                db_execute_many(ops); st.success("Registrado!"); st.rerun()
            except Exception as e: st.error(f"Erro: {e}")

# --- TAB 2: HISTÓRICO ---
# --- TAB 2: HISTÓRICO (TOTALMENTE RESTAURADA) ---
with tab2:
    st.subheader("📋 Histórico e Auditoria")

    # 1. Filtros Superiores
    c_f1, c_f2, c_f3 = st.columns([1, 1, 2])
    f_tipo = c_f1.selectbox("Tipo", ["Todos", "Despesa", "Receita"], key="f_tipo")
    fontes_disp = [f[0] for f in db_query("SELECT nome FROM fontes")]
    f_fonte = c_f2.selectbox("Conta/Fonte", ["Todas"] + fontes_disp)
    f_busca = c_f3.text_input("🔍 Buscar", placeholder="Nota, Categoria ou Beneficiário...")

    df_raw = db_df("SELECT * FROM transacoes ORDER BY data DESC, id DESC")
    
    if not df_raw.empty:
        # Aplicação dos Filtros
        if f_tipo != "Todos": df_raw = df_raw[df_raw['tipo'] == f_tipo]
        if f_fonte != "Todas": df_raw = df_raw[df_raw['fonte'] == f_fonte]
        if f_busca: 
            mask = df_raw.apply(lambda r: f_busca.lower() in str(r).lower(), axis=1)
            df_raw = df_raw[mask]

        if not df_raw.empty:
            df_raw['dt'] = pd.to_datetime(df_raw['data'])
            df_raw['mes'] = df_raw['dt'].dt.strftime('%m/%Y - %B')
            meses = df_raw['mes'].unique()

            st.markdown("---")
            # 2. Agrupamento Temporal (Mês/Ano)
            for m in meses:
                with st.expander(f"📅 {m}", expanded=(m == meses[0])):
                    itens = df_raw[df_raw['mes'] == m]
                    for _, r in itens.iterrows():
                        c_l, c_b = st.columns([5, 1])
                        with c_l:
                            st_map = {"RECEBIDO": "badge-recebido", "PAGO": "badge-pago", "PENDENTE": "badge-pendente", "PREVISTO": "badge-previsto"}
                            badge = st_map.get(r['status_liquidacao'], "badge-pendente")
                            st.markdown(f'<div class="liquidar-row"><span class="{badge}">{r["status_liquidacao"]}</span> <b>{r["dt"].strftime("%d/%m")}</b> | {r["categoria_pai"]} | <b>€{r["valor_eur"]:,.2f}</b><br><small>{r["fonte"]} ➔ {r["beneficiario"] or "N/A"} | {r["nota"]}</small></div>', unsafe_allow_html=True)
                        with c_b:
                            if r['status_liquidacao'] in ['PENDENTE', 'PREVISTO']:
                                if st.button("✅", key=f"liq_{r['id']}"):
                                    status_novo = "RECEBIDO" if r['tipo'] == "Receita" else "PAGO"
                                    db_execute("UPDATE transacoes SET status_liquidacao=?, data_liquidacao=? WHERE id=?", (status_novo, date.today().strftime("%Y-%m-%d"), r['id']))
                                    st.rerun()

            # 3. Tabela Geral de Auditoria e Remoção
            st.markdown("---")
            st.caption("🛠️ Edição e Remoção em Massa")
            df_ed = df_raw.copy()
            df_ed.insert(0, "Remover", False)
            sel_cols = ["Remover", "id", "data", "categoria_pai", "valor_eur", "tipo", "status_liquidacao", "nota"]
            editor = st.data_editor(df_ed[sel_cols], hide_index=True, use_container_width=True, key=f"ed_hist_{st.session_state.ver}")
            
            if st.button("🗑️ Confirmar Remoção Selecionados", type="secondary"):
                ids_rm = df_ed[editor["Remover"] == True]["id"].tolist()
                if ids_rm:
                    ph = ",".join(["?"] * len(ids_rm))
                    db_execute(f"DELETE FROM transacoes WHERE id IN ({ph})", tuple(ids_rm))
                    if 'ver' in st.session_state: st.session_state.ver += 1
                    st.rerun()
        else:
            st.info("Nenhum lançamento encontrado para os filtros aplicados.")
    else:
        st.info("Nenhum lançamento registrado no sistema.")

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
with tab6:
    st.subheader("📊 Saúde Financeira")
    m_ref_dash = st.selectbox("Mês de Referência", m_ref_list, key="m_ref_dash")
    df_d = db_df("SELECT valor_eur, tipo, categoria_pai FROM transacoes WHERE data LIKE ?", (f"{m_ref_dash}%",))
    
    if df_d.empty: st.info("Lance transações para visualizar os gráficos do mês.")
    else:
        c1, c2 = st.columns(2)
        with c1: 
            df_pie = df_d[df_d['tipo']=='Despesa']
            if not df_pie.empty: st.plotly_chart(px.pie(df_pie, values='valor_eur', names='categoria_pai', hole=0.4, title="Gastos por Categoria"), use_container_width=True)
        with c2: 
            st.plotly_chart(px.bar(df_d.groupby('tipo')['valor_eur'].sum().reset_index(), x='tipo', y='valor_eur', color='tipo', title="Balanço Receita x Despesa"), use_container_width=True)
    
    st.divider()
    if st.button("📊 Gerar Relatório Excel (3 Abas)", use_container_width=True, type="primary"):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            db_df("SELECT * FROM transacoes WHERE data LIKE ?", (f"{m_ref_dash}%",)).to_excel(writer, index=False, sheet_name='Transações')
            db_df("SELECT tipo, categoria_pai, SUM(valor_eur) as Total FROM transacoes WHERE data LIKE ? GROUP BY tipo, categoria_pai", (f"{m_ref_dash}%",)).to_excel(writer, index=False, sheet_name='Resumo')
            db_df("SELECT * FROM orcamentos WHERE mes_ano=?", (m_ref_dash,)).to_excel(writer, index=False, sheet_name='Metas')
        st.download_button("⬇️ Baixar Relatório", output.getvalue(), f"Relatorio_{m_ref_dash}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

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
        nc = st.text_input("Nome da Categoria Pai")
        if st.button("➕ Adicionar Pai"):
            if nc: db_execute("INSERT INTO categorias (nome, tipo_categoria) VALUES (?,?)", (nc, tc)); st.rerun()
    with c2:
        st.caption("Adicionar Detalhamento (Filho)")
        pais_list = db_query("SELECT id, nome FROM categorias WHERE pai_id IS NULL")
        if pais_list:
            p_sel_g = st.selectbox("Vincular ao Pai", [p[1] for p in pais_list])
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
    st.markdown("<h2 style='color:#0FFCBE;'>🔄 Transferência Soma Zero</h2>", unsafe_allow_html=True)
    
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
