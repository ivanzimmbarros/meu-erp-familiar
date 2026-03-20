import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import io
import logging
from datetime import datetime, date, timedelta

def criar_quadro_legivel(titulo):
    st.markdown(f"""
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 10px; border: 1px solid #dee2e6;">
            <p style="color: #212529; font-weight: bold; font-size: 18px; margin: 0;">{titulo}</p>
        </div>
    """, unsafe_allow_html=True)

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
    /* Estilo para as linhas de liquidação */
    .liquidar-row {
        background-color: #f8f9fa;
        padding: 12px;
        border-radius: 8px;
        border-left: 5px solid #6c757d;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        font-size: 0.95em;
    }
    
    /* Badges de Status */
    .badge-pendente {
        background-color: #fff3cd;
        color: #856404;
        padding: 2px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 0.8em;
        border: 1px solid #ffeeba;
    }
    
    .badge-previsto {
        background-color: #d1ecf1;
        color: #0c5460;
        padding: 2px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 0.8em;
        border: 1px solid #bee5eb;
    }

    /* Ajuste para o botão dentro do expander */
    div[data-testid="stButton"] button {
        height: 38px;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
#  ESTADO DA SESSÃO
# ─────────────────────────────────────────────
def init_session():
    defaults = {'ver': 0, 'logado': False, 'display_name': None, 'taxa_brl_eur': 0.16}
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v
init_session()

# ─────────────────────────────────────────────
#  HELPERS DE BANCO (Mantidos conforme original)
# ─────────────────────────────────────────────
DB_PATH = 'finance.db'

from dateutil.relativedelta import relativedelta
from datetime import datetime

def calcular_parcelas(data_compra_str, dia_fechamento, dia_vencimento, valor_total, total_parcelas):
    """
    Retorna uma lista de tuplas: (data_vencimento_formatada, valor_parcela, numero_parcela)
    """
    parcelas = []
    
    # Converter string de data para objeto datetime
    d = datetime.strptime(data_compra_str, "%Y-%m-%d")
    
    # Cálculo base do valor
    valor_parcela = round(valor_total / total_parcelas, 2)
    valor_ultima = round(valor_total - (valor_parcela * (total_parcelas - 1)), 2)
    
    # Lógica de virada de mês da fatura:
    # Se a compra foi feita após o dia de fechamento, a 1ª parcela cai na fatura do mês seguinte.
    # Caso contrário, cai na fatura do mês atual.
    mes_offset = 0 if d.day <= dia_fechamento else 1
    
    for i in range(total_parcelas):
        num = i + 1
        # Calcula a data de vencimento daquela parcela específica
        data_venc = d + relativedelta(months=mes_offset + i, day=dia_vencimento)
        
        # Atribui o valor (ajustando a última parcela para fechar o total exato)
        valor = valor_ultima if num == total_parcelas else valor_parcela
        
        parcelas.append((data_venc.strftime("%Y-%m-%d"), valor, num))
        
    return parcelas

def db_query(sql, params=()):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try: return conn.execute(sql, params).fetchall()
    finally: conn.close()

def db_execute(sql, params=()):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try: conn.execute("PRAGMA foreign_keys = ON"); conn.execute(sql, params); conn.commit()
    finally: conn.close()

def db_execute_many(sqls_params):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try: 
        conn.execute("PRAGMA foreign_keys = ON")
        for sql, params in sqls_params: conn.execute(sql, params)
        conn.commit()
    finally: conn.close()

def db_df(sql, params=()):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try: return pd.read_sql_query(sql, conn, params=params)
    finally: conn.close()

def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()


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
        # ── MÓDULO PARCELAMENTO (NOVO) ──
        ("parcela_id",       "TEXT"),
        ("parcela_numero",   "INTEGER DEFAULT 1"),
        ("total_parcelas",   "INTEGER DEFAULT 1"),    
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
        c.execute('''CREATE TABLE IF NOT EXISTS recorrentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            valor_eur REAL NOT NULL,
            categoria_pai TEXT NOT NULL,
            categoria_filho TEXT,
            dia_vencimento INTEGER NOT NULL,
            fonte TEXT NOT NULL,
            forma_pagamento TEXT NOT NULL
        )''')
    
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


# 1. Inicializa o banco
init_db()

# 2. Definição da função de segurança (VERSÃO SEGURA)
def verificar_bloqueio_delecao(tabela, id_item):
    """Retorna True se houver dependências que impedem a exclusão."""
    
    if tabela == "categorias":
        # Verifica se o ID existe antes de processar
        res_nome = db_query("SELECT nome FROM categorias WHERE id=?", (id_item,))
        if not res_nome: return False 
        nome_cat = res_nome[0][0]

        # Verifica subcategorias
        tem_sub = db_query("SELECT id FROM categorias WHERE pai_id=?", (id_item,))
        
        # Verifica transações associadas
        tem_trans = db_query("SELECT id FROM transacoes WHERE categoria_pai=? OR categoria_filho=?", 
                             (nome_cat, nome_cat))
        
        return len(tem_sub) > 0 or len(tem_trans) > 0

    if tabela == "fontes":
        # Verifica se o ID existe antes de processar
        res_conta = db_query("SELECT nome FROM fontes WHERE id=?", (id_item,))
        if not res_conta: return False
        nome_conta = res_conta[0][0]
        
        # Verifica transações vinculadas
        tem_trans = db_query("SELECT id FROM transacoes WHERE fonte=?", (nome_conta,))
        return len(tem_trans) > 0
        
    return False

# 3. Carregamento de configurações iniciais
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


def ajustar_saldo(fonte_nome, valor_banco, usuario):
    """
    Bate o saldo do sistema com o saldo real informado pelo utilizador.
    Cria uma transação de ajuste (Receita ou Despesa) com status PAGO.
    Retorna dict com detalhes do ajuste, ou None se já bate.
    Regista no log de auditoria.
    """
    saldo_calc = calcular_saldo_real(fonte_nome)
    diff = round(valor_banco - saldo_calc, 4)
    if abs(diff) < 0.005:
        return None  # saldo já coincide — nada a fazer

    hoje = datetime.now().strftime("%d/%m/%Y")
    tipo_aj = "Receita" if diff > 0 else "Despesa"
    nota_aj = (
        f"Ajuste de saldo — banco: €{valor_banco:.2f} | "
        f"sistema: €{saldo_calc:.2f} | diff: €{diff:+.2f}"
    )
    try:
        db_execute(
            "INSERT INTO transacoes "
            "(data,categoria_pai,categoria_filho,beneficiario,fonte,"
            "valor_eur,tipo,nota,usuario,forma_pagamento,"
            "status_liquidacao,data_liquidacao) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (hoje, "Ajuste de Saldo", "", "Ajuste Automático", fonte_nome,
             abs(diff), tipo_aj, nota_aj, usuario,
             "Dinheiro/Débito", "PAGO", hoje)
        )
        log_audit(
            "AJUSTE_SALDO",
            f"conta={fonte_nome} banco={valor_banco:.2f} "
            f"sistema={saldo_calc:.2f} diff={diff:+.2f}",
            usuario
        )
    except Exception as e:
        raise RuntimeError(f"Erro ao registar ajuste: {e}") from e

    return {"tipo": tipo_aj, "diferenca": diff, "valor_banco": valor_banco,
            "saldo_anterior": saldo_calc, "data": hoje}


