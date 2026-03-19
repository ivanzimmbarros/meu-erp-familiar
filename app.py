import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import io
import logging
from datetime import datetime

# ─────────────────────────────────────────────
#  AUDITORIA — log para terminal
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[AUDITORIA] %(asctime)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

def log_audit(acao, detalhes, usuario="sistema"):
    logging.info(f"{usuario} | {acao} | {detalhes}")


# ─────────────────────────────────────────────
#  CONFIGURAÇÃO GLOBAL
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="ERP Familiar",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main { background-color: #f8fafc; }
    h1, h2, h3 { font-family: 'Georgia', serif; }

    .saldo-card {
        border-radius: 16px;
        padding: 24px 28px;
        margin-bottom: 16px;
        box-shadow: 0 2px 12px rgba(0,0,0,0.08);
        background: white;
        border-left: 6px solid #e2e8f0;
    }
    .saldo-card h3 {
        margin: 0 0 6px 0; font-size: 1rem; color: #64748b;
        font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;
    }
    .saldo-card .valor-positivo { font-size: 2rem; font-weight: 800; color: #16a34a; }
    .saldo-card .valor-negativo { font-size: 2rem; font-weight: 800; color: #dc2626; }
    .saldo-card .valor-neutro   { font-size: 2rem; font-weight: 800; color: #f59e0b; }
    .saldo-card .detalhe { font-size: 0.8rem; color: #94a3b8; margin-top: 4px; }
    .saldo-card-positivo { border-left-color: #16a34a; }
    .saldo-card-negativo { border-left-color: #dc2626; }
    .saldo-card-cartao   { border-left-color: #8b5cf6; background: #faf5ff; }
    .saldo-card-meta     { border-left-color: #f59e0b; background: #fffbeb; }

    .secao-titulo { font-size: 1.1rem; font-weight: 700; color: #1e293b; padding: 8px 0 4px 0; }
    .secao-sub    { font-size: 0.85rem; color: #64748b; margin-bottom: 16px; }

    .aviso-bloqueio {
        background: #fff7ed; border: 1px solid #fed7aa;
        border-radius: 10px; padding: 14px 18px; margin-bottom: 8px;
        color: #9a3412; font-size: 0.9rem;
    }
    .fatura-aberta  { background: #fff7ed; border: 1px solid #fdba74; border-radius: 12px; padding: 18px 22px; margin-bottom: 12px; }
    .fatura-fechada { background: #f0fdf4; border: 1px solid #86efac; border-radius: 12px; padding: 18px 22px; margin-bottom: 12px; }

    /* Dashboard semáforo */
    .gauge-verde    { background: #dcfce7; border-left: 5px solid #16a34a; border-radius: 10px; padding: 14px 18px; margin-bottom: 10px; }
    .gauge-amarelo  { background: #fef9c3; border-left: 5px solid #ca8a04; border-radius: 10px; padding: 14px 18px; margin-bottom: 10px; }
    .gauge-vermelho { background: #fee2e2; border-left: 5px solid #dc2626; border-radius: 10px; padding: 14px 18px; margin-bottom: 10px; }
    .gauge-titulo   { font-weight: 700; font-size: 0.95rem; color: #1e293b; }
    .gauge-sub      { font-size: 0.8rem; color: #64748b; margin-top: 2px; }

    .top-benef-card {
        background: white; border-radius: 12px; padding: 14px 18px;
        margin-bottom: 8px; box-shadow: 0 1px 6px rgba(0,0,0,0.07);
        display: flex; justify-content: space-between; align-items: center;
    }

    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
#  ESTADO DA SESSÃO
# ─────────────────────────────────────────────
def init_session():
    defaults = {
        'ver': 0,
        'logado': False,
        'display_name': None,
        'taxa_brl_eur': 0.16,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()


# ─────────────────────────────────────────────
#  HELPERS DE BANCO
# ─────────────────────────────────────────────
DB_PATH = 'finance.db'

def db_query(sql, params=()):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()

def db_execute(sql, params=()):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def db_execute_many(sqls_params):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        for sql, params in sqls_params:
            conn.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def db_df(sql, params=()):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


# ─────────────────────────────────────────────
#  INICIALIZAÇÃO / MIGRAÇÃO DO BANCO
#  ⚠️ Não altere esta função — lógica de migração
#     automática de colunas já validada.
# ─────────────────────────────────────────────
def init_db():
    TRANSACOES_COLUNAS = [
        ("id",              "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("data",            "TEXT"),
        ("categoria_pai",   "TEXT"),
        ("categoria_filho", "TEXT"),
        ("beneficiario",    "TEXT"),
        ("fonte",           "TEXT"),
        ("valor_eur",       "REAL"),
        ("tipo",            "TEXT"),
        ("nota",            "TEXT"),
        ("usuario",         "TEXT"),
        ("forma_pagamento", "TEXT DEFAULT 'Dinheiro/Débito'"),
        ("cartao_id",       "INTEGER"),
        ("fatura_ref",      "TEXT"),
        ("status_cartao",   "TEXT DEFAULT 'pendente'"),
    ]

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS usuarios
                     (id INTEGER PRIMARY KEY, username TEXT UNIQUE,
                      password TEXT, nome_exibicao TEXT)''')
        c.execute("CREATE TABLE IF NOT EXISTS fontes "
                  "(id INTEGER PRIMARY KEY, nome TEXT UNIQUE)")
        c.execute("CREATE TABLE IF NOT EXISTS saldos_iniciais "
                  "(fonte TEXT PRIMARY KEY, valor_inicial REAL DEFAULT 0.0)")
        c.execute("CREATE TABLE IF NOT EXISTS beneficiarios "
                  "(id INTEGER PRIMARY KEY, nome TEXT UNIQUE)")
        c.execute('''CREATE TABLE IF NOT EXISTS configuracoes
                     (chave TEXT PRIMARY KEY, valor TEXT)''')
        c.execute("INSERT OR IGNORE INTO configuracoes (chave, valor) "
                  "VALUES ('taxa_brl_eur', '0.16')")

        # categorias hierárquicas
        c.execute("SELECT name FROM sqlite_master "
                  "WHERE type='table' AND name='categorias'")
        if c.fetchone():
            c.execute("PRAGMA table_info(categorias)")
            cols_cat = [col[1] for col in c.fetchall()]
            if 'pai_id' not in cols_cat:
                c.execute("ALTER TABLE categorias RENAME TO categorias_old")
                c.execute('''CREATE TABLE categorias
                             (id INTEGER PRIMARY KEY, nome TEXT UNIQUE,
                              pai_id INTEGER,
                              FOREIGN KEY(pai_id) REFERENCES categorias(id)
                                ON DELETE RESTRICT)''')
                c.execute("INSERT INTO categorias (nome, pai_id) "
                          "SELECT nome, NULL FROM categorias_old")
                c.execute("DROP TABLE categorias_old")
        else:
            c.execute('''CREATE TABLE IF NOT EXISTS categorias
                         (id INTEGER PRIMARY KEY, nome TEXT UNIQUE,
                          pai_id INTEGER,
                          FOREIGN KEY(pai_id) REFERENCES categorias(id)
                            ON DELETE RESTRICT)''')

        # cartões
        c.execute('''CREATE TABLE IF NOT EXISTS cartoes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            nome            TEXT UNIQUE NOT NULL,
            limite          REAL NOT NULL DEFAULT 0,
            dia_fechamento  INTEGER NOT NULL DEFAULT 1,
            dia_vencimento  INTEGER NOT NULL DEFAULT 10,
            conta_pagamento TEXT NOT NULL
        )''')

        # ── NOVA TABELA: orcamentos ─────────────────────────────────────
        # categoria_filho e beneficiario usam '' (string vazia) quando não
        # especificados — garante que UNIQUE funciona correctamente no SQLite
        # (NULL != NULL impediria a deduplicação).
        c.execute('''CREATE TABLE IF NOT EXISTS orcamentos (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            mes_ano          TEXT NOT NULL,
            categoria_pai    TEXT NOT NULL,
            categoria_filho  TEXT NOT NULL DEFAULT '',
            beneficiario     TEXT NOT NULL DEFAULT '',
            valor_previsto   REAL NOT NULL DEFAULT 0,
            UNIQUE(mes_ano, categoria_pai, categoria_filho, beneficiario)
        )''')

        # transacoes + migração de colunas
        c.execute('''CREATE TABLE IF NOT EXISTS transacoes
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      data TEXT, categoria_pai TEXT, categoria_filho TEXT,
                      beneficiario TEXT, fonte TEXT,
                      valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT)''')

        c.execute("PRAGMA table_info(transacoes)")
        cols_existentes = {row[1] for row in c.fetchall()}
        for col_nome, col_def in TRANSACOES_COLUNAS:
            if col_nome == "id":
                continue
            if col_nome not in cols_existentes:
                c.execute(
                    f"ALTER TABLE transacoes ADD COLUMN {col_nome} {col_def}"
                )

        c.execute("INSERT OR IGNORE INTO usuarios "
                  "(username, password, nome_exibicao) VALUES (?,?,?)",
                  ("admin", hash_password("123456"), "Administrador"))
        conn.commit()
    finally:
        conn.close()


init_db()

_taxa_salva = db_query("SELECT valor FROM configuracoes WHERE chave='taxa_brl_eur'")
if _taxa_salva:
    st.session_state['taxa_brl_eur'] = float(_taxa_salva[0][0])


# ─────────────────────────────────────────────
#  FUNÇÕES DE NEGÓCIO — CARTÃO DE CRÉDITO
# ─────────────────────────────────────────────
def calcular_fatura_ref(data_str, dia_fechamento):
    try:
        d = datetime.strptime(data_str, "%d/%m/%Y")
    except Exception:
        d = datetime.now()
    if d.day > dia_fechamento:
        if d.month == 12:
            return f"{d.year + 1:04d}-01"
        return f"{d.year:04d}-{d.month + 1:02d}"
    return f"{d.year:04d}-{d.month:02d}"

def calcular_total_fatura(cartao_id, fatura_ref):
    r = db_query(
        "SELECT SUM(valor_eur) FROM transacoes "
        "WHERE cartao_id=? AND fatura_ref=? AND status_cartao='pendente'",
        (cartao_id, fatura_ref))
    return (r[0][0] or 0.0) if r else 0.0

def calcular_limite_usado(cartao_id):
    r = db_query(
        "SELECT SUM(valor_eur) FROM transacoes "
        "WHERE cartao_id=? AND status_cartao='pendente'",
        (cartao_id,))
    return (r[0][0] or 0.0) if r else 0.0

def calcular_saldo_conta(fonte_nome):
    ini_r = db_query("SELECT valor_inicial FROM saldos_iniciais WHERE fonte=?", (fonte_nome,))
    ini   = ini_r[0][0] if ini_r else 0.0
    rec_r = db_query(
        "SELECT SUM(valor_eur) FROM transacoes "
        "WHERE fonte=? AND tipo='Receita' "
        "AND (forma_pagamento='Dinheiro/Débito' OR forma_pagamento IS NULL)",
        (fonte_nome,))
    rec = (rec_r[0][0] or 0.0) if rec_r else 0.0
    des_r = db_query(
        "SELECT SUM(valor_eur) FROM transacoes "
        "WHERE fonte=? AND tipo='Despesa' "
        "AND (forma_pagamento='Dinheiro/Débito' OR forma_pagamento IS NULL)",
        (fonte_nome,))
    des = (des_r[0][0] or 0.0) if des_r else 0.0
    return ini + rec - des

def calcular_patrimonio_liquido(fonte_nome):
    saldo = calcular_saldo_conta(fonte_nome)
    passivo_r = db_query(
        "SELECT SUM(t.valor_eur) FROM transacoes t "
        "JOIN cartoes c ON t.cartao_id = c.id "
        "WHERE c.conta_pagamento=? AND t.status_cartao='pendente'",
        (fonte_nome,))
    passivo = (passivo_r[0][0] or 0.0) if passivo_r else 0.0
    return saldo - passivo

def pagar_fatura(cartao_id, fatura_ref, usuario):
    total = calcular_total_fatura(cartao_id, fatura_ref)
    if total <= 0:
        raise ValueError("Fatura já paga ou vazia")
    cartao = db_query("SELECT nome, conta_pagamento FROM cartoes WHERE id=?", (cartao_id,))
    if not cartao:
        raise ValueError("Cartão não encontrado")
    nome_cartao, conta_pag = cartao[0]
    hoje = datetime.now().strftime("%d/%m/%Y")
    db_execute_many([
        ("UPDATE transacoes SET status_cartao='pago' "
         "WHERE cartao_id=? AND fatura_ref=? AND status_cartao='pendente'",
         (cartao_id, fatura_ref)),
        ("INSERT INTO transacoes "
         "(data, categoria_pai, categoria_filho, beneficiario, fonte, "
         "valor_eur, tipo, nota, usuario, forma_pagamento, status_cartao) "
         "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
         (hoje, "Cartão de Crédito", "Pagamento de Fatura",
          f"Fatura {nome_cartao} — {fatura_ref}",
          conta_pag, total, "Despesa",
          f"Pagamento da fatura {nome_cartao} referência {fatura_ref}",
          usuario, "Dinheiro/Débito", "pago")),
    ])
    return total


# ─────────────────────────────────────────────
#  FUNÇÕES DE NEGÓCIO — ORÇAMENTO / DASHBOARD
# ─────────────────────────────────────────────
def get_realizado_mes(mes_ano, categoria_pai=None, categoria_filho=None, taxa=None):
    """
    Soma todas as DESPESAS de um mês (regime de competência):
    inclui dinheiro/débito E cartão de crédito pendente.
    mes_ano = 'YYYY-MM'
    """
    if taxa is None:
        taxa = st.session_state.get('taxa_brl_eur', 0.16)
    ano, mes = mes_ano.split("-")

    params = [mes, ano]
    filtros = ["tipo='Despesa'",
               "substr(data,4,2)=?",
               "substr(data,7,4)=?"]

    if categoria_pai:
        filtros.append("categoria_pai=?")
        params.append(categoria_pai)
    if categoria_filho and categoria_filho != "":
        filtros.append("categoria_filho=?")
        params.append(categoria_filho)

    sql = ("SELECT COALESCE(SUM(valor_eur),0) FROM transacoes WHERE "
           + " AND ".join(filtros))
    r = db_query(sql, tuple(params))
    return (r[0][0] or 0.0) if r else 0.0


def get_top_beneficiarios(mes_ano, n=3):
    """Top N beneficiários por despesa no mês (regime competência)."""
    ano, mes = mes_ano.split("-")
    return db_query(
        """SELECT beneficiario, COALESCE(SUM(valor_eur),0) as total
           FROM transacoes
           WHERE tipo='Despesa'
             AND substr(data,4,2)=? AND substr(data,7,4)=?
             AND beneficiario IS NOT NULL AND beneficiario != ''
           GROUP BY beneficiario
           ORDER BY total DESC
           LIMIT ?""",
        (mes, ano, n)
    )


def get_saude_orcamento(mes_ano):
    """
    Retorna lista de dicts com saúde de cada meta do mês.
    status: 'verde' (<80%), 'amarelo' (80–100%), 'vermelho' (>100%)
    """
    metas = db_query(
        "SELECT categoria_pai, categoria_filho, beneficiario, valor_previsto "
        "FROM orcamentos WHERE mes_ano=? ORDER BY categoria_pai, categoria_filho",
        (mes_ano,)
    )
    resultado = []
    for cat_pai, cat_filho, benef, previsto in metas:
        realizado = get_realizado_mes(
            mes_ano,
            categoria_pai=cat_pai,
            categoria_filho=cat_filho if cat_filho else None
        )
        pct = (realizado / previsto * 100) if previsto > 0 else 0.0
        if pct < 80:
            status = "verde"
        elif pct <= 100:
            status = "amarelo"
        else:
            status = "vermelho"
        resultado.append({
            "cat_pai":    cat_pai,
            "cat_filho":  cat_filho,
            "beneficiario": benef,
            "previsto":   previsto,
            "realizado":  realizado,
            "pct":        pct,
            "status":     status,
        })
    return resultado


# ─────────────────────────────────────────────
#  LOGIN
# ─────────────────────────────────────────────
if not st.session_state.logado:
    col_l, col_c, col_r = st.columns([1, 1.4, 1])
    with col_c:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("## 🏠 ERP Familiar")
        st.markdown("##### Controle financeiro da sua família")
        st.divider()
        u = st.text_input("👤 Usuário", placeholder="Digite seu usuário")
        p = st.text_input("🔑 Senha", type="password", placeholder="Digite sua senha")
        if st.button("Entrar →", use_container_width=True, type="primary"):
            row = db_query(
                "SELECT nome_exibicao FROM usuarios WHERE username=? AND password=?",
                (u, hash_password(p))
            )
            if row:
                st.session_state.update({'logado': True, 'display_name': row[0][0]})
                st.rerun()
            else:
                st.error("❌ Usuário ou senha incorretos.")
    st.stop()


# ─────────────────────────────────────────────
#  BARRA LATERAL
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"### 👋 Olá, {st.session_state.display_name}!")
    st.caption(f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    st.divider()
    st.markdown("**Navegação rápida**")
    st.markdown("➕ **Lançar** → Registrar despesa ou receita")
    st.markdown("📋 **Lançamentos** → Ver e apagar registros")
    st.markdown("💰 **Saldos** → Ver dinheiro disponível")
    st.markdown("💳 **Cartões** → Faturas e pagamentos")
    st.markdown("🎯 **Metas** → Planejamento de orçamento")
    st.markdown("📊 **Dashboard** → Saúde financeira")
    st.markdown("⚙️ **Gestão** → Categorias e contas")
    st.divider()
    taxa_atual = st.session_state['taxa_brl_eur']
    st.caption(f"💱 Taxa BRL → EUR: **{taxa_atual:.4f}**")
    st.divider()
    if st.button("🚪 Sair da conta", use_container_width=True):
        st.session_state.clear()
        st.rerun()


# ─────────────────────────────────────────────
#  ABAS PRINCIPAIS  (7 abas)
# ─────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "➕  Novo Lançamento",
    "📋  Lançamentos",
    "💰  Saldos",
    "💳  Cartões",
    "🎯  Metas",
    "📊  Dashboard",
    "⚙️  Gestão",
])


# ══════════════════════════════════════════════
#  TAB 1 — NOVO LANÇAMENTO
# ══════════════════════════════════════════════
with tab1:
    st.markdown("## ➕ Registrar uma Movimentação")
    st.caption("Registre aqui qualquer entrada ou saída de dinheiro da sua família.")
    st.divider()

    cat_df       = db_df("SELECT id, nome, pai_id FROM categorias")
    pai_opts     = cat_df[cat_df['pai_id'].isna()]['nome'].tolist()
    fontes_row   = db_query("SELECT nome FROM fontes")
    fontes_lista = [r[0] for r in fontes_row] if fontes_row else ["Padrão"]
    benef_row    = db_query("SELECT nome FROM beneficiarios")
    benef_opts   = [r[0] for r in benef_row] if benef_row else ["Não especificado"]
    cartoes_row  = db_query("SELECT id, nome FROM cartoes ORDER BY nome")

    sem_categorias = len(pai_opts) == 0
    if sem_categorias:
        st.markdown("""
        <div class="aviso-bloqueio">
        ⚠️ <strong>Nenhuma categoria cadastrada.</strong>
        Vá até a aba <strong>⚙️ Gestão → Seção 1</strong> e adicione ao menos uma
        Categoria Principal antes de lançar uma transação.
        </div>
        """, unsafe_allow_html=True)

    taxa_cambio = st.session_state['taxa_brl_eur']

    with st.form(key=f"f_lanca_{st.session_state.ver}", clear_on_submit=True):
        col_tp1, col_tp2 = st.columns(2)
        with col_tp1:
            tipo = st.radio("**Tipo de movimentação**",
                            ["💸 Despesa", "💵 Receita"], horizontal=True)
            tipo_val = "Despesa" if "Despesa" in tipo else "Receita"
        with col_tp2:
            forma_opts = ["Dinheiro/Débito"]
            if cartoes_row:
                forma_opts.append("Cartão de Crédito")
            forma_pag = st.radio(
                "**Forma de pagamento**", forma_opts, horizontal=True,
                help="Crédito: contabiliza no orçamento agora, débito só no vencimento.")

        cartao_sel_id = None
        cartao_sel_nome = None
        if forma_pag == "Cartão de Crédito" and tipo_val == "Despesa":
            cartao_nomes = [r[1] for r in cartoes_row]
            cartao_sel_nome = st.selectbox("💳 Qual cartão?", cartao_nomes)
            cartao_sel_id   = next(r[0] for r in cartoes_row if r[1] == cartao_sel_nome)
        elif forma_pag == "Cartão de Crédito" and tipo_val == "Receita":
            st.info("ℹ️ Receitas são sempre lançadas em conta bancária.")
            forma_pag = "Dinheiro/Débito"

        st.markdown("---")
        col1, col2, col3 = st.columns([2, 1.2, 1.5])
        with col1:
            val = st.number_input("**Valor**", min_value=0.0, step=0.01, format="%.2f")
        with col2:
            moeda = st.selectbox("**Moeda**", ["EUR", "BRL"],
                                 help=f"BRL → EUR (taxa: {taxa_cambio:.4f})")
        with col3:
            data_lancamento = st.date_input("**Data**", value=datetime.now())

        st.markdown("---")
        col4, col5 = st.columns(2)

        with col4:
            st.markdown("**📂 Categoria**")
            if pai_opts:
                sel_pai = st.selectbox("Tipo de gasto/recebimento", pai_opts,
                                       label_visibility="collapsed")
                pid = int(cat_df[cat_df['nome'] == sel_pai]['id'].iloc[0])
                filhos = cat_df[cat_df['pai_id'] == pid]['nome'].tolist()
                sel_filho = st.selectbox("Detalhamento (opcional)",
                                         filhos if filhos else ["Geral"])
            else:
                st.warning("Sem categorias — cadastre na aba Gestão.")
                sel_pai   = "Sem categoria"
                sel_filho = "Geral"

        with col5:
            if forma_pag == "Dinheiro/Débito":
                st.markdown("**🏦 De onde vem / Para onde vai?**")
                fonte = st.selectbox("Conta ou carteira", fontes_lista,
                                     label_visibility="collapsed")
            else:
                fonte = cartao_sel_nome if cartao_sel_nome else "Cartão"
                st.markdown(f"**💳 Cartão:** {fonte}")
                if cartao_sel_id:
                    usado  = calcular_limite_usado(cartao_sel_id)
                    lim_r  = db_query("SELECT limite FROM cartoes WHERE id=?", (cartao_sel_id,))
                    if lim_r:
                        disp = lim_r[0][0] - usado
                        cor  = "#16a34a" if disp >= 0 else "#dc2626"
                        st.markdown(
                            f"<span style='color:{cor};font-size:0.9rem;'>"
                            f"Disponível: €{disp:,.2f} (usado: €{usado:,.2f})</span>",
                            unsafe_allow_html=True)
            beneficiario = st.selectbox("Beneficiário", benef_opts)

        nota = st.text_input("📝 Observação (opcional)",
                             placeholder="Ex: Supermercado do mês, Salário de março...")

        submitted = st.form_submit_button(
            "✅ Salvar Lançamento", use_container_width=True,
            type="primary", disabled=sem_categorias)

        if submitted:
            if val == 0:
                st.error("O valor não pode ser zero.")
            else:
                v_eur    = val * taxa_cambio if moeda == "BRL" else val
                data_str = data_lancamento.strftime("%d/%m/%Y")
                if forma_pag == "Cartão de Crédito" and cartao_sel_id:
                    dia_fech = db_query(
                        "SELECT dia_fechamento FROM cartoes WHERE id=?",
                        (cartao_sel_id,))[0][0]
                    fatura_ref = calcular_fatura_ref(data_str, dia_fech)
                    db_execute(
                        """INSERT INTO transacoes
                           (data,categoria_pai,categoria_filho,beneficiario,
                            fonte,valor_eur,tipo,nota,usuario,
                            forma_pagamento,cartao_id,fatura_ref,status_cartao)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (data_str, sel_pai, sel_filho, beneficiario,
                         cartao_sel_nome, v_eur, tipo_val, nota,
                         st.session_state.display_name,
                         "Cartão de Crédito", cartao_sel_id, fatura_ref, "pendente"))
                    st.session_state.ver += 1
                    st.success(f"✅ €{v_eur:.2f} no cartão **{cartao_sel_nome}** — fatura {fatura_ref}.")
                    st.rerun()
                else:
                    db_execute(
                        """INSERT INTO transacoes
                           (data,categoria_pai,categoria_filho,beneficiario,
                            fonte,valor_eur,tipo,nota,usuario,forma_pagamento)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (data_str, sel_pai, sel_filho, beneficiario,
                         fonte, v_eur, tipo_val, nota,
                         st.session_state.display_name, "Dinheiro/Débito"))
                    st.session_state.ver += 1
                    st.rerun()


# ══════════════════════════════════════════════
#  TAB 2 — TODOS OS LANÇAMENTOS
# ══════════════════════════════════════════════
with tab2:
    st.markdown("## 📋 Histórico de Lançamentos")
    st.caption("Visualize, filtre, exporte ou remova registros.")
    st.divider()

    fontes_row2  = db_query("SELECT nome FROM fontes")
    cartoes_row2 = db_query("SELECT nome FROM cartoes")
    todas_fontes = (["Todas"] + [r[0] for r in fontes_row2]
                    + [r[0] for r in cartoes_row2])

    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    with col_f1:
        filtro_tipo  = st.selectbox("Tipo", ["Todos","Despesa","Receita"])
    with col_f2:
        filtro_fonte = st.selectbox("Conta/Cartão", todas_fontes)
    with col_f3:
        filtro_forma = st.selectbox("Forma", ["Todas","Dinheiro/Débito","Cartão de Crédito"])
    with col_f4:
        filtro_busca = st.text_input("🔍 Buscar", placeholder="Nota, categoria...")

    df_hist = db_df("SELECT * FROM transacoes ORDER BY id DESC")

    if not df_hist.empty:
        if filtro_tipo  != "Todos":  df_hist = df_hist[df_hist['tipo'] == filtro_tipo]
        if filtro_fonte != "Todas":  df_hist = df_hist[df_hist['fonte'] == filtro_fonte]
        if filtro_forma != "Todas":  df_hist = df_hist[df_hist['forma_pagamento'] == filtro_forma]
        if filtro_busca:
            mask = (df_hist['nota'].str.contains(filtro_busca, case=False, na=False) |
                    df_hist['categoria_pai'].str.contains(filtro_busca, case=False, na=False) |
                    df_hist['categoria_filho'].str.contains(filtro_busca, case=False, na=False))
            df_hist = df_hist[mask]

    st.caption(f"📌 {len(df_hist)} registro(s)")

    if not df_hist.empty:
        col_exp1, col_exp2, _ = st.columns([1, 1, 4])
        csv_bytes = df_hist.to_csv(index=False).encode('utf-8-sig')
        col_exp1.download_button("⬇️ CSV", csv_bytes,
            f"lancamentos_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            "text/csv", use_container_width=True)
        excel_buf = io.BytesIO()
        with pd.ExcelWriter(excel_buf, engine='openpyxl') as w:
            df_hist.to_excel(w, index=False, sheet_name='Lançamentos')
        col_exp2.download_button("⬇️ Excel", excel_buf.getvalue(),
            f"lancamentos_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True)

    st.markdown("---")

    if not df_hist.empty:
        df_edit = df_hist.copy()
        df_edit.insert(0, "Remover", False)
        df_display = df_edit.rename(columns={
            'id':'ID','data':'Data','categoria_pai':'Categoria',
            'categoria_filho':'Detalhamento','beneficiario':'Beneficiário',
            'fonte':'Conta/Cartão','valor_eur':'Valor (€)','tipo':'Tipo',
            'nota':'Observação','usuario':'Registrado por',
            'forma_pagamento':'Forma Pag.','fatura_ref':'Fatura','status_cartao':'Status'})
        editor = st.data_editor(
            df_display, key=f"ed_{st.session_state.ver}",
            use_container_width=True,
            column_config={"Remover": st.column_config.CheckboxColumn("🗑️"),
                           "Valor (€)": st.column_config.NumberColumn(format="€ %.2f")})
        if st.button("🗑️ Confirmar Remoção", type="secondary", key="rm_trans"):
            ids_rm = editor[editor["Remover"] == True]["ID"].tolist()
            if not ids_rm:
                st.warning("Marque pelo menos um registro.")
            else:
                ph = ",".join(["?"] * len(ids_rm))
                db_execute(f"DELETE FROM transacoes WHERE id IN ({ph})", tuple(ids_rm))
                st.session_state.ver += 1
                st.success(f"{len(ids_rm)} removido(s).")
                st.rerun()
    else:
        st.info("Nenhum lançamento encontrado com os filtros aplicados.")


# ══════════════════════════════════════════════
#  TAB 3 — SALDOS
# ══════════════════════════════════════════════
with tab3:
    st.markdown("## 💰 Saldos por Conta")
    st.caption("Saldo em Conta = débito/dinheiro. Patrimônio = Saldo − faturas pendentes.")
    st.divider()

    fontes_saldo = [r[0] for r in db_query("SELECT nome FROM fontes")]

    if not fontes_saldo:
        st.info("💡 Vá até ⚙️ Gestão para cadastrar suas contas bancárias.")
    else:
        total_saldo = 0.0
        total_pl    = 0.0
        cols_saldo  = st.columns(min(len(fontes_saldo), 3))

        for i, f in enumerate(fontes_saldo):
            saldo   = calcular_saldo_conta(f)
            pl      = calcular_patrimonio_liquido(f)
            total_saldo += saldo
            total_pl    += pl

            passivo_r = db_query(
                "SELECT SUM(t.valor_eur) FROM transacoes t "
                "JOIN cartoes c ON t.cartao_id=c.id "
                "WHERE c.conta_pagamento=? AND t.status_cartao='pendente'", (f,))
            passivo = (passivo_r[0][0] or 0.0) if passivo_r else 0.0

            classe_s  = "saldo-card-positivo" if saldo >= 0 else "saldo-card-negativo"
            classe_vs = "valor-positivo"       if saldo >= 0 else "valor-negativo"
            sinal_s   = "+" if saldo > 0 else ""
            classe_pl = "valor-positivo"       if pl >= 0    else "valor-negativo"
            sinal_pl  = "+" if pl > 0 else ""

            ini_r   = db_query("SELECT valor_inicial FROM saldos_iniciais WHERE fonte=?", (f,))
            ini     = ini_r[0][0] if ini_r else 0.0
            ini_txt = f"&nbsp;|&nbsp; Inicial: €{ini:,.2f}" if ini != 0 else ""

            rec_v = db_query("SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo='Receita' AND (forma_pagamento='Dinheiro/Débito' OR forma_pagamento IS NULL)", (f,))[0][0] or 0.0
            des_v = db_query("SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo='Despesa' AND (forma_pagamento='Dinheiro/Débito' OR forma_pagamento IS NULL)", (f,))[0][0] or 0.0

            with cols_saldo[i % 3]:
                st.markdown(f"""
                <div class="saldo-card {classe_s}">
                    <h3>🏦 {f}</h3>
                    <div class="{classe_vs}">{sinal_s}€ {saldo:,.2f}</div>
                    <div class="detalhe">
                        Entradas: €{rec_v:,.2f} &nbsp;|&nbsp; Saídas: €{des_v:,.2f}{ini_txt}
                    </div>
                    {"<div class='detalhe' style='color:#ef4444;margin-top:6px;'>⚠️ Crédito pendente: −€" + f"{passivo:,.2f}</div>" if passivo > 0 else ""}
                    {"<div style='margin-top:8px;font-size:0.85rem;'>PL: <strong class='" + classe_pl + "'>" + sinal_pl + "€ " + f"{pl:,.2f}</strong></div>" if passivo > 0 else ""}
                </div>""", unsafe_allow_html=True)

        st.divider()
        col_tot1, col_tot2 = st.columns(2)
        with col_tot1:
            cls_ts = "valor-positivo" if total_saldo >= 0 else "valor-negativo"
            s_ts   = "+" if total_saldo > 0 else ""
            st.markdown(f"""<div class="saldo-card" style="background:#1e293b;border-left-color:#3b82f6;">
                <h3 style="color:#94a3b8;">🏦 SALDO TOTAL EM CONTA</h3>
                <div class="{cls_ts}" style="font-size:2rem;">{s_ts}€ {total_saldo:,.2f}</div>
                <div class="detalhe" style="color:#64748b;">Dinheiro real disponível</div>
            </div>""", unsafe_allow_html=True)
        with col_tot2:
            cls_pl = "valor-positivo" if total_pl >= 0 else "valor-negativo"
            s_pl   = "+" if total_pl > 0 else ""
            st.markdown(f"""<div class="saldo-card" style="background:#1e293b;border-left-color:#8b5cf6;">
                <h3 style="color:#94a3b8;">📊 PATRIMÔNIO LÍQUIDO</h3>
                <div class="{cls_pl}" style="font-size:2rem;">{s_pl}€ {total_pl:,.2f}</div>
                <div class="detalhe" style="color:#64748b;">Saldo − faturas crédito pendentes</div>
            </div>""", unsafe_allow_html=True)

        st.divider()
        st.markdown("#### 🔧 Ajustar Saldo Inicial por Conta")
        for f in fontes_saldo:
            ini_row2  = db_query("SELECT valor_inicial FROM saldos_iniciais WHERE fonte=?", (f,))
            ini_atual = ini_row2[0][0] if ini_row2 else 0.0
            col_si1, col_si2 = st.columns([3, 1])
            with col_si1:
                novo_ini = st.number_input(f"Saldo inicial de **{f}**",
                    value=float(ini_atual), step=10.0, format="%.2f", key=f"ini_{f}")
            with col_si2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("Salvar", key=f"salvar_ini_{f}"):
                    db_execute("INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)",
                               (f, novo_ini))
                    st.success(f"'{f}' atualizado!")
                    st.rerun()


# ══════════════════════════════════════════════
#  TAB 4 — CARTÕES DE CRÉDITO
# ══════════════════════════════════════════════
with tab4:
    st.markdown("## 💳 Cartões de Crédito")
    st.caption("Gerencie cartões, visualize faturas e pague com um clique.")
    st.divider()

    st.markdown('<div class="secao-titulo">➕ Cadastrar Novo Cartão</div>', unsafe_allow_html=True)
    fontes_c = [r[0] for r in db_query("SELECT nome FROM fontes ORDER BY nome")]

    if not fontes_c:
        st.warning("⚠️ Cadastre ao menos uma conta bancária em ⚙️ Gestão → Seção 2.")
    else:
        with st.form("f_cartao", clear_on_submit=True):
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                n_cartao = st.text_input("Nome do cartão", placeholder="Ex: Visa Gold, Nubank...")
                limite_c = st.number_input("Limite (€)", min_value=0.0, step=100.0, format="%.2f")
            with col_c2:
                dia_fech = st.number_input("Dia de fechamento", min_value=1, max_value=31, value=15)
                dia_venc = st.number_input("Dia de vencimento", min_value=1, max_value=31, value=5)
            conta_pag_sel = st.selectbox("Conta bancária para pagamento", fontes_c)
            if st.form_submit_button("💳 Adicionar Cartão", use_container_width=True, type="primary"):
                if not n_cartao.strip():
                    st.warning("Digite o nome do cartão.")
                elif limite_c <= 0:
                    st.warning("O limite deve ser maior que zero.")
                else:
                    try:
                        db_execute(
                            "INSERT INTO cartoes (nome,limite,dia_fechamento,dia_vencimento,conta_pagamento) VALUES (?,?,?,?,?)",
                            (n_cartao.strip(), limite_c, int(dia_fech), int(dia_venc), conta_pag_sel))
                        st.success(f"Cartão **{n_cartao}** cadastrado! Limite: €{limite_c:,.2f}")
                        st.session_state.ver += 1
                        st.rerun()
                    except Exception:
                        st.error("Já existe um cartão com esse nome.")

    st.divider()
    cartoes_df = db_df("SELECT * FROM cartoes ORDER BY nome")

    if cartoes_df.empty:
        st.info("Nenhum cartão cadastrado ainda.")
    else:
        for _, cartao in cartoes_df.iterrows():
            cid        = int(cartao['id'])
            nome_c     = cartao['nome']
            limite_c   = float(cartao['limite'])
            dia_fech_c = int(cartao['dia_fechamento'])
            dia_venc_c = int(cartao['dia_vencimento'])
            conta_pag  = cartao['conta_pagamento']
            usado      = calcular_limite_usado(cid)
            disp       = limite_c - usado
            pct_uso    = (usado / limite_c * 100) if limite_c > 0 else 0
            cor_disp   = "#16a34a" if disp > limite_c*0.3 else "#f59e0b" if disp > 0 else "#dc2626"

            st.markdown(f"""
            <div class="saldo-card saldo-card-cartao">
                <h3>💳 {nome_c}</h3>
                <div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:8px;">
                    <span>Limite: <strong>€{limite_c:,.2f}</strong></span>
                    <span>Usado: <strong style="color:#ef4444;">€{usado:,.2f}</strong></span>
                    <span>Disponível: <strong style="color:{cor_disp};">€{disp:,.2f}</strong></span>
                    <span>Uso: <strong>{pct_uso:.0f}%</strong></span>
                </div>
                <div class="detalhe">Fechamento: dia {dia_fech_c} | Vencimento: dia {dia_venc_c} | Conta: {conta_pag}</div>
            </div>""", unsafe_allow_html=True)

            faturas_df = db_df(
                "SELECT fatura_ref, SUM(valor_eur) as total, COUNT(*) as n_compras, "
                "MAX(CASE WHEN status_cartao='pendente' THEN 1 ELSE 0 END) as tem_pendente "
                "FROM transacoes WHERE cartao_id=? AND fatura_ref IS NOT NULL "
                "GROUP BY fatura_ref ORDER BY fatura_ref DESC", params=(cid,))

            if faturas_df.empty:
                st.caption("  Nenhuma compra registada neste cartão ainda.")
            else:
                for _, fat in faturas_df.iterrows():
                    fat_ref       = fat['fatura_ref']
                    fat_total     = float(fat['total'])
                    fat_compras   = int(fat['n_compras'])
                    fat_pendente  = bool(fat['tem_pendente'])
                    fat_pend_tot  = calcular_total_fatura(cid, fat_ref)
                    css_fat = "fatura-aberta" if fat_pendente else "fatura-fechada"
                    badge   = "🟠 ABERTA"    if fat_pendente else "✅ PAGA"
                    st.markdown(f"""
                    <div class="{css_fat}">
                        <strong>📅 Fatura {fat_ref}</strong> &nbsp;&nbsp;<span style="font-size:0.85rem;">{badge}</span><br>
                        <span class="detalhe">{fat_compras} compra(s) | Total bruto: €{fat_total:,.2f}
                        {f" | Pendente: <strong>€{fat_pend_tot:,.2f}</strong>" if fat_pendente else ""}
                        </span>
                    </div>""", unsafe_allow_html=True)

                    with st.expander(f"Ver compras da fatura {fat_ref}"):
                        compras_fat = db_df(
                            "SELECT data,categoria_pai,categoria_filho,beneficiario,"
                            "valor_eur,nota,status_cartao FROM transacoes "
                            "WHERE cartao_id=? AND fatura_ref=? ORDER BY data",
                            params=(cid, fat_ref))
                        if not compras_fat.empty:
                            compras_fat = compras_fat.rename(columns={
                                'data':'Data','categoria_pai':'Categoria',
                                'categoria_filho':'Detalhamento','beneficiario':'Beneficiário',
                                'valor_eur':'Valor (€)','nota':'Observação','status_cartao':'Status'})
                            st.dataframe(compras_fat, use_container_width=True, hide_index=True,
                                column_config={"Valor (€)": st.column_config.NumberColumn(format="€ %.2f")})

                    if fat_pendente:
                        saldo_c = calcular_saldo_conta(conta_pag)
                        col_pb1, col_pb2 = st.columns([2, 3])
                        with col_pb1:
                            if st.button(f"💸 Pagar Fatura {fat_ref} — €{fat_pend_tot:,.2f}",
                                         key=f"pagar_{cid}_{fat_ref}", type="primary",
                                         use_container_width=True):
                                try:
                                    total_pago = pagar_fatura(cid, fat_ref, st.session_state.display_name)
                                    st.success(f"✅ Fatura {fat_ref} paga! €{total_pago:,.2f} debitados de **{conta_pag}**.")
                                    st.session_state.ver += 1
                                    st.rerun()
                                except ValueError as e:
                                    st.error(f"❌ {e}")
                        with col_pb2:
                            if saldo_c < fat_pend_tot:
                                st.warning(f"⚠️ Saldo em {conta_pag}: €{saldo_c:,.2f} (insuficiente)")

            trans_count = db_query("SELECT COUNT(*) FROM transacoes WHERE cartao_id=?", (cid,))[0][0]
            if trans_count == 0:
                if st.button(f"🗑️ Remover cartão {nome_c}", key=f"rm_cartao_{cid}", type="secondary"):
                    db_execute("DELETE FROM cartoes WHERE id=?", (cid,))
                    st.success(f"Cartão '{nome_c}' removido.")
                    st.session_state.ver += 1
                    st.rerun()
            else:
                st.caption(f"🔒 {nome_c} tem {trans_count} transação(ões) vinculada(s) — remova-as na aba 📋 primeiro.")
            st.markdown("---")


# ══════════════════════════════════════════════
#  TAB 5 — METAS (PLANEJAMENTO DE ORÇAMENTO)
# ══════════════════════════════════════════════
with tab5:
    st.markdown("## 🎯 Planejamento de Metas")
    st.caption(
        "Defina quanto pretende gastar por categoria e mês. "
        "As metas alimentam o Dashboard de Saúde Financeira."
    )
    st.divider()

    # ── Seleção do mês ────────────────────────
    hoje = datetime.now()
    col_m1, col_m2, col_m3 = st.columns([1, 1, 3])
    with col_m1:
        ano_sel = st.number_input("Ano", min_value=2020, max_value=2100,
                                   value=hoje.year, step=1, key="meta_ano")
    with col_m2:
        mes_sel = st.number_input("Mês", min_value=1, max_value=12,
                                   value=hoje.month, step=1, key="meta_mes")
    mes_ano_sel = f"{int(ano_sel):04d}-{int(mes_sel):02d}"
    st.caption(f"📅 Editando metas de: **{mes_ano_sel}**")

    st.divider()

    # ── Formulário de nova meta ───────────────
    st.markdown('<div class="secao-titulo">➕ Adicionar / Actualizar Meta</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="secao-sub">Se já existe meta para esta combinação, o valor será actualizado.</div>',
                unsafe_allow_html=True)

    cat_df_m = db_df("SELECT id, nome, pai_id FROM categorias")
    pai_opts_m = cat_df_m[cat_df_m['pai_id'].isna()]['nome'].tolist()
    benef_row_m = db_query("SELECT nome FROM beneficiarios ORDER BY nome")
    benef_m = ["(Todos)"] + [r[0] for r in benef_row_m]

    if not pai_opts_m:
        st.warning("⚠️ Cadastre categorias em ⚙️ Gestão antes de definir metas.")
    else:
        with st.form("f_meta", clear_on_submit=True):
            col_m_a, col_m_b, col_m_c = st.columns(3)
            with col_m_a:
                meta_pai = st.selectbox("Categoria Principal", pai_opts_m)
                pid_m = int(cat_df_m[cat_df_m['nome'] == meta_pai]['id'].iloc[0])
                filhos_m = cat_df_m[cat_df_m['pai_id'] == pid_m]['nome'].tolist()
                meta_filho = st.selectbox("Detalhamento",
                                          ["(Todos)"] + filhos_m)
            with col_m_b:
                meta_benef = st.selectbox("Beneficiário", benef_m)
                meta_valor = st.number_input("Valor previsto (€)",
                    min_value=0.01, step=10.0, format="%.2f", value=100.0)
            with col_m_c:
                st.markdown("<br><br><br>", unsafe_allow_html=True)
                submitted_meta = st.form_submit_button(
                    "💾 Salvar Meta", use_container_width=True, type="primary")

            if submitted_meta:
                filho_db  = "" if meta_filho  == "(Todos)" else meta_filho
                benef_db  = "" if meta_benef  == "(Todos)" else meta_benef
                # Verifica se já existe → UPDATE; senão → INSERT
                existe = db_query(
                    "SELECT id FROM orcamentos "
                    "WHERE mes_ano=? AND categoria_pai=? "
                    "AND categoria_filho=? AND beneficiario=?",
                    (mes_ano_sel, meta_pai, filho_db, benef_db))
                if existe:
                    db_execute(
                        "UPDATE orcamentos SET valor_previsto=? "
                        "WHERE mes_ano=? AND categoria_pai=? "
                        "AND categoria_filho=? AND beneficiario=?",
                        (meta_valor, mes_ano_sel, meta_pai, filho_db, benef_db))
                    log_audit("META_UPDATE",
                              f"mes={mes_ano_sel} cat={meta_pai}/{filho_db} "
                              f"benef={benef_db} valor={meta_valor}",
                              st.session_state.display_name)
                    st.success(f"Meta actualizada: {meta_pai}/{meta_filho or 'Todos'} → €{meta_valor:.2f}")
                else:
                    db_execute(
                        "INSERT INTO orcamentos "
                        "(mes_ano,categoria_pai,categoria_filho,beneficiario,valor_previsto) "
                        "VALUES (?,?,?,?,?)",
                        (mes_ano_sel, meta_pai, filho_db, benef_db, meta_valor))
                    log_audit("META_INSERT",
                              f"mes={mes_ano_sel} cat={meta_pai}/{filho_db} "
                              f"benef={benef_db} valor={meta_valor}",
                              st.session_state.display_name)
                    st.success(f"Meta criada: {meta_pai}/{meta_filho or 'Todos'} → €{meta_valor:.2f}")
                st.session_state.ver += 1
                st.rerun()

    st.divider()

    # ── Tabela de metas do mês ────────────────
    st.markdown(f"**Metas definidas para {mes_ano_sel}:**")
    metas_df = db_df(
        "SELECT id, categoria_pai, categoria_filho, beneficiario, valor_previsto "
        "FROM orcamentos WHERE mes_ano=? "
        "ORDER BY categoria_pai, categoria_filho",
        params=(mes_ano_sel,))

    if metas_df.empty:
        st.info(f"Nenhuma meta definida para {mes_ano_sel}. Use o formulário acima.")
    else:
        # Calcula realizado para cada linha
        metas_df['realizado'] = metas_df.apply(
            lambda r: get_realizado_mes(
                mes_ano_sel,
                r['categoria_pai'],
                r['categoria_filho'] if r['categoria_filho'] else None
            ), axis=1)
        metas_df['% uso'] = metas_df.apply(
            lambda r: round(r['realizado'] / r['valor_previsto'] * 100, 1)
            if r['valor_previsto'] > 0 else 0.0, axis=1)

        metas_df = metas_df.rename(columns={
            'categoria_pai': 'Categoria', 'categoria_filho': 'Detalhamento',
            'beneficiario': 'Beneficiário', 'valor_previsto': 'Previsto (€)',
            'realizado': 'Realizado (€)'})

        # Coluna de remoção
        metas_df.insert(0, "Remover", False)
        ed_metas = st.data_editor(
            metas_df,
            key=f"ed_metas_{st.session_state.ver}",
            use_container_width=True,
            column_config={
                "Remover":       st.column_config.CheckboxColumn("🗑️"),
                "Previsto (€)":  st.column_config.NumberColumn(format="€ %.2f"),
                "Realizado (€)": st.column_config.NumberColumn(format="€ %.2f"),
                "% uso":         st.column_config.NumberColumn(format="%.1f %%"),
            }
        )

        if st.button("🗑️ Remover Metas Selecionadas", key="rm_metas"):
            ids_rm_m = ed_metas[ed_metas["Remover"] == True]["id"].tolist()
            if not ids_rm_m:
                st.warning("Selecione pelo menos uma meta.")
            else:
                ph = ",".join(["?"] * len(ids_rm_m))
                db_execute(f"DELETE FROM orcamentos WHERE id IN ({ph})", tuple(ids_rm_m))
                log_audit("META_DELETE", f"ids={ids_rm_m}", st.session_state.display_name)
                st.success(f"{len(ids_rm_m)} meta(s) removida(s).")
                st.session_state.ver += 1
                st.rerun()

        # Totais rápidos
        st.divider()
        total_prev_m  = metas_df['Previsto (€)'].sum()
        total_real_m  = metas_df['Realizado (€)'].sum()
        col_tp1, col_tp2, col_tp3 = st.columns(3)
        col_tp1.metric("Total Planejado",  f"€ {total_prev_m:,.2f}")
        col_tp2.metric("Total Realizado",  f"€ {total_real_m:,.2f}")
        delta = total_prev_m - total_real_m
        col_tp3.metric("Saldo de Metas",   f"€ {delta:,.2f}",
                        delta=f"€ {delta:,.2f}",
                        delta_color="normal" if delta >= 0 else "inverse")


# ══════════════════════════════════════════════
#  TAB 6 — DASHBOARD DE SAÚDE FINANCEIRA
# ══════════════════════════════════════════════
with tab6:
    st.markdown("## 📊 Dashboard de Saúde Financeira")
    st.caption("Painel em tempo real — compare o planejado com o realizado e identifique desvios.")
    st.divider()

    # Seleção do mês do dashboard
    hoje_d = datetime.now()
    col_d1, col_d2, col_d3 = st.columns([1, 1, 4])
    with col_d1:
        dash_ano = st.number_input("Ano", min_value=2020, max_value=2100,
                                    value=hoje_d.year, step=1, key="dash_ano")
    with col_d2:
        dash_mes = st.number_input("Mês", min_value=1, max_value=12,
                                    value=hoje_d.month, step=1, key="dash_mes")
    dash_mes_ano = f"{int(dash_ano):04d}-{int(dash_mes):02d}"

    taxa_dash = st.session_state.get('taxa_brl_eur', 0.16)

    # ── Indicadores Globais ────────────────────
    st.markdown(f"### 🌍 Visão Geral — {dash_mes_ano}")

    total_prev_d  = db_query(
        "SELECT COALESCE(SUM(valor_previsto),0) FROM orcamentos WHERE mes_ano=?",
        (dash_mes_ano,))[0][0]
    total_real_d  = get_realizado_mes(dash_mes_ano)

    # Receitas do mês
    ano_d, mes_d = dash_mes_ano.split("-")
    total_rec_d = db_query(
        "SELECT COALESCE(SUM(valor_eur),0) FROM transacoes "
        "WHERE tipo='Receita' AND substr(data,4,2)=? AND substr(data,7,4)=?",
        (mes_d, ano_d))[0][0]

    saldo_mes_d = total_rec_d - total_real_d
    pct_global  = (total_real_d / total_prev_d * 100) if total_prev_d > 0 else 0

    col_g1, col_g2, col_g3, col_g4 = st.columns(4)
    with col_g1:
        st.markdown(f"""<div class="saldo-card">
            <h3>🎯 Planejado</h3>
            <div class="valor-neutro">€ {total_prev_d:,.2f}</div>
            <div class="detalhe">Total de metas do mês</div>
        </div>""", unsafe_allow_html=True)
    with col_g2:
        cls_rd = "valor-negativo" if total_real_d > total_prev_d else "valor-positivo"
        st.markdown(f"""<div class="saldo-card">
            <h3>💸 Realizado</h3>
            <div class="{cls_rd}">€ {total_real_d:,.2f}</div>
            <div class="detalhe">Despesas (competência)</div>
        </div>""", unsafe_allow_html=True)
    with col_g3:
        cls_rc = "valor-positivo" if total_rec_d > 0 else "valor-negativo"
        st.markdown(f"""<div class="saldo-card">
            <h3>💵 Receitas</h3>
            <div class="{cls_rc}">€ {total_rec_d:,.2f}</div>
            <div class="detalhe">Entradas do mês</div>
        </div>""", unsafe_allow_html=True)
    with col_g4:
        cls_sl = "valor-positivo" if saldo_mes_d >= 0 else "valor-negativo"
        sinal_sl = "+" if saldo_mes_d > 0 else ""
        st.markdown(f"""<div class="saldo-card">
            <h3>⚖️ Saldo do Mês</h3>
            <div class="{cls_sl}">{sinal_sl}€ {saldo_mes_d:,.2f}</div>
            <div class="detalhe">Receitas − Despesas</div>
        </div>""", unsafe_allow_html=True)

    # Barra de progresso global
    if total_prev_d > 0:
        st.markdown("**Consumo global do orçamento:**")
        prog = min(pct_global / 100, 1.0)
        cor_prog = (
            "🟢" if pct_global < 80 else
            "🟡" if pct_global <= 100 else "🔴"
        )
        st.progress(prog, text=f"{cor_prog} {pct_global:.1f}% do orçamento total utilizado")

    st.divider()

    # ── Semáforo por Categoria ─────────────────
    st.markdown("### 🚦 Saúde por Categoria")

    saude = get_saude_orcamento(dash_mes_ano)

    if not saude:
        st.info(f"Nenhuma meta definida para {dash_mes_ano}. Crie metas na aba 🎯 Metas.")
    else:
        col_s1, col_s2 = st.columns(2)
        for idx, item in enumerate(saude):
            cat_pai   = item["cat_pai"]
            cat_filho = item["cat_filho"] or "Todos"
            previsto  = item["previsto"]
            realizado = item["realizado"]
            pct       = item["pct"]
            status    = item["status"]

            css_class = f"gauge-{status}"
            icone = "🟢" if status == "verde" else "🟡" if status == "amarelo" else "🔴"
            prog_val  = min(pct / 100, 1.0)

            label_cat = f"{cat_pai}" + (f" / {cat_filho}" if cat_filho != "Todos" else "")
            diferenca = previsto - realizado
            sinal_dif = "+" if diferenca > 0 else ""
            msg_dif   = (f"Sobra €{abs(diferenca):,.2f}" if diferenca >= 0
                         else f"⚠️ Estourou €{abs(diferenca):,.2f}")

            with (col_s1 if idx % 2 == 0 else col_s2):
                st.markdown(f"""
                <div class="{css_class}">
                    <div class="gauge-titulo">{icone} {label_cat}</div>
                    <div class="gauge-sub">
                        Realizado: <strong>€{realizado:,.2f}</strong>
                        &nbsp;/&nbsp;
                        Previsto: <strong>€{previsto:,.2f}</strong>
                        &nbsp;—&nbsp; {msg_dif}
                    </div>
                </div>""", unsafe_allow_html=True)
                st.progress(prog_val,
                    text=f"{pct:.1f}% utilizado")

    st.divider()

    # ── Top 3 Beneficiários ─────────────────────
    st.markdown("### 🔎 Análise de Causa Raiz — Top 3 Beneficiários")
    st.caption("Quem mais consumiu orçamento neste mês.")

    top3 = get_top_beneficiarios(dash_mes_ano, 3)

    if not top3:
        st.info("Nenhuma despesa registada neste mês ainda.")
    else:
        max_val = max(t[1] for t in top3) if top3 else 1
        medalhas = ["🥇", "🥈", "🥉"]
        for i, (nome, total) in enumerate(top3):
            pct_top = (total / max_val * 100) if max_val > 0 else 0
            medalha = medalhas[i] if i < 3 else "•"
            st.markdown(f"""
            <div class="top-benef-card">
                <div>
                    <span style="font-size:1.3rem;">{medalha}</span>
                    <strong style="margin-left:10px;">{nome}</strong>
                </div>
                <div style="font-size:1.2rem;font-weight:700;color:#1e293b;">
                    € {total:,.2f}
                </div>
            </div>""", unsafe_allow_html=True)
            st.progress(pct_top / 100)

    st.divider()

    # ── Previsto vs Realizado — Tabela ──────────
    st.markdown("### 📋 Relatório Previsto vs. Realizado")

    if saude:
        df_report = pd.DataFrame([{
            "Categoria":    (s["cat_pai"] + (" / " + s["cat_filho"] if s["cat_filho"] else "")),
            "Beneficiário": s["beneficiario"] or "Todos",
            "Previsto (€)": s["previsto"],
            "Realizado (€)":s["realizado"],
            "Δ (€)":        s["previsto"] - s["realizado"],
            "% Uso":        round(s["pct"], 1),
            "Status":       s["status"].upper(),
        } for s in saude])

        st.dataframe(df_report, use_container_width=True, hide_index=True,
            column_config={
                "Previsto (€)":  st.column_config.NumberColumn(format="€ %.2f"),
                "Realizado (€)": st.column_config.NumberColumn(format="€ %.2f"),
                "Δ (€)":         st.column_config.NumberColumn(format="€ %.2f"),
                "% Uso":         st.column_config.NumberColumn(format="%.1f %%"),
            })

        # Exportar relatório
        csv_rep = df_report.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            "⬇️ Exportar Relatório CSV",
            csv_rep,
            f"relatorio_{dash_mes_ano}.csv",
            "text/csv",
            use_container_width=False)
    else:
        st.info("Defina metas na aba 🎯 Metas para ver o relatório comparativo.")


# ══════════════════════════════════════════════
#  TAB 7 — GESTÃO
# ══════════════════════════════════════════════
with tab7:
    st.markdown("## ⚙️ Gestão e Configurações")
    st.caption("Configure as categorias, contas e beneficiários do seu sistema.")

    cat_df2   = db_df("SELECT id, nome, pai_id FROM categorias")
    pai_opts2 = cat_df2[cat_df2['pai_id'].isna()]['nome'].tolist()

    # ══ SEÇÃO 0: TAXA DE CÂMBIO ═══════════════════
    st.markdown("---")
    st.markdown('<div class="secao-titulo">💱 Seção 0 — Taxa de Câmbio BRL → EUR</div>', unsafe_allow_html=True)
    st.markdown('<div class="secao-sub">Define quanto 1 Real brasileiro vale em Euro.</div>', unsafe_allow_html=True)
    col_tx1, col_tx2, col_tx3 = st.columns([1.5, 1, 3])
    with col_tx1:
        nova_taxa = st.number_input("Taxa (1 BRL = X EUR)",
            min_value=0.0001, max_value=10.0,
            value=float(st.session_state['taxa_brl_eur']),
            step=0.001, format="%.4f", key="inp_taxa")
    with col_tx2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 Salvar Taxa", use_container_width=True, key="btn_taxa"):
            db_execute("INSERT OR REPLACE INTO configuracoes (chave,valor) VALUES ('taxa_brl_eur',?)",
                       (str(nova_taxa),))
            st.session_state['taxa_brl_eur'] = nova_taxa
            st.success(f"Taxa atualizada para {nova_taxa:.4f}.")
            st.rerun()
    with col_tx3:
        st.markdown("<br>", unsafe_allow_html=True)
        st.info(f"💡 1 BRL = **{st.session_state['taxa_brl_eur']:.4f} EUR** | "
                f"Ex: R$100 = €{100*st.session_state['taxa_brl_eur']:.2f}")

    # ══ SEÇÃO 1: CATEGORIAS ═══════════════════════
    st.markdown("---")
    st.markdown('<div class="secao-titulo">📂 Seção 1 — Categorias</div>', unsafe_allow_html=True)
    st.markdown('<div class="secao-sub">Organize seus gastos e receitas em categorias e detalhamentos.</div>', unsafe_allow_html=True)
    col_cat1, col_cat2 = st.columns(2)
    with col_cat1:
        st.markdown("**Adicionar Categoria Principal**")
        st.caption("Ex: Alimentação, Transporte, Saúde, Lazer")
        n_pai = st.text_input("Nome", key="inp_pai", placeholder="Ex: Alimentação")
        if st.button("➕ Adicionar Categoria Principal", use_container_width=True):
            if n_pai.strip():
                try:
                    db_execute("INSERT INTO categorias (nome) VALUES (?)", (n_pai.strip(),))
                    st.success(f"Categoria '{n_pai}' adicionada!")
                    st.rerun()
                except Exception:
                    st.error("Já existe uma categoria com esse nome.")
            else:
                st.warning("Digite um nome.")
    with col_cat2:
        st.markdown("**Adicionar Detalhamento**")
        st.caption("Ex: Alimentação → Supermercado, Restaurante...")
        if pai_opts2:
            pai_sel_gest = st.selectbox("Dentro de qual categoria?", pai_opts2, key="sel_pai_gest")
            n_sub = st.text_input("Nome do detalhamento", key="inp_sub", placeholder="Ex: Supermercado")
            if st.button("➕ Adicionar Detalhamento", use_container_width=True):
                if n_sub.strip():
                    try:
                        pid2 = int(cat_df2[cat_df2['nome'] == pai_sel_gest]['id'].iloc[0])
                        db_execute("INSERT INTO categorias (nome,pai_id) VALUES (?,?)",
                                   (n_sub.strip(), pid2))
                        st.success(f"'{n_sub}' adicionado em '{pai_sel_gest}'!")
                        st.rerun()
                    except Exception:
                        st.error("Já existe um detalhamento com esse nome.")
                else:
                    st.warning("Digite um nome.")
        else:
            st.info("Crie uma Categoria Principal primeiro.")

    st.markdown("**Categorias cadastradas:**")
    if not cat_df2.empty:
        cat_view = cat_df2.copy()
        pai_map  = cat_df2[cat_df2['pai_id'].isna()].set_index('id')['nome'].to_dict()
        cat_view['Categoria Principal'] = cat_view['pai_id'].map(pai_map).fillna('— (é principal)')
        cat_view = cat_view.rename(columns={'nome': 'Nome'})
        cat_view.insert(0, "Remover", False)
        cat_display = cat_view[['Remover','id','Nome','Categoria Principal']]
        ed_cat = st.data_editor(cat_display, key=f"ed_cat_{st.session_state.ver}",
            use_container_width=True,
            column_config={"Remover": st.column_config.CheckboxColumn("🗑️")})
        if st.button("🗑️ Remover Categorias Selecionadas", key="rm_cat"):
            ids_cat = ed_cat[ed_cat["Remover"] == True]["id"].tolist()
            if not ids_cat:
                st.warning("Selecione pelo menos uma.")
            else:
                erros = []
                for cid in ids_cat:
                    if db_query("SELECT COUNT(*) FROM categorias WHERE pai_id=?", (cid,))[0][0] > 0:
                        nome_c = cat_df2[cat_df2['id'] == cid]['Nome'].values
                        erros.append(nome_c[0] if len(nome_c) else str(cid))
                if erros:
                    st.error(f"⛔ Remova os detalhamentos de **{', '.join(erros)}** primeiro.")
                else:
                    ph = ",".join(["?"] * len(ids_cat))
                    db_execute(f"DELETE FROM categorias WHERE id IN ({ph})", tuple(ids_cat))
                    st.success(f"{len(ids_cat)} categoria(s) removida(s).")
                    st.rerun()
    else:
        st.info("Nenhuma categoria cadastrada ainda.")

    # ══ SEÇÃO 2: CONTAS E FONTES ══════════════════
    st.markdown("---")
    st.markdown('<div class="secao-titulo">🏦 Seção 2 — Contas e Fontes de Dinheiro</div>', unsafe_allow_html=True)
    st.markdown('<div class="secao-sub">Cadastre as contas onde o dinheiro da sua família fica guardado.</div>', unsafe_allow_html=True)
    col_f1g, col_f2g = st.columns([2, 1])
    with col_f1g:
        n_fonte = st.text_input("Nome da conta", key="inp_fonte",
                                 placeholder="Ex: Banco CGD, Carteira, Poupança...")
    with col_f2g:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("➕ Adicionar Conta", use_container_width=True, key="btn_fonte"):
            if n_fonte.strip():
                try:
                    db_execute("INSERT INTO fontes (nome) VALUES (?)", (n_fonte.strip(),))
                    st.success(f"Conta '{n_fonte}' adicionada!")
                    st.rerun()
                except Exception:
                    st.error("Já existe uma conta com esse nome.")
            else:
                st.warning("Digite um nome.")
    fontes_df = db_df("SELECT id, nome FROM fontes")
    st.markdown("**Contas cadastradas:**")
    if not fontes_df.empty:
        fontes_df.insert(0, "Remover", False)
        fontes_df = fontes_df.rename(columns={'nome': 'Nome da Conta'})
        ed_fontes = st.data_editor(fontes_df, key=f"ed_fontes_{st.session_state.ver}",
            use_container_width=True,
            column_config={"Remover": st.column_config.CheckboxColumn("🗑️")})
        if st.button("🗑️ Remover Contas Selecionadas", key="rm_fontes"):
            ids_f   = ed_fontes[ed_fontes["Remover"] == True]["id"].tolist()
            nomes_f = ed_fontes[ed_fontes["Remover"] == True]["Nome da Conta"].tolist()
            if not ids_f:
                st.warning("Selecione pelo menos uma conta.")
            else:
                ph = ",".join(["?"] * len(ids_f))
                ops = [(f"DELETE FROM fontes WHERE id IN ({ph})", tuple(ids_f))]
                for nm in nomes_f:
                    ops.append(("DELETE FROM saldos_iniciais WHERE fonte=?", (nm,)))
                db_execute_many(ops)
                st.success(f"{len(ids_f)} conta(s) removida(s).")
                st.rerun()
    else:
        st.info("Nenhuma conta cadastrada ainda.")

    # ══ SEÇÃO 3: BENEFICIÁRIOS ════════════════════
    st.markdown("---")
    st.markdown('<div class="secao-titulo">👤 Seção 3 — Beneficiários</div>', unsafe_allow_html=True)
    st.markdown('<div class="secao-sub">Registe quem costuma enviar ou receber dinheiro da sua família.</div>', unsafe_allow_html=True)
    col_b1g, col_b2g = st.columns([2, 1])
    with col_b1g:
        n_benef = st.text_input("Nome do beneficiário", key="inp_benef",
                                 placeholder="Ex: Pingo Doce, João Silva...")
    with col_b2g:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("➕ Adicionar Beneficiário", use_container_width=True, key="btn_benef"):
            if n_benef.strip():
                try:
                    db_execute("INSERT INTO beneficiarios (nome) VALUES (?)", (n_benef.strip(),))
                    st.success(f"'{n_benef}' adicionado!")
                    st.rerun()
                except Exception:
                    st.error("Já existe um beneficiário com esse nome.")
            else:
                st.warning("Digite um nome.")
    benef_df = db_df("SELECT id, nome FROM beneficiarios")
    st.markdown("**Beneficiários cadastrados:**")
    if not benef_df.empty:
        benef_df.insert(0, "Remover", False)
        benef_df = benef_df.rename(columns={'nome': 'Nome'})
        ed_benef = st.data_editor(benef_df, key=f"ed_benef_{st.session_state.ver}",
            use_container_width=True,
            column_config={"Remover": st.column_config.CheckboxColumn("🗑️")})
        if st.button("🗑️ Remover Beneficiários Selecionados", key="rm_benef"):
            ids_b = ed_benef[ed_benef["Remover"] == True]["id"].tolist()
            if not ids_b:
                st.warning("Selecione pelo menos um.")
            else:
                ph = ",".join(["?"] * len(ids_b))
                db_execute(f"DELETE FROM beneficiarios WHERE id IN ({ph})", tuple(ids_b))
                st.success(f"{len(ids_b)} removido(s).")
                st.rerun()
    else:
        st.info("Nenhum beneficiário cadastrado ainda.")

    # ══ SEÇÃO 4: UTILIZADORES ════════════════════
    st.markdown("---")
    st.markdown('<div class="secao-titulo">👥 Seção 4 — Utilizadores do Sistema</div>', unsafe_allow_html=True)
    st.markdown('<div class="secao-sub">Adicione os membros da família que também podem usar o sistema.</div>', unsafe_allow_html=True)
    col_u1, col_u2, col_u3 = st.columns(3)
    with col_u1:
        n_user = st.text_input("Nome de utilizador", key="inp_user", placeholder="Ex: maria")
    with col_u2:
        n_nome = st.text_input("Nome para exibição", key="inp_nome", placeholder="Ex: Maria Silva")
    with col_u3:
        n_pass = st.text_input("Senha inicial", type="password", key="inp_pass",
                               placeholder="Mínimo 4 caracteres")
    if st.button("➕ Adicionar Utilizador", key="btn_user"):
        if n_user.strip() and n_pass.strip() and n_nome.strip():
            if len(n_pass) < 4:
                st.warning("A senha deve ter pelo menos 4 caracteres.")
            else:
                try:
                    db_execute(
                        "INSERT INTO usuarios (username,password,nome_exibicao) VALUES (?,?,?)",
                        (n_user.strip(), hash_password(n_pass), n_nome.strip()))
                    st.success(f"Utilizador '{n_nome}' adicionado!")
                    st.rerun()
                except Exception:
                    st.error("Já existe um utilizador com esse nome de login.")
        else:
            st.warning("Preencha todos os campos.")
    users_df = db_df("SELECT id, username, nome_exibicao FROM usuarios")
    users_df = users_df.rename(columns={'username':'Login','nome_exibicao':'Nome de Exibição'})
    st.markdown("**Utilizadores cadastrados:**")
    st.dataframe(users_df, use_container_width=True, hide_index=True)
