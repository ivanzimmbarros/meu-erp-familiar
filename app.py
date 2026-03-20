import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import io
import logging
from datetime import datetime, date, timedelta

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
    .saldo-card .valor-carmim   { font-size: 2rem; font-weight: 800; color: #9b1c1c; }
    .saldo-card .detalhe { font-size: 0.8rem; color: #94a3b8; margin-top: 4px; }
    .saldo-card-positivo  { border-left-color: #16a34a; }
    .saldo-card-negativo  { border-left-color: #dc2626; }
    .saldo-card-cartao    { border-left-color: #8b5cf6; background: #faf5ff; }
    .saldo-card-meta      { border-left-color: #f59e0b; background: #fffbeb; }
    .saldo-card-insolvencia {
        border-left-color: #9b1c1c;
        background: #fef2f2;
        border: 2px solid #fca5a5;
    }

    .secao-titulo { font-size: 1.1rem; font-weight: 700; color: #1e293b; padding: 8px 0 4px 0; }
    .secao-sub    { font-size: 0.85rem; color: #64748b; margin-bottom: 16px; }

    .aviso-bloqueio {
        background: #fff7ed; border: 1px solid #fed7aa;
        border-radius: 10px; padding: 14px 18px; margin-bottom: 8px;
        color: #9a3412; font-size: 0.9rem;
    }
    .aviso-insolvencia {
        background: #fef2f2; border: 2px solid #f87171;
        border-radius: 12px; padding: 16px 20px; margin: 12px 0;
        color: #7f1d1d; font-size: 0.95rem; font-weight: 600;
    }
    .aviso-pendente {
        background: #fffbeb; border: 1px solid #fcd34d;
        border-radius: 10px; padding: 14px 18px; margin: 8px 0;
        color: #78350f; font-size: 0.9rem;
    }

    /* Status de liquidação */
    .badge-pago     { background:#dcfce7; color:#166534; padding:2px 10px; border-radius:999px; font-size:0.75rem; font-weight:700; }
    .badge-pendente { background:#fef9c3; color:#854d0e; padding:2px 10px; border-radius:999px; font-size:0.75rem; font-weight:700; }
    .badge-previsto { background:#e0f2fe; color:#0c4a6e; padding:2px 10px; border-radius:999px; font-size:0.75rem; font-weight:700; }

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
    .liquidar-row {
        background: #fffbeb; border-radius: 8px; padding: 10px 14px;
        margin-bottom: 6px; font-size: 0.88rem;
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
# ─────────────────────────────────────────────
def init_db():
    """
    Idempotente. Colunas novas adicionadas via ALTER TABLE.
    Novas colunas em transacoes:
      status_liquidacao → PAGO | PENDENTE | PREVISTO
      data_liquidacao   → data em que foi efectivamente liquidado
    Registos antigos migrados para PAGO por defeito.
    """
    TRANSACOES_COLUNAS = [
        ("id",               "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("data",             "TEXT"),
        ("categoria_pai",    "TEXT"),
        ("categoria_filho",  "TEXT"),
        ("beneficiario",     "TEXT"),
        ("fonte",            "TEXT"),
        ("valor_eur",        "REAL"),
        ("tipo",             "TEXT"),
        ("nota",             "TEXT"),
        ("usuario",          "TEXT"),
        ("forma_pagamento",  "TEXT DEFAULT 'Dinheiro/Débito'"),
        ("cartao_id",        "INTEGER"),
        ("fatura_ref",       "TEXT"),
        ("status_cartao",    "TEXT DEFAULT 'pendente'"),
        # ── módulo liquidez ──
        ("status_liquidacao","TEXT DEFAULT 'PAGO'"),
        ("data_liquidacao",  "TEXT"),
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

        # orçamentos
        c.execute(
            "CREATE TABLE IF NOT EXISTS orcamentos ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "mes_ano TEXT NOT NULL, "
            "categoria_pai TEXT NOT NULL, "
            "categoria_filho TEXT NOT NULL DEFAULT '', "
            "beneficiario TEXT NOT NULL DEFAULT '', "
            "valor_previsto REAL NOT NULL DEFAULT 0, "
            "tipo_meta TEXT NOT NULL DEFAULT 'Despesa', "
            "UNIQUE(mes_ano, categoria_pai, categoria_filho, beneficiario, tipo_meta)"
            ")"
        )
        c.execute("PRAGMA table_info(orcamentos)")
        _orc_cols = {row[1] for row in c.fetchall()}
        if 'tipo_meta' not in _orc_cols:
            c.execute("ALTER TABLE orcamentos "
                      "ADD COLUMN tipo_meta TEXT NOT NULL DEFAULT 'Despesa'")

        # transacoes + migração automática de colunas
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

        # Migração: registos antigos sem status_liquidacao → PAGO
        c.execute(
            "UPDATE transacoes SET status_liquidacao='PAGO' "
            "WHERE status_liquidacao IS NULL"
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
         "valor_eur, tipo, nota, usuario, forma_pagamento, status_cartao, "
         "status_liquidacao, data_liquidacao) "
         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
         (hoje, "Cartão de Crédito", "Pagamento de Fatura",
          f"Fatura {nome_cartao} — {fatura_ref}",
          conta_pag, total, "Despesa",
          f"Pagamento da fatura {nome_cartao} referência {fatura_ref}",
          usuario, "Dinheiro/Débito", "pago", "PAGO", hoje)),
    ])
    return total


# ─────────────────────────────────────────────
#  FUNÇÕES DE NEGÓCIO — LIQUIDEZ / FLUXO DE CAIXA
# ─────────────────────────────────────────────
def determinar_status_liquidacao(data_str, status_manual=None):
    """
    Auto-determina status_liquidacao pela data:
      data > hoje  → PREVISTO
      data <= hoje → PAGO  (salvo override via status_manual)
    Permite override para PENDENTE no acto do lançamento.
    """
    if status_manual:
        return status_manual
    try:
        d = datetime.strptime(data_str, "%d/%m/%Y").date()
    except Exception:
        d = date.today()
    return "PREVISTO" if d > date.today() else "PAGO"


def calcular_saldo_real(fonte_nome):
    """
    Saldo efectivo: soma apenas transações com status_liquidacao='PAGO'.
    Dinheiro que já entrou ou saiu da conta de facto.
    """
    ini_r = db_query(
        "SELECT valor_inicial FROM saldos_iniciais WHERE fonte=?", (fonte_nome,))
    ini = ini_r[0][0] if ini_r else 0.0

    rec = db_query(
        "SELECT COALESCE(SUM(valor_eur),0) FROM transacoes "
        "WHERE fonte=? AND tipo='Receita' AND status_liquidacao='PAGO' "
        "AND (forma_pagamento='Dinheiro/Débito' OR forma_pagamento IS NULL)",
        (fonte_nome,))[0][0]

    des = db_query(
        "SELECT COALESCE(SUM(valor_eur),0) FROM transacoes "
        "WHERE fonte=? AND tipo='Despesa' AND status_liquidacao='PAGO' "
        "AND (forma_pagamento='Dinheiro/Débito' OR forma_pagamento IS NULL)",
        (fonte_nome,))[0][0]

    return ini + rec - des


def calcular_comprometido(fonte_nome):
    """
    Total comprometido futuro:
      (+) Despesas PENDENTES + PREVISTAS
      (-) Receitas PENDENTES + PREVISTAS (entradas esperadas)
      (+) Faturas de cartão de crédito pendentes
    """
    desp = db_query(
        "SELECT COALESCE(SUM(valor_eur),0) FROM transacoes "
        "WHERE fonte=? AND tipo='Despesa' "
        "AND status_liquidacao IN ('PENDENTE','PREVISTO') "
        "AND (forma_pagamento='Dinheiro/Débito' OR forma_pagamento IS NULL)",
        (fonte_nome,))[0][0]

    rec = db_query(
        "SELECT COALESCE(SUM(valor_eur),0) FROM transacoes "
        "WHERE fonte=? AND tipo='Receita' "
        "AND status_liquidacao IN ('PENDENTE','PREVISTO') "
        "AND (forma_pagamento='Dinheiro/Débito' OR forma_pagamento IS NULL)",
        (fonte_nome,))[0][0]

    fat = db_query(
        "SELECT COALESCE(SUM(t.valor_eur),0) FROM transacoes t "
        "JOIN cartoes c ON t.cartao_id=c.id "
        "WHERE c.conta_pagamento=? AND t.status_cartao='pendente'",
        (fonte_nome,))[0][0]

    return desp - rec + fat


def calcular_saldo_livre(fonte_nome):
    """
    Disponibilidade Real = Saldo Real − Comprometido.
    Valor negativo sinaliza risco de insolvência.
    """
    return calcular_saldo_real(fonte_nome) - calcular_comprometido(fonte_nome)


def calcular_saldo_conta(fonte_nome):
    """Alias retrocompatível para calcular_saldo_real."""
    return calcular_saldo_real(fonte_nome)


def calcular_patrimonio_liquido(fonte_nome):
    """Saldo real menos faturas de cartão pendentes."""
    saldo = calcular_saldo_real(fonte_nome)
    passivo = db_query(
        "SELECT COALESCE(SUM(t.valor_eur),0) FROM transacoes t "
        "JOIN cartoes c ON t.cartao_id=c.id "
        "WHERE c.conta_pagamento=? AND t.status_cartao='pendente'",
        (fonte_nome,))[0][0]
    return saldo - passivo


def liquidar_transacao(trans_id, usuario):
    """
    Efectiva um pagamento: PENDENTE ou PREVISTO → PAGO.
    Regista data_liquidacao = hoje.
    """
    hoje = datetime.now().strftime("%d/%m/%Y")
    db_execute(
        "UPDATE transacoes SET status_liquidacao='PAGO', data_liquidacao=? "
        "WHERE id=?",
        (hoje, trans_id)
    )
    log_audit("LIQUIDACAO", f"id={trans_id} → PAGO em {hoje}", usuario)
    return hoje


def get_pendentes_vencidos():
    """Transações PENDENTES de débito — vencimento passou mas não liquidadas."""
    return db_query(
        "SELECT id, data, fonte, valor_eur, tipo, nota, beneficiario "
        "FROM transacoes "
        "WHERE status_liquidacao='PENDENTE' "
        "AND (forma_pagamento='Dinheiro/Débito' OR forma_pagamento IS NULL) "
        "ORDER BY data"
    )


def get_total_pendentes():
    """Total monetário de todas as transações PENDENTES."""
    r = db_query(
        "SELECT COALESCE(SUM(valor_eur),0) FROM transacoes "
        "WHERE status_liquidacao='PENDENTE' "
        "AND tipo='Despesa' "
        "AND (forma_pagamento='Dinheiro/Débito' OR forma_pagamento IS NULL)"
    )
    return r[0][0] if r else 0.0


# ─────────────────────────────────────────────
#  FUNÇÕES DE NEGÓCIO — ORÇAMENTO / DASHBOARD
# ─────────────────────────────────────────────
def get_realizado_mes(mes_ano, tipo="Despesa",
                      categoria_pai=None, categoria_filho=None):
    """
    Soma transacoes do mês por tipo (regime de competência).
    Inclui PAGO + PENDENTE + PREVISTO para reflectir o comprometimento real.
    """
    ano, mes = mes_ano.split("-")
    params  = [tipo, mes, ano]
    filtros = ["tipo=?", "substr(data,4,2)=?", "substr(data,7,4)=?"]

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


def get_top_beneficiarios(mes_ano, tipo="Despesa", n=3):
    ano, mes = mes_ano.split("-")
    return db_query(
        """SELECT beneficiario, COALESCE(SUM(valor_eur),0) as total
           FROM transacoes
           WHERE tipo=?
             AND substr(data,4,2)=? AND substr(data,7,4)=?
             AND beneficiario IS NOT NULL AND beneficiario != ''
           GROUP BY beneficiario
           ORDER BY total DESC
           LIMIT ?""",
        (tipo, mes, ano, n)
    )


def get_saude_orcamento(mes_ano):
    metas = db_query(
        "SELECT categoria_pai, categoria_filho, beneficiario, "
        "valor_previsto, tipo_meta "
        "FROM orcamentos WHERE mes_ano=? "
        "ORDER BY tipo_meta, categoria_pai, categoria_filho",
        (mes_ano,)
    )
    resultado = []
    for cat_pai, cat_filho, benef, previsto, tipo_meta in metas:
        realizado = get_realizado_mes(
            mes_ano, tipo=tipo_meta,
            categoria_pai=cat_pai,
            categoria_filho=cat_filho if cat_filho else None
        )
        pct = (realizado / previsto * 100) if previsto > 0 else 0.0
        if tipo_meta == "Receita":
            status = "verde" if pct >= 100 else "amarelo" if pct >= 80 else "vermelho"
        else:
            status = "verde" if pct < 80 else "amarelo" if pct <= 100 else "vermelho"
        resultado.append({
            "cat_pai": cat_pai, "cat_filho": cat_filho,
            "beneficiario": benef, "previsto": previsto,
            "realizado": realizado, "pct": pct,
            "status": status, "tipo_meta": tipo_meta,
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

    # Alerta global de pendentes na sidebar
    n_pend = len(get_pendentes_vencidos())
    if n_pend > 0:
        st.warning(f"⚠️ {n_pend} conta(s) vencida(s) a liquidar!")

    st.markdown("**Navegação rápida**")
    st.markdown("➕ **Lançar** → Registrar despesa ou receita")
    st.markdown("📋 **Lançamentos** → Ver e liquidar")
    st.markdown("💰 **Saldos** → Real vs Livre")
    st.markdown("💳 **Cartões** → Faturas e pagamentos")
    st.markdown("🎯 **Metas** → Planejamento")
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
    st.caption("Registre entradas, saídas e compromissos futuros.")
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
        Vá até <strong>⚙️ Gestão → Seção 1</strong> e adicione ao menos uma
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

        # ── Status de liquidação ────────────────────────────────────
        data_str_preview = data_lancamento.strftime("%d/%m/%Y")
        status_auto = determinar_status_liquidacao(data_str_preview)

        st.markdown("---")
        col_liq1, col_liq2 = st.columns([2, 2])
        with col_liq1:
            if status_auto == "PREVISTO":
                st.markdown(
                    f'<span class="badge-previsto">🔵 PREVISTO — data futura, sem impacto no saldo real</span>',
                    unsafe_allow_html=True)
                status_liq_final = "PREVISTO"
            else:
                opcoes_status = ["PAGO — já efectuado", "PENDENTE — venceu mas ainda não pago"]
                status_choice = st.radio(
                    "**Status de liquidação**", opcoes_status,
                    horizontal=True,
                    help="PAGO afecta o Saldo Real imediatamente. PENDENTE fica como alerta.")
                status_liq_final = "PAGO" if "PAGO" in status_choice else "PENDENTE"

        with col_liq2:
            if status_auto == "PREVISTO":
                st.caption("💡 Datas futuras são automaticamente marcadas como PREVISTO. "
                           "O saldo real só será afectado ao liquidar.")
            elif status_liq_final == "PENDENTE":
                st.markdown(
                    '<div class="aviso-pendente">⚠️ Este lançamento ficará como pendente. '
                    'Use o botão ✅ na aba Lançamentos para liquidar quando pagar.</div>',
                    unsafe_allow_html=True)

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
                data_str = data_str_preview
                data_liq = data_str if status_liq_final == "PAGO" else None

                if forma_pag == "Cartão de Crédito" and cartao_sel_id:
                    dia_fech = db_query(
                        "SELECT dia_fechamento FROM cartoes WHERE id=?",
                        (cartao_sel_id,))[0][0]
                    fatura_ref = calcular_fatura_ref(data_str, dia_fech)
                    db_execute(
                        """INSERT INTO transacoes
                           (data,categoria_pai,categoria_filho,beneficiario,
                            fonte,valor_eur,tipo,nota,usuario,
                            forma_pagamento,cartao_id,fatura_ref,status_cartao,
                            status_liquidacao)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (data_str, sel_pai, sel_filho, beneficiario,
                         cartao_sel_nome, v_eur, tipo_val, nota,
                         st.session_state.display_name,
                         "Cartão de Crédito", cartao_sel_id,
                         fatura_ref, "pendente", "PAGO"))
                    st.session_state.ver += 1
                    st.success(f"✅ €{v_eur:.2f} no cartão **{cartao_sel_nome}** — fatura {fatura_ref}.")
                    st.rerun()
                else:
                    db_execute(
                        """INSERT INTO transacoes
                           (data,categoria_pai,categoria_filho,beneficiario,
                            fonte,valor_eur,tipo,nota,usuario,forma_pagamento,
                            status_liquidacao,data_liquidacao)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (data_str, sel_pai, sel_filho, beneficiario,
                         fonte, v_eur, tipo_val, nota,
                         st.session_state.display_name, "Dinheiro/Débito",
                         status_liq_final, data_liq))
                    st.session_state.ver += 1
                    if status_liq_final == "PREVISTO":
                        st.info(f"🔵 Lançamento PREVISTO registado: €{v_eur:.2f} em {data_str}")
                    elif status_liq_final == "PENDENTE":
                        st.warning(f"⏳ Lançamento PENDENTE registado: €{v_eur:.2f} — lembre de liquidar!")
                    st.rerun()


# ══════════════════════════════════════════════
#  TAB 2 — TODOS OS LANÇAMENTOS
# ══════════════════════════════════════════════
with tab2:
    st.markdown("## 📋 Histórico de Lançamentos")
    st.caption("Visualize, filtre, exporte, liquide ou remova registros.")
    st.divider()

    # ── Alerta de pendentes vencidos ──────────
    pend_list = get_pendentes_vencidos()
    if pend_list:
        total_pend_v = sum(r[3] for r in pend_list if r[4] == "Despesa")
        st.markdown(
            f'<div class="aviso-pendente">⚠️ <strong>Atenção: Contas Vencidas</strong> — '
            f'{len(pend_list)} transação(ões) PENDENTE(S) não liquidada(s). '
            f'Total em aberto: <strong>€{total_pend_v:,.2f}</strong>. '
            f'Clique em ✅ abaixo para liquidar.</div>',
            unsafe_allow_html=True)

    fontes_row2  = db_query("SELECT nome FROM fontes")
    cartoes_row2 = db_query("SELECT nome FROM cartoes")
    todas_fontes = (["Todas"] + [r[0] for r in fontes_row2]
                    + [r[0] for r in cartoes_row2])

    col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns(5)
    with col_f1:
        filtro_tipo   = st.selectbox("Tipo",   ["Todos","Despesa","Receita"])
    with col_f2:
        filtro_fonte  = st.selectbox("Conta",  todas_fontes)
    with col_f3:
        filtro_forma  = st.selectbox("Forma",  ["Todas","Dinheiro/Débito","Cartão de Crédito"])
    with col_f4:
        filtro_status = st.selectbox("Status", ["Todos","PAGO","PENDENTE","PREVISTO"])
    with col_f5:
        filtro_busca  = st.text_input("🔍 Buscar", placeholder="Nota, categoria...")

    df_hist = db_df("SELECT * FROM transacoes ORDER BY id DESC")

    if not df_hist.empty:
        if filtro_tipo   != "Todos":    df_hist = df_hist[df_hist['tipo'] == filtro_tipo]
        if filtro_fonte  != "Todas":    df_hist = df_hist[df_hist['fonte'] == filtro_fonte]
        if filtro_forma  != "Todas":    df_hist = df_hist[df_hist['forma_pagamento'] == filtro_forma]
        if filtro_status != "Todos":    df_hist = df_hist[df_hist['status_liquidacao'] == filtro_status]
        if filtro_busca:
            mask = (df_hist['nota'].str.contains(filtro_busca, case=False, na=False) |
                    df_hist['categoria_pai'].str.contains(filtro_busca, case=False, na=False) |
                    df_hist['categoria_filho'].str.contains(filtro_busca, case=False, na=False))
            df_hist = df_hist[mask]

    st.caption(f"📌 {len(df_hist)} registro(s)")

    # ── Exportação ─────────────────────────────
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

    # ── Botões de liquidação para PENDENTES/PREVISTOS ────
    df_liquidaveis = df_hist[
        df_hist['status_liquidacao'].isin(['PENDENTE','PREVISTO'])
    ] if not df_hist.empty else pd.DataFrame()

    if not df_liquidaveis.empty:
        st.markdown("**✅ Liquidar transações pendentes / previstas:**")
        for _, row in df_liquidaveis.iterrows():
            tid    = int(row['id'])
            sliq   = row['status_liquidacao']
            badge  = f'<span class="badge-pendente">PENDENTE</span>' if sliq == 'PENDENTE' \
                     else f'<span class="badge-previsto">PREVISTO</span>'
            col_a, col_b = st.columns([5, 1])
            with col_a:
                st.markdown(
                    f'<div class="liquidar-row">'
                    f'{badge} &nbsp; {row["data"]} &nbsp;|&nbsp; '
                    f'{row["categoria_pai"]}/{row["categoria_filho"] or "—"} &nbsp;|&nbsp; '
                    f'{row["beneficiario"] or "—"} &nbsp;|&nbsp; '
                    f'<strong>€{float(row["valor_eur"]):,.2f}</strong> ({row["tipo"]})'
                    f'</div>',
                    unsafe_allow_html=True)
            with col_b:
                if st.button("✅ Liquidar", key=f"liq_{tid}_{st.session_state.ver}",
                             use_container_width=True, type="primary"):
                    liquidar_transacao(tid, st.session_state.display_name)
                    st.session_state.ver += 1
                    st.toast(f"✅ Transação #{tid} liquidada! Saldo real actualizado.", icon="✅")
                    st.rerun()
        st.markdown("---")

    # ── Tabela completa ──────────────────────────
    if not df_hist.empty:
        df_edit = df_hist.copy()
        df_edit.insert(0, "Remover", False)
        df_display = df_edit.rename(columns={
            'id':'ID','data':'Data','categoria_pai':'Categoria',
            'categoria_filho':'Detalhamento','beneficiario':'Beneficiário',
            'fonte':'Conta/Cartão','valor_eur':'Valor (€)','tipo':'Tipo',
            'nota':'Observação','usuario':'Por',
            'forma_pagamento':'Forma','fatura_ref':'Fatura',
            'status_cartao':'St.Cartão',
            'status_liquidacao':'Liquidação','data_liquidacao':'Dt.Liq.'})
        editor = st.data_editor(
            df_display, key=f"ed_{st.session_state.ver}",
            use_container_width=True,
            column_config={
                "Remover":    st.column_config.CheckboxColumn("🗑️"),
                "Valor (€)":  st.column_config.NumberColumn(format="€ %.2f"),
                "Liquidação": st.column_config.SelectboxColumn(
                    options=["PAGO","PENDENTE","PREVISTO"]),
            })
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
    st.caption(
        "**Saldo Real** = dinheiro já efectivado (PAGO). "
        "**Saldo Livre** = Saldo Real − compromissos futuros (PENDENTE + PREVISTO + cartão).")
    st.divider()

    fontes_saldo = [r[0] for r in db_query("SELECT nome FROM fontes")]

    if not fontes_saldo:
        st.info("💡 Vá até ⚙️ Gestão para cadastrar suas contas bancárias.")
    else:
        total_real  = 0.0
        total_livre = 0.0
        cols_saldo  = st.columns(min(len(fontes_saldo), 3))

        for i, f in enumerate(fontes_saldo):
            saldo_r = calcular_saldo_real(f)
            saldo_l = calcular_saldo_livre(f)
            comp    = calcular_comprometido(f)
            total_real  += saldo_r
            total_livre += saldo_l

            # Passivo cartão
            passivo = db_query(
                "SELECT COALESCE(SUM(t.valor_eur),0) FROM transacoes t "
                "JOIN cartoes c ON t.cartao_id=c.id "
                "WHERE c.conta_pagamento=? AND t.status_cartao='pendente'", (f,))[0][0]

            ini_r   = db_query("SELECT valor_inicial FROM saldos_iniciais WHERE fonte=?", (f,))
            ini     = ini_r[0][0] if ini_r else 0.0
            ini_txt = f"&nbsp;|&nbsp; Inicial: €{ini:,.2f}" if ini != 0 else ""

            cls_r  = "saldo-card-positivo" if saldo_r >= 0 else "saldo-card-negativo"
            cls_vr = "valor-positivo"       if saldo_r >= 0 else "valor-negativo"
            sinal_r = "+" if saldo_r > 0 else ""

            cls_vl  = "valor-positivo" if saldo_l >= 0 else "valor-carmim"
            sinal_l = "+" if saldo_l > 0 else ""

            risco_txt = ""
            if saldo_l < 0:
                risco_txt = "<div style='margin-top:6px;font-size:0.8rem;color:#9b1c1c;font-weight:700;'>🚨 RISCO DE INSOLVÊNCIA</div>"

            with cols_saldo[i % 3]:
                st.markdown(f"""
                <div class="saldo-card {cls_r}">
                    <h3>🏦 {f}</h3>
                    <div class="{cls_vr}">{sinal_r}€ {saldo_r:,.2f}</div>
                    <div class="detalhe">Saldo Real (PAGO){ini_txt}</div>
                    <div style="margin-top:10px;padding-top:10px;border-top:1px solid #f1f5f9;">
                        <div class="{cls_vl}" style="font-size:1.4rem;">{sinal_l}€ {saldo_l:,.2f}</div>
                        <div class="detalhe">Saldo Livre (Real − Compromissos)</div>
                        {f"<div class='detalhe' style='color:#ef4444;margin-top:4px;'>Comprometido: €{comp:,.2f}" +
                         (f" | Cartão: €{passivo:,.2f}" if passivo > 0 else "") + "</div>"
                         if comp != 0 or passivo > 0 else ""}
                    </div>
                    {risco_txt}
                </div>""", unsafe_allow_html=True)

        st.divider()

        # Cards de totais
        col_tot1, col_tot2 = st.columns(2)
        with col_tot1:
            cls_tr = "valor-positivo" if total_real >= 0 else "valor-negativo"
            s_tr   = "+" if total_real > 0 else ""
            st.markdown(f"""<div class="saldo-card" style="background:#1e293b;border-left-color:#3b82f6;">
                <h3 style="color:#94a3b8;">🏦 SALDO REAL TOTAL</h3>
                <div class="{cls_tr}" style="font-size:2rem;">{s_tr}€ {total_real:,.2f}</div>
                <div class="detalhe" style="color:#64748b;">Dinheiro efectivamente disponível (PAGO)</div>
            </div>""", unsafe_allow_html=True)
        with col_tot2:
            is_insol = total_livre < 0
            card_cls = "saldo-card-insolvencia" if is_insol else ""
            cls_tl   = "valor-carmim" if is_insol else "valor-positivo" if total_livre >= 0 else "valor-negativo"
            s_tl     = "+" if total_livre > 0 else ""
            insol_msg = "<div class='detalhe' style='color:#9b1c1c;font-weight:700;margin-top:6px;'>🚨 RISCO DE INSOLVÊNCIA</div>" if is_insol else ""
            st.markdown(f"""<div class="saldo-card {card_cls}" style="{'background:#fef2f2;' if is_insol else 'background:#1e293b;'}border-left-color:{'#9b1c1c' if is_insol else '#10b981'};">
                <h3 style="color:{'#9b1c1c' if is_insol else '#94a3b8'};">📊 DISPONIBILIDADE REAL</h3>
                <div class="{cls_tl}" style="font-size:2rem;">{s_tl}€ {total_livre:,.2f}</div>
                <div class="detalhe" style="color:{'#9b1c1c' if is_insol else '#64748b'};">Saldo Real − todos os compromissos</div>
                {insol_msg}
            </div>""", unsafe_allow_html=True)

        # ── Saldos iniciais ──────────────────────────────────────────
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
                        st.success(f"Cartão **{n_cartao}** cadastrado!")
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
                    fat_ref      = fat['fatura_ref']
                    fat_total    = float(fat['total'])
                    fat_compras  = int(fat['n_compras'])
                    fat_pendente = bool(fat['tem_pendente'])
                    fat_pend_tot = calcular_total_fatura(cid, fat_ref)
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
                        saldo_c = calcular_saldo_real(conta_pag)
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
                                st.warning(f"⚠️ Saldo real em {conta_pag}: €{saldo_c:,.2f} (insuficiente)")

            trans_count = db_query("SELECT COUNT(*) FROM transacoes WHERE cartao_id=?", (cid,))[0][0]
            if trans_count == 0:
                if st.button(f"🗑️ Remover cartão {nome_c}", key=f"rm_cartao_{cid}", type="secondary"):
                    db_execute("DELETE FROM cartoes WHERE id=?", (cid,))
                    st.success(f"Cartão '{nome_c}' removido.")
                    st.session_state.ver += 1
                    st.rerun()
            else:
                st.caption(f"🔒 {nome_c} tem {trans_count} transação(ões) — remova-as na aba 📋 primeiro.")
            st.markdown("---")


# ══════════════════════════════════════════════
#  TAB 5 — METAS (PLANEJAMENTO DE ORÇAMENTO)
# ══════════════════════════════════════════════
with tab5:
    st.markdown("## 🎯 Planejamento de Metas")
    st.caption(
        "Defina metas de Despesa (teto de gastos) e de Receita (piso esperado) "
        "por categoria e mês."
    )
    st.divider()

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

    st.markdown('<div class="secao-titulo">➕ Adicionar / Actualizar Meta</div>', unsafe_allow_html=True)
    st.markdown('<div class="secao-sub">Se já existe meta para esta combinação, o valor será actualizado.</div>', unsafe_allow_html=True)

    cat_df_m    = db_df("SELECT id, nome, pai_id FROM categorias")
    pai_opts_m  = cat_df_m[cat_df_m['pai_id'].isna()]['nome'].tolist()
    benef_row_m = db_query("SELECT nome FROM beneficiarios ORDER BY nome")
    benef_m     = ["(Todos)"] + [r[0] for r in benef_row_m]

    if not pai_opts_m:
        st.warning("⚠️ Cadastre categorias em ⚙️ Gestão antes de definir metas.")
    else:
        with st.form("f_meta", clear_on_submit=True):
            col_m_a, col_m_b, col_m_c = st.columns(3)
            with col_m_a:
                meta_tipo = st.radio(
                    "**Tipo de Meta**", ["💸 Despesa", "💵 Receita"], horizontal=True,
                    help="Despesa: teto máximo. Receita: piso mínimo esperado.")
                meta_tipo_val = "Despesa" if "Despesa" in meta_tipo else "Receita"
                meta_pai = st.selectbox("Categoria Principal", pai_opts_m)
                pid_m = int(cat_df_m[cat_df_m['nome'] == meta_pai]['id'].iloc[0])
                filhos_m = cat_df_m[cat_df_m['pai_id'] == pid_m]['nome'].tolist()
                meta_filho = st.selectbox("Detalhamento", ["(Todos)"] + filhos_m)
            with col_m_b:
                meta_benef = st.selectbox("Beneficiário", benef_m)
                meta_valor = st.number_input(
                    "Valor previsto (€)", min_value=0.01, step=10.0, format="%.2f", value=100.0)
            with col_m_c:
                st.markdown("<br><br><br><br>", unsafe_allow_html=True)
                submitted_meta = st.form_submit_button(
                    "💾 Salvar Meta", use_container_width=True, type="primary")

            if submitted_meta:
                filho_db = "" if meta_filho == "(Todos)" else meta_filho
                benef_db = "" if meta_benef == "(Todos)" else meta_benef
                existe = db_query(
                    "SELECT id FROM orcamentos "
                    "WHERE mes_ano=? AND categoria_pai=? "
                    "AND categoria_filho=? AND beneficiario=? AND tipo_meta=?",
                    (mes_ano_sel, meta_pai, filho_db, benef_db, meta_tipo_val))
                if existe:
                    db_execute(
                        "UPDATE orcamentos SET valor_previsto=? "
                        "WHERE mes_ano=? AND categoria_pai=? "
                        "AND categoria_filho=? AND beneficiario=? AND tipo_meta=?",
                        (meta_valor, mes_ano_sel, meta_pai, filho_db, benef_db, meta_tipo_val))
                    log_audit("META_UPDATE",
                              f"mes={mes_ano_sel} tipo={meta_tipo_val} "
                              f"cat={meta_pai}/{filho_db} valor={meta_valor}",
                              st.session_state.display_name)
                    st.success(f"Meta actualizada: [{meta_tipo_val}] {meta_pai}/{meta_filho or 'Todos'} → €{meta_valor:.2f}")
                else:
                    db_execute(
                        "INSERT INTO orcamentos "
                        "(mes_ano,categoria_pai,categoria_filho,beneficiario,valor_previsto,tipo_meta) "
                        "VALUES (?,?,?,?,?,?)",
                        (mes_ano_sel, meta_pai, filho_db, benef_db, meta_valor, meta_tipo_val))
                    log_audit("META_INSERT",
                              f"mes={mes_ano_sel} tipo={meta_tipo_val} "
                              f"cat={meta_pai}/{filho_db} valor={meta_valor}",
                              st.session_state.display_name)
                    st.success(f"Meta criada: [{meta_tipo_val}] {meta_pai}/{meta_filho or 'Todos'} → €{meta_valor:.2f}")
                st.session_state.ver += 1
                st.rerun()

    st.divider()
    st.markdown(f"**Metas definidas para {mes_ano_sel}:**")

    metas_df = db_df(
        "SELECT id, tipo_meta, categoria_pai, categoria_filho, "
        "beneficiario, valor_previsto "
        "FROM orcamentos WHERE mes_ano=? "
        "ORDER BY tipo_meta DESC, categoria_pai, categoria_filho",
        params=(mes_ano_sel,))

    if metas_df.empty:
        st.info(f"Nenhuma meta definida para {mes_ano_sel}. Use o formulário acima.")
    else:
        metas_df['realizado'] = metas_df.apply(
            lambda r: get_realizado_mes(
                mes_ano_sel, tipo=r['tipo_meta'],
                categoria_pai=r['categoria_pai'],
                categoria_filho=r['categoria_filho'] if r['categoria_filho'] else None
            ), axis=1)
        metas_df['% uso'] = metas_df.apply(
            lambda r: round(r['realizado'] / r['valor_previsto'] * 100, 1)
            if r['valor_previsto'] > 0 else 0.0, axis=1)
        metas_df = metas_df.rename(columns={
            'tipo_meta': 'Tipo', 'categoria_pai': 'Categoria',
            'categoria_filho': 'Detalhamento', 'beneficiario': 'Beneficiário',
            'valor_previsto': 'Previsto (€)', 'realizado': 'Realizado (€)'})
        metas_df.insert(0, "Remover", False)
        ed_metas = st.data_editor(
            metas_df, key=f"ed_metas_{st.session_state.ver}",
            use_container_width=True,
            column_config={
                "Remover":       st.column_config.CheckboxColumn("🗑️"),
                "Previsto (€)":  st.column_config.NumberColumn(format="€ %.2f"),
                "Realizado (€)": st.column_config.NumberColumn(format="€ %.2f"),
                "% uso":         st.column_config.NumberColumn(format="%.1f %%"),
            })
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

        st.divider()
        col_tot_d, col_tot_r = st.columns(2)
        df_desp = metas_df[metas_df['Tipo'] == 'Despesa']
        df_rec  = metas_df[metas_df['Tipo'] == 'Receita']
        with col_tot_d:
            st.markdown("**💸 Despesas**")
            prev_d = df_desp['Previsto (€)'].sum() if not df_desp.empty else 0.0
            real_d = df_desp['Realizado (€)'].sum() if not df_desp.empty else 0.0
            delta_d = prev_d - real_d
            c1,c2,c3 = st.columns(3)
            c1.metric("Planejado",  f"€ {prev_d:,.2f}")
            c2.metric("Realizado",  f"€ {real_d:,.2f}")
            c3.metric("Margem",     f"€ {delta_d:,.2f}",
                      delta=f"€ {delta_d:,.2f}",
                      delta_color="normal" if delta_d >= 0 else "inverse")
        with col_tot_r:
            st.markdown("**💵 Receitas**")
            prev_r = df_rec['Previsto (€)'].sum() if not df_rec.empty else 0.0
            real_r = df_rec['Realizado (€)'].sum() if not df_rec.empty else 0.0
            delta_r = real_r - prev_r
            c1,c2,c3 = st.columns(3)
            c1.metric("Meta",      f"€ {prev_r:,.2f}")
            c2.metric("Realizado", f"€ {real_r:,.2f}")
            c3.metric("Superávit", f"€ {delta_r:,.2f}",
                      delta=f"€ {delta_r:,.2f}",
                      delta_color="normal" if delta_r >= 0 else "inverse")


# ══════════════════════════════════════════════
#  TAB 6 — DASHBOARD DE SAÚDE FINANCEIRA
# ══════════════════════════════════════════════
with tab6:
    st.markdown("## 📊 Dashboard de Saúde Financeira")
    st.caption("Painel em tempo real — liquidez, orçamento e saúde financeira.")
    st.divider()

    hoje_d = datetime.now()
    col_d1, col_d2, _ = st.columns([1, 1, 4])
    with col_d1:
        dash_ano = st.number_input("Ano", min_value=2020, max_value=2100,
                                    value=hoje_d.year, step=1, key="dash_ano")
    with col_d2:
        dash_mes = st.number_input("Mês", min_value=1, max_value=12,
                                    value=hoje_d.month, step=1, key="dash_mes")
    dash_mes_ano = f"{int(dash_ano):04d}-{int(dash_mes):02d}"
    ano_d, mes_d = dash_mes_ano.split("-")

    # ── BLOCO 1: Liquidez ──────────────────────
    st.markdown(f"### 💧 Liquidez — {dash_mes_ano}")

    fontes_dash = [r[0] for r in db_query("SELECT nome FROM fontes")]
    total_real_dash  = sum(calcular_saldo_real(f)  for f in fontes_dash)
    total_livre_dash = sum(calcular_saldo_livre(f) for f in fontes_dash)
    total_comp_dash  = sum(calcular_comprometido(f) for f in fontes_dash)
    total_pend_dash  = get_total_pendentes()
    risco_global     = total_livre_dash < 0

    # Alerta de insolvência
    if risco_global:
        st.markdown(
            f'<div class="aviso-insolvencia">🚨 <strong>ALERTA: RISCO DE INSOLVÊNCIA</strong> — '
            f'A Disponibilidade Real é de <strong>€{total_livre_dash:,.2f}</strong>. '
            f'Os compromissos futuros superam o saldo disponível.</div>',
            unsafe_allow_html=True)

    # Alerta de pendentes
    if total_pend_dash > 0:
        pend_count = len(get_pendentes_vencidos())
        st.markdown(
            f'<div class="aviso-pendente">⏳ <strong>Atenção: Contas Vencidas</strong> — '
            f'{pend_count} transação(ões) PENDENTE(S) | '
            f'Total: <strong>€{total_pend_dash:,.2f}</strong>. '
            f'Aceda à aba 📋 Lançamentos para liquidar.</div>',
            unsafe_allow_html=True)

    col_lq1, col_lq2, col_lq3, col_lq4 = st.columns(4)
    with col_lq1:
        cls_r2 = "valor-positivo" if total_real_dash >= 0 else "valor-negativo"
        s_r2   = "+" if total_real_dash > 0 else ""
        st.markdown(f"""<div class="saldo-card">
            <h3>🏦 Saldo Real</h3>
            <div class="{cls_r2}">€ {total_real_dash:,.2f}</div>
            <div class="detalhe">Dinheiro já efectivado (PAGO)</div>
        </div>""", unsafe_allow_html=True)
    with col_lq2:
        cls_comp = "valor-neutro" if total_comp_dash > 0 else "valor-positivo"
        st.markdown(f"""<div class="saldo-card">
            <h3>⏳ Comprometido</h3>
            <div class="{cls_comp}">€ {total_comp_dash:,.2f}</div>
            <div class="detalhe">PENDENTE + PREVISTO + Cartão</div>
        </div>""", unsafe_allow_html=True)
    with col_lq3:
        if risco_global:
            st.markdown(f"""<div class="saldo-card saldo-card-insolvencia">
                <h3>⚠️ Disponibilidade Real</h3>
                <div class="valor-carmim">€ {total_livre_dash:,.2f}</div>
                <div class="detalhe" style="color:#9b1c1c;font-weight:600;">🚨 Risco de Insolvência</div>
            </div>""", unsafe_allow_html=True)
        else:
            cls_l2 = "valor-positivo" if total_livre_dash >= 0 else "valor-negativo"
            s_l2   = "+" if total_livre_dash > 0 else ""
            st.markdown(f"""<div class="saldo-card saldo-card-positivo">
                <h3>✅ Disponibilidade Real</h3>
                <div class="{cls_l2}">{s_l2}€ {total_livre_dash:,.2f}</div>
                <div class="detalhe">Saldo Real − todos os compromissos</div>
            </div>""", unsafe_allow_html=True)
    with col_lq4:
        cls_pend = "valor-negativo" if total_pend_dash > 0 else "valor-positivo"
        st.markdown(f"""<div class="saldo-card">
            <h3>🔴 Contas Vencidas</h3>
            <div class="{cls_pend}">€ {total_pend_dash:,.2f}</div>
            <div class="detalhe">PENDENTES não liquidadas</div>
        </div>""", unsafe_allow_html=True)

    st.divider()

    # ── BLOCO 2: Orçamento ────────────────────
    st.markdown(f"### 🌍 Orçamento — {dash_mes_ano}")

    prev_des_d = db_query(
        "SELECT COALESCE(SUM(valor_previsto),0) FROM orcamentos "
        "WHERE mes_ano=? AND tipo_meta='Despesa'", (dash_mes_ano,))[0][0]
    real_des_d = get_realizado_mes(dash_mes_ano, tipo="Despesa")
    prev_rec_d = db_query(
        "SELECT COALESCE(SUM(valor_previsto),0) FROM orcamentos "
        "WHERE mes_ano=? AND tipo_meta='Receita'", (dash_mes_ano,))[0][0]
    real_rec_d = get_realizado_mes(dash_mes_ano, tipo="Receita")
    saldo_mes_d = real_rec_d - real_des_d
    pct_des_d   = (real_des_d / prev_des_d * 100) if prev_des_d > 0 else 0
    pct_rec_d   = (real_rec_d / prev_rec_d * 100) if prev_rec_d > 0 else 0

    col_g1, col_g2, col_g3 = st.columns(3)
    with col_g1:
        cls_d = "valor-negativo" if real_des_d > prev_des_d and prev_des_d > 0 else "valor-neutro"
        st.markdown(f"""<div class="saldo-card">
            <h3>💸 Despesas</h3>
            <div class="{cls_d}">€ {real_des_d:,.2f}</div>
            <div class="detalhe">Meta: €{prev_des_d:,.2f} | {pct_des_d:.0f}% utilizado</div>
        </div>""", unsafe_allow_html=True)
    with col_g2:
        cls_r = "valor-positivo" if real_rec_d >= prev_rec_d and prev_rec_d > 0 else \
                "valor-neutro"   if real_rec_d >= prev_rec_d*0.8 else "valor-negativo"
        st.markdown(f"""<div class="saldo-card">
            <h3>💵 Receitas</h3>
            <div class="{cls_r}">€ {real_rec_d:,.2f}</div>
            <div class="detalhe">Meta: €{prev_rec_d:,.2f} | {pct_rec_d:.0f}% atingido</div>
        </div>""", unsafe_allow_html=True)
    with col_g3:
        cls_sl = "valor-positivo" if saldo_mes_d >= 0 else "valor-negativo"
        s_sl   = "+" if saldo_mes_d > 0 else ""
        st.markdown(f"""<div class="saldo-card">
            <h3>⚖️ Saldo do Mês</h3>
            <div class="{cls_sl}">{s_sl}€ {saldo_mes_d:,.2f}</div>
            <div class="detalhe">Receitas − Despesas</div>
        </div>""", unsafe_allow_html=True)

    if prev_des_d > 0:
        prog_des = min(pct_des_d/100, 1.0)
        ic_des   = "🟢" if pct_des_d < 80 else "🟡" if pct_des_d <= 100 else "🔴"
        st.progress(prog_des, text=f"💸 Despesas: {ic_des} {pct_des_d:.1f}% do orçamento")
    if prev_rec_d > 0:
        prog_rec = min(pct_rec_d/100, 1.0)
        ic_rec   = "🟢" if pct_rec_d >= 100 else "🟡" if pct_rec_d >= 80 else "🔴"
        st.progress(prog_rec, text=f"💵 Receitas: {ic_rec} {pct_rec_d:.1f}% da meta atingida")

    st.divider()

    # ── Semáforo por Categoria ─────────────────
    st.markdown("### 🚦 Saúde por Categoria")
    saude = get_saude_orcamento(dash_mes_ano)

    if not saude:
        st.info(f"Nenhuma meta definida para {dash_mes_ano}. Crie metas na aba 🎯 Metas.")
    else:
        saude_des = [s for s in saude if s['tipo_meta'] == 'Despesa']
        saude_rec = [s for s in saude if s['tipo_meta'] == 'Receita']
        for grupo_label, grupo_items in [("💸 Metas de Despesa", saude_des),
                                          ("💵 Metas de Receita", saude_rec)]:
            if not grupo_items:
                continue
            st.markdown(f"**{grupo_label}**")
            col_s1, col_s2 = st.columns(2)
            for idx, item in enumerate(grupo_items):
                css_class = f"gauge-{item['status']}"
                icone     = "🟢" if item['status']=="verde" else "🟡" if item['status']=="amarelo" else "🔴"
                prog_val  = min(item['pct']/100, 1.0)
                label_cat = item['cat_pai'] + (f" / {item['cat_filho']}" if item['cat_filho'] else "")
                if item['tipo_meta'] == "Despesa":
                    diferenca = item['previsto'] - item['realizado']
                    msg_dif = (f"Margem: €{abs(diferenca):,.2f}" if diferenca >= 0
                               else f"⚠️ Estouro: €{abs(diferenca):,.2f}")
                else:
                    diferenca = item['realizado'] - item['previsto']
                    msg_dif = (f"Superávit: €{abs(diferenca):,.2f}" if diferenca >= 0
                               else f"⚠️ Déficit: €{abs(diferenca):,.2f}")
                with (col_s1 if idx % 2 == 0 else col_s2):
                    st.markdown(f"""
                    <div class="{css_class}">
                        <div class="gauge-titulo">{icone} {label_cat}</div>
                        <div class="gauge-sub">
                            Realizado: <strong>€{item['realizado']:,.2f}</strong>
                            &nbsp;/&nbsp;
                            {"Limite" if item['tipo_meta']=="Despesa" else "Meta"}: <strong>€{item['previsto']:,.2f}</strong>
                            &nbsp;—&nbsp; {msg_dif}
                        </div>
                    </div>""", unsafe_allow_html=True)
                    st.progress(prog_val,
                        text=f"{item['pct']:.1f}% {'utilizado' if item['tipo_meta']=='Despesa' else 'atingido'}")

    st.divider()

    # ── Top 3 Beneficiários ──────────────────────
    st.markdown("### 🔎 Análise de Causa Raiz")
    col_top_d, col_top_r = st.columns(2)
    with col_top_d:
        st.markdown("**💸 Top 3 — Quem mais gastou**")
        top3_des = get_top_beneficiarios(dash_mes_ano, tipo="Despesa", n=3)
        if not top3_des:
            st.info("Nenhuma despesa registada.")
        else:
            max_d = max(t[1] for t in top3_des) or 1
            for i, (nome, total) in enumerate(top3_des):
                medalha = ["🥇","🥈","🥉"][i]
                st.markdown(f"""<div class="top-benef-card">
                    <div><span style="font-size:1.2rem;">{medalha}</span>
                    <strong style="margin-left:8px;">{nome}</strong></div>
                    <div style="font-weight:700;">€ {total:,.2f}</div>
                </div>""", unsafe_allow_html=True)
                st.progress(total/max_d)
    with col_top_r:
        st.markdown("**💵 Top 3 — Quem mais trouxe receita**")
        top3_rec = get_top_beneficiarios(dash_mes_ano, tipo="Receita", n=3)
        if not top3_rec:
            st.info("Nenhuma receita registada.")
        else:
            max_r = max(t[1] for t in top3_rec) or 1
            for i, (nome, total) in enumerate(top3_rec):
                medalha = ["🥇","🥈","🥉"][i]
                st.markdown(f"""<div class="top-benef-card">
                    <div><span style="font-size:1.2rem;">{medalha}</span>
                    <strong style="margin-left:8px;">{nome}</strong></div>
                    <div style="font-weight:700;color:#16a34a;">€ {total:,.2f}</div>
                </div>""", unsafe_allow_html=True)
                st.progress(total/max_r)

    st.divider()

    # ── Relatório ──────────────────────────────
    st.markdown("### 📋 Relatório Previsto vs. Realizado")
    if saude:
        df_report = pd.DataFrame([{
            "Tipo":          s["tipo_meta"],
            "Categoria":     s["cat_pai"] + (" / " + s["cat_filho"] if s["cat_filho"] else ""),
            "Beneficiário":  s["beneficiario"] or "Todos",
            "Previsto (€)":  s["previsto"],
            "Realizado (€)": s["realizado"],
            "Δ (€)":         (s["previsto"]-s["realizado"] if s["tipo_meta"]=="Despesa"
                               else s["realizado"]-s["previsto"]),
            "% Atingido":    round(s["pct"], 1),
            "Status":        s["status"].upper(),
        } for s in saude])
        st.dataframe(df_report, use_container_width=True, hide_index=True,
            column_config={
                "Previsto (€)":  st.column_config.NumberColumn(format="€ %.2f"),
                "Realizado (€)": st.column_config.NumberColumn(format="€ %.2f"),
                "Δ (€)":         st.column_config.NumberColumn(format="€ %.2f"),
                "% Atingido":    st.column_config.NumberColumn(format="%.1f %%"),
            })
        csv_rep = df_report.to_csv(index=False).encode('utf-8-sig')
        st.download_button("⬇️ Exportar Relatório CSV", csv_rep,
            f"relatorio_{dash_mes_ano}.csv", "text/csv")
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
