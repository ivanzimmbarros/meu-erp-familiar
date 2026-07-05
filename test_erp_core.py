# -*- coding: utf-8 -*-
"""
============================================================================
 REDE DE SEGURANÇA DE TESTES — ERP FAMILIAR (test_erp_core.py)
============================================================================

Valida o NÚCLEO LÓGICO do sistema após a refatoração em módulos
(`database.py`, `auth.py`, `finance.py`) e o `app.py` de UI.

Vantagem da nova arquitetura: os módulos de núcleo NÃO dependem do Streamlit,
então podem ser importados e testados diretamente, sem mocks de GUI. Cada
teste aponta `database.DB_PATH` para um banco SQLite temporário isolado, sem
tocar no `finance.db` real.

Há ainda um SMOKE TEST que importa o `app.py` (UI) usando um mock leve de
Streamlit, garantindo que a camada de interface continua importável após a
divisão de arquivos.

Execução:
    pytest -v test_erp_core.py
    (ou)  python -m unittest -v test_erp_core
"""

import os
import sys
import io
import types
import sqlite3
import tempfile
import shutil
import hashlib
import importlib
import importlib.util
import unittest
from datetime import date, datetime

import pandas as pd

import database
import auth
import finance
import reports


ADMIN_USER = "admin_master"
ADMIN_PASSWORD = "MasterPass123!"
ADMIN_EMAIL = "admin@local.dev"


# ---------------------------------------------------------------------------
# BASE: banco isolado por teste
# ---------------------------------------------------------------------------
class ERPTestBase(unittest.TestCase):
    def setUp(self):
        database.close_connections()
        self._tmp_dir = tempfile.mkdtemp(prefix="erp_test_")
        self.db_path = os.path.join(self._tmp_dir, "finance_test.db")
        database.DB_PATH = self.db_path
        database.init_db()
        auth.seed_admin(ADMIN_USER, ADMIN_PASSWORD, ADMIN_EMAIL)

    def tearDown(self):
        # Fecha conexões do pool antes de remover o diretório (lock no Windows).
        database.close_connections()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _add_fonte(self, nome, saldo_inicial=0.0):
        database.db_execute("INSERT INTO fontes (nome) VALUES (?)", (nome,))
        database.db_execute(
            "INSERT INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)",
            (nome, saldo_inicial),
        )

    def _add_transacao(self, **kw):
        cols = ", ".join(kw.keys())
        ph = ", ".join(["?"] * len(kw))
        database.db_execute(
            f"INSERT INTO transacoes ({cols}) VALUES ({ph})", tuple(kw.values())
        )


# ===========================================================================
# (a) INICIALIZAÇÃO DO BANCO DE DADOS
# ===========================================================================
class TestInicializacaoBanco(ERPTestBase):
    TABELAS_ESPERADAS = {
        "usuarios", "fontes", "saldos_iniciais", "beneficiarios",
        "configuracoes", "categorias", "cartoes", "orcamentos", "transacoes",
        "importacoes_staging", "auditoria_sistema",
    }

    def test_todas_as_tabelas_criadas(self):
        rows = database.db_query("SELECT name FROM sqlite_master WHERE type='table'")
        tabelas = {r[0] for r in rows}
        faltando = self.TABELAS_ESPERADAS - tabelas
        self.assertFalse(faltando, f"Tabelas ausentes após init_db(): {faltando}")

    def test_coluna_force_reset_existe(self):
        cols = [c[1] for c in database.db_query("PRAGMA table_info(usuarios)")]
        self.assertIn("force_reset", cols)

    def test_taxa_cambio_padrao_inserida(self):
        res = database.db_query(
            "SELECT valor FROM configuracoes WHERE chave='taxa_brl_eur'"
        )
        self.assertTrue(res)
        self.assertEqual(float(res[0][0]), 0.16)

    # NOVO: valida a criação dos índices de performance.
    def test_indices_de_performance_criados(self):
        rows = database.db_query("SELECT name FROM sqlite_master WHERE type='index'")
        indices = {r[0] for r in rows}
        esperados = {
            "idx_transacoes_fonte",
            "idx_transacoes_cartao_id",
            "idx_transacoes_status_liquidacao",
            "idx_transacoes_fatura_ref",
            "idx_transacoes_data",
            "idx_transacoes_data_nota",
            "idx_transacoes_nota",
            "idx_staging_fonte",
        }
        faltando = esperados - indices
        self.assertFalse(faltando, f"Índices ausentes: {faltando}")


# ===========================================================================
# (b) CRIAÇÃO DE USUÁRIO E HASH DE SENHA (agora PBKDF2)
# ===========================================================================
class TestUsuarioESenha(ERPTestBase):
    def test_admin_seed_criado_e_autenticavel(self):
        # NOVO comportamento: hash é PBKDF2 e a verificação é via auth.autenticar.
        user = auth.autenticar(ADMIN_USER, ADMIN_PASSWORD)
        self.assertIsNotNone(user)
        self.assertEqual(user["perfil"], "Administrador")

    def test_criacao_e_verificacao_de_usuario(self):
        senha = "SenhaForte#2024"
        auth.criar_usuario("joao", senha, "João Silva", "joao@fam.dev", "Utilizador")
        user = auth.autenticar("joao", senha)
        self.assertIsNotNone(user)
        self.assertEqual(user["nome"], "João Silva")

    def test_senha_nao_e_armazenada_em_texto_plano(self):
        senha = "TextoPlano123"
        auth.criar_usuario("maria", senha, "Maria", "maria@fam.dev")
        guardado = database.db_query(
            "SELECT password FROM usuarios WHERE username='maria'"
        )[0][0]
        self.assertNotIn(senha, guardado)
        self.assertTrue(guardado.startswith("pbkdf2_sha256$"))

    def test_seed_admin_exige_troca_de_senha_inicial(self):
        # O admin semente nasce com force_reset=1 (troca obrigatória no 1º login).
        self.assertTrue(auth.precisa_trocar_senha(ADMIN_USER))


# ===========================================================================
# (NOVO) SEGURANÇA DO HASH PBKDF2
# ===========================================================================
class TestPBKDF2(ERPTestBase):
    def test_formato_do_hash_pbkdf2(self):
        h = auth.hash_password("abc123")
        partes = h.split("$")
        self.assertEqual(len(partes), 4)
        self.assertEqual(partes[0], "pbkdf2_sha256")
        self.assertEqual(int(partes[1]), auth.PBKDF2_ITERATIONS)
        # salt (16 bytes => 32 hex) e hash sha256 (32 bytes => 64 hex)
        self.assertEqual(len(partes[2]), 32)
        self.assertEqual(len(partes[3]), 64)

    def test_salt_aleatorio_gera_hashes_diferentes(self):
        h1 = auth.hash_password("mesma_senha")
        h2 = auth.hash_password("mesma_senha")
        self.assertNotEqual(h1, h2, "Cada hash deve usar um salt aleatório distinto.")

    def test_verificacao_senha_correta_e_incorreta(self):
        h = auth.hash_password("Correta!1")
        self.assertTrue(auth.verify_password("Correta!1", h))
        self.assertFalse(auth.verify_password("Errada!2", h))

    def test_salt_fixo_reproduz_o_mesmo_hash(self):
        salt = bytes.fromhex("00112233445566778899aabbccddeeff")
        h1 = auth.hash_password("repetivel", salt=salt)
        h2 = auth.hash_password("repetivel", salt=salt)
        self.assertEqual(h1, h2)

    def test_retrocompatibilidade_com_sha256_legado(self):
        # Usuário antigo cujo hash ainda está em SHA-256 puro deve conseguir logar.
        senha = "AntigoLegado9"
        legacy = hashlib.sha256(senha.encode()).hexdigest()
        database.db_execute(
            "INSERT INTO usuarios (username, password, nome_exibicao, email, perfil) "
            "VALUES (?,?,?,?,?)",
            ("legado", legacy, "Usuário Legado", "legado@fam.dev", "Utilizador"),
        )
        self.assertTrue(auth.is_legacy_hash(legacy))
        self.assertIsNotNone(auth.autenticar("legado", senha))
        self.assertIsNone(auth.autenticar("legado", "errada"))

    def test_autenticar_usuario_inexistente_retorna_none(self):
        self.assertIsNone(auth.autenticar("fantasma", "qualquer"))


