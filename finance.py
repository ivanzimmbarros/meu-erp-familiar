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

from database import (
    db_query, db_execute, db_execute_many,
    normalizar_texto, _existe_normalizado, DuplicadoError,
    subcategoria_pertence,
)


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
# ROLLOVER DE METAS / ORÇAMENTO ACUMULADO (MODELO DE ENVELOPES — YNAB)
# ---------------------------------------------------------------------------
def mes_anterior(mes_ano):
    """Retorna o mês imediatamente anterior a `mes_ano` (formato 'YYYY-MM'),
    tratando corretamente a virada de ano ('2024-01' -> '2023-12')."""
    d = datetime.strptime(f"{mes_ano}-01", "%Y-%m-%d") - relativedelta(months=1)
    return d.strftime("%Y-%m")


def planejado_mes(categoria_pai, categoria_filho, tipo_meta, mes_ano):
    """Valor previsto (meta/teto) cadastrado em `orcamentos` para o mês."""
    r = db_query(
        "SELECT valor_previsto FROM orcamentos WHERE mes_ano=? AND categoria_pai=? "
        "AND categoria_filho=? AND tipo_meta=?",
        (mes_ano, categoria_pai, categoria_filho, tipo_meta),
    )
    return (r[0][0] if r and r[0][0] is not None else 0.0)


def realizado_mes(categoria_pai, categoria_filho, tipo, mes_ano):
    """Soma das transações realizadas no mês para a categoria/subcategoria.

    Subcategoria 'Geral' agrega toda a categoria principal (espelha a regra
    usada na tela de Metas)."""
    if categoria_filho == "Geral":
        v = db_query(
            "SELECT SUM(valor_eur) FROM transacoes WHERE categoria_pai=? "
            "AND data LIKE ? AND tipo=?",
            (categoria_pai, f"{mes_ano}%", tipo),
        )[0][0]
    else:
        v = db_query(
            "SELECT SUM(valor_eur) FROM transacoes WHERE categoria_pai=? "
            "AND categoria_filho=? AND data LIKE ? AND tipo=?",
            (categoria_pai, categoria_filho, f"{mes_ano}%", tipo),
        )[0][0]
    return v or 0.0


def _residual_mes(categoria_pai, categoria_filho, tipo_meta, mes_ano):
    """Saldo residual de um único mês (sem herança).

    - Despesa: Planejado - Realizado (sobra positiva, estouro negativo).
    - Receita: Realizado - Planejado (excedente positivo, déficit negativo)."""
    planejado = planejado_mes(categoria_pai, categoria_filho, tipo_meta, mes_ano)
    realizado = realizado_mes(categoria_pai, categoria_filho, tipo_meta, mes_ano)
    if tipo_meta == "Receita":
        return realizado - planejado
    return planejado - realizado


def calcular_rollover_categoria(categoria_pai, categoria_filho, tipo_meta,
                                mes_ano, max_meses=12):
    """Saldo de rollover HERDADO para `mes_ano`, acumulado de forma linear e
    cumulativa a partir dos meses anteriores.

    Soma os saldos residuais dos meses anteriores (do mais antigo ao mês
    imediatamente anterior), de modo que o saldo de um mês já carrega o saldo
    herdado do mês que o precede. A varredura é limitada a `max_meses` (padrão
    12) meses anteriores, evitando loops/lentidão. Meses sem meta e sem
    movimentos contribuem com 0."""
    # Constrói a janela [mês_anterior-(max_meses-1) ... mês_anterior], do mais
    # antigo para o mais recente, e acumula os residuais linearmente.
    meses = []
    m = mes_anterior(mes_ano)
    for _ in range(max(1, int(max_meses))):
        meses.append(m)
        m = mes_anterior(m)
    meses.reverse()

    saldo = 0.0
    for mes in meses:
        saldo += _residual_mes(categoria_pai, categoria_filho, tipo_meta, mes)
    return round(saldo, 2)


def calcular_orcamento_ajustado(meta_base, rollover):
    """Orçamento efetivo do mês = meta base + saldo de rollover herdado."""
    return round((meta_base or 0.0) + (rollover or 0.0), 2)


