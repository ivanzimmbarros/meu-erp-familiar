# -*- coding: utf-8 -*-
"""
============================================================================
 CAMADA FINANCEIRA — ERP FAMILIAR (finance.py)
============================================================================
Centraliza as regras de negócio e os cálculos matemáticos do sistema:
parcelamento, fatura de cartão, saldos (real/comprometido/disponível),
transferências e travas de exclusão.

Não importa Streamlit. Depende apenas de `database`.
"""
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

from database import db_query, db_execute, db_execute_many


# ---------------------------------------------------------------------------
# STATUS / PARCELAMENTO
# ---------------------------------------------------------------------------
def determinar_status_operacao(tipo, eh_primeira_parcela=True):
    if not eh_primeira_parcela:
        return "PENDENTE"
    return "RECEBIDO" if tipo == "Receita" else "PAGO"


def calcular_parcelas(data_str, dia_fech, dia_venc, valor_total, total_parc, is_cartao=False):
    """Gera a lista de parcelas: [(data_venc, valor, numero), ...].

    Regra de cartão (corrigida):
      - Compra APÓS o dia de fechamento empurra a 1ª fatura para o mês seguinte.
      - A 1ª parcela NUNCA pode vencer antes da data da compra. Se o vencimento
        calculado cair antes da compra (ex.: dia de vencimento < dia da compra
        no mesmo mês), o primeiro vencimento é empurrado +1 mês, e todas as
        parcelas seguintes seguem esse offset de forma linear.

    O arredondamento joga os centavos residuais na ÚLTIMA parcela.
    """
    if total_parc is None or int(total_parc) < 1:
        raise ValueError("O número de parcelas deve ser no mínimo 1.")
    if valor_total is None or float(valor_total) <= 0:
        raise ValueError("O valor total deve ser maior que zero.")
    total_parc = int(total_parc)

    parcelas = []
    d = datetime.strptime(data_str, "%Y-%m-%d")
    v_parc = round(valor_total / total_parc, 2)
    v_ult = round(valor_total - (v_parc * (total_parc - 1)), 2)

    if is_cartao:
        # Offset base: compra depois do fechamento já cai na fatura seguinte.
        offset = 1 if d.day > dia_fech else 0
        # Trava de integridade: 1ª parcela não pode vencer antes da compra.
        primeiro_venc = d + relativedelta(months=offset, day=dia_venc)
        if primeiro_venc < d:
            offset += 1
    else:
        offset = 0

    for i in range(total_parc):
        num = i + 1
        if is_cartao:
            data_v = d + relativedelta(months=offset + i, day=dia_venc)
        else:
            data_v = d + relativedelta(months=offset + i, day=d.day)
        val = v_ult if num == total_parc else v_parc
        parcelas.append((data_v.strftime("%Y-%m-%d"), val, num))
    return parcelas


def calcular_fatura_ref(data_str, dia_fech):
    d = datetime.strptime(data_str, "%Y-%m-%d")
    if d.day > dia_fech:
        d += relativedelta(months=1)
    return d.strftime("%Y-%m")


# ---------------------------------------------------------------------------
# SALDOS
# ---------------------------------------------------------------------------
def calcular_saldo_real(fonte):
    """Dinheiro que REALMENTE existe na conta agora (saldo inicial + entradas
    recebidas - saídas pagas, ignorando movimentos de cartão de crédito)."""
    res_ini = db_query("SELECT valor_inicial FROM saldos_iniciais WHERE fonte=?", (fonte,))
    ini = res_ini[0][0] if res_ini else 0.0
    rec = db_query(
        "SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo='Receita' "
        "AND status_liquidacao='RECEBIDO' AND forma_pagamento != 'Cartão de Crédito'",
        (fonte,),
    )[0][0] or 0.0
    des = db_query(
        "SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo='Despesa' "
        "AND status_liquidacao='PAGO' AND forma_pagamento != 'Cartão de Crédito'",
        (fonte,),
    )[0][0] or 0.0
    return round(ini + rec - des, 2)


def calcular_comprometido(fonte):
    """Tudo que vai sair da conta no futuro (boletos pendentes/previstos +
    faturas de cartão pendentes que debitam nesta conta)."""
    sql_pend = (
        "SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo=? "
        "AND status_liquidacao IN ('PENDENTE','PREVISTO') AND forma_pagamento != 'Cartão de Crédito'"
    )
    desp_p = db_query(sql_pend, (fonte, "Despesa"))[0][0] or 0.0
    rec_p = db_query(sql_pend, (fonte, "Receita"))[0][0] or 0.0

    fat = db_query(
        """
        SELECT SUM(t.valor_eur)
        FROM transacoes t
        JOIN cartoes c ON t.cartao_id = c.id
        WHERE c.conta_pagamento=? AND t.status_cartao='pendente'
        """,
        (fonte,),
    )[0][0] or 0.0

    return round(desp_p - rec_p + fat, 2)