# ===========================================================================
# (NOVO) GESTÃO DE CONTAS E RECUPERAÇÃO
# ===========================================================================
class TestGestaoContas(ERPTestBase):
    def test_criar_usuario_duplicado_e_bloqueado(self):
        # Agora a prevenção amigável (DuplicadoError) intercepta o duplicado
        # exato ANTES da restrição UNIQUE do banco (sqlite3.IntegrityError).
        auth.criar_usuario("dup", "senha1", "Dup", "dup@fam.dev")
        with self.assertRaises(database.DuplicadoError):
            auth.criar_usuario("dup", "senha2", "Dup2", "dup2@fam.dev")

    def test_novo_usuario_exige_troca_de_senha_no_primeiro_login(self):
        # Política de segurança: todo usuário recém-criado nasce com troca
        # obrigatória de senha (force_reset=1) por padrão.
        auth.criar_usuario("novato", "Inicial#1", "Novato", "novato@fam.dev")
        self.assertTrue(auth.precisa_trocar_senha("novato"))
        fr = database.db_query(
            "SELECT force_reset FROM usuarios WHERE username='novato'"
        )[0][0]
        self.assertEqual(fr, 1)

    def test_definir_nova_senha_zera_force_reset(self):
        auth.criar_usuario("reset_user", "antiga1", "Reset", "r@fam.dev", force_reset=1)
        self.assertTrue(auth.precisa_trocar_senha("reset_user"))
        auth.definir_nova_senha("reset_user", "NovaSenha#9")
        self.assertFalse(auth.precisa_trocar_senha("reset_user"))
        self.assertIsNotNone(auth.autenticar("reset_user", "NovaSenha#9"))

    def test_iniciar_recuperacao_marca_reset_e_troca_hash(self):
        auth.criar_usuario("recov", "original1", "Recov", "recov@fam.dev")
        hash_antigo = database.db_query(
            "SELECT password FROM usuarios WHERE username='recov'"
        )[0][0]
        temp = auth.iniciar_recuperacao("recov@fam.dev")
        self.assertIsNotNone(temp)
        hash_novo = database.db_query(
            "SELECT password FROM usuarios WHERE username='recov'"
        )[0][0]
        self.assertNotEqual(hash_antigo, hash_novo)
        self.assertTrue(auth.precisa_trocar_senha("recov"))
        self.assertIsNotNone(auth.autenticar("recov", temp))

    def test_iniciar_recuperacao_email_inexistente_retorna_none(self):
        self.assertIsNone(auth.iniciar_recuperacao("naoexiste@fam.dev"))


# ===========================================================================
# (c) CÁLCULO DE PARCELAS E FATURA DE CARTÃO
# ===========================================================================
class TestParcelas(ERPTestBase):
    def test_parcelamento_simples_distribui_centavos_na_ultima(self):
        parc = finance.calcular_parcelas("2024-01-15", 0, 0, 100.0, 3, is_cartao=False)
        valores = [p[1] for p in parc]
        self.assertEqual(valores, [33.33, 33.33, 33.34])
        self.assertEqual([p[2] for p in parc], [1, 2, 3])
        self.assertAlmostEqual(sum(valores), 100.0, places=2)

    def test_parcelamento_simples_datas_mensais_mesmo_dia(self):
        parc = finance.calcular_parcelas("2024-01-15", 0, 0, 90.0, 3, is_cartao=False)
        datas = [p[0] for p in parc]
        self.assertEqual(datas, ["2024-01-15", "2024-02-15", "2024-03-15"])

    def test_parcela_unica_valor_total(self):
        parc = finance.calcular_parcelas("2024-05-10", 0, 0, 250.0, 1, is_cartao=False)
        self.assertEqual(len(parc), 1)
        self.assertEqual(parc[0][1], 250.0)
        self.assertEqual(parc[0][0], "2024-05-10")

    def test_cartao_compra_apos_fechamento_aplica_offset(self):
        # Compra dia 26 (> fechamento 25) => 1ª fatura no mês seguinte (inalterado).
        parc = finance.calcular_parcelas("2024-01-26", 25, 5, 300.0, 3, is_cartao=True)
        datas = [p[0] for p in parc]
        self.assertEqual(datas, ["2024-02-05", "2024-03-05", "2024-04-05"])


# ===========================================================================
# (NOVO) CORREÇÃO DO BUG DO CARTÃO: 1ª PARCELA NUNCA ANTES DA COMPRA
# ===========================================================================
class TestRegrasCartaoCorrigidas(ERPTestBase):
    def test_compra_antes_fechamento_vence_no_mes_seguinte(self):
        # ANTES (bug): 1ª parcela vencia em 2024-01-05 (antes da compra de 10/01).
        # AGORA: empurra +1 mês => 2024-02-05.
        parc = finance.calcular_parcelas("2024-01-10", 25, 5, 300.0, 3, is_cartao=True)
        datas = [p[0] for p in parc]
        self.assertEqual(datas, ["2024-02-05", "2024-03-05", "2024-04-05"])

    def test_primeira_parcela_nunca_anterior_a_compra(self):
        cenarios = [
            ("2024-01-10", 25, 5),   # venc < dia compra, antes do fechamento
            ("2024-03-28", 25, 1),   # após fechamento, venc dia 1
            ("2024-06-15", 20, 10),  # venc < dia compra
            ("2024-12-31", 28, 5),   # virada de ano
        ]
        for data_compra, fech, venc in cenarios:
            parc = finance.calcular_parcelas(data_compra, fech, venc, 120.0, 2, is_cartao=True)
            d_compra = datetime.strptime(data_compra, "%Y-%m-%d")
            primeiro = datetime.strptime(parc[0][0], "%Y-%m-%d")
            self.assertGreaterEqual(
                primeiro, d_compra,
                f"1ª parcela {parc[0][0]} não pode ser anterior à compra {data_compra}",
            )

    def test_compra_antes_fechamento_com_venc_posterior_mantem_mes(self):
        # Compra dia 10, fechamento 25, vencimento dia 20 (>= dia da compra):
        # NÃO deve empurrar; 1ª parcela vence no mesmo mês (2024-01-20).
        parc = finance.calcular_parcelas("2024-01-10", 25, 20, 300.0, 3, is_cartao=True)
        datas = [p[0] for p in parc]
        self.assertEqual(datas, ["2024-01-20", "2024-02-20", "2024-03-20"])

    def test_parcelas_seguem_offset_linearmente(self):
        parc = finance.calcular_parcelas("2024-01-10", 25, 5, 600.0, 4, is_cartao=True)
        datas = [p[0] for p in parc]
        self.assertEqual(
            datas, ["2024-02-05", "2024-03-05", "2024-04-05", "2024-05-05"]
        )


class TestFaturaRef(ERPTestBase):
    def test_compra_antes_do_fechamento_fatura_mes_corrente(self):
        self.assertEqual(finance.calcular_fatura_ref("2024-03-10", 25), "2024-03")

    def test_compra_apos_fechamento_fatura_mes_seguinte(self):
        self.assertEqual(finance.calcular_fatura_ref("2024-03-26", 25), "2024-04")

    def test_compra_em_dezembro_apos_fechamento_vira_ano_seguinte(self):
        self.assertEqual(finance.calcular_fatura_ref("2024-12-31", 25), "2025-01")


class TestStatusOperacao(ERPTestBase):
    def test_primeira_parcela_receita_recebido(self):
        self.assertEqual(finance.determinar_status_operacao("Receita", True), "RECEBIDO")

    def test_primeira_parcela_despesa_pago(self):
        self.assertEqual(finance.determinar_status_operacao("Despesa", True), "PAGO")

    def test_parcelas_seguintes_pendente(self):
        self.assertEqual(finance.determinar_status_operacao("Despesa", False), "PENDENTE")
        self.assertEqual(finance.determinar_status_operacao("Receita", False), "PENDENTE")


# ===========================================================================
# (d) SALDO REAL, COMPROMETIDO E DISPONÍVEL
# ===========================================================================
class TestSaldos(ERPTestBase):
    def setUp(self):
        super().setUp()
        self._add_fonte("Conta A", saldo_inicial=1000.0)

        self._add_transacao(
            data="2024-01-05", categoria_pai="Salário", fonte="Conta A",
            valor_eur=500.0, tipo="Receita", forma_pagamento="Dinheiro/Débito",
            status_liquidacao="RECEBIDO",
        )
        self._add_transacao(
            data="2024-01-06", categoria_pai="Mercado", fonte="Conta A",
            valor_eur=200.0, tipo="Despesa", forma_pagamento="Dinheiro/Débito",
            status_liquidacao="PAGO",
        )
        self._add_transacao(
            data="2024-02-10", categoria_pai="Aluguel", fonte="Conta A",
            valor_eur=100.0, tipo="Despesa", forma_pagamento="Dinheiro/Débito",
            status_liquidacao="PENDENTE",
        )
        self._add_transacao(
            data="2024-02-15", categoria_pai="Reembolso", fonte="Conta A",
            valor_eur=50.0, tipo="Receita", forma_pagamento="Dinheiro/Débito",
            status_liquidacao="PREVISTO",
        )

        database.db_execute(
            "INSERT INTO cartoes (nome, limite, dia_fechamento, dia_vencimento, conta_pagamento) "
            "VALUES (?,?,?,?,?)",
            ("Cartão X", 5000.0, 25, 5, "Conta A"),
        )
        cartao_id = database.db_query("SELECT id FROM cartoes WHERE nome='Cartão X'")[0][0]
        self._add_transacao(
            data="2024-02-03", categoria_pai="Compras", fonte="Cartão X",
            valor_eur=300.0, tipo="Despesa", forma_pagamento="Cartão de Crédito",
            cartao_id=cartao_id, status_cartao="pendente", status_liquidacao="PENDENTE",
        )

    def test_saldo_real(self):
        self.assertEqual(finance.calcular_saldo_real("Conta A"), 1300.0)

    def test_comprometido(self):
        self.assertEqual(finance.calcular_comprometido("Conta A"), 350.0)

    def test_disponivel(self):
        self.assertEqual(finance.calcular_disponivel("Conta A"), 950.0)

    def test_saldo_real_ignora_movimentos_de_cartao(self):
        self.assertEqual(finance.calcular_saldo_real("Conta A"), 1300.0)

    def test_conta_sem_movimentos_retorna_saldo_inicial(self):
        self._add_fonte("Conta Vazia", saldo_inicial=42.5)
        self.assertEqual(finance.calcular_saldo_real("Conta Vazia"), 42.5)
        self.assertEqual(finance.calcular_comprometido("Conta Vazia"), 0.0)


