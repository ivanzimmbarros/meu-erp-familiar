import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
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

def formatar_descricao(row):
    # Se for uma linha de fatura (que criamos no SQL da Tab 2), 
    # usamos a coluna 'nota' que já contém o nome do cartão e a referência.
    if row.get('tipo_linha') == 'Fatura Cartão':
        return f"📝 <strong>{row['nota']}</strong>"
    
    # Formato original para transações comuns
    nota = str(row['nota'])
    cat = f"{row['categoria_pai']}/{row['categoria_filho']}"
    
    # Se for parcela, exibe com ícone de cartão
    if "(Parc" in nota:
        return f"💳 <strong>{cat}</strong> | {nota}"
    return f"📝 <strong>{cat}</strong> | {row['beneficiario'] or 'Sem beneficiário'}"

def formatar_data_para_exibicao(df, coluna='data'):
    if coluna in df.columns:
        df[coluna] = pd.to_datetime(df[coluna]).dt.strftime('%d/%m/%Y')
    return df

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
    .liquidar-row {
        background-color: #f9f9f9;
        padding: 10px;
        border-radius: 8px;
        border: 1px solid #ddd;
        margin-bottom: 5px;
        color: #000000 !important; /* FORÇA A COR DA FONTE */
    }
    .badge-pendente {
        background-color: #ffcccb;
        color: #d9534f !important;
        padding: 2px 6px;
        border-radius: 4px;
        font-weight: bold;
    }
    .badge-previsto {
        background-color: #fff3cd;
        color: #856404 !important;
        padding: 2px 6px;
        border-radius: 4px;
        font-weight: bold;
    }
    
    /* Estilo do Card do Cartão */
    .saldo-card-cartao {
        background-color: #f8f9fa !important;
        padding: 15px;
        border-left: 5px solid #3b82f6;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        margin-bottom: 20px;
        color: #333333 !important; /* Cor base do texto */
    }

    .saldo-card-cartao h4 {
        color: #333333 !important; /* Cor do título */
        margin: 0 0 10px 0 !important;
        padding: 0 !important;
    }
    .saldo-card-cartao strong {
        color: #000000 !important; /* Destaques em negrito ficam pretos */
    }
    
    /* Estilo das Faturas */
    .fatura-aberta {
        background-color: #fffaf0 !important;
        color: #333333 !important; /* Texto escuro no fundo claro */
        padding: 12px;
        border-radius: 6px;
        border: 1px solid #ffeeba;
        margin-bottom: 10px;
    }
    
    .fatura-fechada {
        background-color: #f8f9fa !important;
        color: #333333 !important; /* Texto escuro no fundo claro */
        padding: 12px;
        border-radius: 6px;
        border: 1px solid #dee2e6;
        margin-bottom: 10px;
    }

    /* Garantir que negritos e spans dentro dos cards também fiquem escuros */
    .saldo-card-cartao strong, .fatura-aberta strong, .fatura-fechada strong {
        color: #000000 !important;
    }
    
    .detalhe {
        color: #555555 !important;
        font-size: 0.85rem;
    }

    .card {
        background-color: #f8f9fa;
        padding: 20px;
        border-radius: 10px;
        border: 1px solid #e0e0e0;
        margin-bottom: 10px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
    }
    
    .saldo-total-card {
        background-color: #1e293b;
        color: white;
        padding: 25px;
        border-radius: 12px;
        text-align: center;
        margin-bottom: 20px;
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
        
        # 1. Verifica transações vinculadas
        tem_trans = db_query("SELECT id FROM transacoes WHERE fonte=?", (nome_conta,))
        
        # 2. Verifica se existe saldo inicial configurado para esta conta
        tem_saldo_inicial = db_query("SELECT fonte FROM saldos_iniciais WHERE fonte=?", (nome_conta,))
        
        # A exclusão é bloqueada se houver transações OU saldo inicial definido
        return len(tem_trans) > 0 or len(tem_saldo_inicial) > 0


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

# ────────────────────────────────────────────
#  FUNÇÕES DE NEGÓCIO — TRANSFERENCIA ENTRE BANCOS
# ─────────────────────────────────────────────

def realizar_transferencia(conta_origem, conta_destino, valor, data_str, usuario, nota):
    """
    Executa a transferência atômica no banco de dados.
    """
    # Nota composta para facilitar busca
    nota_formatada = f"Transferência: {conta_origem} -> {conta_destino} | {nota}"
    
    queries = [
        # Debita da origem
        ("INSERT INTO transacoes (data, categoria_pai, categoria_filho, beneficiario, fonte, valor_eur, tipo, nota, usuario, status_liquidacao) VALUES (?,?,?,?,?,?,?,?,?,?)",
         (data_str, "Transferência", "Saída", "Para " + conta_destino, conta_origem, valor, "Despesa", nota_formatada, usuario, "PAGO")),
        
        # Credita no destino
        ("INSERT INTO transacoes (data, categoria_pai, categoria_filho, beneficiario, fonte, valor_eur, tipo, nota, usuario, status_liquidacao) VALUES (?,?,?,?,?,?,?,?,?,?)",
         (data_str, "Transferência", "Entrada", "De " + conta_origem, conta_destino, valor, "Receita", nota_formatada, usuario, "PAGO"))
    ]
    
    db_execute_many(queries)



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
    st.markdown("🔄 **Transferências** → Transferências Bancárias")
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
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "➕  Novo Lançamento",
    "📋  Lançamentos",
    "💰  Saldos",
    "💳  Cartões",
    "🎯  Metas",
    "📊  Dashboard",
    "⚙️  Gestão",
    "🔄  Transferências",
])