def fracao_progresso(realizado, orcamento_ajustado):
    """Fração [0..1] para a barra de progresso, robusta a orçamento ajustado
    zerado/negativo (estouro massivo herdado): nesse caso devolve 1.0 quando
    há realizado e 0.0 caso contrário, sem dividir por zero."""
    realizado = realizado or 0.0
    if orcamento_ajustado is None or orcamento_ajustado <= 0:
        return 1.0 if realizado > 0 else 0.0
    return min(max(realizado / orcamento_ajustado, 0.0), 1.0)


def rollover_esta_ativo():
    """Lê em `configuracoes` se o rollover está globalmente ativo ('1')."""
    r = db_query("SELECT valor FROM configuracoes WHERE chave='rollover_ativo'")
    return bool(r) and str(r[0][0]) == "1"


def definir_rollover_ativo(ativo):
    """Persiste o estado global do rollover em `configuracoes`."""
    db_execute(
        "INSERT OR REPLACE INTO configuracoes (chave, valor) VALUES ('rollover_ativo', ?)",
        ("1" if ativo else "0",),
    )


# ---------------------------------------------------------------------------
# ASSINATURAS / CONTAS FIXAS RECORRENTES (CRUD SEGURO)
# ---------------------------------------------------------------------------
def _validar_dados_assinatura(nome, valor_eur, dia_vencimento, conta_padrao,
                              categoria_pai, categoria_filho):
    """Valida (e normaliza) os campos de uma assinatura. Levanta ValueError
    com mensagem amigável no primeiro problema encontrado. Retorna a tupla
    saneada (nome, valor, dia, conta, pai, filho)."""
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Informe o nome da assinatura.")
    if valor_eur is None or float(valor_eur) <= 0:
        raise ValueError("O valor da assinatura deve ser maior que zero.")
    try:
        dia = int(dia_vencimento)
    except (TypeError, ValueError):
        raise ValueError("Dia de vencimento inválido.")
    if dia < 1 or dia > 31:
        raise ValueError("O dia de vencimento deve estar entre 1 e 31.")
    if not (conta_padrao or "").strip():
        raise ValueError("Selecione a conta de débito padrão.")
    if not (categoria_pai or "").strip():
        raise ValueError("A Categoria Principal é obrigatória.")
    if not (categoria_filho or "").strip():
        raise ValueError("A Subcategoria é obrigatória.")
    return nome, float(valor_eur), dia, conta_padrao, categoria_pai, categoria_filho


def criar_assinatura(nome, valor_eur, dia_vencimento, conta_padrao,
                     categoria_pai, categoria_filho, ativa=1):
    """Cadastra uma assinatura/conta fixa barrando nomes equivalentes sob
    normalização (anti-duplicado inteligente)."""
    nome, valor, dia, conta, pai, filho = _validar_dados_assinatura(
        nome, valor_eur, dia_vencimento, conta_padrao, categoria_pai, categoria_filho
    )
    if _existe_normalizado("assinaturas", nome):
        raise DuplicadoError(f"Já existe uma assinatura equivalente a “{nome}”.")
    db_execute(
        "INSERT INTO assinaturas (nome, valor_eur, dia_vencimento, conta_padrao, "
        "categoria_pai, categoria_filho, ativa) VALUES (?,?,?,?,?,?,?)",
        (nome, valor, dia, conta, pai, filho, 1 if ativa else 0),
    )


def atualizar_assinatura(assinatura_id, nome, valor_eur, dia_vencimento,
                         conta_padrao, categoria_pai, categoria_filho, ativa=1):
    """Edita uma assinatura existente preservando a trava anti-duplicado
    (ignorando a própria linha) e as validações de domínio."""
    nome, valor, dia, conta, pai, filho = _validar_dados_assinatura(
        nome, valor_eur, dia_vencimento, conta_padrao, categoria_pai, categoria_filho
    )
    if _existe_normalizado("assinaturas", nome, excluir_id=assinatura_id):
        raise DuplicadoError(f"Já existe uma assinatura equivalente a “{nome}”.")
    db_execute(
        "UPDATE assinaturas SET nome=?, valor_eur=?, dia_vencimento=?, conta_padrao=?, "
        "categoria_pai=?, categoria_filho=?, ativa=? WHERE id=?",
        (nome, valor, dia, conta, pai, filho, 1 if ativa else 0, assinatura_id),
    )


def definir_status_assinatura(assinatura_id, ativa):
    """Ativa/inativa uma assinatura (pausar/retomar cobrança prevista)."""
    db_execute(
        "UPDATE assinaturas SET ativa=? WHERE id=?",
        (1 if ativa else 0, assinatura_id),
    )