# ===========================================================================
# (e) TRANSFERÊNCIA ENTRE CONTAS (SOMA ZERO)
# ===========================================================================
class TestTransferencia(ERPTestBase):
    def setUp(self):
        super().setUp()
        self._add_fonte("Conta Origem", saldo_inicial=1000.0)
        self._add_fonte("Conta Destino", saldo_inicial=200.0)

    def test_transferencia_debita_origem_e_credita_destino(self):
        finance.realizar_transferencia(
            "Conta Origem", "Conta Destino", 150.0, "2024-04-01", "tester", "Mesada"
        )
        self.assertEqual(finance.calcular_saldo_real("Conta Origem"), 850.0)
        self.assertEqual(finance.calcular_saldo_real("Conta Destino"), 350.0)

    def test_transferencia_preserva_o_total_soma_zero(self):
        antes = (finance.calcular_saldo_real("Conta Origem")
                 + finance.calcular_saldo_real("Conta Destino"))
        finance.realizar_transferencia(
            "Conta Origem", "Conta Destino", 333.33, "2024-04-02", "tester", "Ajuste"
        )
        depois = (finance.calcular_saldo_real("Conta Origem")
                  + finance.calcular_saldo_real("Conta Destino"))
        self.assertAlmostEqual(antes, depois, places=2)

    def test_transferencia_gera_duas_pernas(self):
        finance.realizar_transferencia(
            "Conta Origem", "Conta Destino", 100.0, "2024-04-03", "tester", "Teste pernas"
        )
        linhas = database.db_query(
            "SELECT tipo, fonte, status_liquidacao FROM transacoes "
            "WHERE categoria_pai='Transferência' ORDER BY tipo"
        )
        self.assertEqual(len(linhas), 2)
        despesa = [l for l in linhas if l[0] == "Despesa"][0]
        receita = [l for l in linhas if l[0] == "Receita"][0]
        self.assertEqual((despesa[1], despesa[2]), ("Conta Origem", "PAGO"))
        self.assertEqual((receita[1], receita[2]), ("Conta Destino", "RECEBIDO"))


# ===========================================================================
# (NOVO) POOL / CACHE DE CONEXÕES SQLITE
# ===========================================================================
class TestPoolConexoes(ERPTestBase):
    def test_conexao_e_reutilizada_do_cache(self):
        c1 = database.get_connection()
        c2 = database.get_connection()
        self.assertIs(c1, c2, "get_connection deve reutilizar a mesma conexão em cache.")

    def test_close_connections_limpa_o_cache(self):
        database.get_connection()
        self.assertIn(database.DB_PATH, database._CONN_CACHE)
        database.close_connections()
        self.assertEqual(len(database._CONN_CACHE), 0)

    def test_operacoes_funcionam_apos_reabertura(self):
        self._add_fonte("Pool A", 10.0)
        database.close_connections()  # simula descarte de conexão
        # Nova conexão deve ser criada automaticamente e enxergar os dados.
        res = database.db_query("SELECT valor_inicial FROM saldos_iniciais WHERE fonte='Pool A'")
        self.assertEqual(res[0][0], 10.0)


# ===========================================================================
# (NOVO) BACKUP / RESTAURAÇÃO E VALIDAÇÃO DE INTEGRIDADE
# ===========================================================================
class TestBackupRestore(ERPTestBase):
    def setUp(self):
        super().setUp()
        self._add_fonte("Conta Backup", saldo_inicial=777.0)
        auth.criar_usuario("backup_user", "senha123", "Backup", "b@fam.dev")

    def test_export_gera_sqlite_valido(self):
        dados = database.export_db_bytes()
        self.assertTrue(dados.startswith(database.SQLITE_HEADER))
        ok, msg = database.validar_backup(dados)
        self.assertTrue(ok, msg)

    def test_validar_rejeita_arquivo_nao_sqlite(self):
        ok, msg = database.validar_backup(b"isto definitivamente nao e um banco sqlite" * 5)
        self.assertFalse(ok)

    def test_validar_rejeita_arquivo_vazio(self):
        ok, _ = database.validar_backup(b"")
        self.assertFalse(ok)

    def test_validar_rejeita_sqlite_sem_tabelas_essenciais(self):
        # Cria um SQLite legítimo, porém SEM as tabelas usuarios/transacoes.
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            conn = sqlite3.connect(tmp)
            conn.execute("CREATE TABLE lixo (x INTEGER)")
            conn.commit()
            conn.close()
            with open(tmp, "rb") as f:
                dados = f.read()
        finally:
            os.remove(tmp)
        ok, msg = database.validar_backup(dados)
        self.assertFalse(ok)
        self.assertIn("essenciais", msg.lower())

    def test_restauracao_round_trip(self):
        # 1. Snapshot com os dados atuais.
        backup = database.export_db_bytes()
        # 2. Altera o banco (remove a conta).
        database.db_execute("DELETE FROM saldos_iniciais WHERE fonte='Conta Backup'")
        database.db_execute("DELETE FROM fontes WHERE nome='Conta Backup'")
        self.assertEqual(
            database.db_query("SELECT COUNT(*) FROM fontes WHERE nome='Conta Backup'")[0][0], 0
        )
        # 3. Restaura o snapshot.
        ok, msg = database.restaurar_db(backup)
        self.assertTrue(ok, msg)
        # 4. Dado voltou.
        res = database.db_query("SELECT valor_inicial FROM saldos_iniciais WHERE fonte='Conta Backup'")
        self.assertEqual(res[0][0], 777.0)
        self.assertIsNotNone(auth.autenticar("backup_user", "senha123"))

    def test_restauracao_invalida_nao_destroi_banco(self):
        antes = database.db_query("SELECT COUNT(*) FROM fontes")[0][0]
        ok, _ = database.restaurar_db(b"arquivo corrompido nao sqlite")
        self.assertFalse(ok)
        # Banco atual permanece intacto e operável.
        depois = database.db_query("SELECT COUNT(*) FROM fontes")[0][0]
        self.assertEqual(antes, depois)


# ===========================================================================
# (NOVO) ROTAS / PÁGINAS E PERMISSÕES DE PERFIL
# ===========================================================================
class TestPaginasEPermissoes(unittest.TestCase):
    def setUp(self):
        self.pages_config = importlib.import_module("pages_config")

    def test_admin_ve_pagina_de_gestao(self):
        chaves = {p["key"] for p in self.pages_config.get_pages(is_admin=True)}
        self.assertIn("gestao", chaves)

    def test_utilizador_comum_nao_ve_gestao(self):
        chaves = {p["key"] for p in self.pages_config.get_pages(is_admin=False)}
        self.assertNotIn("gestao", chaves)

    def test_utilizador_tem_exatamente_uma_pagina_a_menos(self):
        admin = self.pages_config.get_pages(is_admin=True)
        comum = self.pages_config.get_pages(is_admin=False)
        self.assertEqual(len(admin) - len(comum), 1)

    def test_existe_exatamente_uma_pagina_padrao(self):
        defaults = [p for p in self.pages_config.PAGES if p.get("default")]
        self.assertEqual(len(defaults), 1)

    def test_todos_os_arquivos_de_pagina_existem(self):
        base = os.path.dirname(os.path.abspath(__file__))
        for p in self.pages_config.PAGES:
            caminho = os.path.join(base, p["file"])
            self.assertTrue(os.path.exists(caminho), f"Arquivo de página ausente: {p['file']}")


# ===========================================================================
# (NOVO) INTEGRIDADE DA REFATORAÇÃO / ARQUITETURA
# ===========================================================================
class TestArquiteturaModular(unittest.TestCase):
    def test_modulos_de_nucleo_nao_importam_streamlit(self):
        # database/finance/auth/import_parser devem ser puros (sem dependência de UI).
        for nome in ("database", "finance", "auth", "import_parser"):
            mod = importlib.import_module(nome)
            fonte = open(mod.__file__, encoding="utf-8").read()
            self.assertNotIn(
                "import streamlit", fonte,
                f"O módulo {nome}.py não deve importar streamlit.",
            )

    def test_login_duplicado_removido_da_tab_historico(self):
        # O bloco de login só pode existir UMA vez no app.py (camada global).
        app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
        conteudo = open(app_path, encoding="utf-8").read()
        ocorrencias = conteudo.count("🔒 Portal de Acesso")
        self.assertEqual(
            ocorrencias, 1,
            f"Esperado 1 bloco de login; encontrado {ocorrencias} (duplicata não removida).",
        )

    def test_app_py_importa_sem_erros_com_mock_de_streamlit(self):
        # SMOKE TEST: garante que o entrypoint (app.py) ainda é importável e
        # que o gate de login global dispara st.stop() antes da navegação.
        app_module = _import_app_with_mock()
        self.assertIsNotNone(app_module)

    def test_app_usa_navegacao_multipaginas(self):
        # Garante que a migração para st.navigation/st.Page foi efetivada
        # e que o antigo st.tabs não é mais usado no entrypoint.
        app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
        conteudo = open(app_path, encoding="utf-8").read()
        self.assertIn("st.navigation", conteudo)
        self.assertIn("st.Page", conteudo)
        self.assertNotIn("st.tabs", conteudo)


