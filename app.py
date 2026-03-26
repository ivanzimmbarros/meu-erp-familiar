import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import hashlib
import logging
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

# ─────────────────────────────────────────────
#  CONFIGURAÇÃO GLOBAL — DEVE SER A 1ª CHAMADA
# ─────────────────────────────────────────────

st.set_page_config(page_title="FinanceMaster", layout="wide")

# ─────────────────────────────────────────────
#  LOGGING E CONSTANTES
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[AUDITORIA] %(asctime)s | %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)
DB_PATH = 'finance.db'

# ─────────────────────────────────────────────
#  DBMANAGER — ACESSO UNIFICADO AO BANCO
# ─────────────────────────────────────────────
class DBManager:
    @staticmethod
    def get_conn():
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def execute(cls, sql, params=()):
        try:
            with cls.get_conn() as conn:
                conn.execute(sql, params)
                conn.commit()
        except sqlite3.Error as e:
            logging.error(f"DB execute error: {e} | SQL: {sql}")
            raise

    @classmethod
    def execute_many(cls, operations):
        """Executa múltiplas operações SQL numa transação atômica."""
        try:
            with cls.get_conn() as conn:
                for sql, params in operations:
                    conn.execute(sql, params)
                conn.commit()
        except sqlite3.Error as e:
            logging.error(f"DB execute_many error: {e}")
            raise

    @classmethod
    def query(cls, sql, params=()):
        try:
            with cls.get_conn() as conn:
                rows = conn.execute(sql, params).fetchall()
                return [tuple(r) for r in rows]
        except sqlite3.Error as e:
            logging.error(f"DB query error: {e}")
            return []

    @classmethod
    def df(cls, sql, params=()):
        try:
            with cls.get_conn() as conn:
                return pd.read_sql_query(sql, conn, params=list(params))
        except Exception as e:
            logging.error(f"DB df error: {e}")
            return pd.DataFrame()

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