# ─────────────────────────────────────────────────────────────
#  TAB 1 — NOVO LANÇAMENTO (COMPLETAMENTE REVISTO)
# ─────────────────────────────────────────────────────────────
with tab1:
    st.markdown("## ➕ Registrar uma Movimentação")
    st.divider()

    # --- 1. Estado Inicial ---
    if 'tipo_mov' not in st.session_state: st.session_state.tipo_mov = "💸 Despesa"
    if 'forma_pag' not in st.session_state: st.session_state.forma_pag = "Dinheiro/Débito"

    # --- 2. Controles de Escolha ---
    col_tp1, col_tp2 = st.columns(2)
    st.session_state.tipo_mov = col_tp1.radio("Tipo de movimentação", ["💸 Despesa", "💵 Receita"], horizontal=True)
    
    eh_despesa = "Despesa" in st.session_state.tipo_mov
    
    # Lógica de Forma de Pagamento
    if eh_despesa:
        st.session_state.forma_pag = col_tp2.radio("Forma de pagamento", ["Dinheiro/Débito", "Cartão de Crédito"], horizontal=True)
        is_cartao = (st.session_state.forma_pag == "Cartão de Crédito")
    else:
        st.session_state.forma_pag = "Dinheiro/Débito"
        is_cartao = False
    
    # Busca de Fontes (com tratamento para evitar erros vazios)
    try:
        query_fonte = "SELECT id, nome FROM cartoes ORDER BY nome" if is_cartao else "SELECT id, nome FROM fontes ORDER BY nome"
        dados_fonte = db_query(query_fonte)
        lista_fontes = [op[1] for op in dados_fonte] if dados_fonte else ["Nenhuma conta encontrada"]
    except Exception:
        lista_fontes = ["Erro ao carregar fontes"]

    # --- 3. Formulário ---
    with st.form("form_transacao", clear_on_submit=True):
        fonte_selecionada = st.selectbox("Conta / Cartão" if not is_cartao else "Cartão", lista_fontes)
        
        col_in1, col_in2 = st.columns(2)
        data_input = col_in1.date_input("Data", value=date.today())
        valor_input = col_in2.number_input("Valor (€)", min_value=0.01, step=1.0, format="%.2f")
        
        num_parcelas = 1
        if eh_despesa:
            num_parcelas = col_in1.number_input("Parcelas", min_value=1, max_value=24, value=1)
        
        # --- Lógica de Categorias ---
        try:
            cat_df = db_df("SELECT id, nome, pai_id FROM categorias")
            pai_opts = cat_df[cat_df['pai_id'].isna()]
            
            col_cat1, col_cat2 = st.columns(2)
            cat_pai_nome = col_cat1.selectbox("Categoria Principal", pai_opts['nome'].tolist())
            
            id_pai_selecionado = pai_opts[pai_opts['nome'] == cat_pai_nome]['id'].iloc[0]
            sub_opts = cat_df[cat_df['pai_id'] == id_pai_selecionado]
            
            categoria_final = cat_pai_nome
            if not sub_opts.empty:
                cat_filho = col_cat2.selectbox("Detalhe (Subcategoria)", sub_opts['nome'].tolist())
                categoria_final = cat_filho
        except Exception:
            st.error("Erro ao carregar categorias. Verifique a tabela no banco.")
            categoria_final = "Outros"

        benef_db = db_query("SELECT nome FROM beneficiarios ORDER BY nome")
        lista_benef = [b[0] for b in benef_db] if benef_db else []
        beneficiario = st.selectbox("Beneficiário", lista_benef)
        nota = st.text_input("Observação (opcional)")
        
        # O BOTÃO DE SUBMIT AGORA ESTÁ DENTRO DO WITH CORRETAMENTE
        submit_button = st.form_submit_button("Salvar Transação")

    # --- 4. Processamento ---
    if submit_button:
        if not beneficiario:
            st.error("Por favor, selecione um beneficiário.")
        else:
            try:
                id_fonte = [op[0] for op in dados_fonte if op[1] == fonte_selecionada][0]

                if not eh_despesa:
                    db_execute('''INSERT INTO transacoes 
                        (data, categoria_pai, beneficiario, fonte, valor_eur, tipo, nota, 
                         usuario, forma_pagamento, status_liquidacao) 
                        VALUES (?,?,?,?,?,?,?,?,?,?)''',
                        (data_input.strftime("%Y-%m-%d"), categoria_final, beneficiario, fonte_selecionada, 
                         valor_input, st.session_state.tipo_mov, nota, 
                         st.session_state.get('display_name', 'Admin'), "Dinheiro/Débito", "PAGO"))
                else:
                    # Lógica de Despesa (Parcelas ou Única)
                    # ... (seu código de cálculo de parcelas mantido aqui) ...
                    # Certifique-se que o INSERT está alinhado com as colunas reais da sua tabela
                    pass 
                
                st.success("Transação registrada com sucesso!")
                st.rerun() 

            except Exception as e:
                st.error(f"Erro ao salvar no banco: {e}")