# ===========================================================================
# (NOVO) NORMALIZAÇÃO DE TEXTO (BASE DO ANTI-DUPLICADO INTELIGENTE)
# ===========================================================================
class TestNormalizacaoTexto(unittest.TestCase):
    def test_acentos_e_caixa_sao_equivalentes(self):
        for v in ["Alimentação", "alimentação", "ALIMENTAÇÃO", "Alimentacao"]:
            self.assertEqual(database.normalizar_texto(v), "alimentacao")

    def test_recorta_e_colapsa_espacos(self):
        self.assertEqual(database.normalizar_texto("   Conta   Corrente  "), "conta corrente")

    def test_none_e_vazio(self):
        self.assertEqual(database.normalizar_texto(None), "")
        self.assertEqual(database.normalizar_texto("   "), "")


# ===========================================================================
# (NOVO) PREVENÇÃO INTELIGENTE DE DUPLICADOS EM TODO O SISTEMA
# ===========================================================================
class TestDuplicadosCadastrais(ERPTestBase):
    def _id_categoria(self, nome):
        return database.db_query("SELECT id FROM categorias WHERE nome=?", (nome,))[0][0]

    def test_fonte_equivalente_bloqueada(self):
        database.criar_fonte("Banco do Brasil")
        for variante in ["banco do brasil", "BANCO DO BRASIL", "  Banco   do   Brasil "]:
            with self.assertRaises(database.DuplicadoError):
                database.criar_fonte(variante)
        self.assertEqual(database.db_query("SELECT COUNT(*) FROM fontes")[0][0], 1)

    def test_beneficiario_equivalente_bloqueado(self):
        database.criar_beneficiario("João Silva")
        with self.assertRaises(database.DuplicadoError):
            database.criar_beneficiario("joao silva")

    def test_cartao_equivalente_bloqueado(self):
        database.criar_fonte("Conta Pgto")
        database.criar_cartao("Nubank", 1000.0, "Conta Pgto", 25, 5)
        with self.assertRaises(database.DuplicadoError):
            database.criar_cartao("  NUBANK ", 500.0, "Conta Pgto", 20, 1)

    def test_categoria_principal_equivalente_bloqueada(self):
        database.criar_categoria_principal("Alimentação", "Despesa")
        for v in ["alimentacao", "ALIMENTAÇÃO", "Alimentacao"]:
            with self.assertRaises(database.DuplicadoError):
                database.criar_categoria_principal(v, "Despesa")

    def test_categoria_equivalente_bloqueada_mesmo_em_natureza_diferente(self):
        # COMPLIANCE 1a: nomes equivalentes barrados ainda que em naturezas distintas.
        database.criar_categoria_principal("Investimentos", "Despesa")
        with self.assertRaises(database.DuplicadoError):
            database.criar_categoria_principal("investimentos", "Receita")

    def test_subcategoria_equivalente_bloqueada_globalmente(self):
        database.criar_categoria_principal("Casa", "Despesa")
        database.criar_categoria_principal("Renda", "Receita")
        database.criar_subcategoria("Aluguel", self._id_categoria("Casa"))
        # Mesmo sob outra categoria/natureza, "aluguel" equivalente é barrado.
        with self.assertRaises(database.DuplicadoError):
            database.criar_subcategoria("  ALUGUEL ", self._id_categoria("Renda"))

    def test_subcategoria_nao_colide_com_categoria_principal(self):
        database.criar_categoria_principal("Saúde", "Despesa")
        database.criar_categoria_principal("Transporte", "Despesa")
        with self.assertRaises(database.DuplicadoError):
            database.criar_subcategoria("saude", self._id_categoria("Transporte"))

    def test_usuario_login_equivalente_bloqueado(self):
        auth.criar_usuario("Joao", "Senha#1", "Joao", "j@fam.dev")
        with self.assertRaises(database.DuplicadoError):
            auth.criar_usuario("  joao ", "Senha#2", "Joao2", "j2@fam.dev")


# ===========================================================================
# (NOVO) HIERARQUIA ESTRITA NATUREZA -> CATEGORIA -> SUBCATEGORIA
# ===========================================================================
class TestHierarquiaCategorias(ERPTestBase):
    def setUp(self):
        super().setUp()
        database.criar_categoria_principal("Casa", "Despesa")
        database.criar_categoria_principal("Renda", "Receita")
        self.id_casa = database.db_query("SELECT id FROM categorias WHERE nome='Casa'")[0][0]
        self.id_renda = database.db_query("SELECT id FROM categorias WHERE nome='Renda'")[0][0]
        database.criar_subcategoria("Aluguel", self.id_casa)
        database.criar_subcategoria("Salario", self.id_renda)

    def test_principais_filtradas_por_natureza(self):
        desp = {n for _, n in database.listar_categorias_principais("Despesa")}
        rec = {n for _, n in database.listar_categorias_principais("Receita")}
        self.assertIn("Casa", desp)
        self.assertNotIn("Renda", desp)
        self.assertIn("Renda", rec)
        self.assertNotIn("Casa", rec)

    def test_subcategorias_apenas_do_pai_selecionado(self):
        self.assertEqual({n for _, n in database.listar_subcategorias(self.id_casa)}, {"Aluguel"})
        self.assertEqual({n for _, n in database.listar_subcategorias(self.id_renda)}, {"Salario"})

    def test_subcategoria_nao_vaza_para_outro_pai(self):
        # COMPLIANCE 4: filho de "Renda" jamais é aceito sob "Casa".
        self.assertFalse(database.subcategoria_pertence(self.id_casa, "Salario"))
        self.assertTrue(database.subcategoria_pertence(self.id_casa, "Aluguel"))

    def test_subcategoria_pertence_respeita_normalizacao(self):
        self.assertTrue(database.subcategoria_pertence(self.id_casa, "  aluguel "))

    def test_criar_subcategoria_exige_pai_principal_valido(self):
        # Pai inexistente -> erro.
        with self.assertRaises(ValueError):
            database.criar_subcategoria("Orfa", 99999)
        # Pai que é uma subcategoria (nível 3) -> erro: hierarquia tem só 3 níveis.
        id_aluguel = database.db_query("SELECT id FROM categorias WHERE nome='Aluguel'")[0][0]
        with self.assertRaises(ValueError):
            database.criar_subcategoria("NetoProibido", id_aluguel)


# ===========================================================================
# (QA) ROBUSTEZ DE TRANSFERÊNCIA (ENTRADAS INVÁLIDAS)
# ===========================================================================
class TestRobustezTransferencia(ERPTestBase):
    def setUp(self):
        super().setUp()
        self._add_fonte("Conta A", 100.0)
        self._add_fonte("Conta B", 100.0)

    def test_transferencia_mesma_conta_e_bloqueada(self):
        with self.assertRaises(ValueError):
            finance.realizar_transferencia("Conta A", "Conta A", 10.0, "2024-01-01", "u", "x")

    def test_transferencia_valor_zero_ou_negativo_bloqueada(self):
        for v in (0.0, -5.0):
            with self.assertRaises(ValueError):
                finance.realizar_transferencia("Conta A", "Conta B", v, "2024-01-01", "u", "x")

    def test_transferencia_valida_nao_levanta(self):
        finance.realizar_transferencia("Conta A", "Conta B", 25.0, "2024-01-01", "u", "ok")
        self.assertEqual(finance.calcular_saldo_real("Conta A"), 75.0)
        self.assertEqual(finance.calcular_saldo_real("Conta B"), 125.0)


# ===========================================================================
# (QA) ROBUSTEZ E EDGE CASES DO CÁLCULO DE PARCELAS
# ===========================================================================
class TestRobustezParcelas(ERPTestBase):
    def test_parcelas_zero_levanta_erro(self):
        with self.assertRaises(ValueError):
            finance.calcular_parcelas("2024-01-10", 25, 5, 100.0, 0, is_cartao=False)

    def test_valor_invalido_levanta_erro(self):
        for v in (0.0, -10.0):
            with self.assertRaises(ValueError):
                finance.calcular_parcelas("2024-01-10", 25, 5, v, 3, is_cartao=False)

    def test_vencimento_dia_31_clampa_em_fevereiro_bissexto(self):
        # Vencimento dia 31 + fevereiro de ano bissexto: deve cair em 29/02 (sem crash).
        parc = finance.calcular_parcelas("2024-01-15", 10, 31, 300.0, 3, is_cartao=True)
        datas = [p[0] for p in parc]
        self.assertEqual(datas, ["2024-02-29", "2024-03-31", "2024-04-30"])

    def test_compra_dia_31_primeira_parcela_nunca_antes_da_compra(self):
        parc = finance.calcular_parcelas("2024-01-31", 5, 10, 300.0, 2, is_cartao=True)
        d_compra = datetime.strptime("2024-01-31", "%Y-%m-%d")
        self.assertGreaterEqual(datetime.strptime(parc[0][0], "%Y-%m-%d"), d_compra)

    def test_centavos_residuais_na_ultima_parcela(self):
        parc = finance.calcular_parcelas("2024-01-10", 0, 0, 100.0, 3, is_cartao=False)
        valores = [p[1] for p in parc]
        self.assertAlmostEqual(sum(valores), 100.0, places=2)
        self.assertEqual(valores[-1], 33.34)