# ─────────────────────────────────────────────
#  SESSION STATE — INICIALIZAÇÃO SEGURA
# ─────────────────────────────────────────────
def init_session():
    defaults = {
        "logged_in": False,
        "user": "",
        "db_connected": True,
        "mes_filtro": datetime.now().month,
        "ano_filtro": datetime.now().year,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session()

# ─────────────────────────────────────────────
#  INICIALIZAÇÃO DO BANCO (TODAS AS TABELAS)
# ─────────────────────────────────────────────
def init_db():
    DBManager.execute('''CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE,
        password TEXT,
        nome_exibicao TEXT)''')

    DBManager.execute('''CREATE TABLE IF NOT EXISTS transacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        data TEXT, categoria_pai TEXT, categoria_filho TEXT,
        beneficiario TEXT, fonte TEXT, valor_eur REAL, tipo TEXT,
        nota TEXT, usuario TEXT,
        forma_pagamento TEXT DEFAULT 'Dinheiro/Débito',
        cartao_id INTEGER, fatura_ref TEXT,
        status_cartao TEXT DEFAULT 'pendente',
        status_liquidacao TEXT DEFAULT 'PAGO',
        data_liquidacao TEXT, parcela_id TEXT,
        parcela_numero INTEGER DEFAULT 1,
        total_parcelas INTEGER DEFAULT 1)''')

    DBManager.execute('''CREATE TABLE IF NOT EXISTS fontes (
        id INTEGER PRIMARY KEY, nome TEXT UNIQUE)''')

    DBManager.execute('''CREATE TABLE IF NOT EXISTS saldos_iniciais (
        fonte TEXT PRIMARY KEY, valor_inicial REAL DEFAULT 0.0)''')

    DBManager.execute('''CREATE TABLE IF NOT EXISTS beneficiarios (
        id INTEGER PRIMARY KEY, nome TEXT UNIQUE)''')

    DBManager.execute('''CREATE TABLE IF NOT EXISTS configuracoes (
        chave TEXT PRIMARY KEY, valor TEXT)''')

    DBManager.execute('''CREATE TABLE IF NOT EXISTS categorias (
        id INTEGER PRIMARY KEY, nome TEXT UNIQUE, pai_id INTEGER,
        FOREIGN KEY(pai_id) REFERENCES categorias(id)
        ON DELETE RESTRICT)''')

    DBManager.execute('''CREATE TABLE IF NOT EXISTS cartoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT UNIQUE NOT NULL,
        limite REAL NOT NULL DEFAULT 0,
        dia_fechamento INTEGER NOT NULL DEFAULT 1,
        dia_vencimento INTEGER NOT NULL DEFAULT 10,
        conta_pagamento TEXT NOT NULL)''')

    DBManager.execute('''CREATE TABLE IF NOT EXISTS orcamentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mes_ano TEXT NOT NULL, categoria_pai TEXT NOT NULL,
        categoria_filho TEXT NOT NULL DEFAULT '',
        beneficiario TEXT NOT NULL DEFAULT '',
        valor_previsto REAL NOT NULL DEFAULT 0,
        tipo_meta TEXT NOT NULL DEFAULT 'Despesa',
        UNIQUE(mes_ano, categoria_pai, categoria_filho,
               beneficiario, tipo_meta))''')

    DBManager.execute('''CREATE TABLE IF NOT EXISTS metas_novo (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        categoria TEXT, valor_meta REAL, mes TEXT)''')

    # Dados padrão
    DBManager.execute(
        "INSERT OR IGNORE INTO usuarios "
        "(username, password, nome_exibicao) VALUES (?,?,?)",
        ("admin", hash_password("123456"), "Administrador"))

    DBManager.execute(
        "INSERT OR IGNORE INTO configuracoes (chave, valor) "
        "VALUES ('taxa_brl_eur', '0.16')")

init_db()

# ─────────────────────────────────────────────
#  FUNÇÕES DE NEGÓCIO
# ─────────────────────────────────────────────
def calcular_saldo_real(fonte_nome):
    """Calcula saldo efetivo (apenas transações PAGAS)."""
    res = DBManager.query("""
        SELECT
            (SELECT COALESCE(valor_inicial,0)
             FROM saldos_iniciais WHERE fonte=?) +
            (SELECT COALESCE(SUM(valor_eur),0)
             FROM transacoes
             WHERE fonte=? AND tipo='Receita'
             AND status_liquidacao='PAGO') -
            (SELECT COALESCE(SUM(valor_eur),0)
             FROM transacoes
             WHERE fonte=? AND tipo='Despesa'
             AND status_liquidacao='PAGO')
    """, (fonte_nome, fonte_nome, fonte_nome))
    return res[0][0] if res and res[0][0] is not None else 0.0

def calcular_parcelas(data_compra_str, dia_fechamento, dia_vencimento,
                      valor_total, total_parcelas):
    """Gera cronograma de parcelas em formato ISO (YYYY-MM-DD)."""
    d = datetime.strptime(data_compra_str, "%Y-%m-%d")
    valor_parcela = round(valor_total / total_parcelas, 2)
    valor_ultima = round(
        valor_total - (valor_parcela * (total_parcelas - 1)), 2)
    mes_offset = 0 if d.day <= dia_fechamento else 1

    parcelas = []
    for i in range(total_parcelas):
        data_venc = d + relativedelta(
            months=mes_offset + i, day=dia_vencimento)
        val = valor_ultima if (i + 1) == total_parcelas else valor_parcela
        parcelas.append((data_venc.strftime("%Y-%m-%d"), val, i + 1))
    return parcelas


def processar_pagamento_fatura(cartao_id, fatura_ref, usuario):
    """Executa pagamento de fatura como transação atômica."""
    rows = DBManager.query("""
        SELECT SUM(valor_eur) FROM transacoes
        WHERE cartao_id=? AND fatura_ref=?
        AND status_cartao='pendente'
    """, (cartao_id, fatura_ref))
    total = rows[0][0] if rows and rows[0][0] else 0.0

    if total <= 0:
        raise ValueError("Fatura já quitada ou inexistente.")

    cartao = DBManager.query(
        "SELECT nome, conta_pagamento FROM cartoes WHERE id=?",
        (cartao_id,))
    if not cartao:
        raise ValueError("Cartão não encontrado.")

    nome_cartao, conta_pgto = cartao[0]
    hoje = datetime.now().strftime("%Y-%m-%d")

    DBManager.execute_many([
        ("""UPDATE transacoes
            SET status_cartao='pago'
            WHERE cartao_id=? AND fatura_ref=?
            AND status_cartao='pendente'""",
         (cartao_id, fatura_ref)),
        ("""INSERT INTO transacoes
            (data, categoria_pai, categoria_filho, beneficiario,
             fonte, valor_eur, tipo, nota, usuario,
             status_liquidacao, data_liquidacao)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
         (hoje, "Cartão de Crédito", "Pagamento de Fatura",
          f"Fatura {nome_cartao}", conta_pgto, total, "Despesa",
          f"Pgto Ref: {fatura_ref}", usuario, "PAGO", hoje))
    ])
    logging.info(f"{usuario} | PAGAMENTO_FATURA | {nome_cartao} | {total}")
    return total


def ajustar_saldo_banco(fonte_nome, valor_banco, usuario):
    """Calcula diferença e registra ajuste como despesa/receita PAGA."""
    saldo_calc = calcular_saldo_real(fonte_nome)
    diff = round(valor_banco - saldo_calc, 4)
    if abs(diff) < 0.005:
        return None

    hoje = datetime.now().strftime("%Y-%m-%d")
    tipo_aj = "Receita" if diff > 0 else "Despesa"
    DBManager.execute("""
        INSERT INTO transacoes
        (data, categoria_pai, valor_eur, tipo, nota,
         fonte, status_liquidacao, usuario)
        VALUES (?,?,?,?,?,?,?,?)""",
        (hoje, "Ajuste de Saldo", abs(diff), tipo_aj,
         f"Ajuste automático diff: {diff:+.4f}",
         fonte_nome, "PAGO", usuario))
    logging.info(f"{usuario} | AJUSTE_SALDO | {fonte_nome} | {diff:+.4f}")


def realizar_transferencia(origem, destino, valor, data_str, usuario, nota):
    """Cria par de transações de transferência com atomicidade."""
    DBManager.execute_many([
        ("""INSERT INTO transacoes
            (data, categoria_pai, beneficiario, fonte,
             valor_eur, tipo, nota, usuario, status_liquidacao)
            VALUES (?,?,?,?,?,?,?,?,?)""",
         (data_str, "Transferência", f"Para {destino}",
          origem, valor, "Despesa", nota, usuario, "PAGO")),
        ("""INSERT INTO transacoes
            (data, categoria_pai, beneficiario, fonte,
             valor_eur, tipo, nota, usuario, status_liquidacao)
            VALUES (?,?,?,?,?,?,?,?,?)""",
         (data_str, "Transferência", f"De {origem}",
          destino, valor, "Receita", nota, usuario, "PAGO"))
    ])
    logging.info(
        f"{usuario} | TRANSFERENCIA | {origem}->{destino} | {valor:.2f}")

# ─────────────────────────────────────────────
#  AUTENTICAÇÃO — TELA DE LOGIN
# ─────────────────────────────────────────────
if not st.session_state.logged_in:
    st.markdown("""
    <style>
      /* Login centralizado e responsivo */
      [data-testid="stSidebar"] {
          min-width: 100% !important;
          max-width: 100% !important;
      }
      [data-testid="stSidebarContent"] {
          padding: 2rem 1.5rem !important;
      }
      .login-title {
          font-size: 1.8rem;
          font-weight: 800;
          color: #ffffff !important;
          margin-bottom: 0.2rem;
      }
      .login-sub {
          font-size: 0.95rem;
          color: #a0a8c0 !important;
          margin-bottom: 1.5rem;
      }
    </style>
    """, unsafe_allow_html=True)

    st.sidebar.markdown(
        '<p class="login-title">💰 FinanceMaster</p>'
        '<p class="login-sub">Controle Financeiro Doméstico</p>',
        unsafe_allow_html=True)

    user_input = st.sidebar.text_input(
        "Usuário", placeholder="Digite seu usuário")
    pw_input = st.sidebar.text_input(
        "Senha", type="password", placeholder="Digite sua senha")

    if st.sidebar.button("Entrar", use_container_width=True):
        if not user_input or not pw_input:
            st.sidebar.error("Preencha usuário e senha.")
        else:
            resultado = DBManager.query(
                "SELECT nome_exibicao FROM usuarios "
                "WHERE username=? AND password=?",
                (user_input, hash_password(pw_input)))
            if resultado:
                st.session_state.logged_in = True
                st.session_state.user = resultado[0][0]
                logging.info(
                    f"LOGIN | {user_input} | "
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")
                st.rerun()
            else:
                st.sidebar.error("Usuário ou senha incorretos.")
                logging.warning(
                    f"LOGIN_FALHOU | {user_input} | "
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M')}")

    st.sidebar.markdown("---")
    st.sidebar.caption("v2.0 · Acesso restrito")
    st.stop()

# ─────────────────────────────────────────────
#  ÁREA LOGADA — CABEÇALHO E FILTRO GLOBAL
# ─────────────────────────────────────────────
col_header, col_logout = st.columns([5, 1])
with col_header:
    st.title(f"Bem-vindo, {st.session_state.user} 👋")
with col_logout:
    if st.button("Sair", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.user = ""
        st.rerun()

# Filtro Global de Mês/Ano (usado em Dashboard e Metas)
st.markdown("#### 📅 Período de Análise")
col_f1, col_f2 = st.columns(2)
mes_sel = col_f1.selectbox(
    "Mês", range(1, 13),
    index=st.session_state.mes_filtro - 1,
    format_func=lambda m: datetime(2000, m, 1).strftime("%B").capitalize(),
    key="mes_global")
ano_sel = col_f2.number_input(
    "Ano", min_value=2020, max_value=2099,
    value=st.session_state.ano_filtro,
    step=1, key="ano_global")

st.session_state.mes_filtro = mes_sel
st.session_state.ano_filtro = int(ano_sel)
filtro_mes_ano = f"{int(ano_sel)}-{mes_sel:02d}"

st.divider()

# ─────────────────────────────────────────────
#  ESTRUTURA DE ABAS PRINCIPAL
# ─────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Dashboard",
    "➕ Lançamentos",
    "📋 Relatórios",
    "💳 Cartões",
    "⚙️ Configurações"
])

# ─────────────────────────────────────────────
#  TAB 1 — DASHBOARD
# ─────────────────────────────────────────────
with tab1:
    # 1. Cards de Saldo por Conta
    st.subheader("💰 Resumo do Saldo Atual")
    fontes = [f[0] for f in DBManager.query("SELECT nome FROM fontes")]

    if fontes:
        cols = st.columns(len(fontes))
        for i, fonte in enumerate(fontes):
            saldo = calcular_saldo_real(fonte)
            delta_color = "normal" if saldo >= 0 else "inverse"
            cols[i].metric(
                label=fonte,
                value=f"€ {saldo:,.2f}",
                delta=None,
                delta_color=delta_color)
    else:
        st.info("Nenhuma conta cadastrada. Adicione em ⚙️ Configurações.")

    st.divider()

    # 2. Análise Financeira (Gráficos)
    st.subheader("📈 Análise Financeira")
    df_all = DBManager.df(
        "SELECT * FROM transacoes WHERE status_liquidacao='PAGO'")

    if not df_all.empty:
        df_all['data'] = pd.to_datetime(df_all['data'], errors='coerce')

        c1, c2 = st.columns(2)

        # Gráfico de Rosca — Despesas por Categoria
        df_desp = df_all[df_all['tipo'] == 'Despesa']
        if not df_desp.empty:
            fig_pie = px.pie(
                df_desp, values='valor_eur', names='categoria_pai',
                hole=0.4, title="Despesas por Categoria",
                color_discrete_sequence=px.colors.sequential.Blues_r)
            fig_pie.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#1a1a2e')
            c1.plotly_chart(fig_pie, use_container_width=True)
        else:
            c1.info("Sem despesas registadas.")

        # Gráfico de Barras — Receita vs Despesa mensal
        df_mensal = (
            df_all
            .groupby([df_all['data'].dt.to_period('M'), 'tipo'])['valor_eur']
            .sum()
            .unstack(fill_value=0)
            .reset_index())
        df_mensal['data'] = df_mensal['data'].astype(str)

        if not df_mensal.empty:
            fig_bar = px.bar(
                df_mensal, x='data',
                y=[c for c in df_mensal.columns if c != 'data'],
                barmode='group',
                title="Evolução Mensal (Receita × Despesa)",
                color_discrete_map={
                    'Receita': '#27ae60', 'Despesa': '#e74c3c'},
                labels={'value': '€', 'data': 'Mês'})
            fig_bar.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#1a1a2e')
            c2.plotly_chart(fig_bar, use_container_width=True)
        else:
            c2.info("Dados insuficientes para o gráfico.")
    else:
        st.info("Nenhuma transação PAGA registada ainda.")

    st.divider()

    # 3. Metas de Economia (filtradas pelo mês selecionado)
    st.subheader("🎯 Metas de Economia")
    metas = DBManager.query(
        "SELECT categoria, valor_meta FROM metas_novo WHERE mes=?",
        (filtro_mes_ano,))

    if metas:
        df_desp_mes = DBManager.df(
            "SELECT categoria_pai, SUM(valor_eur) as total "
            "FROM transacoes "
            "WHERE tipo='Despesa' AND status_liquidacao='PAGO' "
            "AND data LIKE ? "
            "GROUP BY categoria_pai",
            (f"{filtro_mes_ano}%",))

        gasto_por_cat = {}
        if not df_desp_mes.empty:
            gasto_por_cat = dict(
                zip(df_desp_mes['categoria_pai'], df_desp_mes['total']))

        for categoria, alvo in metas:
            gasto = gasto_por_cat.get(categoria, 0.0)
            progresso = min(gasto / alvo, 1.0) if alvo > 0 else 0.0
            cor = "🟢" if progresso < 0.75 else ("🟡" if progresso < 1.0
                                                  else "🔴")
            col_m1, col_m2 = st.columns([1, 3])
            col_m1.write(f"{cor} **{categoria}**")
            col_m2.progress(
                progresso,
                text=f"€ {gasto:,.2f} de € {alvo:,.2f}")
    else:
        st.info(f"Sem metas definidas para {filtro_mes_ano}.")

# ─────────────────────────────────────────────
#  TAB 2 — LANÇAMENTOS
# ─────────────────────────────────────────────
with tab2:
    st.subheader("➕ Novo Lançamento")
    fontes_list = [f[0] for f in DBManager.query("SELECT nome FROM fontes")]
    cats_pai = [c[0] for c in DBManager.query(
        "SELECT nome FROM categorias WHERE pai_id IS NULL")]
    if not cats_pai:
        cats_pai = ["Alimentação","Moradia","Transporte","Lazer",
                    "Salário","Outros"]

    with st.form("form_lancamento", clear_on_submit=True):
        c1, c2 = st.columns(2)
        data_lanc = c1.date_input("Data", date.today())
        valor_lanc = c2.number_input("Valor (€)", min_value=0.01,
                                     format="%.2f")
        tipo_lanc = st.radio("Tipo", ["Despesa", "Receita"],
                             horizontal=True)
        fonte_lanc = st.selectbox("Fonte / Conta", fontes_list
                                  if fontes_list else ["— sem contas —"])

        cat_pai_sel = st.selectbox("Categoria Pai", cats_pai)
        cats_filho = [c[0] for c in DBManager.query(
            "SELECT c.nome FROM categorias c "
            "INNER JOIN categorias p ON c.pai_id=p.id "
            "WHERE p.nome=?", (cat_pai_sel,))] or ["Geral"]
        cat_filho_sel = st.selectbox("Categoria Filho", cats_filho)
        beneficiario_lanc = st.text_input("Beneficiário (opcional)")
        num_parcelas = st.number_input(
            "Número de Parcelas", min_value=1, max_value=48, value=1)
        status_lanc = st.selectbox(
            "Status", ["PAGO", "PENDENTE"])
        nota_lanc = st.text_input("Nota / Descrição")

        submitted = st.form_submit_button(
            "✅ Confirmar Lançamento", use_container_width=True)

    if submitted:
        if not fontes_list:
            st.error("Cadastre ao menos uma conta em ⚙️ Configurações.")
        else:
            try:
                if num_parcelas == 1:
                    DBManager.execute("""
                        INSERT INTO transacoes
                        (data, valor_eur, tipo, fonte, categoria_pai,
                         categoria_filho, beneficiario, nota, usuario,
                         status_liquidacao)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (data_lanc.strftime("%Y-%m-%d"), valor_lanc,
                         tipo_lanc, fonte_lanc, cat_pai_sel,
                         cat_filho_sel, beneficiario_lanc,
                         nota_lanc, st.session_state.user, status_lanc))
                else:
                    parcelas = calcular_parcelas(
                        data_lanc.strftime("%Y-%m-%d"),
                        25, data_lanc.day, valor_lanc, num_parcelas)
                    ops = []
                    for p_data, p_val, p_num in parcelas:
                        ops.append(("""
                            INSERT INTO transacoes
                            (data, valor_eur, tipo, fonte, categoria_pai,
                             categoria_filho, beneficiario, nota, usuario,
                             status_liquidacao, parcela_numero,
                             total_parcelas)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (p_data, p_val, tipo_lanc, fonte_lanc,
                             cat_pai_sel, cat_filho_sel, beneficiario_lanc,
                             f"{nota_lanc} ({p_num}/{num_parcelas})",
                             st.session_state.user, "PENDENTE",
                             p_num, num_parcelas)))
                    DBManager.execute_many(ops)

                logging.info(
                    f"{st.session_state.user} | LANCAMENTO | "
                    f"{tipo_lanc} | € {valor_lanc:.2f}")
                st.success("✅ Lançamento(s) registado(s) com sucesso!")
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao registar lançamento: {e}")

    # Histórico Recente
    st.divider()
    st.subheader("🕒 Histórico Recente")
    df_hist = DBManager.df("""
        SELECT data, tipo, categoria_pai, categoria_filho,
               fonte, valor_eur, status_liquidacao, nota
        FROM transacoes
        ORDER BY data DESC, id DESC
        LIMIT 20""")
    if not df_hist.empty:
        df_hist.columns = ["Data","Tipo","Cat. Pai","Cat. Filho",
                           "Conta","Valor (€)","Status","Nota"]
        st.dataframe(df_hist, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma transação registada ainda.")

# ─────────────────────────────────────────────
#  TAB 3 — RELATÓRIOS
# ─────────────────────────────────────────────
with tab3:
    st.subheader("📋 Filtrar Transações")
    col_r1, col_r2, col_r3 = st.columns(3)
    r_inicio = col_r1.date_input("Data Início",
                                  date(int(ano_sel), mes_sel, 1))
    r_fim = col_r2.date_input("Data Fim", date.today())
    r_tipo = col_r3.selectbox("Tipo", ["Todos","Despesa","Receita"])

    if st.button("🔍 Carregar Relatório", use_container_width=True):
        params_r = [r_inicio.strftime("%Y-%m-%d"),
                    r_fim.strftime("%Y-%m-%d")]
        sql_r = """SELECT data, tipo, categoria_pai, categoria_filho,
                          beneficiario, fonte, valor_eur,
                          status_liquidacao, nota
                   FROM transacoes
                   WHERE data BETWEEN ? AND ?"""
        if r_tipo != "Todos":
            sql_r += " AND tipo=?"
            params_r.append(r_tipo)
        sql_r += " ORDER BY data DESC"
        df_rel = DBManager.df(sql_r, tuple(params_r))
        if not df_rel.empty:
            df_rel.columns = ["Data","Tipo","Cat. Pai","Cat. Filho",
                              "Beneficiário","Conta","Valor (€)",
                              "Status","Nota"]
            st.dataframe(df_rel, use_container_width=True,
                         hide_index=True)
            csv = df_rel.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Exportar CSV", csv,
                               f"relatorio_{filtro_mes_ano}.csv",
                               "text/csv", use_container_width=True)
        else:
            st.info("Nenhuma transação encontrada para o período.")

    st.divider()
    st.subheader("🔄 Transferência entre Contas")
    fontes_transf = [f[0] for f in DBManager.query(
        "SELECT nome FROM fontes")]
    if len(fontes_transf) >= 2:
        t_sub = False
        with st.form("form_transferencia", clear_on_submit=True):
            t_origem = st.selectbox("Origem", fontes_transf)
            destinos = [f for f in fontes_transf if f != t_origem]
            t_destino = st.selectbox("Destino", destinos)
            t_valor = st.number_input("Valor (€)", min_value=0.01,
                                      format="%.2f")
            t_data = st.date_input("Data", date.today())
            t_nota = st.text_input("Nota")
            t_sub = st.form_submit_button("↔️ Transferir",
                                          use_container_width=True)
        if t_sub:
            try:
                realizar_transferencia(
                    t_origem, t_destino, t_valor,
                    t_data.strftime("%Y-%m-%d"),
                    st.session_state.user, t_nota)
                st.success("✅ Transferência realizada com sucesso!")
                st.rerun()
            except Exception as e:
                st.error(f"Erro na transferência: {e}")
    else:
        st.info("Cadastre ao menos duas contas para transferir.")

# ─────────────────────────────────────────────
#  TAB 4 — CARTÕES DE CRÉDITO
# ─────────────────────────────────────────────
with tab4:
    st.subheader("💳 Gestão de Cartões de Crédito")
    cartoes = DBManager.query(
        "SELECT id, nome, limite, conta_pagamento, "
        "dia_vencimento FROM cartoes")

    if cartoes:
        for id_c, nome_c, limite_c, conta_c, venc_c in cartoes:
            fatura_rows = DBManager.query(
                "SELECT COALESCE(SUM(valor_eur),0) FROM transacoes "
                "WHERE cartao_id=? AND status_liquidacao='PENDENTE'",
                (id_c,))
            valor_fat = fatura_rows[0][0] if fatura_rows else 0.0
            lim_disp = limite_c - valor_fat

            with st.container(border=True):
                cc1, cc2, cc3 = st.columns(3)
                cc1.metric("Cartão", nome_c)
                cc2.metric("Fatura Atual", f"€ {valor_fat:,.2f}")
                cc3.metric("Limite Disp.", f"€ {lim_disp:,.2f}")
                st.caption(
                    f"Conta: {conta_c} · Vencimento: dia {venc_c}")
                if valor_fat > 0:
                    if st.button(f"💳 Pagar Fatura — {nome_c}",
                                 key=f"pay_{id_c}",
                                 use_container_width=True):
                        try:
                            fatura_ref = datetime.now().strftime("%Y-%m")
                            total_pago = processar_pagamento_fatura(
                                id_c, fatura_ref, st.session_state.user)
                            st.success(
                                f"✅ Fatura {fatura_ref} paga: "
                                f"€ {total_pago:,.2f}")
                            st.rerun()
                        except ValueError as e:
                            st.error(str(e))
                else:
                    st.success("✅ Fatura quitada.")
    else:
        st.info("Nenhum cartão cadastrado.")

    st.divider()
    with st.expander("➕ Cadastrar Novo Cartão"):
        with st.form("form_cartao_novo", clear_on_submit=True):
            nc_nome = st.text_input("Nome do Cartão")
            nc_limite = st.number_input("Limite Total (€)", min_value=0.0,
                                        format="%.2f")
            nc_conta = st.text_input("Conta para Pagamento")
            nc_fech = st.number_input("Dia Fechamento",
                                      min_value=1, max_value=31, value=25)
            nc_venc = st.number_input("Dia Vencimento",
                                      min_value=1, max_value=31, value=10)
            if st.form_submit_button("💾 Salvar Cartão",
                                     use_container_width=True):
                if nc_nome and nc_conta:
                    DBManager.execute(
                        "INSERT OR IGNORE INTO cartoes "
                        "(nome, limite, conta_pagamento, "
                        "dia_fechamento, dia_vencimento) "
                        "VALUES (?,?,?,?,?)",
                        (nc_nome, nc_limite, nc_conta,
                         nc_fech, nc_venc))
                    st.success(f"Cartão '{nc_nome}' cadastrado!")
                    st.rerun()
                else:
                    st.error("Nome e conta são obrigatórios.")

# ─────────────────────────────────────────────
#  TAB 5 — CONFIGURAÇÕES
# ─────────────────────────────────────────────
with tab5:
    st.subheader("⚙️ Configurações do Sistema")

    # 1. GESTÃO DE CONTAS (FONTES)
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("### 🏦 Contas")
        with st.form("form_fonte", clear_on_submit=True):
            nome_fonte = st.text_input("Nome da Conta")
            saldo_init = st.number_input("Saldo Inicial (€)",
                                         value=0.0, format="%.2f")
            if st.form_submit_button("➕ Adicionar Conta",
                                     use_container_width=True):
                if nome_fonte.strip():
                    DBManager.execute(
                        "INSERT OR IGNORE INTO fontes (nome) VALUES (?)",
                        (nome_fonte.strip(),))
                    DBManager.execute(
                        "INSERT OR IGNORE INTO saldos_iniciais "
                        "(fonte, valor_inicial) VALUES (?,?)",
                        (nome_fonte.strip(), saldo_init))
                    st.success(f"Conta '{nome_fonte}' adicionada!")
                    st.rerun()
                else:
                    st.error("Nome da conta não pode ser vazio.")

        st.markdown("**Contas cadastradas:**")
        fontes_cfg = DBManager.query("SELECT nome FROM fontes")
        for (f_nome,) in fontes_cfg:
            col_fn, col_fd = st.columns([3, 1])
            col_fn.write(f_nome)
            if col_fd.button("🗑️", key=f"del_fonte_{f_nome}",
                             use_container_width=True):
                DBManager.execute(
                    "DELETE FROM fontes WHERE nome=?", (f_nome,))
                DBManager.execute(
                    "DELETE FROM saldos_iniciais WHERE fonte=?",
                    (f_nome,))
                st.rerun()

    # 2. GESTÃO DE CATEGORIAS
    with col_b:
        st.markdown("### 📂 Categorias")
        with st.expander("➕ Nova Categoria Pai"):
            nome_pai = st.text_input("Nome da Categoria Pai",
                                     key="inp_cat_pai")
            if st.button("Criar Pai", key="btn_cat_pai",
                         use_container_width=True):
                if nome_pai.strip():
                    DBManager.execute(
                        "INSERT OR IGNORE INTO categorias "
                        "(nome, pai_id) VALUES (?,NULL)",
                        (nome_pai.strip(),))
                    st.rerun()

        with st.expander("➕ Nova Categoria Filho"):
            pais = DBManager.query(
                "SELECT id, nome FROM categorias WHERE pai_id IS NULL")
            if pais:
                pai_dict = {nome: pid for pid, nome in pais}
                nome_filho = st.text_input("Nome da Categoria Filho",
                                           key="inp_cat_filho")
                escolha_pai = st.selectbox(
                    "Categoria Pai", list(pai_dict.keys()),
                    key="sel_cat_pai")
                if st.button("Criar Filho", key="btn_cat_filho",
                             use_container_width=True):
                    if nome_filho.strip():
                        DBManager.execute(
                            "INSERT OR IGNORE INTO categorias "
                            "(nome, pai_id) VALUES (?,?)",
                            (nome_filho.strip(), pai_dict[escolha_pai]))
                        st.rerun()
            else:
                st.info("Crie primeiro uma Categoria Pai.")

        st.markdown("**Categorias cadastradas:**")
        cats_all = DBManager.query(
            "SELECT c.id, c.nome, p.nome FROM categorias c "
            "LEFT JOIN categorias p ON c.pai_id=p.id "
            "ORDER BY CASE WHEN p.nome IS NULL THEN 0 ELSE 1 END, p.nome, c.nome")
        for c_id, c_nome, c_pai_nome in cats_all:
            label = f"{c_nome}" if not c_pai_nome \
                else f"  ↳ {c_nome} ({c_pai_nome})"
            col_cl, col_cd = st.columns([3, 1])
            col_cl.write(label)
            if col_cd.button("🗑️", key=f"del_cat_{c_id}",
                             use_container_width=True):
                DBManager.execute(
                    "DELETE FROM categorias WHERE id=?", (c_id,))
                st.rerun()

    st.divider()

    # 3. AJUSTE DE SALDO MANUAL
    st.markdown("### 🛠️ Ajuste de Saldo Manual")
    with st.form("form_ajuste", clear_on_submit=True):
        fontes_aj = [f[0] for f in DBManager.query(
            "SELECT nome FROM fontes")]
        conta_aj = st.selectbox("Conta", fontes_aj
                                if fontes_aj else ["— sem contas —"])
        novo_saldo = st.number_input("Saldo Real no Banco (€)",
                                     value=0.0, format="%.2f")
        if st.form_submit_button("🔄 Sincronizar Saldo",
                                 use_container_width=True):
            if fontes_aj:
                ajustar_saldo_banco(
                    conta_aj, novo_saldo, st.session_state.user)
                st.success("Saldo sincronizado com sucesso!")
                st.rerun()

    st.divider()

    # 4. METAS DE ECONOMIA
    st.markdown("### 🎯 Metas de Economia")
    with st.form("form_meta", clear_on_submit=True):
        cats_meta = [c[0] for c in DBManager.query(
            "SELECT nome FROM categorias WHERE pai_id IS NULL")]
        if not cats_meta:
            cats_meta = ["Alimentação","Moradia","Transporte",
                         "Lazer","Outros"]
        cat_meta = st.selectbox("Categoria", cats_meta)
        valor_meta = st.number_input("Meta Mensal (€)",
                                     min_value=0.0, format="%.2f")
        if st.form_submit_button("💾 Definir Meta",
                                 use_container_width=True):
            DBManager.execute(
                "INSERT OR REPLACE INTO metas_novo "
                "(categoria, valor_meta, mes) VALUES (?,?,?)",
                (cat_meta, valor_meta, filtro_mes_ano))
            st.success(f"Meta definida para {filtro_mes_ano}!")
            st.rerun()

    st.divider()

    # 5. AUDITORIA E MANUTENÇÃO
    st.markdown("### 📋 Auditoria (Últimos 20 registos)")
    try:
        with open("app.log", "r") as f:
            logs = f.readlines()[-20:]
        st.code("".join(logs), language="text")
    except FileNotFoundError:
        st.info("Nenhum log encontrado.")

    st.markdown("### ⚠️ Manutenção")
    col_mc, col_md = st.columns(2)
    with col_mc:
        if st.button("🔄 Limpar Cache", use_container_width=True):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.session_state["cache_limpo"] = True
            st.rerun()
        if st.session_state.get("cache_limpo"):
            st.success("✅ Cache limpo com sucesso!")
            st.session_state["cache_limpo"] = False

    with col_md:
        if st.button("💣 Resetar Banco de Dados",
                     use_container_width=True,
                     type="primary"):
            st.session_state["confirmar_reset"] = True

        if st.session_state.get("confirmar_reset"):
            st.warning("⚠️ Tem a certeza? Esta acção é irreversível.")
            col_sim, col_nao = st.columns(2)
            with col_sim:
                if st.button("✅ Sim, resetar", key="btn_sim_reset",
                             use_container_width=True):
                    DBManager.execute("DELETE FROM transacoes")
                    DBManager.execute("DELETE FROM fontes")
                    DBManager.execute("DELETE FROM saldos_iniciais")
                    DBManager.execute("DELETE FROM metas_novo")
                    st.session_state["confirmar_reset"] = False
                    st.session_state["reset_feito"] = True
                    st.rerun()
            with col_nao:
                if st.button("❌ Cancelar", key="btn_nao_reset",
                             use_container_width=True):
                    st.session_state["confirmar_reset"] = False
                    st.rerun()

        if st.session_state.get("reset_feito"):
            st.success("✅ Banco de dados resetado com sucesso.")
            st.session_state["reset_feito"] = False