def excluir_assinatura(assinatura_id):
    """Remove uma assinatura. As transações já lançadas permanecem intactas."""
    db_execute("DELETE FROM assinaturas WHERE id=?", (assinatura_id,))


def listar_assinaturas(apenas_ativas=False, conta=None):
    """Lista assinaturas ordenadas cronologicamente pelo dia de vencimento.

    Retorna linhas (id, nome, valor_eur, dia_vencimento, conta_padrao,
    categoria_pai, categoria_filho, ativa)."""
    sql = (
        "SELECT id, nome, valor_eur, dia_vencimento, conta_padrao, "
        "categoria_pai, categoria_filho, ativa FROM assinaturas"
    )
    cond, params = [], []
    if apenas_ativas:
        cond.append("ativa=1")
    if conta is not None:
        cond.append("conta_padrao=?")
        params.append(conta)
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY dia_vencimento ASC, nome ASC"
    return db_query(sql, tuple(params))


def assinatura_tem_pagamento_no_mes(assinatura_id, ano_mes=None):
    """True se já houver, no mês `ano_mes` (YYYY-MM; default = mês corrente),
    um lançamento de Despesa que corresponda a esta assinatura na conta de
    débito padrão — casando pelo nome (na nota ou no beneficiário) OU pela
    hierarquia de categoria (pai + filho)."""
    rows = db_query(
        "SELECT nome, conta_padrao, categoria_pai, categoria_filho "
        "FROM assinaturas WHERE id=?",
        (assinatura_id,),
    )
    if not rows:
        return False
    nome, conta, cat_pai, cat_filho = rows[0]
    ano_mes = ano_mes or date.today().strftime("%Y-%m")
    alvo = normalizar_texto(nome)

    lancs = db_query(
        "SELECT beneficiario, nota, categoria_pai, categoria_filho "
        "FROM transacoes WHERE fonte=? AND tipo='Despesa' AND substr(data,1,7)=?",
        (conta, ano_mes),
    )
    for benef, nota, cp, cf in lancs:
        if alvo and (alvo == normalizar_texto(benef) or alvo in normalizar_texto(nota)):
            return True
        if cat_pai and cat_filho and cp == cat_pai and cf == cat_filho:
            return True
    return False


def registrar_pagamento_assinatura(assinatura_id, usuario=None, data_str=None):
    """Lançamento em 1-clique: registra uma Despesa PAGA hoje (ou em
    `data_str`) herdando todos os dados da assinatura, refletindo de imediato
    nos saldos. Retorna o `id` da transação criada."""
    rows = db_query(
        "SELECT nome, valor_eur, conta_padrao, categoria_pai, categoria_filho "
        "FROM assinaturas WHERE id=?",
        (assinatura_id,),
    )
    if not rows:
        raise ValueError("Assinatura inexistente.")
    nome, valor, conta, cat_pai, cat_filho = rows[0]
    data_str = data_str or date.today().strftime("%Y-%m-%d")
    db_execute(
        "INSERT INTO transacoes (data, categoria_pai, categoria_filho, beneficiario, "
        "fonte, valor_eur, tipo, nota, usuario, forma_pagamento, status_liquidacao) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (data_str, cat_pai, cat_filho, nome, conta, valor, "Despesa",
         f"Assinatura: {nome}", usuario, "Dinheiro/Débito", "PAGO"),
    )
    return db_query("SELECT last_insert_rowid()")[0][0]


def registrar_pagamentos_assinaturas(ids, usuario=None, data_str=None):
    """Dá baixa em LOTE numa lista de assinaturas pendentes. Retorna a
    quantidade de pagamentos efetivamente registrados."""
    registrados = 0
    for aid in ids:
        registrar_pagamento_assinatura(aid, usuario=usuario, data_str=data_str)
        registrados += 1
    return registrados