# ===========================================================================
# (QA) TRAVAS DE INTEGRIDADE ADICIONAIS NA DELEÇÃO
# ===========================================================================
class TestTravasDelecaoExtras(ERPTestBase):
    def test_fonte_usada_como_conta_de_cartao_e_bloqueada(self):
        database.criar_fonte("Conta Pagto")
        id_fonte = database.db_query("SELECT id FROM fontes WHERE nome='Conta Pagto'")[0][0]
        database.criar_cartao("Visa", 1000.0, "Conta Pagto", 25, 5)
        self.assertTrue(
            finance.verificar_bloqueio_delecao("fontes", id_fonte),
            "Deletar conta usada como pagamento de cartão deveria ser bloqueado.",
        )

    def test_categoria_com_orcamento_vinculado_e_bloqueada(self):
        database.criar_categoria_principal("Casa", "Despesa")
        id_cat = database.db_query("SELECT id FROM categorias WHERE nome='Casa'")[0][0]
        database.criar_subcategoria("Aluguel", id_cat)
        database.db_execute(
            "INSERT INTO orcamentos (mes_ano, categoria_pai, categoria_filho, valor_previsto, tipo_meta) "
            "VALUES ('2024-01','Casa','Aluguel',500.0,'Despesa')"
        )
        self.assertTrue(
            finance.verificar_bloqueio_delecao("categorias", id_cat),
            "Deletar categoria com meta/orçamento vinculado deveria ser bloqueado.",
        )

    def test_fonte_livre_pode_ser_deletada(self):
        database.criar_fonte("Conta Solta")
        id_fonte = database.db_query("SELECT id FROM fontes WHERE nome='Conta Solta'")[0][0]
        self.assertFalse(finance.verificar_bloqueio_delecao("fontes", id_fonte))


# ===========================================================================
# (QA) LIQUIDAÇÃO DE PENDENTES (status + reflexo no saldo)
# ===========================================================================
class TestLiquidacao(ERPTestBase):
    def setUp(self):
        super().setUp()
        self._add_fonte("Conta L", saldo_inicial=0.0)

    def test_liquidar_despesa_marca_pago_com_data(self):
        self._add_transacao(
            data="2024-01-10", categoria_pai="Mercado", fonte="Conta L",
            valor_eur=40.0, tipo="Despesa", forma_pagamento="Dinheiro/Débito",
            status_liquidacao="PENDENTE",
        )
        tid = database.db_query("SELECT id FROM transacoes WHERE categoria_pai='Mercado'")[0][0]
        finance.liquidar_transacao(tid, "Despesa")
        row = database.db_query(
            "SELECT status_liquidacao, data_liquidacao FROM transacoes WHERE id=?", (tid,)
        )[0]
        self.assertEqual(row[0], "PAGO")
        self.assertEqual(row[1], date.today().strftime("%Y-%m-%d"))

    def test_liquidar_receita_marca_recebido(self):
        self._add_transacao(
            data="2024-01-10", categoria_pai="Bonus", fonte="Conta L",
            valor_eur=80.0, tipo="Receita", forma_pagamento="Dinheiro/Débito",
            status_liquidacao="PREVISTO",
        )
        tid = database.db_query("SELECT id FROM transacoes WHERE categoria_pai='Bonus'")[0][0]
        finance.liquidar_transacao(tid, "Receita")
        self.assertEqual(
            database.db_query("SELECT status_liquidacao FROM transacoes WHERE id=?", (tid,))[0][0],
            "RECEBIDO",
        )

    def test_liquidacao_reflete_no_saldo_real(self):
        self._add_transacao(
            data="2024-01-10", categoria_pai="Conta de Luz", fonte="Conta L",
            valor_eur=100.0, tipo="Despesa", forma_pagamento="Dinheiro/Débito",
            status_liquidacao="PENDENTE",
        )
        # Antes de liquidar, pendente não afeta o saldo real.
        self.assertEqual(finance.calcular_saldo_real("Conta L"), 0.0)
        tid = database.db_query("SELECT id FROM transacoes WHERE categoria_pai='Conta de Luz'")[0][0]
        finance.liquidar_transacao(tid, "Despesa")
        # Depois de liquidar (PAGO), o saldo real reflete a saída.
        self.assertEqual(finance.calcular_saldo_real("Conta L"), -100.0)


# ===========================================================================
# (QA) RELATÓRIO EXCEL DE 3 ABAS (BI GERENCIAL)
# ===========================================================================
class TestRelatorioExcel(ERPTestBase):
    def test_relatorio_possui_exatamente_tres_abas(self):
        xl = pd.ExcelFile(io.BytesIO(reports.gerar_relatorio_excel_bytes()))
        self.assertEqual(xl.sheet_names, ["Transacoes", "Metas", "Resumo_Saldos"])

    def test_relatorio_funciona_com_banco_vazio(self):
        # Mesmo sem fontes/transações, as 3 abas devem existir (com cabeçalho).
        xl = pd.ExcelFile(io.BytesIO(reports.gerar_relatorio_excel_bytes()))
        self.assertEqual(len(xl.sheet_names), 3)

    def test_resumo_saldos_reflete_contas_e_movimentos(self):
        self._add_fonte("Conta R", saldo_inicial=500.0)
        self._add_transacao(
            data="2024-01-05", categoria_pai="Salário", fonte="Conta R",
            valor_eur=200.0, tipo="Receita", forma_pagamento="Dinheiro/Débito",
            status_liquidacao="RECEBIDO",
        )
        xl = pd.ExcelFile(io.BytesIO(reports.gerar_relatorio_excel_bytes()))
        resumo = xl.parse("Resumo_Saldos")
        linha = resumo[resumo["Conta"] == "Conta R"].iloc[0]
        self.assertEqual(linha["Saldo Real (EUR)"], 700.0)


# ===========================================================================
# (UX) LIMPEZA DE ESTADO DOS FORMULÁRIOS APÓS COMMIT
# ===========================================================================
class TestLimpezaEstadoFormularios(unittest.TestCase):
    """Valida o utilitário puro de reset de campos (ui_state.limpar_campos_sessao),
    que zera os seletores reativos fora do st.form após um commit bem-sucedido."""

    def test_remove_por_prefixo_e_por_chave(self):
        from ui_state import limpar_campos_sessao
        ss = {
            "pai_Despesa": "Casa", "sub_Despesa_1": "Aluguel",
            "t_reg_final": "Despesa", "forma_reg": "Cartão de Crédito",
            "logado": True, "user": "ivan",
        }
        removidas = limpar_campos_sessao(
            ss, prefixos=("pai_", "sub_"), chaves=("t_reg_final", "forma_reg")
        )
        for k in ("pai_Despesa", "sub_Despesa_1", "t_reg_final", "forma_reg"):
            self.assertNotIn(k, ss)
        # Estado de sessão alheio (login) deve permanecer intacto.
        self.assertIn("logado", ss)
        self.assertIn("user", ss)
        self.assertEqual(
            set(removidas), {"pai_Despesa", "sub_Despesa_1", "t_reg_final", "forma_reg"}
        )

    def test_sem_correspondencia_nao_altera_estado(self):
        from ui_state import limpar_campos_sessao
        ss = {"a": 1, "b": 2}
        self.assertEqual(limpar_campos_sessao(ss, prefixos=("x_",), chaves=("y",)), [])
        self.assertEqual(ss, {"a": 1, "b": 2})

    def test_reset_de_metas_nao_afeta_chaves_de_lancamentos(self):
        from ui_state import limpar_campos_sessao
        ss = {
            "p_meta_Despesa": "Casa", "f_meta_Despesa_1": "Aluguel",
            "hier_t_meta_final": "Despesa", "pai_Despesa": "X",
        }
        limpar_campos_sessao(ss, prefixos=("p_meta_", "f_meta_"), chaves=("hier_t_meta_final",))
        self.assertNotIn("p_meta_Despesa", ss)
        self.assertNotIn("f_meta_Despesa_1", ss)
        self.assertNotIn("hier_t_meta_final", ss)
        self.assertIn("pai_Despesa", ss)  # pertence a Lançamentos; não pode ser tocado


# ===========================================================================
# (UX) COBERTURA: TODO FORMULÁRIO LIMPA OS CAMPOS APÓS O COMMIT
# ===========================================================================
class TestFormulariosClearOnSubmit(unittest.TestCase):
    VIEWS = ("novos_lancamentos", "gestao", "cartoes", "metas", "transferencias", "assinaturas")

    def _src(self, nome):
        base = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(base, "views", f"{nome}.py"), encoding="utf-8") as f:
            return f.read()

    def test_todo_st_form_tem_clear_on_submit(self):
        import re
        for nome in self.VIEWS:
            src = self._src(nome)
            formas = list(re.finditer(r"st\.form\(", src))
            self.assertTrue(formas, f"Nenhum st.form encontrado em views/{nome}.py")
            for m in formas:
                fim = src.find(")", m.start())
                trecho = src[m.start():fim + 1]
                self.assertIn(
                    "clear_on_submit=True", trecho,
                    f"st.form sem clear_on_submit em views/{nome}.py -> {trecho}",
                )

    def test_lancamentos_reseta_seletores_reativos_apos_commit(self):
        src = self._src("novos_lancamentos")
        self.assertIn("_reset_lancamento", src)
        self.assertIn("limpar_campos_sessao", src)

    def test_metas_reseta_seletores_reativos_apos_commit(self):
        src = self._src("metas")
        self.assertIn("_reset_meta", src)
        self.assertIn("limpar_campos_sessao", src)


