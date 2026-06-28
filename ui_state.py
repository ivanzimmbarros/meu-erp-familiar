# -*- coding: utf-8 -*-
"""
============================================================================
 LIMPEZA DE ESTADO DE FORMULÁRIOS (PÓS-COMMIT) — ERP FAMILIAR (ui_state.py)
============================================================================
Utilitário PURO (sem Streamlit) para resetar campos de formulário após um
commit bem-sucedido. Opera sobre qualquer objeto dict-like (inclusive o
`st.session_state`), o que o torna diretamente testável.

Uso típico (no topo da view, ANTES de instanciar os widgets):

    if st.session_state.pop("_reset_lancamento", False):
        limpar_campos_sessao(st.session_state, prefixos=("pai_", "sub_"),
                             chaves=("t_reg_final", "forma_reg"))

Como as chaves são removidas antes da recriação dos widgets, o Streamlit os
reconstrói com seus valores padrão (selects no 1º item, textos vazios, etc.).
"""


def limpar_campos_sessao(session_state, prefixos=(), chaves=()):
    """Remove de `session_state` as chaves cujo nome esteja em `chaves` OU que
    comecem com algum dos `prefixos`. Não toca em nenhuma outra chave (ex.:
    estado de login/sessão permanece intacto).

    Retorna a lista das chaves efetivamente removidas (útil para asserts)."""
    prefixos = tuple(prefixos)
    chaves = set(chaves)
    alvo = [
        k for k in list(session_state.keys())
        if k in chaves or any(str(k).startswith(p) for p in prefixos)
    ]
    for k in alvo:
        del session_state[k]
    return alvo
