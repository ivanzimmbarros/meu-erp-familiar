# -*- coding: utf-8 -*-
"""
============================================================================
 CAMADA DE DADOS — ERP FAMILIAR (database.py)
============================================================================
Responsabilidade ÚNICA: acesso ao banco SQLite, schema, pool de conexões e
ferramentas de backup/restauração.

- Não importa Streamlit (pode ser usado por scripts, testes e CLI).
- O caminho do banco é controlado pela variável de módulo `DB_PATH`.
- POOL DE CONEXÕES: mantém uma conexão SQLite viva por caminho de banco
  (cache de recurso leve, protegido por lock reentrante), evitando reabrir o
  arquivo de disco a cada chamada/ciclo de renderização do Streamlit.
"""
import os
import sqlite3
import tempfile
import threading
import unicodedata

import pandas as pd

DB_PATH = "finance.db"

# Naturezas válidas (topo da hierarquia Natureza -> Categoria -> Subcategoria).
NATUREZAS = ("Despesa", "Receita")


class DuplicadoError(Exception):
    """Erro de cadastro duplicado (nome equivalente sob normalização).

    Carrega uma mensagem amigável pronta para ser exibida ao usuário."""
    pass

# ---------------------------------------------------------------------------
# POOL / CACHE DE CONEXÕES
# ---------------------------------------------------------------------------
_CONN_CACHE = {}
_LOCK = threading.RLock()


def get_connection():
    """Retorna (criando sob demanda) a conexão em cache para o DB_PATH atual.

    Usa check_same_thread=False pois o Streamlit pode reusar a conexão entre
    threads de rerun; o acesso é serializado por `_LOCK`.
    """
    with _LOCK:
        conn = _CONN_CACHE.get(DB_PATH)
        if conn is None:
            conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            conn.execute("PRAGMA foreign_keys = ON")
            _CONN_CACHE[DB_PATH] = conn
        return conn


def close_connections():
    """Fecha e descarta todas as conexões em cache (libera locks de arquivo).

    Necessário antes de restaurar/sobrescrever o banco e útil em testes."""
    with _LOCK:
        for conn in list(_CONN_CACHE.values()):
            try:
                conn.close()
            except Exception:
                pass
        _CONN_CACHE.clear()


# ---------------------------------------------------------------------------
# PRIMITIVAS DE ACESSO (usam o pool)
# ---------------------------------------------------------------------------
def db_execute(sql, params=()):
    with _LOCK:
        conn = get_connection()
        conn.execute(sql, params)
        conn.commit()


def db_query(sql, params=()):
    with _LOCK:
        conn = get_connection()
        return conn.execute(sql, params).fetchall()


def db_df(sql, params=()):
    with _LOCK:
        conn = get_connection()
        return pd.read_sql_query(sql, conn, params=params)


def db_execute_many(ops):
    with _LOCK:
        conn = get_connection()
        for sql, params in ops:
            conn.execute(sql, params)
        conn.commit()


# ---------------------------------------------------------------------------
# NORMALIZAÇÃO DE TEXTO E INTEGRIDADE CADASTRAL (ANTI-DUPLICADO INTELIGENTE)
# ---------------------------------------------------------------------------
def normalizar_texto(texto) -> str:
    """Canoniza um texto para comparação de equivalência.

    Remove acentos/diacríticos, recorta espaços nas pontas, colapsa espaços
    internos repetidos e padroniza para caixa baixa (casefold). Assim
    "Alimentação", "alimentação", "ALIMENTAÇÃO" e "Alimentacao" tornam-se
    todos "alimentacao".
    """
    if texto is None:
        return ""
    base = unicodedata.normalize("NFKD", str(texto))
    base = "".join(ch for ch in base if not unicodedata.combining(ch))
    base = " ".join(base.split())
    return base.casefold()