# ===========================================================================
# (NOVO) CALENDÁRIO DE ASSINATURAS E CONTAS FIXAS
# ===========================================================================
class TestAssinaturas(ERPTestBase):
    """Cobre o módulo de assinaturas/contas fixas: schema, CRUD anti-duplicado,
    lógica preditiva no comprometido e o lançamento (baixa) em 1-clique."""

    def setUp(self):
        super().setUp()
        self._add_fonte("Conta Principal", saldo_inicial=1000.0)
        database.criar_categoria_principal("Lazer", "Despesa")
        id_lazer = database.db_query(
            "SELECT id FROM categorias WHERE nome='Lazer'"
        )[0][0]
        database.criar_subcategoria("Streaming", id_lazer)

    def _criar(self, nome="Netflix", valor=15.99, dia=10):
        finance.criar_assinatura(
            nome, valor, dia, "Conta Principal", "Lazer", "Streaming"
        )
        return database.db_query(
            "SELECT id FROM assinaturas WHERE nome=?", (nome,)
        )[0][0]

    # --- Schema ---------------------------------------------------------
    def test_tabela_assinaturas_criada_no_init(self):
        rows = database.db_query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='assinaturas'"
        )
        self.assertTrue(rows, "init_db() deveria criar a tabela 'assinaturas'.")

    def test_criar_assinatura_persiste_todos_os_campos(self):
        self._criar("Spotify", 9.99, 5)
        r = database.db_query(
            "SELECT nome, valor_eur, dia_vencimento, conta_padrao, categoria_pai, "
            "categoria_filho, ativa FROM assinaturas WHERE nome='Spotify'"
        )[0]
        self.assertEqual(
            r, ("Spotify", 9.99, 5, "Conta Principal", "Lazer", "Streaming", 1)
        )

    # --- (1) Não-duplicidade sob normalização ---------------------------
    def test_assinatura_duplicada_sob_normalizacao_bloqueada(self):
        self._criar("Netflix")
        for variante in ["netflix", "NETFLIX", "  Netflix ", "Nétflix"]:
            with self.assertRaises(database.DuplicadoError):
                finance.criar_assinatura(
                    variante, 10.0, 1, "Conta Principal", "Lazer", "Streaming"
                )
        self.assertEqual(
            database.db_query("SELECT COUNT(*) FROM assinaturas")[0][0], 1
        )

    def test_validacoes_de_dominio_da_assinatura(self):
        # Valor <= 0 e dia fora de 1..31 devem ser rejeitados.
        with self.assertRaises(ValueError):
            finance.criar_assinatura("X", 0.0, 10, "Conta Principal", "Lazer", "Streaming")
        with self.assertRaises(ValueError):
            finance.criar_assinatura("Y", 5.0, 0, "Conta Principal", "Lazer", "Streaming")
        with self.assertRaises(ValueError):
            finance.criar_assinatura("Z", 5.0, 32, "Conta Principal", "Lazer", "Streaming")

    def test_listar_assinaturas_ordena_por_dia_de_vencimento(self):
        self._criar("Aluguel", 800.0, 20)
        self._criar("Internet", 50.0, 5)
        ordem = [linha[1] for linha in finance.listar_assinaturas(apenas_ativas=True)]
        self.assertEqual(ordem, ["Internet", "Aluguel"])

    # --- (2) Lógica preditiva do calcular_comprometido ------------------
    def test_comprometido_inclui_assinatura_nao_paga(self):
        self._criar("Netflix", 15.99, 10)
        self.assertAlmostEqual(
            finance.calcular_comprometido("Conta Principal"), 15.99, places=2
        )

    def test_comprometido_some_apos_registrar_pagamento(self):
        aid = self._criar("Netflix", 15.99, 10)
        # Antes: previsto entra no comprometido.
        self.assertAlmostEqual(
            finance.calcular_comprometido("Conta Principal"), 15.99, places=2
        )
        finance.registrar_pagamento_assinatura(aid, usuario="tester")
        # Depois: pago no mês => previsão some do comprometido...
        self.assertEqual(finance.calcular_comprometido("Conta Principal"), 0.0)
        # ...e o saldo real reflete imediatamente a saída.
        self.assertEqual(finance.calcular_saldo_real("Conta Principal"), 984.01)
        self.assertTrue(finance.assinatura_tem_pagamento_no_mes(aid))

    def test_assinatura_pausada_nao_entra_na_previsao(self):
        aid = self._criar("Netflix", 15.99, 10)
        self.assertAlmostEqual(
            finance.calcular_comprometido("Conta Principal"), 15.99, places=2
        )
        finance.definir_status_assinatura(aid, ativa=0)
        self.assertEqual(finance.calcular_comprometido("Conta Principal"), 0.0)

    def test_pagamento_de_outra_conta_nao_zera_previsao(self):
        # Assinatura debita em "Conta Principal"; um pagamento em outra conta
        # não pode ser confundido como quitação desta assinatura.
        self._add_fonte("Conta Secundaria", saldo_inicial=500.0)
        self._criar("Netflix", 15.99, 10)
        self._add_transacao(
            data=date.today().strftime("%Y-%m-%d"), categoria_pai="Lazer",
            categoria_filho="Streaming", beneficiario="Netflix",
            fonte="Conta Secundaria", valor_eur=15.99, tipo="Despesa",
            forma_pagamento="Dinheiro/Débito", status_liquidacao="PAGO",
        )
        self.assertAlmostEqual(
            finance.calcular_comprometido("Conta Principal"), 15.99, places=2
        )

    # --- (3) Fluxo de baixa unitária e em lote --------------------------
    def test_baixa_unitaria_cria_despesa_paga_herdando_dados(self):
        aid = self._criar("Netflix", 15.99, 10)
        finance.registrar_pagamento_assinatura(aid, usuario="tester")
        t = database.db_query(
            "SELECT categoria_pai, categoria_filho, beneficiario, fonte, valor_eur, "
            "tipo, status_liquidacao FROM transacoes ORDER BY id DESC LIMIT 1"
        )[0]
        self.assertEqual(
            t,
            ("Lazer", "Streaming", "Netflix", "Conta Principal", 15.99,
             "Despesa", "PAGO"),
        )

    def test_baixa_em_lote_registra_todas_as_pendentes(self):
        ids = [
            self._criar("Netflix", 15.99, 10),
            self._criar("Spotify", 9.99, 5),
            self._criar("Disney", 7.99, 20),
        ]
        total = round(15.99 + 9.99 + 7.99, 2)
        self.assertAlmostEqual(
            finance.calcular_comprometido("Conta Principal"), total, places=2
        )
        n = finance.registrar_pagamentos_assinaturas(ids, usuario="tester")
        self.assertEqual(n, 3)
        for aid in ids:
            self.assertTrue(finance.assinatura_tem_pagamento_no_mes(aid))
        # Todas pagas => previsão zera o comprometido.
        self.assertEqual(finance.calcular_comprometido("Conta Principal"), 0.0)

    def test_pagina_assinaturas_registrada_no_menu(self):
        import pages_config
        chaves = {p["key"] for p in pages_config.get_pages(is_admin=False)}
        self.assertIn("assinaturas", chaves)


