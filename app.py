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
    .stApp { max-width: 100%; margin: 0 auto; background-color: #fcfcfc; }
    .card { background: #ffffff; padding: 18px; border-radius: 12px; border: 1px solid #eaeaea; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 12px; }
    .liquidar-row { background: #ffffff; padding: 12px; border-radius: 8px; border: 1px solid #eee; margin-bottom: 6px; color: #1a1a1a; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; }
    .badge-pendente { background: #fee2e2; color: #991b1b; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 0.75rem; }
    .badge-recebido { background: #d1fae5; color: #065f46; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 0.75rem; }
    .badge-pago { background: #f3f4f6; color: #374151; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 0.75rem; }
    .badge-previsto { background: #fef3c7; color: #92400e; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 0.75rem; }
    @media (max-width: 600px) { .liquidar-row { flex-direction: column; align-items: flex-start; } .stButton>button { width: 100% !important; } }
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
with tab2:
    st.subheader("📋 Auditoria de Lançamentos")
    f_raw = db_df("SELECT * FROM transacoes ORDER BY data DESC")
    if not f_raw.empty:
        f_raw['dt'] = pd.to_datetime(f_raw['data'])
        f_raw['mes'] = f_raw['dt'].dt.strftime('%m/%Y - %B')
        for m in f_raw['mes'].unique():
            with st.expander(f"📅 {m}"):
                for _, r in f_raw[f_raw['mes'] == m].iterrows():
                    c_l, c_b = st.columns([5,1])
                    with c_l:
                        badge = "badge-recebido" if r['status_liquidacao'] == "RECEBIDO" else "badge-pago" if r['status_liquidacao'] == "PAGO" else "badge-pendente"
                        st.markdown(f'<div class="liquidar-row"><span class="{badge}">{r["status_liquidacao"]}</span> {r["dt"].strftime("%d/%m")} | {r["categoria_pai"]} | <b>€{r["valor_eur"]:,.2f}</b><br><small>{r["nota"]}</small></div>', unsafe_allow_html=True)
                    with c_b:
                        if r['status_liquidacao'] == 'PENDENTE':
                            if st.button("✅", key=f"l_{r['id']}"):
                                db_execute("UPDATE transacoes SET status_liquidacao=?, data_liquidacao=? WHERE id=?", 
                                           ("RECEBIDO" if r['tipo']=="Receita" else "PAGO", date.today().strftime("%Y-%m-%d"), r['id']))
                                st.rerun()

# --- TAB 3 E 4: SALDOS E CARTÕES ---
with tab3:
    st.subheader("💰 Patrimônio e Liquidez")
    fnts = [f[0] for f in db_query("SELECT nome FROM fontes ORDER BY nome")]
    tr, tl = 0.0, 0.0
    cols = st.columns(3)
    for i, f in enumerate(fnts):
        sr = calcular_saldo_real(f); sc = calcular_comprometido(f); sl = sr - sc
        tr += sr; tl += sl
        with cols[i%3]: st.markdown(f'<div class="card"><b>🏦 {f}</b><br>Real: €{sr:,.2f}<br>Livre: <b style="color:{"#10b981" if sl>=0 else "#ef4444"};">€{sl:,.2f}</b></div>', unsafe_allow_html=True)
    st.divider(); c_t1, c_t2 = st.columns(2); c_t1.metric("SALDO REAL TOTAL", f"€ {tr:,.2f}"); c_t2.metric("DISPONIBILIDADE REAL", f"€ {tl:,.2f}", delta_color="normal" if tl>=0 else "inverse")
    if tl < 0: st.error("🚨 RISCO DE INSOLVÊNCIA PATRIMONIAL!")

with tab4:
    st.subheader("💳 Gestão de Crédito")
    cts = db_df("SELECT * FROM cartoes ORDER BY nome")
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

# --- TAB 5 E 6: METAS E DASHBOARD (COM PATCH EXCEL) ---
with tab5:
    st.subheader("🎯 Orçamento e Metas")
    m_ref = date.today().strftime("%Y-%m")
    metas = db_df("SELECT * FROM orcamentos WHERE mes_ano=?", (m_ref,))
    for _, r in metas.iterrows():
        real = db_query("SELECT SUM(valor_eur) FROM transacoes WHERE categoria_pai=? AND data LIKE ? AND tipo=?", (r['categoria_pai'], f"{m_ref}%", r['tipo_meta']))[0][0] or 0.0
        p = min(real / r['valor_previsto'], 1.0) if r['valor_previsto'] > 0 else 0.0
        st.write(f"**{r['categoria_pai']}** ({r['tipo_meta']})"); st.progress(p, text=f"€{real:,.2f} / €{r['valor_previsto']:,.2f}")

with tab6:
    st.subheader("📊 Saúde Financeira")
    df_d = db_df("SELECT valor_eur, tipo, categoria_pai FROM transacoes WHERE data LIKE ?", (f"{m_ref}%",))
    if not df_d.empty:
        c1, c2 = st.columns(2)
        with c1: st.plotly_chart(px.pie(df_d[df_d['tipo']=='Despesa'], values='valor_eur', names='categoria_pai', hole=0.4, title="Gastos"), use_container_width=True)
        with c2: st.plotly_chart(px.bar(df_d.groupby('tipo')['valor_eur'].sum().reset_index(), x='tipo', y='valor_eur', color='tipo', title="Balanço"), use_container_width=True)
    
    st.divider()
    if st.button("📊 Gerar Relatório Excel (3 Abas)", use_container_width=True, type="primary"):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            db_df("SELECT * FROM transacoes WHERE data LIKE ?", (f"{m_ref}%",)).to_excel(writer, index=False, sheet_name='Transações')
            db_df("SELECT tipo, categoria_pai, SUM(valor_eur) as Total FROM transacoes WHERE data LIKE ? GROUP BY tipo, categoria_pai", (f"{m_ref}%",)).to_excel(writer, index=False, sheet_name='Resumo')
            db_df("SELECT * FROM orcamentos WHERE mes_ano=?", (m_ref,)).to_excel(writer, index=False, sheet_name='Metas')
        st.download_button("⬇️ Baixar Relatório Completo", output.getvalue(), f"Relatorio_{m_ref}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# --- TAB 7: GESTÃO (FINALIZADA) ---
# --- SUBSTITUIÇÃO OBRIGATÓRIA NA TAB 7 ---
with tab7:
    st.markdown("#### 💱 Seção 0 - Câmbio")
    ntax = st.number_input("Taxa BRL/EUR", value=st.session_state.taxa, format="%.4f")
    if st.button("💾 Salvar Câmbio"):
        db_execute("UPDATE configuracoes SET valor=? WHERE chave='taxa_brl_eur'", (str(ntax),))
        st.session_state.taxa = ntax; st.rerun()

    st.divider(); st.markdown("#### 📂 Seção 1 - Categorias")
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
        p_sel_g = st.selectbox("Vincular ao Pai", [p[1] for p in pais_list])
        ns = st.text_input("Nome do Detalhe")
        if st.button("➕ Adicionar Filho"):
            id_p_g = [p[0] for p in pais_list if p[1] == p_sel_g][0]
            db_execute("INSERT INTO categorias (nome, pai_id) VALUES (?,?)", (ns, id_p_g)); st.rerun()

    dfc = db_df("SELECT id, nome, tipo_categoria FROM categorias")
    edc = st.data_editor(dfc, hide_index=True, use_container_width=True)
    if st.button("🗑️ Remover Categoria Selecionada"):
        for _, r in dfc[edc.iloc[:, 0] == True].iterrows(): # Ajuste se usar checkbox lateral
            if not verificar_bloqueio_delecao("categorias", r['id']): db_execute("DELETE FROM categorias WHERE id=?", (r['id'],)); st.rerun()

    st.divider(); st.markdown("#### 👤 Seção 3 - Beneficiários")
    nb = st.text_input("Novo Beneficiário")
    if st.button("➕ Adicionar Benef."):
        if nb: db_execute("INSERT OR IGNORE INTO beneficiarios (nome) VALUES (?)", (nb,)); st.rerun()
    dfb = db_df("SELECT * FROM beneficiarios")
    edb = st.data_editor(dfb, hide_index=True, use_container_width=True)
    if st.button("🗑️ Remover Benef."):
        for _, r in dfb.iterrows():
            if not verificar_bloqueio_delecao("beneficiarios", r['id']): db_execute("DELETE FROM beneficiarios WHERE id=?", (r['id'],)); st.rerun()

    st.divider(); st.markdown("#### 👥 Seção 4 - Usuários (SHA-256)")
    u1, u2, u3 = st.columns(3)
    unome = u1.text_input("Nome Exibição"); ulog = u2.text_input("Login"); usenh = u3.text_input("Senha", type="password")
    if st.button("👤 Criar Novo Usuário"):
        if unome and ulog and usenh:
            db_execute("INSERT INTO usuarios (username, password, nome_exibicao) VALUES (?,?,?)", 
                       (ulog, hashlib.sha256(usenh.encode()).hexdigest(), unome)); st.success("Usuário Criado!")
# --- TAB 8: TRANSFERÊNCIAS (SOMA ZERO) ---
with tab8:
    st.subheader("🔄 Transferência Soma Zero")
    flist = [f[0] for f in db_query("SELECT nome FROM fontes ORDER BY nome")]
    if len(flist) >= 2:
        with st.form("ft"):
            co = st.selectbox("Origem", flist); cd = st.selectbox("Destino", [f for f in flist if f != co])
            vt = st.number_input("Valor (€)", 0.01)
            if st.form_submit_button("Transferir"):
                realizar_transferencia(co, cd, vt, hoje_iso, st.session_state.user, "Transferência Manual")
                st.success("Concluído!"); st.rerun()