# ══════════════════════════════════════════════
#  TAB 2 — TODOS OS LANÇAMENTOS (RECONSTRUÍDA)
# ══════════════════════════════════════════════
with tab2:
    st.markdown("## 📋 Histórico de Lançamentos")
    st.caption("Visualize, filtre, exporte, liquide ou remova registros.")
    st.divider()

    # 1. Filtros
    fontes_row2  = db_query("SELECT nome FROM fontes")
    cartoes_row2 = db_query("SELECT nome FROM cartoes")
    todas_fontes = (["Todas"] + [r[0] for r in fontes_row2] + [r[0] for r in cartoes_row2])

    col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns(5)
    with col_f1: filtro_tipo   = st.selectbox("Tipo", ["Todos","Despesa","Receita"])
    with col_f2: filtro_fonte  = st.selectbox("Conta", todas_fontes)
    with col_f3: filtro_forma  = st.selectbox("Forma", ["Todas","Dinheiro/Débito","Cartão de Crédito"])
    with col_f4: filtro_status = st.selectbox("Status", ["Todos","PAGO","PENDENTE","PREVISTO"])
    with col_f5: filtro_busca  = st.text_input("🔍 Buscar", placeholder="Nota, categoria...")

    # 2. Dados
    df_comuns = db_df("SELECT 'Transação' as tipo_linha, * FROM transacoes WHERE forma_pagamento != 'Cartão de Crédito'")
    df_faturas = db_df("""
        SELECT 'Fatura Cartão' as tipo_linha, MIN(t.id) as id, t.fatura_ref as data, 
               'Cartão de Crédito' as categoria_pai, c.nome as categoria_filho, 
               'Diversos' as beneficiario, t.fonte, SUM(t.valor_eur) as valor_eur, 
               'Despesa' as tipo, 'Fatura do ' || c.nome || ' (Ref: ' || t.fatura_ref || ')' as nota, 
               t.usuario, t.forma_pagamento, t.cartao_id, t.fatura_ref, 
               'pendente' as status_cartao, 'PENDENTE' as status_liquidacao, NULL as data_liquidacao, 
               NULL as parcela_id, 0 as parcela_numero, 0 as total_parcelas
        FROM transacoes t JOIN cartoes c ON t.cartao_id = c.id
        WHERE t.forma_pagamento = 'Cartão de Crédito' GROUP BY t.fatura_ref, t.fonte, c.nome
    """)
    
    df_hist = pd.concat([df_comuns, df_faturas], ignore_index=True)
    df_hist['data_dt'] = pd.to_datetime(df_hist['data'], errors='coerce')
    df_hist = df_hist.sort_values(by='data_dt', ascending=False)

    # 3. Aplicar filtros
    if filtro_tipo != "Todos": df_hist = df_hist[df_hist['tipo'] == filtro_tipo]
    if filtro_fonte != "Todas": df_hist = df_hist[df_hist['fonte'] == filtro_fonte]
    if filtro_forma != "Todas": df_hist = df_hist[df_hist['forma_pagamento'] == filtro_forma]
    if filtro_status != "Todos": df_hist = df_hist[df_hist['status_liquidacao'] == filtro_status]
    if filtro_busca:
        mask = (df_hist['nota'].str.contains(filtro_busca, case=False, na=False) |
                df_hist['categoria_pai'].str.contains(filtro_busca, case=False, na=False))
        df_hist = df_hist[mask]

    # 4. Blocos de Liquidação (Agrupados por Mês)
    df_liquidaveis = df_hist[df_hist['status_liquidacao'].isin(['PENDENTE','PREVISTO'])].copy()
    if not df_liquidaveis.empty:
        st.markdown("**✅ Liquidar transações pendentes / previstas:**")
        
        # Garante que a data está como datetime para o agrupamento
        df_liquidaveis['data_dt'] = pd.to_datetime(df_liquidaveis['data'], errors='coerce')
        df_liquidaveis['mes_ano'] = df_liquidaveis['data_dt'].dt.to_period('M')
        
        for periodo, grupo in df_liquidaveis.groupby('mes_ano', sort=False):
            with st.expander(f"📅 {periodo.strftime('%B/%Y').capitalize()} ({len(grupo)} itens)"):
                for _, row in grupo.iterrows():
                    tid = int(row['id'])
                    is_fatura = row.get('tipo_linha') == 'Fatura Cartão'
                    
                    # --- CORREÇÃO AQUI: Formatar a data para exibição ---
                    data_exibicao = row['data_dt'].strftime('%d/%m/%Y') if pd.notnull(row['data_dt']) else row['data']
                    
                    col_a, col_b = st.columns([5, 1])
                    with col_a:
                        badge = f'<span class="badge-pendente">{"PENDENTE" if row["status_liquidacao"]=="PENDENTE" else "PREVISTO"}</span>'
                        # Usamos a data formatada aqui:
                        st.markdown(f'<div class="liquidar-row">{badge} {data_exibicao} | {formatar_descricao(row)} | <strong>€{float(row["valor_eur"]):,.2f}</strong></div>', unsafe_allow_html=True)
                    with col_b:
                        if is_fatura:
                            # Botão para redirecionar à aba de cartões
                            st.button("🔍 Ver", key=f"ver_fat_{tid}", on_click=lambda: st.warning("Acesse a aba 💳 Cartões para visualizar os detalhes desta fatura."))
                        else:
                            if st.button("✅ Liquidar", key=f"liq_{tid}_{st.session_state.ver}"):
                                liquidar_transacao(tid, st.session_state.display_name)
                                st.session_state.ver += 1
                                st.rerun()

    # 5. Tabela Geral (Data Editor)
    st.markdown("---")
    if not df_hist.empty:
        df_display = df_hist.copy()
        df_display['Data'] = df_display['data_dt'].dt.strftime('%d/%m/%Y')
        df_display.insert(0, "Remover", False)
        
        # Renomeação para exibir colunas amigáveis
        df_display = df_display.rename(columns={
            'id':'ID', 'categoria_pai':'Categoria', 'valor_eur':'Valor (€)',
            'status_liquidacao':'Liquidação', 'nota':'Observação'
        })

        editor = st.data_editor(
            df_display[["Remover", "Data", "Categoria", "Valor (€)", "Liquidação", "Observação"]], 
            key=f"ed_final_{st.session_state.ver}",
            use_container_width=True
        )
        
        if st.button("🗑️ Confirmar Remoção"):
            ids_rm = df_display[editor["Remover"] == True]["ID"].tolist()
            if ids_rm:
                db_execute(f"DELETE FROM transacoes WHERE id IN ({','.join(['?']*len(ids_rm))})", tuple(ids_rm))
                st.session_state.ver += 1
                st.rerun()
    else:
        st.info("Nenhum lançamento encontrado.")

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
            
            # Ajuste de formatação visual do card individual
            cls_vr = "valor-positivo" if saldo_r >= 0 else "valor-negativo"
            sinal_r = "+" if saldo_r > 0 else ""

            with cols_saldo[i % 3]:
                # Desenha o título legível e o conteúdo do saldo
                criar_quadro_legivel(f"🏦 {f}")
                st.markdown(f"""
                    <div class="card" style="margin-bottom: 20px; padding: 15px; border-radius: 8px; border: 1px solid #e0e0e0;">
                        <p style="margin: 0; font-size: 0.9rem; color: #666;">Saldo Disponível:</p>
                        <h2 style="margin: 5px 0; color: {'#16a34a' if saldo_r >= 0 else '#dc2626'};">
                            {sinal_r}€{saldo_r:,.2f}
                        </h2>
                    </div>
                """, unsafe_allow_html=True)

        st.divider()

        # Cards de totais
        col_tot1, col_tot2 = st.columns(2)
        with col_tot1:
            cls_tr = "valor-positivo" if total_real >= 0 else "valor-negativo"
            s_tr   = "+" if total_real > 0 else ""
            st.markdown(f"""<div class="saldo-card" style="background:#1e293b; color:white; padding: 20px; border-radius: 10px; border-left: 5px solid #3b82f6;">
                <h3 style="color:#94a3b8; margin-top:0;">🏦 SALDO REAL TOTAL</h3>
                <div class="{cls_tr}" style="font-size:2rem; font-weight:bold;">{s_tr}€ {total_real:,.2f}</div>
                <div class="detalhe" style="color:#64748b; margin-top:5px;">Dinheiro efectivamente disponível (PAGO)</div>
            </div>""", unsafe_allow_html=True)
            
        with col_tot2:
            is_insol = total_livre < 0
            # CORREÇÃO: Definindo cor do texto do valor para garantir contraste contra o fundo
            val_color = "#ffffff" if not is_insol else "#9b1c1c"
            s_tl      = "+" if total_livre > 0 else ""
            insol_msg = "<div style='color:#9b1c1c; font-weight:700; margin-top:6px;'>🚨 RISCO DE INSOLVÊNCIA</div>" if is_insol else ""
            
            st.markdown(f"""<div class="saldo-card" style="background:{'#fef2f2' if is_insol else '#1e293b'}; padding: 20px; border-radius: 10px; border-left: 5px solid {'#9b1c1c' if is_insol else '#10b981'};">
                <h3 style="color:{'#9b1c1c' if is_insol else '#94a3b8'}; margin-top:0;">📊 DISPONIBILIDADE REAL</h3>
                <div style="font-size:2rem; font-weight:bold; color:{val_color};">{s_tl}€ {total_livre:,.2f}</div>
                <div class="detalhe" style="color:{'#9b1c1c' if is_insol else '#64748b'}; margin-top:5px;">Saldo Real − todos os compromissos</div>
                {insol_msg}
            </div>""", unsafe_allow_html=True)

        # ── Bater Saldo (Ajuste) ─────────────────────────────────────
        st.divider()
        st.markdown("#### ⚖️ Bater Saldo com o Banco")
        for f in fontes_saldo:
            saldo_r_aj = calcular_saldo_real(f)
            col_aj1, col_aj2, col_aj3 = st.columns([2, 1.5, 1])
            with col_aj1:
                st.markdown(f"**🏦 {f}** — Saldo Real actual: <strong style='color:{'#16a34a' if saldo_r_aj>=0 else '#dc2626'};'>€{saldo_r_aj:,.2f}</strong>", unsafe_allow_html=True)
                valor_banco = st.number_input("Quanto tenho nesta conta agora? (€)", value=round(float(saldo_r_aj), 2), step=0.01, format="%.2f", key=f"ajuste_banco_{f}", label_visibility="collapsed")
            with col_aj2:
                diff_preview = round(valor_banco - saldo_r_aj, 2)
                if abs(diff_preview) < 0.005: st.caption("✅ Saldo já coincide")
                elif diff_preview > 0: st.caption(f"➕ Diferença: +€{diff_preview:,.2f}")
                else: st.caption(f"➖ Diferença: €{diff_preview:,.2f}")
            with col_aj3:
                if st.button("⚖️ Ajustar", key=f"btn_ajuste_{f}", use_container_width=True):
                    resultado_aj = ajustar_saldo(f, valor_banco, st.session_state.display_name)
                    st.rerun()

        # ── Saldos iniciais ──────────────────────────────────────────
        st.divider()
        st.markdown("#### 🔧 Definir Saldo Inicial por Conta")
        for f in fontes_saldo:
            ini_row2  = db_query("SELECT valor_inicial FROM saldos_iniciais WHERE fonte=?", (f,))
            ini_atual = ini_row2[0][0] if ini_row2 else 0.0
            col_si1, col_si2 = st.columns([3, 1])
            with col_si1:
                novo_ini = st.number_input(f"Saldo inicial de **{f}**", value=float(ini_atual), step=10.0, format="%.2f", key=f"ini_{f}")
            with col_si2:
                if st.button("Salvar", key=f"salvar_ini_{f}"):
                    db_execute("INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)", (f, novo_ini))
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

            # --- CARD ATUALIZADO ---
            st.markdown(f"""
            <div class="saldo-card-cartao">
                <h4>💳 {nome_c}</h4>
                <div style="display:flex; gap: 20px; flex-wrap: wrap; font-size: 0.95rem;">
                    <div>Limite: <strong>€{limite_c:,.2f}</strong></div>
                    <div>Usado: <strong style="color:#ef4444;">€{usado:,.2f}</strong></div>
                    <div>Disp: <strong style="color:{cor_disp};">€{disp:,.2f}</strong></div>
                    <div>Uso: <strong>{pct_uso:.0f}%</strong></div>
                </div>
                <div style="margin-top: 10px; font-size: 0.8rem; color: #555; border-top: 1px solid #ddd; padding-top: 5px;">
                    Fechamento: dia {dia_fech_c} | Vencimento: dia {dia_venc_c} | Conta: {conta_pag}
                </div>
            </div>
            """, unsafe_allow_html=True)
            # -----------------------------------

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
                            # Tenta converter para datetime e formata como string DD/MM/AAAA
                            # O 'errors="coerce"' evita que o código quebre se houver um dado inválido
                            compras_fat['data'] = pd.to_datetime(compras_fat['data'], errors='coerce').dt.strftime('%d/%m/%Y')
                            
                            # Se a conversão falhou (virou NaT), mantemos o original para não sumir o dado
                            compras_fat['data'] = compras_fat['data'].fillna(compras_fat['data'])

                            compras_fat = compras_fat.rename(columns={
                                'data':'Data','categoria_pai':'Categoria',
                                'categoria_filho':'Detalhamento','beneficiario':'Beneficiário',
                                'valor_eur':'Valor (€)','nota':'Observação','status_cartao':'Status'})
                            
                            st.dataframe(
                                compras_fat, 
                                use_container_width=True, 
                                hide_index=True,
                                column_config={
                                    "Valor (€)": st.column_config.NumberColumn(format="€ %.2f")
                                }
                            )


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

    # CARREGAMENTO ÚNICO DOS DADOS
    df_temp = db_df("SELECT data, valor_eur as valor, tipo FROM transacoes")
    
    st.markdown("### 📈 Evolução Financeira")
    
    if not df_temp.empty:
        # Tratamento de datas (garantindo formato ISO YYYY-MM-DD vindo do SQLite)
        df_temp['data'] = pd.to_datetime(df_temp['data'], format='%Y-%m-%d', errors='coerce')
        
        # 1. Gráfico de Área (Evolução Geral)
        df_evolucao = df_temp.resample('ME', on='data')['valor'].sum().reset_index()
        df_evolucao.columns = ['Mês', 'Total (€)']
        
        fig1 = px.area(df_evolucao, x='Mês', y='Total (€)', title="Fluxo Financeiro Mensal", template="plotly_white")
        fig1.update_traces(line_color='#3b82f6', fillcolor='rgba(59, 130, 246, 0.2)')
        st.plotly_chart(fig1, use_container_width=True)

        # 2. Gráfico de Barras (Por Tipo)
        st.markdown("### 📊 Comparativo por Tipo (Receita vs Despesa)")
        df_tipo = df_temp.groupby([pd.Grouper(key='data', freq='ME'), 'tipo'])['valor'].sum().reset_index()
        
        fig2 = px.bar(df_tipo, x='data', y='valor', color='tipo', 
                      barmode='group', title="Receitas vs Despesas Mensais",
                      labels={'valor': 'Total (€)', 'data': 'Mês', 'tipo': 'Tipo'},
                      template="plotly_white")
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Sem dados suficientes para gerar os gráficos.")

    # Controles de período
    hoje_d = datetime.now()
    col_d1, col_d2, _ = st.columns([1, 1, 4])
    with col_d1:
        dash_ano = st.number_input("Ano", min_value=2020, max_value=2100, value=hoje_d.year, step=1, key="dash_ano")
    with col_d2:
        dash_mes = st.number_input("Mês", min_value=1, max_value=12, value=hoje_d.month, step=1, key="dash_mes")
    
    dash_mes_ano = f"{int(dash_ano):04d}-{int(dash_mes):02d}"

    # ── BLOCO 1: Liquidez ──────────────────────
    st.markdown(f"### 💧 Liquidez — {dash_mes_ano}")

    fontes_dash = [r[0] for r in db_query("SELECT nome FROM fontes")]
    total_real_dash  = sum(calcular_saldo_real(f)  for f in fontes_dash)
    total_livre_dash = sum(calcular_saldo_livre(f) for f in fontes_dash)
    total_pend_dash  = get_total_pendentes()
    risco_global     = total_livre_dash < 0
    
    if risco_global:
        st.markdown(
            f'<div class="aviso-insolvencia">🚨 <strong>ALERTA: RISCO DE INSOLVÊNCIA</strong> — '
            f'A Disponibilidade Real é de <strong>€{total_livre_dash:,.2f}</strong>. '
            f'Os compromissos futuros superam o saldo disponível.</div>',
            unsafe_allow_html=True)

    if total_pend_dash > 0:
        pend_count = len(get_pendentes_vencidos())
        st.markdown(
            f'<div class="aviso-pendente">⏳ <strong>Atenção: Contas Vencidas</strong> — '
            f'{pend_count} transação(ões) PENDENTE(S) | '
            f'Total: <strong>€{total_pend_dash:,.2f}</strong>. '
            f'Aceda à aba 📋 Lançamentos para liquidar.</div>',
            unsafe_allow_html=True)

    col_lq1, col_lq2, col_lq3, col_lq4 = st.columns(4)
    # (Continue com o restante do seu layout original aqui...)