def _existe_normalizado(tabela: str, nome: str, coluna: str = "nome", excluir_id=None) -> bool:
    """True se já existir, na `tabela`, um valor equivalente a `nome` sob
    normalização (case/acento-insensível). `excluir_id` ignora a própria linha
    em edições."""
    alvo = normalizar_texto(nome)
    if not alvo:
        return False
    rows = db_query(f"SELECT id, {coluna} FROM {tabela}")
    for rid, valor in rows:
        if excluir_id is not None and rid == excluir_id:
            continue
        if normalizar_texto(valor) == alvo:
            return True
    return False


def criar_fonte(nome: str):
    """Cadastra uma conta bancária (fonte) barrando equivalentes."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Informe um nome para a conta.")
    if _existe_normalizado("fontes", nome):
        raise DuplicadoError(f"Já existe uma conta equivalente a “{nome}”.")
    db_execute("INSERT INTO fontes (nome) VALUES (?)", (nome,))


def criar_beneficiario(nome: str):
    """Cadastra um beneficiário barrando equivalentes."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Informe um nome para o beneficiário.")
    if _existe_normalizado("beneficiarios", nome):
        raise DuplicadoError(f"Já existe um beneficiário equivalente a “{nome}”.")
    db_execute("INSERT INTO beneficiarios (nome) VALUES (?)", (nome,))


def criar_cartao(nome: str, limite: float, conta_pagamento: str,
                 dia_fechamento: int, dia_vencimento: int):
    """Cadastra um cartão de crédito barrando equivalentes."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Informe um nome para o cartão.")
    if _existe_normalizado("cartoes", nome):
        raise DuplicadoError(f"Já existe um cartão equivalente a “{nome}”.")
    db_execute(
        "INSERT INTO cartoes (nome, limite, conta_pagamento, dia_fechamento, dia_vencimento) "
        "VALUES (?,?,?,?,?)",
        (nome, limite, conta_pagamento, dia_fechamento, dia_vencimento),
    )


def criar_categoria_principal(nome: str, natureza: str):
    """Cria uma Categoria Principal vinculada a uma Natureza (Receita/Despesa).

    O nome não pode ser equivalente a NENHUMA categoria/subcategoria existente,
    mesmo em natureza diferente (unicidade global sob normalização)."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Informe o nome da categoria.")
    if natureza not in NATUREZAS:
        raise ValueError("Natureza inválida (use 'Receita' ou 'Despesa').")
    if _existe_normalizado("categorias", nome):
        raise DuplicadoError(
            f"Já existe uma categoria/subcategoria equivalente a “{nome}”."
        )
    db_execute(
        "INSERT INTO categorias (nome, tipo_categoria) VALUES (?,?)", (nome, natureza)
    )