def previsao_assinaturas_pendentes(fonte, ano_mes=None):
    """Soma das assinaturas ATIVAS da conta que ainda NÃO têm pagamento
    registrado no mês corrente — a parcela preditiva do comprometido."""
    ano_mes = ano_mes or date.today().strftime("%Y-%m")
    total = 0.0
    ativas = db_query(
        "SELECT id, valor_eur FROM assinaturas WHERE conta_padrao=? AND ativa=1",
        (fonte,),
    )
    for aid, valor in ativas:
        if not assinatura_tem_pagamento_no_mes(aid, ano_mes):
            total += valor or 0.0
    return round(total, 2)


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
    faturas de cartão pendentes que debitam nesta conta + assinaturas ativas
    ainda não pagas neste mês — previsão real de caixa futuro)."""
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

    # Camada preditiva: assinaturas ativas desta conta que ainda não foram
    # pagas no mês corrente entram como saída prevista; somem após a baixa.
    assin = previsao_assinaturas_pendentes(fonte)

    return round(desp_p - rec_p + fat + assin, 2)


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


# ---------------------------------------------------------------------------
# REVISÃO E ATRIBUIÇÃO PARA CASAIS (COLABORAÇÃO — MONARCH MONEY)
# ---------------------------------------------------------------------------
def contar_pendencias_revisao(username):
    """Quantidade de transações pendentes de revisão atribuídas ao usuário."""
    if not username:
        return 0
    return db_query(
        "SELECT COUNT(*) FROM transacoes WHERE status_revisao='PENDENTE' AND atribuido_a=?",
        (username,),
    )[0][0] or 0


def listar_transacoes_pendentes_revisao(username):
    """Transações com `status_revisao='PENDENTE'` atribuídas a `username`.

    Cada item é um dict com os campos necessários para montar o card de
    revisão. Ordenadas da mais recente para a mais antiga."""
    if not username:
        return []
    rows = db_query(
        "SELECT id, data, categoria_pai, categoria_filho, beneficiario, fonte, "
        "valor_eur, tipo, nota, usuario, forma_pagamento FROM transacoes "
        "WHERE status_revisao='PENDENTE' AND atribuido_a=? ORDER BY data DESC, id DESC",
        (username,),
    )
    campos = (
        "id", "data", "categoria_pai", "categoria_filho", "beneficiario",
        "fonte", "valor_eur", "tipo", "nota", "usuario", "forma_pagamento",
    )
    return [dict(zip(campos, r)) for r in rows]


def concluir_revisao_transacao(trans_id, nova_categoria_pai, nova_categoria_filho,
                               nova_nota, usuario_revisor=None):
    """Conclui a revisão de uma transação: valida a hierarquia, grava as novas
    categorias/nota e marca como 'REVISADO' (saindo da fila de pendências).

    Levanta ValueError se a subcategoria não pertencer à categoria principal."""
    if not (nova_categoria_pai or "").strip():
        raise ValueError("Selecione a Categoria Principal.")
    if not (nova_categoria_filho or "").strip():
        raise ValueError("Selecione a Subcategoria.")
    id_pai_res = db_query(
        "SELECT id FROM categorias WHERE nome=? AND pai_id IS NULL",
        (nova_categoria_pai,),
    )
    if not id_pai_res:
        raise ValueError("Categoria Principal inexistente.")
    if not subcategoria_pertence(id_pai_res[0][0], nova_categoria_filho):
        raise ValueError(
            "A Subcategoria não pertence à Categoria Principal escolhida."
        )
    db_execute(
        "UPDATE transacoes SET categoria_pai=?, categoria_filho=?, nota=?, "
        "status_revisao='REVISADO' WHERE id=?",
        (nova_categoria_pai, nova_categoria_filho, nova_nota, trans_id),
    )


def liquidar_transacao(trans_id, tipo, usuario=None):
    """Dá baixa em um pagamento/recebimento (marca como efetivado hoje)."""
    status = "RECEBIDO" if tipo == "Receita" else "PAGO"
    db_execute(
        "UPDATE transacoes SET status_liquidacao=?, data_liquidacao=? WHERE id=?",
        (status, date.today().strftime("%Y-%m-%d"), trans_id),
    )


# ---------------------------------------------------------------------------
# IMPORTAÇÃO DE EXTRATOS (STAGING, CLASSIFICAÇÃO E AUDITORIA)
# ---------------------------------------------------------------------------
class ContaDestinoObrigatoriaError(ValueError):
    """Levantada quando o upload é tentado sem conta de destino selecionada."""


def registrar_auditoria(usuario, acao, detalhes=""):
    """Grava um evento na trilha de auditoria operacional."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db_execute(
        "INSERT INTO auditoria_sistema (timestamp, usuario, acao, detalhes) VALUES (?,?,?,?)",
        (ts, usuario or "sistema", acao, detalhes or ""),
    )