def calcular_disponivel(fonte):
    """Saldo disponível = saldo real - comprometido."""
    return round(calcular_saldo_real(fonte) - calcular_comprometido(fonte), 2)


# ---------------------------------------------------------------------------
# TRANSFERÊNCIAS
# ---------------------------------------------------------------------------
def realizar_transferencia(origem, destino, valor, data_str, usuario, nota):
    """Movimentação de soma zero: debita a origem (Despesa/PAGO) e credita o
    destino (Receita/RECEBIDO) de forma atômica.

    Valida que origem e destino são distintos e que o valor é positivo, para
    evitar transferências degeneradas (mesma conta) ou de valor nulo/negativo.
    """
    if not origem or not destino:
        raise ValueError("Origem e destino são obrigatórios.")
    if origem == destino:
        raise ValueError("A conta de origem deve ser diferente da conta de destino.")
    if valor is None or float(valor) <= 0:
        raise ValueError("O valor da transferência deve ser maior que zero.")
    nota_f = f"Transferência: {origem} ➔ {destino} | {nota}"
    ops = [
        (
            "INSERT INTO transacoes (data, categoria_pai, beneficiario, fonte, valor_eur, tipo, nota, usuario, status_liquidacao) VALUES (?,?,?,?,?,?,?,?,?)",
            (data_str, "Transferência", f"Para {destino}", origem, valor, "Despesa", nota_f, usuario, "PAGO"),
        ),
        (
            "INSERT INTO transacoes (data, categoria_pai, beneficiario, fonte, valor_eur, tipo, nota, usuario, status_liquidacao) VALUES (?,?,?,?,?,?,?,?,?)",
            (data_str, "Transferência", f"De {origem}", destino, valor, "Receita", nota_f, usuario, "RECEBIDO"),
        ),
    ]
    db_execute_many(ops)


# ---------------------------------------------------------------------------
# TRAVAS DE EXCLUSÃO / LIQUIDAÇÃO
# ---------------------------------------------------------------------------
def verificar_bloqueio_delecao(tabela, id_item):
    if tabela == "categorias":
        res = db_query("SELECT nome FROM categorias WHERE id=?", (id_item,))
        if not res:
            return False
        n = res[0][0]
        # Bloqueia se houver: subcategorias filhas, transações usando o nome
        # (como pai ou filho) OU metas/orçamentos vinculados ao nome.
        return len(db_query("SELECT id FROM categorias WHERE pai_id=?", (id_item,))) > 0 or \
            len(db_query("SELECT id FROM transacoes WHERE categoria_pai=? OR categoria_filho=?", (n, n))) > 0 or \
            len(db_query("SELECT id FROM orcamentos WHERE categoria_pai=? OR categoria_filho=?", (n, n))) > 0
    if tabela == "fontes":
        res = db_query("SELECT nome FROM fontes WHERE id=?", (id_item,))
        if not res:
            return False
        n = res[0][0]
        # Bloqueia se houver: transações na conta, saldo inicial registrado OU
        # algum cartão que usa esta conta como conta de pagamento.
        return len(db_query("SELECT id FROM transacoes WHERE fonte=?", (n,))) > 0 or \
            len(db_query("SELECT fonte FROM saldos_iniciais WHERE fonte=?", (n,))) > 0 or \
            len(db_query("SELECT id FROM cartoes WHERE conta_pagamento=?", (n,))) > 0
    if tabela == "beneficiarios":
        res = db_query("SELECT nome FROM beneficiarios WHERE id=?", (id_item,))
        if not res:
            return False
        return len(db_query("SELECT id FROM transacoes WHERE beneficiario=?", (res[0][0],))) > 0
    return False


def liquidar_transacao(trans_id, tipo, usuario=None):
    """Dá baixa em um pagamento/recebimento (marca como efetivado hoje)."""
    status = "RECEBIDO" if tipo == "Receita" else "PAGO"
    db_execute(
        "UPDATE transacoes SET status_liquidacao=?, data_liquidacao=? WHERE id=?",
        (status, date.today().strftime("%Y-%m-%d"), trans_id),
    )