def criar_subcategoria(nome: str, pai_id: int):
    """Cria uma Subcategoria estritamente vinculada à sua Categoria Principal.

    Exige um `pai_id` de categoria principal existente e barra nomes
    equivalentes a qualquer categoria/subcategoria já cadastrada."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Informe o nome da subcategoria.")
    pai = db_query(
        "SELECT id FROM categorias WHERE id=? AND pai_id IS NULL", (pai_id,)
    )
    if not pai:
        raise ValueError("Categoria principal inexistente para vincular a subcategoria.")
    if _existe_normalizado("categorias", nome):
        raise DuplicadoError(
            f"Já existe uma categoria/subcategoria equivalente a “{nome}”."
        )
    db_execute("INSERT INTO categorias (nome, pai_id) VALUES (?,?)", (nome, pai_id))


# ---------------------------------------------------------------------------
# HIERARQUIA NATUREZA -> CATEGORIA -> SUBCATEGORIA (LEITURA FILTRADA)
# ---------------------------------------------------------------------------
def listar_categorias_principais(natureza: str):
    """Categorias principais de uma natureza: [(id, nome), ...] ordenadas."""
    return db_query(
        "SELECT id, nome FROM categorias WHERE pai_id IS NULL AND tipo_categoria=? ORDER BY nome",
        (natureza,),
    )


def listar_subcategorias(pai_id):
    """Subcategorias DIRETAS de uma categoria pai: [(id, nome), ...].

    COMPLIANCE: retorna exclusivamente os filhos reais do `pai_id`; nunca
    vaza nós de outras categorias/naturezas."""
    if pai_id is None:
        return []
    return db_query(
        "SELECT id, nome FROM categorias WHERE pai_id=? ORDER BY nome", (pai_id,)
    )


def subcategoria_pertence(pai_id, nome_sub: str) -> bool:
    """True somente se `nome_sub` for filho direto (sob normalização) do
    `pai_id`. Usada como trava de hierarquia no momento de salvar."""
    if pai_id is None or not (nome_sub or "").strip():
        return False
    alvo = normalizar_texto(nome_sub)
    filhos = db_query("SELECT nome FROM categorias WHERE pai_id=?", (pai_id,))
    return any(normalizar_texto(f[0]) == alvo for f in filhos)


# ---------------------------------------------------------------------------
# SCHEMA
# ---------------------------------------------------------------------------
TABLES = [
    "CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT, nome_exibicao TEXT, email TEXT, perfil TEXT DEFAULT 'Utilizador')",
    "CREATE TABLE IF NOT EXISTS fontes (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)",
    "CREATE TABLE IF NOT EXISTS saldos_iniciais (fonte TEXT PRIMARY KEY, valor_inicial REAL DEFAULT 0.0)",
    "CREATE TABLE IF NOT EXISTS beneficiarios (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)",
    "CREATE TABLE IF NOT EXISTS configuracoes (chave TEXT PRIMARY KEY, valor TEXT)",
    "CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE, pai_id INTEGER, tipo_categoria TEXT, FOREIGN KEY(pai_id) REFERENCES categorias(id) ON DELETE RESTRICT)",
    "CREATE TABLE IF NOT EXISTS cartoes (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE, limite REAL, dia_fechamento INTEGER, dia_vencimento INTEGER, conta_pagamento TEXT)",
    "CREATE TABLE IF NOT EXISTS orcamentos (id INTEGER PRIMARY KEY AUTOINCREMENT, mes_ano TEXT, categoria_pai TEXT, categoria_filho TEXT DEFAULT 'Geral', valor_previsto REAL, tipo_meta TEXT, UNIQUE(mes_ano, categoria_pai, categoria_filho, tipo_meta))",
    "CREATE TABLE IF NOT EXISTS transacoes (id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT, categoria_pai TEXT, categoria_filho TEXT, beneficiario TEXT, fonte TEXT, valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT, forma_pagamento TEXT DEFAULT 'Dinheiro/Débito', cartao_id INTEGER, fatura_ref TEXT, status_cartao TEXT DEFAULT 'pendente', status_liquidacao TEXT DEFAULT 'PAGO', data_liquidacao TEXT, parcela_id TEXT, parcela_numero INTEGER DEFAULT 1, total_parcelas INTEGER DEFAULT 1)",
    "CREATE TABLE IF NOT EXISTS assinaturas (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE, valor_eur REAL, dia_vencimento INTEGER, conta_padrao TEXT, categoria_pai TEXT, categoria_filho TEXT, ativa INTEGER DEFAULT 1)",
]

MIGRATIONS = [
    ("orcamentos", "categoria_filho", "TEXT DEFAULT 'Geral'"),
    ("usuarios", "email", "TEXT"),
    ("usuarios", "perfil", "TEXT DEFAULT 'Utilizador'"),
    ("usuarios", "force_reset", "INTEGER DEFAULT 0"),
    # Revisão e atribuição para casais (estilo Monarch Money).
    ("transacoes", "status_revisao", "TEXT DEFAULT 'REVISADO'"),
    ("transacoes", "atribuido_a", "TEXT"),
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_transacoes_fonte ON transacoes(fonte)",
    "CREATE INDEX IF NOT EXISTS idx_transacoes_cartao_id ON transacoes(cartao_id)",
    "CREATE INDEX IF NOT EXISTS idx_transacoes_status_liquidacao ON transacoes(status_liquidacao)",
    "CREATE INDEX IF NOT EXISTS idx_transacoes_fatura_ref ON transacoes(fatura_ref)",
    "CREATE INDEX IF NOT EXISTS idx_transacoes_data ON transacoes(data)",
    "CREATE INDEX IF NOT EXISTS idx_transacoes_fonte_tipo_status ON transacoes(fonte, tipo, status_liquidacao)",
    "CREATE INDEX IF NOT EXISTS idx_assinaturas_conta_ativa ON assinaturas(conta_padrao, ativa)",
    "CREATE INDEX IF NOT EXISTS idx_transacoes_revisao ON transacoes(atribuido_a, status_revisao)",
]


def init_db():
    """Cria tabelas, aplica migrações, cria índices e semeia a taxa padrão.

    NÃO cria o usuário administrador (responsabilidade de `auth.seed_admin`)."""
    for sql in TABLES:
        db_execute(sql)

    for tabela, coluna, tipo in MIGRATIONS:
        try:
            db_execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
        except Exception:
            pass  # Coluna já existe

    for sql in INDEXES:
        db_execute(sql)

    db_execute(
        "INSERT OR IGNORE INTO configuracoes (chave, valor) VALUES ('taxa_brl_eur', '0.16')"
    )
    # Rollover de metas (envelopes acumulados, estilo YNAB). '1' = ativo.
    db_execute(
        "INSERT OR IGNORE INTO configuracoes (chave, valor) VALUES ('rollover_ativo', '1')"
    )


# ---------------------------------------------------------------------------
# BACKUP / RESTAURAÇÃO
# ---------------------------------------------------------------------------
SQLITE_HEADER = b"SQLite format 3\x00"
# Tabelas mínimas que um backup precisa conter para ser aceito.
REQUIRED_TABLES = {"usuarios", "transacoes"}


def export_db_bytes() -> bytes:
    """Gera um snapshot CONSISTENTE do banco ativo e devolve seus bytes.

    Usa a API de backup nativa do SQLite (segura mesmo com a conexão em uso)."""
    with _LOCK:
        src = get_connection()
        fd, tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            dst = sqlite3.connect(tmp_path)
            with dst:
                src.backup(dst)
            dst.close()
            with open(tmp_path, "rb") as f:
                return f.read()
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def validar_backup(data_bytes: bytes):
    """Valida rigorosamente um arquivo de backup.

    Retorna (ok: bool, mensagem: str). Checa:
      1. Cabeçalho mágico do SQLite.
      2. Integridade interna (PRAGMA integrity_check).
      3. Presença das tabelas essenciais do sistema.
    """
    if not data_bytes or len(data_bytes) < 100:
        return False, "Arquivo vazio ou pequeno demais para ser um banco válido."
    if not data_bytes.startswith(SQLITE_HEADER):
        return False, "Arquivo não é um banco SQLite válido (cabeçalho inválido)."

    fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with open(tmp_path, "wb") as f:
            f.write(data_bytes)
        conn = sqlite3.connect(tmp_path)
        try:
            integ = conn.execute("PRAGMA integrity_check").fetchone()
            if not integ or integ[0] != "ok":
                return False, "Falha na verificação de integridade do SQLite."
            tabelas = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            faltando = REQUIRED_TABLES - tabelas
            if faltando:
                return False, (
                    "Backup não contém tabelas essenciais: "
                    + ", ".join(sorted(faltando)) + "."
                )
        finally:
            conn.close()
        return True, "Backup válido."
    except sqlite3.DatabaseError as e:
        return False, f"Arquivo corrompido ou ilegível: {e}"
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def restaurar_db(data_bytes: bytes):
    """Valida e, se aprovado, substitui o banco ativo pelo conteúdo enviado.

    Retorna (ok: bool, mensagem: str). Se a validação falhar, o banco atual
    permanece intacto."""
    ok, msg = validar_backup(data_bytes)
    if not ok:
        return False, msg

    with _LOCK:
        close_connections()
        # Remove arquivos auxiliares (WAL/journal) que possam mascarar os dados.
        for ext in ("-wal", "-shm", "-journal"):
            aux = DB_PATH + ext
            if os.path.exists(aux):
                try:
                    os.remove(aux)
                except OSError:
                    pass
        with open(DB_PATH, "wb") as f:
            f.write(data_bytes)
    return True, "Banco de dados restaurado com sucesso."