def classificar_por_descricao(raw_descricao):
    """Auto-classificação (Req. 6): busca a transação mais recente com a mesma
    descrição exata em `nota` e devolve (natureza, categoria_pai, categoria_filho).

    Retorna (None, None, None) se não houver correspondência."""
    desc = (raw_descricao or "").strip()
    if not desc:
        return None, None, None
    rows = db_query(
        "SELECT tipo, categoria_pai, categoria_filho FROM transacoes "
        "WHERE nota=? ORDER BY data DESC, id DESC LIMIT 1",
        (desc,),
    )
    if rows:
        return rows[0]
    return None, None, None


def _buscar_classificacao_historico(raw_descricao):
    """Varredura retroativa no histórico: correspondência exata e, em seguida,
    padrão normalizado (substring) na descrição bruta."""
    desc = (raw_descricao or "").strip()
    if not desc:
        return None, None, None
    exata = classificar_por_descricao(desc)
    if exata[0]:
        return exata
    alvo = normalizar_texto(desc)
    if not alvo:
        return None, None, None
    rows = db_query(
        "SELECT tipo, categoria_pai, categoria_filho, nota FROM transacoes "
        "WHERE nota IS NOT NULL AND TRIM(nota) != '' "
        "ORDER BY data DESC, id DESC"
    )
    for tipo, pai, filho, nota in rows:
        nn = normalizar_texto(nota)
        if nn == alvo or alvo in nn or nn in alvo:
            return tipo, pai, filho
    return None, None, None


def listar_staging(fonte_destino=None):
    """Retorna linhas do buffer de importação, opcionalmente filtradas por conta."""
    if fonte_destino:
        return db_query(
            "SELECT id, raw_descricao, data, valor_eur, natureza, categoria_pai, "
            "categoria_filho, beneficiario, nota, fonte_destino "
            "FROM importacoes_staging WHERE fonte_destino=? ORDER BY data, id",
            (fonte_destino,),
        )
    return db_query(
        "SELECT id, raw_descricao, data, valor_eur, natureza, categoria_pai, "
        "categoria_filho, beneficiario, nota, fonte_destino "
        "FROM importacoes_staging ORDER BY data, id"
    )


def inserir_upload_no_staging(linhas, fonte_destino, usuario=None):
    """Insere linhas parseadas no staging aplicando auto-classificação inicial.

    Levanta ContaDestinoObrigatoriaError se a conta não estiver definida."""
    conta = (fonte_destino or "").strip()
    if not conta:
        raise ContaDestinoObrigatoriaError(
            "Selecione a conta de destino antes de importar o arquivo."
        )
    if not linhas:
        raise ValueError("Nenhuma linha para importar.")

    ops = []
    for linha in linhas:
        raw = (linha.get("raw_descricao") or "").strip()
        data = linha.get("data")
        valor = linha.get("valor_eur")
        natureza = linha.get("natureza")
        if not raw or not data or valor is None:
            continue
        tipo_auto, pai_auto, filho_auto = classificar_por_descricao(raw)
        if tipo_auto:
            natureza = natureza or tipo_auto
            pai, filho = pai_auto, filho_auto
        else:
            pai, filho = None, None
        ops.append((
            "INSERT INTO importacoes_staging "
            "(raw_descricao, data, valor_eur, natureza, categoria_pai, "
            "categoria_filho, beneficiario, nota, fonte_destino) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (raw, data, float(valor), natureza, pai, filho, "", "", conta),
        ))
    if not ops:
        raise ValueError("Nenhuma linha válida para inserir no staging.")
    db_execute_many(ops)
    registrar_auditoria(
        usuario, "UPLOAD_EXTRATO",
        f"{len(ops)} linha(s) em '{conta}'",
    )
    return len(ops)


def atualizar_linha_staging(staging_id, raw_descricao, data, valor_eur, natureza,
                            categoria_pai, categoria_filho, beneficiario, nota):
    """Persiste edições manuais de uma linha do buffer."""
    db_execute(
        "UPDATE importacoes_staging SET raw_descricao=?, data=?, valor_eur=?, "
        "natureza=?, categoria_pai=?, categoria_filho=?, beneficiario=?, nota=? "
        "WHERE id=?",
        (raw_descricao, data, valor_eur, natureza, categoria_pai,
         categoria_filho, beneficiario or "", nota or "", staging_id),
    )