def gerar_relatorio_excel(mes_ano):
    """
    Gera relatório Excel com 3 abas:
      - Transações do Mês
      - Resumo por Categoria
      - Metas vs Realizado
    Nome do ficheiro sugerido: ERP_Familiar_Backup_MM_AAAA.xlsx
    """
    ano, mes = mes_ano.split("-")

    # Aba 1 — Transações do mês
    df_trans = db_df(
        """SELECT data as "Data", categoria_pai as "Categoria",
                  categoria_filho as "Detalhamento",
                  beneficiario as "Beneficiário",
                  fonte as "Conta/Cartão",
                  valor_eur as "Valor (€)",
                  tipo as "Tipo", nota as "Observação",
                  status_liquidacao as "Liquidação",
                  data_liquidacao as "Dt. Liquidação",
                  usuario as "Registado por"
           FROM transacoes
           WHERE substr(data,4,2)=? AND substr(data,7,4)=?
           ORDER BY data, id""",
        (mes, ano)
    )

    # Aba 2 — Resumo por Categoria
    df_cat = db_df(
        """SELECT tipo as "Tipo",
                  categoria_pai as "Categoria",
                  categoria_filho as "Detalhamento",
                  COUNT(*) as "Qtd. Lançamentos",
                  COALESCE(SUM(valor_eur),0) as "Total (€)"
           FROM transacoes
           WHERE substr(data,4,2)=? AND substr(data,7,4)=?
           GROUP BY tipo, categoria_pai, categoria_filho
           ORDER BY tipo, "Total (€)" DESC""",
        (mes, ano)
    )

    # Aba 3 — Metas vs Realizado
    metas = db_query(
        "SELECT tipo_meta, categoria_pai, categoria_filho, "
        "beneficiario, valor_previsto "
        "FROM orcamentos WHERE mes_ano=? "
        "ORDER BY tipo_meta, categoria_pai",
        (mes_ano,)
    )
    rows_meta = []
    for tipo_m, cat_p, cat_f, benef, prev in metas:
        real = db_query(
            "SELECT COALESCE(SUM(valor_eur),0) FROM transacoes "
            "WHERE tipo=? AND categoria_pai=? "
            "AND substr(data,4,2)=? AND substr(data,7,4)=?",
            (tipo_m, cat_p, mes, ano)
        )[0][0]
        pct = round(real / prev * 100, 1) if prev > 0 else 0.0
        diff_v = (prev - real) if tipo_m == "Despesa" else (real - prev)
        rows_meta.append({
            "Tipo": tipo_m,
            "Categoria": cat_p,
            "Detalhamento": cat_f or "Todos",
            "Beneficiário": benef or "Todos",
            "Previsto (€)": round(prev, 2),
            "Realizado (€)": round(real, 2),
            "Diferença (€)": round(diff_v, 2),
            "% Atingido": pct,
        })
    df_metas = pd.DataFrame(rows_meta) if rows_meta else pd.DataFrame(
        columns=["Tipo","Categoria","Detalhamento","Beneficiário",
                 "Previsto (€)","Realizado (€)","Diferença (€)","% Atingido"])

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df_trans.to_excel(writer, index=False, sheet_name='Transações do Mês')
        df_cat.to_excel(writer, index=False, sheet_name='Resumo por Categoria')
        df_metas.to_excel(writer, index=False, sheet_name='Metas vs Realizado')
    buf.seek(0)
    return buf.getvalue()


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