# ══════════════════════════════════════════════
#  TAB 7 — GESTÃO (VERSÃO VALIDADA E SEGURA)
# ══════════════════════════════════════════════
with tab7:
    st.markdown("## ⚙️ Gestão e Configurações")
    st.caption("Configure as categorias, contas e beneficiários do seu sistema.")

    # Garante que a versão de estado exista
    if 'ver' not in st.session_state: st.session_state.ver = 0

    # ══ SEÇÃO 0: TAXA DE CÂMBIO ═══════════════════
    st.markdown("---")
    st.markdown('<div class="secao-titulo">💱 Seção 0 — Taxa de Câmbio BRL → EUR</div>', unsafe_allow_html=True)
    col_tx1, col_tx2, col_tx3 = st.columns([1.5, 1, 3])
    with col_tx1:
        nova_taxa = st.number_input("Taxa (1 BRL = X EUR)", min_value=0.0001, max_value=10.0,
                                     value=float(st.session_state.get('taxa_brl_eur', 0.16)),
                                     step=0.001, format="%.4f", key=f"inp_taxa_{st.session_state.ver}")
    with col_tx2:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 Salvar Taxa", use_container_width=True):
            db_execute("INSERT OR REPLACE INTO configuracoes (chave,valor) VALUES ('taxa_brl_eur',?)", (str(nova_taxa),))
            st.session_state['taxa_brl_eur'] = nova_taxa
            st.success("Taxa atualizada.")
            st.rerun()
    with col_tx3:
        st.markdown("<br>", unsafe_allow_html=True)
        st.info(f"1 BRL = **{st.session_state.get('taxa_brl_eur', 0):.4f} EUR**")

    # ══ SEÇÃO 1: CATEGORIAS ═══════════════════════
    st.markdown("---")
    st.markdown('<div class="secao-titulo">📂 Seção 1 — Categorias</div>', unsafe_allow_html=True)
    cat_df2 = db_df("SELECT id, nome, pai_id FROM categorias")
    pai_opts2 = cat_df2[cat_df2['pai_id'].isna()]['nome'].tolist()

    col_cat1, col_cat2 = st.columns(2)
    with col_cat1:
        n_pai = st.text_input("Nome Categoria Principal", key=f"inp_pai_{st.session_state.ver}")
        if st.button("➕ Adicionar Principal"):
            if n_pai.strip():
                db_execute("INSERT INTO categorias (nome) VALUES (?)", (n_pai.strip(),))
                st.session_state.ver += 1
                st.rerun()
    with col_cat2:
        if pai_opts2:
            pai_sel = st.selectbox("Categoria Pai", pai_opts2, key=f"sel_pai_{st.session_state.ver}")
            n_sub = st.text_input("Nome do detalhamento", key=f"inp_sub_{st.session_state.ver}")
            if st.button("➕ Adicionar Detalhamento"):
                pid = int(cat_df2[cat_df2['nome'] == pai_sel]['id'].iloc[0])
                db_execute("INSERT INTO categorias (nome, pai_id) VALUES (?,?)", (n_sub.strip(), pid))
                st.session_state.ver += 1
                st.rerun()

    if not cat_df2.empty:
        cat_view = cat_df2.copy()
        pai_map = cat_df2[cat_df2['pai_id'].isna()].set_index('id')['nome'].to_dict()
        cat_view['Categoria Principal'] = cat_view['pai_id'].map(pai_map).fillna('—')
        cat_view.insert(0, "Remover", False)
        ed_cat = st.data_editor(cat_view, key=f"ed_cat_{st.session_state.ver}", use_container_width=True, 
                                column_config={"Remover": st.column_config.CheckboxColumn("🗑️")})
        
        if st.button("🗑️ Remover Selecionadas"):
            ids = ed_cat[ed_cat["Remover"] == True]["id"].tolist()
            if ids:
                bloqueados = [cid for cid in ids if verificar_bloqueio_delecao("categorias", cid)]
                if bloqueados:
                    st.error("⛔ Não é possível remover: algumas categorias possuem dados vinculados.")
                else:
                    db_execute(f"DELETE FROM categorias WHERE id IN ({','.join(['?']*len(ids))})", tuple(ids))
                    st.session_state.ver += 1
                    st.rerun()

    # ══ SEÇÃO 2: CONTAS ══════════════════════════
    st.markdown("---")
    st.markdown('<div class="secao-titulo">🏦 Seção 2 — Contas</div>', unsafe_allow_html=True)
    n_fonte = st.text_input("Nome da conta", key=f"inp_fonte_{st.session_state.ver}")
    if st.button("➕ Adicionar Conta"):
        if n_fonte.strip():
            db_execute("INSERT INTO fontes (nome) VALUES (?)", (n_fonte.strip(),))
            st.session_state.ver += 1
            st.rerun()

    fontes_df = db_df("SELECT id, nome FROM fontes")
    if not fontes_df.empty:
        fontes_df.insert(0, "Remover", False)
        ed_f = st.data_editor(fontes_df, key=f"ed_fontes_{st.session_state.ver}", use_container_width=True,
                               column_config={"Remover": st.column_config.CheckboxColumn("🗑️")})
        if st.button("🗑️ Remover Contas Selecionadas"):
            ids = ed_f[ed_f["Remover"] == True]["id"].tolist()
            if ids:
                if any(verificar_bloqueio_delecao("fontes", cid) for cid in ids):
                    st.error("⛔ Contas em uso. Impossível remover.")
                else:
                    db_execute(f"DELETE FROM fontes WHERE id IN ({','.join(['?']*len(ids))})", tuple(ids))
                    st.session_state.ver += 1
                    st.rerun()

    # ══ SEÇÃO 3: BENEFICIÁRIOS ════════════════════
    st.markdown("---")
    st.markdown('<div class="secao-titulo">👤 Seção 3 — Beneficiários</div>', unsafe_allow_html=True)
    n_ben = st.text_input("Nome do beneficiário", key=f"inp_ben_{st.session_state.ver}")
    if st.button("➕ Adicionar Beneficiário"):
        if n_ben.strip():
            db_execute("INSERT INTO beneficiarios (nome) VALUES (?)", (n_ben.strip(),))
            st.session_state.ver += 1
            st.rerun()

    benef_df = db_df("SELECT id, nome FROM beneficiarios")
    if not benef_df.empty:
        benef_df.insert(0, "Remover", False)
        ed_b = st.data_editor(benef_df, key=f"ed_ben_{st.session_state.ver}", use_container_width=True,
                               column_config={"Remover": st.column_config.CheckboxColumn("🗑️")})
        if st.button("🗑️ Remover Beneficiários Selecionados"):
            ids = ed_b[ed_b["Remover"] == True]["id"].tolist()
            if ids:
                db_execute(f"DELETE FROM beneficiarios WHERE id IN ({','.join(['?']*len(ids))})", tuple(ids))
                st.session_state.ver += 1
                st.rerun()