# ===========================================================================
# (NOVO) ROLLOVER DE METAS / ORÇAMENTO ACUMULADO (ENVELOPES — YNAB)
# ===========================================================================
class TestRollover(ERPTestBase):
    """Cobre o orçamento acumulado: saldo residual por natureza, propagação
    cumulativa linear, janela de 12 meses, e robustez da barra de progresso."""

    def _meta(self, mes, valor, tipo, pai="Casa", filho="Aluguel"):
        database.db_execute(
            "INSERT OR REPLACE INTO orcamentos (mes_ano, categoria_pai, "
            "categoria_filho, valor_previsto, tipo_meta) VALUES (?,?,?,?,?)",
            (mes, pai, filho, valor, tipo),
        )

    def _trans(self, mes, valor, tipo, pai="Casa", filho="Aluguel"):
        self._add_transacao(
            data=f"{mes}-15", categoria_pai=pai, categoria_filho=filho,
            valor_eur=valor, tipo=tipo, forma_pagamento="Dinheiro/Débito",
            status_liquidacao=("RECEBIDO" if tipo == "Receita" else "PAGO"),
        )

    # --- (1) Despesa com sobra positiva ---------------------------------
    def test_rollover_despesa_sobra_positiva(self):
        self._meta("2024-01", 100.0, "Despesa")
        self._trans("2024-01", 70.0, "Despesa")
        self.assertAlmostEqual(
            finance.calcular_rollover_categoria("Casa", "Aluguel", "Despesa", "2024-02"),
            30.0, places=2,
        )

    # --- (2) Despesa com estouro negativo -------------------------------
    def test_rollover_despesa_estouro_negativo(self):
        self._meta("2024-01", 100.0, "Despesa")
        self._trans("2024-01", 130.0, "Despesa")
        self.assertAlmostEqual(
            finance.calcular_rollover_categoria("Casa", "Aluguel", "Despesa", "2024-02"),
            -30.0, places=2,
        )

    # --- (3) Receita positiva e negativa --------------------------------
    def test_rollover_receita_positivo(self):
        self._meta("2024-01", 1000.0, "Receita", pai="Renda", filho="Salario")
        self._trans("2024-01", 1200.0, "Receita", pai="Renda", filho="Salario")
        self.assertAlmostEqual(
            finance.calcular_rollover_categoria("Renda", "Salario", "Receita", "2024-02"),
            200.0, places=2,
        )

    def test_rollover_receita_negativo(self):
        self._meta("2024-01", 1000.0, "Receita", pai="Renda", filho="Salario")
        self._trans("2024-01", 800.0, "Receita", pai="Renda", filho="Salario")
        self.assertAlmostEqual(
            finance.calcular_rollover_categoria("Renda", "Salario", "Receita", "2024-02"),
            -200.0, places=2,
        )

    # --- Virada de ano no cálculo do mês anterior -----------------------
    def test_mes_anterior_trata_virada_de_ano(self):
        self.assertEqual(finance.mes_anterior("2024-01"), "2023-12")
        self.assertEqual(finance.mes_anterior("2024-02"), "2024-01")
        self.assertEqual(finance.mes_anterior("2024-12"), "2024-11")

    # --- (4) Propagação linear cumulativa em 3 meses --------------------
    def test_propagacao_cumulativa_tres_meses(self):
        # M1: 100 - 80  = +20
        self._meta("2024-01", 100.0, "Despesa"); self._trans("2024-01", 80.0, "Despesa")
        # M2: 100 - 110 = -10  => saldo(M2) = +20 - 10 = +10
        self._meta("2024-02", 100.0, "Despesa"); self._trans("2024-02", 110.0, "Despesa")
        # Rollover herdado por M2 = saldo de M1 = +20
        self.assertAlmostEqual(
            finance.calcular_rollover_categoria("Casa", "Aluguel", "Despesa", "2024-02"),
            20.0, places=2,
        )
        # Rollover herdado por M3 = saldo acumulado de M1+M2 = +10
        self.assertAlmostEqual(
            finance.calcular_rollover_categoria("Casa", "Aluguel", "Despesa", "2024-03"),
            10.0, places=2,
        )

    def test_rollover_sem_dados_retorna_zero(self):
        self.assertEqual(
            finance.calcular_rollover_categoria("Casa", "Aluguel", "Despesa", "2024-05"),
            0.0,
        )

    # --- Janela máxima de 12 meses --------------------------------------
    def test_rollover_limitado_a_12_meses(self):
        # 2023-12 está fora da janela de 12 meses anteriores a 2025-01
        # (janela = 2024-01 .. 2024-12) e NÃO deve ser contabilizado.
        self._meta("2023-12", 100.0, "Despesa")  # residual +100 (fora da janela)
        self._meta("2024-01", 100.0, "Despesa"); self._trans("2024-01", 50.0, "Despesa")  # +50
        self.assertAlmostEqual(
            finance.calcular_rollover_categoria("Casa", "Aluguel", "Despesa", "2025-01"),
            50.0, places=2,
        )

    # --- (5) Robustez: orçamento ajustado e divisão por zero ------------
    def test_orcamento_ajustado_soma_base_e_rollover(self):
        self.assertEqual(finance.calcular_orcamento_ajustado(100.0, 20.0), 120.0)
        self.assertEqual(finance.calcular_orcamento_ajustado(100.0, -150.0), -50.0)

    def test_fracao_progresso_robusta_a_zero_e_negativo(self):
        # Orçamento ajustado <= 0: nunca divide por zero.
        self.assertEqual(finance.fracao_progresso(50.0, 0.0), 1.0)
        self.assertEqual(finance.fracao_progresso(0.0, 0.0), 0.0)
        self.assertEqual(finance.fracao_progresso(50.0, -20.0), 1.0)
        # Caso normal: limita entre 0 e 1.
        self.assertAlmostEqual(finance.fracao_progresso(50.0, 100.0), 0.5, places=2)
        self.assertEqual(finance.fracao_progresso(200.0, 100.0), 1.0)

    def test_estouro_massivo_anterior_gera_ajustado_negativo_seguro(self):
        # M1 estoura forte: 100 - 400 = -300 herdado para M2.
        self._meta("2024-01", 100.0, "Despesa"); self._trans("2024-01", 400.0, "Despesa")
        roll = finance.calcular_rollover_categoria("Casa", "Aluguel", "Despesa", "2024-02")
        self.assertAlmostEqual(roll, -300.0, places=2)
        ajustado = finance.calcular_orcamento_ajustado(100.0, roll)  # -200
        self.assertEqual(ajustado, -200.0)
        # A barra deve sair sem crash mesmo com ajustado negativo.
        self.assertEqual(finance.fracao_progresso(10.0, ajustado), 1.0)

    # --- Configuração global do recurso ---------------------------------
    def test_seed_rollover_ativo_e_alternancia(self):
        self.assertTrue(finance.rollover_esta_ativo())  # seed inicial = '1'
        finance.definir_rollover_ativo(False)
        self.assertFalse(finance.rollover_esta_ativo())
        self.assertEqual(
            database.db_query(
                "SELECT valor FROM configuracoes WHERE chave='rollover_ativo'"
            )[0][0],
            "0",
        )
        finance.definir_rollover_ativo(True)
        self.assertTrue(finance.rollover_esta_ativo())


# ===========================================================================
# (NOVO) REVISÃO E ATRIBUIÇÃO PARA CASAIS (COLABORAÇÃO — MONARCH MONEY)
# ===========================================================================
class TestRevisaoCasais(ERPTestBase):
    """Cobre a migração das colunas de revisão, a atribuição de pendências, a
    listagem filtrada por usuário e a conclusão (recategorização) da revisão."""

    def setUp(self):
        super().setUp()
        auth.criar_usuario("ana", "Senha#1", "Ana", "ana@fam.dev")
        auth.criar_usuario("bruno", "Senha#2", "Bruno", "bruno@fam.dev")
        self._add_fonte("Conta Casal", saldo_inicial=1000.0)
        database.criar_categoria_principal("Casa", "Despesa")
        id_casa = database.db_query("SELECT id FROM categorias WHERE nome='Casa'")[0][0]
        database.criar_subcategoria("Aluguel", id_casa)
        database.criar_subcategoria("Mercado", id_casa)
        database.criar_categoria_principal("Lazer", "Despesa")
        id_lazer = database.db_query("SELECT id FROM categorias WHERE nome='Lazer'")[0][0]
        database.criar_subcategoria("Cinema", id_lazer)

    def _add_pendente(self, atribuido, nota="orig", pai="Casa", filho="Aluguel"):
        self._add_transacao(
            data="2024-02-01", categoria_pai=pai, categoria_filho=filho,
            beneficiario="Loja", fonte="Conta Casal", valor_eur=100.0,
            tipo="Despesa", nota=nota, usuario="ana",
            forma_pagamento="Dinheiro/Débito", status_liquidacao="PAGO",
            status_revisao="PENDENTE", atribuido_a=atribuido,
        )
        return database.db_query(
            "SELECT id FROM transacoes WHERE nota=? AND atribuido_a=?",
            (nota, atribuido),
        )[0][0]

    # --- (1) Migração das colunas de revisão ----------------------------
    def test_colunas_revisao_criadas_na_migracao(self):
        cols = [c[1] for c in database.db_query("PRAGMA table_info(transacoes)")]
        self.assertIn("status_revisao", cols)
        self.assertIn("atribuido_a", cols)

    def test_status_revisao_default_revisado(self):
        # Lançamento normal (sem informar a coluna) nasce como REVISADO.
        self._add_transacao(
            data="2024-01-01", categoria_pai="Casa", categoria_filho="Aluguel",
            fonte="Conta Casal", valor_eur=10.0, tipo="Despesa",
        )
        v = database.db_query("SELECT status_revisao FROM transacoes")[0][0]
        self.assertEqual(v, "REVISADO")

    # --- (2) Lançamento pendente com atribuição correta -----------------
    def test_lancamento_pendente_atribuido_aparece_na_fila(self):
        self._add_pendente("ana", nota="conta de luz")
        pend = finance.listar_transacoes_pendentes_revisao("ana")
        self.assertEqual(len(pend), 1)
        self.assertEqual(pend[0]["nota"], "conta de luz")
        self.assertEqual(finance.contar_pendencias_revisao("ana"), 1)

    # --- (3) Listagem filtrada por usuário (A não vê pendências de B) ----
    def test_filtragem_isola_pendencias_por_usuario(self):
        self._add_pendente("ana", nota="da ana")
        self._add_pendente("bruno", nota="do bruno")
        pend_ana = finance.listar_transacoes_pendentes_revisao("ana")
        pend_bruno = finance.listar_transacoes_pendentes_revisao("bruno")
        self.assertEqual(len(pend_ana), 1)
        self.assertEqual(len(pend_bruno), 1)
        self.assertEqual(pend_ana[0]["nota"], "da ana")
        self.assertEqual(pend_bruno[0]["nota"], "do bruno")
        self.assertEqual(finance.contar_pendencias_revisao("ana"), 1)

    # --- (4) Conclusão de revisão: recategoriza, marca REVISADO, some ----
    def test_concluir_revisao_atualiza_e_remove_da_fila(self):
        tid = self._add_pendente("ana", nota="original")
        finance.concluir_revisao_transacao(
            tid, "Lazer", "Cinema", "nota revisada", usuario_revisor="ana"
        )
        row = database.db_query(
            "SELECT categoria_pai, categoria_filho, nota, status_revisao "
            "FROM transacoes WHERE id=?",
            (tid,),
        )[0]
        self.assertEqual(row, ("Lazer", "Cinema", "nota revisada", "REVISADO"))
        # Saiu da fila de pendências da Ana.
        self.assertEqual(finance.listar_transacoes_pendentes_revisao("ana"), [])
        self.assertEqual(finance.contar_pendencias_revisao("ana"), 0)

    def test_concluir_revisao_rejeita_subcategoria_de_outro_pai(self):
        # "Cinema" é filho de "Lazer"; não pode ser aceito sob "Casa".
        tid = self._add_pendente("ana", nota="hierarquia")
        with self.assertRaises(ValueError):
            finance.concluir_revisao_transacao(
                tid, "Casa", "Cinema", "x", usuario_revisor="ana"
            )
        # Continua pendente (nada foi alterado).
        self.assertEqual(finance.contar_pendencias_revisao("ana"), 1)

    def test_pagina_revisao_registrada_no_menu_para_todos(self):
        import pages_config
        chaves_comum = {p["key"] for p in pages_config.get_pages(is_admin=False)}
        chaves_admin = {p["key"] for p in pages_config.get_pages(is_admin=True)}
        self.assertIn("revisao", chaves_comum)
        self.assertIn("revisao", chaves_admin)