def excluir_staging(ids, usuario=None):
    """Remove linhas do buffer por id. Retorna quantidade excluída."""
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    db_execute(
        f"DELETE FROM importacoes_staging WHERE id IN ({placeholders})",
        tuple(ids),
    )
    registrar_auditoria(
        usuario, "EXCLUSAO_STAGING", f"{len(ids)} linha(s) removida(s)",
    )
    return len(ids)


def analisar_staging(fonte_destino=None, usuario=None):
    """Botão Analisar (Req. 7): preenche categorias via histórico e limpa beneficiário."""
    rows = listar_staging(fonte_destino)
    atualizados = 0
    for sid, raw, *_ in rows:
        tipo, pai, filho = _buscar_classificacao_historico(raw)
        if tipo and pai and filho:
            db_execute(
                "UPDATE importacoes_staging SET natureza=?, categoria_pai=?, "
                "categoria_filho=?, beneficiario=? WHERE id=?",
                (tipo, pai, filho, "", sid),
            )
            atualizados += 1
    if usuario:
        registrar_auditoria(
            usuario, "ANALISE_STAGING",
            f"{atualizados} linha(s) classificada(s) automaticamente",
        )
    return atualizados


def contabilizar_staging(ids, usuario, fonte_destino=None):
    """Move linhas selecionadas do staging para `transacoes` (Req. 4 e 5).

    Preserva a descrição bruta em `nota`, insere sem apagar lançamentos
    pré-existentes na mesma data."""
    if not ids:
        raise ValueError("Nenhuma linha selecionada para contabilizar.")

    placeholders = ",".join("?" * len(ids))
    rows = db_query(
        f"SELECT id, raw_descricao, data, valor_eur, natureza, categoria_pai, "
        f"categoria_filho, beneficiario, nota, fonte_destino "
        f"FROM importacoes_staging WHERE id IN ({placeholders})",
        tuple(ids),
    )
    if not rows:
        raise ValueError("Registros de staging não encontrados.")

    ops = []
    contabilizados = 0
    for row in rows:
        sid, raw, data, valor, natureza, pai, filho, benef, nota_extra, fonte = row
        if fonte_destino and fonte != fonte_destino:
            raise ValueError(
                f"Linha {sid} pertence a outra conta de destino."
            )
        if not (natureza or "").strip():
            raise ValueError(
                f"Linha {sid}: selecione a Natureza antes de contabilizar."
            )
        if not (pai or "").strip() or not (filho or "").strip():
            raise ValueError(
                f"Linha {sid}: selecione Categoria e Subcategoria."
            )
        if not (fonte or "").strip():
            raise ValueError(f"Linha {sid}: conta de destino não definida.")
        if valor is None or float(valor) <= 0:
            raise ValueError(f"Linha {sid}: valor inválido.")

        id_pai = db_query(
            "SELECT id FROM categorias WHERE nome=? AND pai_id IS NULL", (pai,),
        )
        if not id_pai or not subcategoria_pertence(id_pai[0][0], filho):
            raise ValueError(
                f"Linha {sid}: hierarquia de categorias inválida."
            )

        status = determinar_status_operacao(natureza)
        nota_final = (raw or "").strip()
        extra = (nota_extra or "").strip()
        if extra and extra != nota_final:
            nota_final = f"{nota_final} | {extra}" if nota_final else extra

        ops.append((
            "INSERT INTO transacoes (data, categoria_pai, categoria_filho, beneficiario, "
            "fonte, valor_eur, tipo, nota, usuario, forma_pagamento, status_liquidacao) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (data, pai, filho, benef or "", fonte, float(valor), natureza,
             nota_final, usuario, "Dinheiro/Débito", status),
        ))
        ops.append(("DELETE FROM importacoes_staging WHERE id=?", (sid,)))
        contabilizados += 1

    db_execute_many(ops)
    registrar_auditoria(
        usuario, "CONTABILIZACAO_LOTE",
        f"{contabilizados} transação(ões) importada(s)",
    )
    return contabilizados


def contar_auditoria(acao=None):
    """Conta registros de auditoria, opcionalmente filtrados por ação."""
    if acao:
        return db_query(
            "SELECT COUNT(*) FROM auditoria_sistema WHERE acao=?", (acao,),
        )[0][0] or 0
    return db_query("SELECT COUNT(*) FROM auditoria_sistema")[0][0] or 0

