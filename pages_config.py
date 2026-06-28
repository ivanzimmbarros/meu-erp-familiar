# -*- coding: utf-8 -*-
"""
============================================================================
 REGISTRO DE PÁGINAS / ROTAS — ERP FAMILIAR (pages_config.py)
============================================================================
Fonte única de verdade da navegação multi-páginas.

Mantido PURO (sem importar Streamlit) para que as regras de rota e de
permissão de perfil possam ser testadas isoladamente. O `app.py` consome
esta configuração para montar os objetos `st.Page` / `st.navigation`.
"""

# Cada página: arquivo (relativo à raiz), título, ícone, se é só para admin
# e se é a página padrão (URL raiz).
#
# NOTA DE ARQUITETURA: as páginas ficam em `views/` (e NÃO em `pages/`) de
# propósito. O Streamlit faz descoberta AUTOMÁTICA de qualquer `pages/` e a
# exibe na sidebar até que `st.navigation` seja chamado. Como o gate de login
# global faz `st.stop()` ANTES de `st.navigation`, um `pages/` exporia o menu
# (e permitiria navegar direto para páginas) a usuários não autenticados.
# Usar `views/` elimina a descoberta automática e mantém o login intacto.
PAGES = [
    {"key": "novos_lancamentos", "file": "views/novos_lancamentos.py", "title": "Novos Lançamentos", "icon": "➕", "admin_only": False, "default": True},
    {"key": "historico",        "file": "views/historico.py",        "title": "Histórico",          "icon": "📋", "admin_only": False, "default": False},
    {"key": "saldos",           "file": "views/saldos.py",           "title": "Saldos",             "icon": "💰", "admin_only": False, "default": False},
    {"key": "cartoes",          "file": "views/cartoes.py",          "title": "Cartões",            "icon": "💳", "admin_only": False, "default": False},
    {"key": "metas",            "file": "views/metas.py",            "title": "Metas",              "icon": "🎯", "admin_only": False, "default": False},
    {"key": "dashboard",        "file": "views/dashboard.py",        "title": "Dashboards",         "icon": "📊", "admin_only": False, "default": False},
    {"key": "transferencias",   "file": "views/transferencias.py",   "title": "Transferências",     "icon": "🔄", "admin_only": False, "default": False},
    {"key": "gestao",           "file": "views/gestao.py",           "title": "Gestão Geral",       "icon": "⚙️", "admin_only": True,  "default": False},
]


def get_pages(is_admin: bool):
    """Retorna a lista de páginas visíveis para o perfil informado.

    A página de Gestão Geral (admin_only) só aparece para administradores."""
    return [p for p in PAGES if (not p["admin_only"]) or is_admin]