# ===========================================================================
# (NOVO) MÓDULO DE IMPORTAÇÃO DE EXTRATOS
# ===========================================================================
class TestImportacaoExtratos(ERPTestBase):
    """Cobre staging, auto-classificação, análise retroativa, preservação de
    histórico e trilha de auditoria do importador."""

    def setUp(self):
        super().setUp()
        self._add_fonte("Conta Import", 1000.0)
        database.criar_categoria_principal("Alimentação", "Despesa")
        id_pai = database.db_query(
            "SELECT id FROM categorias WHERE nome='Alimentação'"
        )[0][0]
        database.criar_subcategoria("Supermercado", id_pai)
        database.criar_beneficiario("Lidl")

    def _linha(self, desc="COMPRA LIDL 123", data="2024-06-15", valor=42.50):
        return {
            "raw_descricao": desc,
            "data": data,
            "valor_eur": valor,
            "natureza": "Despesa",
        }

    def test_upload_sem_conta_levanta_excecao(self):
        with self.assertRaises(finance.ContaDestinoObrigatoriaError):
            finance.inserir_upload_no_staging(
                [self._linha()], "", usuario="tester",
            )

    def test_segunda_importacao_herda_classificacao_da_primeira(self):
        finance.inserir_upload_no_staging(
            [self._linha()], "Conta Import", usuario="tester",
        )
        staging = finance.listar_staging("Conta Import")
        self.assertEqual(len(staging), 1)
        sid = staging[0][0]
        finance.atualizar_linha_staging(
            sid, "COMPRA LIDL 123", "2024-06-15", 42.50,
            "Despesa", "Alimentação", "Supermercado", "Lidl", "",
        )
        finance.contabilizar_staging([sid], "tester", fonte_destino="Conta Import")

        finance.inserir_upload_no_staging(
            [self._linha(desc="COMPRA LIDL 123", data="2024-07-01", valor=30.0)],
            "Conta Import", usuario="tester",
        )
        staging2 = finance.listar_staging("Conta Import")
        self.assertEqual(staging2[0][4], "Despesa")
        self.assertEqual(staging2[0][5], "Alimentação")
        self.assertEqual(staging2[0][6], "Supermercado")

    def test_contabilizacao_preserva_lancamentos_manuais_na_mesma_data(self):
        self._add_transacao(
            data="2024-06-15", categoria_pai="Alimentação",
            categoria_filho="Supermercado", beneficiario="Manual",
            fonte="Conta Import", valor_eur=99.0, tipo="Despesa",
            nota="Lançamento manual pré-existente", usuario="tester",
            status_liquidacao="PAGO",
        )
        antes = database.db_query("SELECT COUNT(*) FROM transacoes")[0][0]

        finance.inserir_upload_no_staging(
            [self._linha()], "Conta Import", usuario="tester",
        )
        sid = finance.listar_staging("Conta Import")[0][0]
        finance.atualizar_linha_staging(
            sid, "COMPRA LIDL 123", "2024-06-15", 42.50,
            "Despesa", "Alimentação", "Supermercado", "", "",
        )
        finance.contabilizar_staging([sid], "tester", fonte_destino="Conta Import")

        depois = database.db_query("SELECT COUNT(*) FROM transacoes")[0][0]
        self.assertEqual(depois, antes + 1)
        manual = database.db_query(
            "SELECT nota FROM transacoes WHERE beneficiario='Manual'"
        )
        self.assertTrue(manual)
        self.assertEqual(manual[0][0], "Lançamento manual pré-existente")

    def test_analisar_preenche_categorias_e_limpa_beneficiario(self):
        self._add_transacao(
            data="2024-05-01", categoria_pai="Alimentação",
            categoria_filho="Supermercado", beneficiario="Lidl",
            fonte="Conta Import", valor_eur=50.0, tipo="Despesa",
            nota="PADRAO MERCADO XYZ", usuario="tester",
            status_liquidacao="PAGO",
        )
        finance.inserir_upload_no_staging(
            [{"raw_descricao": "PADRAO MERCADO XYZ", "data": "2024-06-20",
              "valor_eur": 25.0, "natureza": "Despesa"}],
            "Conta Import", usuario="tester",
        )
        sid = finance.listar_staging("Conta Import")[0][0]
        database.db_execute(
            "UPDATE importacoes_staging SET beneficiario='Temp' WHERE id=?",
            (sid,),
        )
        n = finance.analisar_staging("Conta Import", usuario="tester")
        self.assertEqual(n, 1)
        row = finance.listar_staging("Conta Import")[0]
        self.assertEqual(row[4], "Despesa")
        self.assertEqual(row[5], "Alimentação")
        self.assertEqual(row[6], "Supermercado")
        self.assertEqual(row[7], "")

    def test_auditoria_registra_upload_e_contabilizacao(self):
        finance.inserir_upload_no_staging(
            [self._linha()], "Conta Import", usuario="tester",
        )
        self.assertGreater(finance.contar_auditoria("UPLOAD_EXTRATO"), 0)
        sid = finance.listar_staging("Conta Import")[0][0]
        finance.atualizar_linha_staging(
            sid, "COMPRA LIDL 123", "2024-06-15", 42.50,
            "Despesa", "Alimentação", "Supermercado", "", "",
        )
        finance.contabilizar_staging([sid], "tester", fonte_destino="Conta Import")
        self.assertGreater(finance.contar_auditoria("CONTABILIZACAO_LOTE"), 0)
        logs = database.db_query(
            "SELECT acao, usuario FROM auditoria_sistema ORDER BY id"
        )
        acoes = [l[0] for l in logs]
        self.assertIn("UPLOAD_EXTRATO", acoes)
        self.assertIn("CONTABILIZACAO_LOTE", acoes)
        self.assertTrue(all(l[1] == "tester" for l in logs))

    def test_pagina_importador_registrada_no_menu(self):
        import pages_config
        chaves = {p["key"] for p in pages_config.get_pages(is_admin=False)}
        self.assertIn("importador", chaves)


# ---------------------------------------------------------------------------
# Infra do smoke test de import do app.py (mock leve de Streamlit)
# ---------------------------------------------------------------------------
class _StopExecution(Exception):
    pass


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value


class _Element:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        return getattr(sys.modules["streamlit"], name)


def _import_app_with_mock():
    st = types.ModuleType("streamlit")
    st.session_state = _SessionState()
    st.secrets = {
        "initial_setup": {
            "admin_user": ADMIN_USER,
            "admin_password": ADMIN_PASSWORD,
            "admin_email": ADMIN_EMAIL,
        },
        "smtp": {"user": "n@local", "password": "x", "server": "localhost", "port": 25},
    }
    st.stop = lambda *a, **k: (_ for _ in ()).throw(_StopExecution())
    st.columns = lambda spec, *a, **k: [
        _Element() for _ in range(spec if isinstance(spec, int) else len(spec))
    ]
    st.tabs = lambda items, *a, **k: [_Element() for _ in items]
    st.container = lambda *a, **k: _Element()
    st.expander = lambda *a, **k: _Element()
    st.form = lambda *a, **k: _Element()
    st.sidebar = _Element()
    st.text_input = lambda *a, **k: ""
    st.number_input = lambda *a, **k: k.get("min_value", 0) or 0
    st.date_input = lambda *a, **k: date.today()
    st.selectbox = lambda label=None, options=None, *a, **k: (list(options)[0] if options else None)
    st.radio = lambda label=None, options=None, *a, **k: (list(options)[0] if options else None)
    st.multiselect = lambda *a, **k: []
    st.button = lambda *a, **k: False
    st.form_submit_button = lambda *a, **k: False
    st.__getattr__ = lambda name: (lambda *a, **k: None)
    sys.modules["streamlit"] = st

    # Banco temporário só para o import (init_db + seed_admin rodam no topo do app).
    tmp_dir = tempfile.mkdtemp(prefix="erp_app_import_")
    database.DB_PATH = os.path.join(tmp_dir, "finance_app.db")

    app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
    spec = importlib.util.spec_from_file_location("erp_app_smoke", app_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except _StopExecution:
        pass
    finally:
        database.close_connections()
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return module


if __name__ == "__main__":
    unittest.main(verbosity=2)