# ─────────────────────────────────────────────
#  TAB 1 — NOVO LANÇAMENTO (COMPLETA E VALIDADA)
# ─────────────────────────────────────────────

with tab1:
    st.markdown("## ➕ Registrar uma Movimentação")
    st.divider()

    # --- 1. Estado Inicial (Session State) ---
    if 'tipo_mov' not in st.session_state: st.session_state.tipo_mov = "💸 Despesa"
    if 'forma_pag' not in st.session_state: st.session_state.forma_pag = "Dinheiro/Débito"

        # 2. Controles de Escolha (Reativos)
    col_tp1, col_tp2 = st.columns(2)
    st.session_state.tipo_mov = col_tp1.radio("Tipo de movimentação", ["💸 Despesa", "💵 Receita"], horizontal=True)
    st.session_state.forma_pag = col_tp2.radio("Forma de pagamento", ["Dinheiro/Débito", "Cartão de Crédito"], horizontal=True)

    # Lógica de controle: Parcelamento permitido se for Despesa (independente da fonte)
    eh_despesa = "Despesa" in st.session_state.tipo_mov
    is_cartao = (st.session_state.forma_pag == "Cartão de Crédito" and eh_despesa)
    
    if is_cartao:
        label_fonte = "💳 Selecione o Cartão"
        dados_fonte = db_query("SELECT id, nome FROM cartoes ORDER BY nome")
    else:
        label_fonte = "🏦 Conta / Fonte"
        dados_fonte = db_query("SELECT id, nome FROM fontes ORDER BY nome")

    # --- 3. Formulário ---
    with st.form("form_transacao", clear_on_submit=True):
        fonte_selecionada = st.selectbox(label_fonte, [op[1] for op in dados_fonte])
        col_in1, col_in2 = st.columns(2)
        data_input = col_in1.date_input("Data", value=date.today())
        valor_input = col_in2.number_input("Valor (€)", min_value=0.01, step=1.0, format="%.2f")
        
        # Agora o input de parcelas aparece sempre que for despesa
        num_parcelas = 1
        if eh_despesa:
            num_parcelas = col_in1.number_input("Parcelas", min_value=1, max_value=24, value=1)
        
        # ... (restante do código: Categoria, Beneficiário, Nota)
        cat_df = db_df("SELECT id, nome, pai_id FROM categorias")
        pai_opts = cat_df[cat_df['pai_id'].isna()]['nome'].tolist()
        cat_pai = st.selectbox("Categoria Principal", pai_opts)
        benef_db = db_query("SELECT nome FROM beneficiarios ORDER BY nome")
        lista_benef = [""] + [b[0] for b in benef_db]
        beneficiario = st.selectbox("Beneficiário", lista_benef)
        nota = st.text_input("Observação (opcional)")
        submit_button = st.form_submit_button("Salvar Transação")

    # --- 4. Processamento ---
    if submit_button:
        if not beneficiario:
            st.error("Por favor, selecione um beneficiário.")
        else:
            try:
                id_fonte = [op[0] for op in dados_fonte if op[1] == fonte_selecionada][0]

                # Lógica de parcelamento (agora para Cartão OU Débito)
                if eh_despesa and num_parcelas > 1:
                    if is_cartao:
                        cartao_info = db_query("SELECT dia_fechamento, dia_vencimento FROM cartoes WHERE id=?", (id_fonte,))[0]
                        lista_parcelas = calcular_parcelas(data_input.strftime("%Y-%m-%d"), cartao_info[0], cartao_info[1], valor_input, num_parcelas)
                    else:
                        # Para Débito, parcelas mensais simples a partir da data informada
                        lista_parcelas = []
                        v_p = round(valor_input / num_parcelas, 2)
                        for i in range(num_parcelas):
                            data_v = data_input + relativedelta(months=i)
                            lista_parcelas.append((data_v.strftime("%Y-%m-%d"), v_p, i + 1))

                    for data_venc, val, num in lista_parcelas:
                        db_execute('''INSERT INTO transacoes 
                            (data, categoria_pai, beneficiario, fonte, valor_eur, tipo, nota, usuario, forma_pagamento, cartao_id, status_liquidacao, fatura_ref, status_cartao) 
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (data_input.strftime("%Y-%m-%d"), cat_pai, beneficiario, fonte_selecionada, val, st.session_state.tipo_mov, 
                             f"{nota} (Parc {num}/{num_parcelas})", st.session_state.get('display_name', 'Admin'), 
                             st.session_state.forma_pag, id_fonte if is_cartao else None, "PENDENTE", data_venc, "pendente" if is_cartao else None))
                    
                    st.success(f"Despesa parcelada em {num_parcelas}x com sucesso!")

                else:
                    # Transação única
                    fatura_ref = None
                    if is_cartao:
                        fechamento = int(db_query("SELECT dia_fechamento FROM cartoes WHERE id=?", (id_fonte,))[0][0])
                        fatura_ref = calcular_fatura_ref(data_input.strftime("%d/%m/%Y"), fechamento)

                    db_execute('''INSERT INTO transacoes (data, categoria_pai, beneficiario, fonte, valor_eur, tipo, nota, usuario, forma_pagamento, cartao_id, status_liquidacao, fatura_ref, status_cartao) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                        (data_input.strftime("%Y-%m-%d"), cat_pai, beneficiario, fonte_selecionada, valor_input, st.session_state.tipo_mov, nota, 
                         st.session_state.get('display_name', 'Admin'), st.session_state.forma_pag, id_fonte if is_cartao else None, 
                         "PAGO" if not is_cartao else "PENDENTE", fatura_ref, "pendente" if is_cartao else None))
                    
                    st.success("Transação registrada com sucesso!")
            except Exception as e:
                st.error(f"Erro ao salvar: {e}")


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

    # Formatação visual para parcelas
    if not df_hist.empty:
        df_hist['nota'] = df_hist['nota'].apply(lambda x: f"💳 {x}" if "(Parc" in str(x) else x)

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
    ].copy() if not df_hist.empty else pd.DataFrame()

    if not df_liquidaveis.empty:
        st.markdown("**✅ Liquidar transações pendentes / previstas:**")
        
        # Converte coluna 'data' para datetime para facilitar o agrupamento
        # Tenta converter forçando o formato dia/mês/ano
        df_liquidaveis['data_dt'] = pd.to_datetime(df_liquidaveis['data'], format='%d/%m/%Y', errors='coerce')
        df_liquidaveis = df_liquidaveis.sort_values('data_dt')
        
        # Cria a coluna de referência de mês/ano
        df_liquidaveis['mes_ano'] = df_liquidaveis['data_dt'].dt.to_period('M')
        
        # Agrupa pelo período
        for periodo, grupo in df_liquidaveis.groupby('mes_ano'):
            nome_expansor = periodo.strftime('%B/%Y').capitalize()
            
            with st.expander(f"📅 {nome_expansor} ({len(grupo)} itens)"):
                for _, row in grupo.iterrows():
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
                            st.toast(f"✅ Transação #{tid} liquidada!", icon="✅")
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
                try:
                    db_execute(f"DELETE FROM transacoes WHERE id IN ({ph})", tuple(ids_rm))
                    st.session_state.ver += 1
                    st.toast(f"🗑️ {len(ids_rm)} lançamento(s) removido(s) com sucesso.", icon="🗑️")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Não foi possível remover: {e}")
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


            # Pré-calcula strings — evita f-strings aninhadas no HTML
            risco_txt = ""
            if saldo_l < 0:
                risco_txt = ("<div style='margin-top:6px;font-size:0.8rem;"
                             "color:#9b1c1c;font-weight:700;'>"
                             "🚨 RISCO DE INSOLVÊNCIA</div>")

            comp_txt = ""
            if comp != 0 or passivo > 0:
                comp_txt = f"<div class='detalhe' style='color:#ef4444;margin-top:4px;'>Comprometido: €{comp:,.2f}"
                if passivo > 0:
                    comp_txt += f" | Cartão: €{passivo:,.2f}"
                comp_txt += "</div>"

            with cols_saldo[i % 3]:
                # 1. Chama sua função para desenhar o título/moldura superior
                criar_quadro_legivel(f"🏦 {f}")
                
                # 2. Chama o restante do card (sem o título antigo)
                st.markdown(
                    f'<div class="saldo-card {cls_r}" style="border-top-left-radius: 0; border-top-right-radius: 0; border-top: none;">'
                    f'<div class="{cls_vr}">{sinal_r}€ {saldo_r:,.2f}</div>'
                    f'<div class="detalhe">Saldo Real (PAGO){ini_txt}</div>'
                    '<div style="margin-top:10px;padding-top:10px;border-top:1px solid #f1f5f9;">'
                    f'<div class="{cls_vl}" style="font-size:1.4rem;">{sinal_l}€ {saldo_l:,.2f}</div>'
                    '<div class="detalhe">Saldo Livre (Real − Compromissos)</div>'
                    f'{comp_txt}'
                    '</div>'
                    f'{risco_txt}'
                    '</div>',
                    unsafe_allow_html=True
                )

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
            # Pré-calcula strings — evita f-strings aninhadas no HTML
            insol_msg  = ("<div class='detalhe' style='color:#9b1c1c;"
                           "font-weight:700;margin-top:6px;'>"
                           "🚨 RISCO DE INSOLVÊNCIA</div>") if is_insol else ""
            bg_color   = "background:#fef2f2;" if is_insol else "background:#1e293b;"
            brd_color  = "#9b1c1c" if is_insol else "#10b981"
            h3_color   = "#9b1c1c" if is_insol else "#94a3b8"
            det_color  = "#9b1c1c" if is_insol else "#64748b"
            st.markdown(
                f'<div class="saldo-card {card_cls}" style="{bg_color}border-left-color:{brd_color};">' 
                f'<h3 style="color:{h3_color};">📊 DISPONIBILIDADE REAL</h3>'
                f'<div class="{cls_tl}" style="font-size:2rem;">{s_tl}€ {total_livre:,.2f}</div>'
                f'<div class="detalhe" style="color:{det_color};">Saldo Real − todos os compromissos</div>'
                f'{insol_msg}'
                '</div>',
                unsafe_allow_html=True)

        # ── Bater Saldo (Ajuste) ─────────────────────────────────────
        st.divider()
        st.markdown("#### ⚖️ Bater Saldo com o Banco")
        st.caption(
            "Informe o saldo real que o banco mostra agora. "
            "O sistema cria um ajuste automático para eliminar diferenças de centavos.")
        for f in fontes_saldo:
            saldo_r_aj = calcular_saldo_real(f)
            col_aj1, col_aj2, col_aj3 = st.columns([2, 1.5, 1])
            with col_aj1:
                st.markdown(f"**🏦 {f}** — Saldo Real actual: "
                            f"<strong style='color:{'#16a34a' if saldo_r_aj>=0 else '#dc2626'};'>"
                            f"€{saldo_r_aj:,.2f}</strong>", unsafe_allow_html=True)
                valor_banco = st.number_input(
                    "Quanto tenho nesta conta agora? (€)",
                    value=round(float(saldo_r_aj), 2),
                    step=0.01, format="%.2f",
                    key=f"ajuste_banco_{f}",
                    label_visibility="collapsed"
                )
            with col_aj2:
                diff_preview = round(valor_banco - saldo_r_aj, 2)
                if abs(diff_preview) < 0.005:
                    st.caption("✅ Saldo já coincide")
                elif diff_preview > 0:
                    st.caption(f"➕ Diferença: +€{diff_preview:,.2f}")
                else:
                    st.caption(f"➖ Diferença: €{diff_preview:,.2f}")
            with col_aj3:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("⚖️ Ajustar", key=f"btn_ajuste_{f}",
                             use_container_width=True):
                    try:
                        resultado_aj = ajustar_saldo(
                            f, valor_banco, st.session_state.display_name)
                        if resultado_aj is None:
                            st.toast("✅ Saldo já está correcto, nenhum ajuste necessário.", icon="✅")
                        else:
                            sinal = "+" if resultado_aj["diferenca"] > 0 else ""
                            st.toast(
                                f"⚖️ Saldo de '{f}' ajustado! "
                                f"Diferença: {sinal}€{resultado_aj['diferenca']:,.2f}",
                                icon="⚖️")
                        st.session_state.ver += 1
                        st.rerun()
                    except RuntimeError as e:
                        st.error(f"❌ {e}")

        # ── Saldos iniciais ──────────────────────────────────────────
        st.divider()
        st.markdown("#### 🔧 Definir Saldo Inicial por Conta")
        st.caption("Use se as contas já tinham dinheiro antes de começar a usar o sistema.")
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
                    st.toast(f"✅ Saldo inicial de '{f}' actualizado para €{novo_ini:,.2f}!", icon="✅")
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

            # --- CORREÇÃO AQUI ---
            # 1. Título com a função de quadro
            criar_quadro_legivel(f"💳 {nome_c}")
            
            # 2. Corpo do cartão (borda superior removida e margem negativa)
            st.markdown(f"""
            <div class="saldo-card saldo-card-cartao" style="border-top-left-radius: 0; border-top-right-radius: 0; border-top: none; margin-top: -15px;">
                <div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:8px;">
                    <span>Limite: <strong>€{limite_c:,.2f}</strong></span>
                    <span>Usado: <strong style="color:#ef4444;">€{usado:,.2f}</strong></span>
                    <span>Disponível: <strong style="color:{cor_disp};">€{disp:,.2f}</strong></span>
                    <span>Uso: <strong>{pct_uso:.0f}%</strong></span>
                </div>
                <div class="detalhe">Fechamento: dia {dia_fech_c} | Vencimento: dia {dia_venc_c} | Conta: {conta_pag}</div>
            </div>""", unsafe_allow_html=True)
            # ---------------------

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

    st.divider()

    # ── Exportação de Backup por Mês ──────────────────────
    st.markdown("### 📥 Exportar Dados do Mês")
    st.caption("Gera um ficheiro Excel com transações, resumo por categoria e metas vs realizado.")

    col_exp_a, col_exp_b, col_exp_c = st.columns([1, 1, 3])
    with col_exp_a:
        exp_ano = st.number_input("Ano", min_value=2020, max_value=2100,
                                   value=hoje_d.year, step=1, key="exp_ano")
    with col_exp_b:
        exp_mes = st.number_input("Mês", min_value=1, max_value=12,
                                   value=hoje_d.month, step=1, key="exp_mes")

    exp_mes_ano = f"{int(exp_ano):04d}-{int(exp_mes):02d}"
    nome_arquivo = f"ERP_Familiar_Backup_{int(exp_mes):02d}_{int(exp_ano)}.xlsx"

    try:
        xlsx_data = gerar_relatorio_excel(exp_mes_ano)
        st.download_button(
            label=f"📥 Exportar {nome_arquivo}",
            data=xlsx_data,
            file_name=nome_arquivo,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=False,
            type="primary",
        )
        st.caption(
            f"O arquivo contém: **Transações de {int(exp_mes):02d}/{int(exp_ano)}**, "
            f"**Resumo por Categoria** e **Metas vs Realizado**.")
    except Exception as e:
        st.error(f"❌ Erro ao gerar relatório: {e}")


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
                    st.toast(f"✅ Categoria '{n_pai}' adicionada com sucesso!", icon="✅")
                    st.rerun()
                except Exception:
                    st.error("❌ Já existe uma categoria com esse nome.")
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
                        st.toast(f"✅ '{n_sub}' adicionado em '{pai_sel_gest}'!", icon="✅")
                        st.rerun()
                    except Exception:
                        st.error("❌ Já existe um detalhamento com esse nome.")
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
                bloqueados = []
                for cid in ids_cat:
                    # Verifica bloqueio usando a função de segurança
                    if verificar_bloqueio_delecao("categorias", cid):
                        nome_cat = cat_df2[cat_df2['id'] == cid]['nome'].values[0]
                        bloqueados.append(nome_cat)
                
                if bloqueados:
                    st.error(f"⛔ Não é possível remover: **{', '.join(bloqueados)}** possuem subcategorias ou transações vinculadas.")
                else:
                    ph = ",".join(["?"] * len(ids_cat))
                    try:
                        db_execute(f"DELETE FROM categorias WHERE id IN ({ph})", tuple(ids_cat))
                        
                        # --- ADICIONE ESTA LINHA ---
                        st.session_state["inp_pai"] = ""
                        st.session_state["inp_sub"] = ""
                        st.session_state.ver += 1 
                        # ---------------------------
                        
                        st.toast(f"🗑️ {len(ids_cat)} categoria(s) removida(s).", icon="🗑️")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erro ao remover: {e}")

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
                    st.toast(f"✅ Conta '{n_fonte}' adicionada com sucesso!", icon="✅")
                    
                    # Limpeza do campo (isso limpa o widget text_input lá em cima)
                    st.session_state["inp_fonte"] = ""
                    
                    st.rerun()
                except Exception:
                    st.error("❌ Já existe uma conta com esse nome.")
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
                # --- INÍCIO DA INSERÇÃO DA LÓGICA DE BLOQUEIO ---
                bloqueados = []
                for cid in ids_f:
                    if verificar_bloqueio_delecao("fontes", cid):
                        bloqueados.append(str(cid))
                
                if bloqueados:
                    st.error(f"⛔ Não é possível remover: uma ou mais contas selecionadas possuem transações ou saldos vinculados.")
                else:
                    # --- LÓGICA DE EXCLUSÃO ORIGINAL ---
                    ph = ",".join(["?"] * len(ids_f))
                    ops = [(f"DELETE FROM fontes WHERE id IN ({ph})", tuple(ids_f))]
                    for nm in nomes_f:
                        ops.append(("DELETE FROM saldos_iniciais WHERE fonte=?", (nm,)))
                    
                    try:
                        db_execute_many(ops)
                        st.session_state.ver += 1
                        st.session_state["inp_fonte"] = "" 
                        st.toast(f"🗑️ {len(ids_f)} conta(s) removida(s).", icon="🗑️")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Erro ao remover conta(s): {e}")
                # --- FIM DA INSERÇÃO ---


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
                    st.toast(f"✅ Beneficiário '{n_benef}' adicionado!", icon="✅")
                    st.rerun()
                except Exception:
                    st.error("❌ Já existe um beneficiário com esse nome.")
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
                try:
                    db_execute(f"DELETE FROM beneficiarios WHERE id IN ({ph})", tuple(ids_b))
                    st.toast(f"🗑️ {len(ids_b)} beneficiário(s) removido(s).", icon="🗑️")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Erro ao remover: {e}")
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
                    st.toast(f"✅ Utilizador '{n_nome}' adicionado com sucesso!", icon="✅")
                    st.rerun()
                except Exception:
                    st.error("❌ Já existe um utilizador com esse nome de login.")
        else:
            st.warning("Preencha todos os campos.")
    users_df = db_df("SELECT id, username, nome_exibicao FROM usuarios")
    users_df = users_df.rename(columns={'username':'Login','nome_exibicao':'Nome de Exibição'})
    st.markdown("**Utilizadores cadastrados:**")
    st.dataframe(users_df, use_container_width=True, hide_index=True)