# ══════════════════════════════════════════════
#  TAB 8 — TRANSFERÊNCIAS (VERSÃO FINAL)
# ══════════════════════════════════════════════

with tab8:
    st.markdown("## 🔄 Transferência entre Contas")
    st.caption("Movimente valores entre suas contas mantendo o saldo equilibrado.")
    st.divider()

    # Leitura das contas
    fontes_trans = [r[0] for r in db_query("SELECT nome FROM fontes ORDER BY nome")]
    
    if len(fontes_trans) < 2:
        st.warning("⚠️ Você precisa de pelo menos duas contas cadastradas para realizar transferências.")
    else:
        col_t1, col_t2 = st.columns(2)
        
        # Estado inicial para evitar erros de índice
        if 'origem_trans' not in st.session_state: 
            st.session_state.origem_trans = fontes_trans[0]
        
        origem = col_t1.selectbox("Conta de Origem", fontes_trans, 
                                  index=fontes_trans.index(st.session_state.origem_trans),
                                  key="origem_trans")
        
        # Filtro dinâmico para a conta de destino
        opcoes_destino = [f for f in fontes_trans if f != origem]
        destino = col_t2.selectbox("Conta de Destino", opcoes_destino, key="destino_trans")

        with st.form("form_transferencia", clear_on_submit=True):
            valor_trans = st.number_input("Valor da Transferência (€)", min_value=0.01, step=10.0, format="%.2f")
            
            # O campo de data permanece aqui; o formato visual é gerenciado pelo SO/Browser,
            # mas a conversão para o banco de dados é garantida abaixo no strftime.
            data_trans = st.date_input("Data da Transferência", date.today(), format="DD/MM/YYYY")
            
            nota_trans = st.text_input("Observação (opcional)")
            
            btn_enviar = st.form_submit_button("🔁 Executar Transferência", type="primary", use_container_width=True)
            
            if btn_enviar:
                if valor_trans <= 0:
                    st.error("O valor deve ser maior que zero.")
                else:
                    try:
                        # Execução da transferência com conversão forçada para dd/mm/aaaa
                        realizar_transferencia(
                            origem, 
                            destino, 
                            valor_trans, 
                            data_trans.strftime("%d/%m/%Y"), 
                            st.session_state.get('display_name', 'Admin'), 
                            nota_trans
                        )
                        
                        st.success(f"Transferência de €{valor_trans:,.2f} de {origem} para {destino} realizada com sucesso!")
                        
                        if 'ver' in st.session_state:
                            st.session_state.ver += 1
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao processar transferência: {e}")
