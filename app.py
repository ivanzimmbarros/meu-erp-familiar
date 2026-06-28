import streamlit as st
import re
from datetime import date

from database import db_query, init_db
from auth import (
    autenticar, gerar_otp, enviar_email, seed_admin,
    precisa_trocar_senha, definir_nova_senha, iniciar_recuperacao,
)
from pages_config import get_pages

# --- 1. CONFIGURAÇÃO GLOBAL E CSS MOBILE-FIRST ---
st.set_page_config(page_title="ERP Familiar", page_icon="🏠", layout="wide")

st.markdown("""
<style>
    /* 1. FUNDO GERAL E CONTAINER (Journal Paper Style) */
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
        background-color: #D5D5D5 !important;
        color: #2F2F2F !important;
    }

    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 1rem !important;
        padding-left: 3rem !important;
        padding-right: 3rem !important;
    }

    /* 2. SIDEBAR (Overcast Style) */
    [data-testid="stSidebar"] {
        background-color: #9099A2 !important;
        border-right: 1px solid rgba(0,0,0,0.1);
    }

    [data-testid="stSidebar"] .stMarkdown, [data-testid="stSidebar"] p, [data-testid="stSidebar"] span {
        color: #FFFFFF !important;
    }

    /* 4. MÉTRICAS AVANÇADAS */
    [data-testid="stMetric"] {
        background-color: #FFFFFF;
        padding: 15px;
        border-radius: 4px;
        border-left: 4px solid #6D7993;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }

    [data-testid="stMetricLabel"] p {
        color: #9099A2 !important;
        font-size: 0.85rem !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    /* 5. BOTÕES (Dusty Style) */
    .stButton>button {
        background-color: #96858F !important;
        color: #FFFFFF !important;
        border-radius: 4px !important;
        border: none !important;
        font-weight: 600 !important;
        text-transform: uppercase;
        letter-spacing: 1px;
        transition: 0.3s ease;
    }

    .stButton>button:hover {
        background-color: #6D7993 !important;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }

    /* 6. INPUTS, SELECTS E DATA EDITORS */
    div[data-baseweb="input"], div[data-baseweb="select"], .stNumberInput input {
        background-color: #FFFFFF !important;
        color: #2F2F2F !important;
        border: 1px solid #9099A2 !important;
    }

    /* 7. CARDS E LISTAGENS */
    .card, .liquidar-row {
        background-color: #FFFFFF !important;
        border-left: 6px solid #6D7993 !important;
        border-radius: 4px;
        padding: 15px;
        margin-bottom: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }

    /* Scrollbar Journal Style */
    ::-webkit-scrollbar { width: 8px; }
    ::-webkit-scrollbar-track { background: #D5D5D5; }
    ::-webkit-scrollbar-thumb { background: #9099A2; border-radius: 10px; }

    /* 8. PADRONIZAÇÃO ABSOLUTA DE FONTES */
    h1, h2, h3, h4, h5, h6, [data-testid="stHeaderElement"], .stMarkdown h4 {
        font-family: 'Inter', 'Source Sans Pro', 'Helvetica Neue', Helvetica, Arial, sans-serif !important;
        color: #2F2F2F !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em !important;
    }

    h1 { font-size: 1.8rem !important; }
    h2 { font-size: 1.6rem !important; }
    h3 { font-size: 1.4rem !important; }
    h4 { font-size: 1.25rem !important; }

    .stMarkdown h2 {
        color: #2F2F2F !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 700 !important;
    }
</style>
""", unsafe_allow_html=True)

# --- 2. BOOTSTRAP DO BANCO E ESTADO DA SESSÃO ---
init_db()

_setup = st.secrets["initial_setup"]
seed_admin(_setup["admin_user"], _setup["admin_password"], _setup["admin_email"])

if 'ver' not in st.session_state:
    try:
        taxa_db = db_query("SELECT valor FROM configuracoes WHERE chave='taxa_brl_eur'")
        t_init = float(taxa_db[0][0]) if taxa_db else 0.16
    except Exception:
        t_init = 0.16
    st.session_state.update({
        'ver': 0, 'logado': False, 'user': None, 'display_name': None,
        'perfil': None,
        'taxa': t_init
    })

# --- 3. MOTOR DE ACESSO (LOGIN GLOBAL ÚNICO, ANTES DE QUALQUER PÁGINA) ---
if 'auth_step' not in st.session_state:
    st.session_state.auth_step = 'login'

if not st.session_state.logado:
    _, col_auth, _ = st.columns([1, 1.5, 1])
    with col_auth:
        st.markdown("<br><h2 style='text-align: center;'>🔒 Portal de Acesso</h2>", unsafe_allow_html=True)

        # CAMADA 1: LOGIN
        if st.session_state.auth_step == 'login':
            u_in = st.text_input("Usuário", key="u_login")
            p_in = st.text_input("Senha", type="password", key="p_login")
            if st.button("ENTRAR", width="stretch", type="primary"):
                user = autenticar(u_in, p_in)
                if user:
                    otp = gerar_otp()
                    try:
                        enviar_email("🔑 Código 2FA", f"Seu código é: {otp}", user['email'], st.secrets["smtp"])
                        st.session_state.update({'temp_user': u_in, 'temp_perfil': user['perfil'], 'temp_display': user['nome'], 'correct_otp': otp, 'auth_step': '2fa'})
                        st.rerun()
                    except Exception as e:
                        st.error(f"⚠️ Erro SMTP: {e}")
                else:
                    st.error("Acesso negado.")
            if st.button("Esqueci a Senha"):
                st.session_state.auth_step = 'recovery'; st.rerun()

        # CAMADA 2: VERIFICAÇÃO 2FA + CHEQUE DE RESET
        elif st.session_state.auth_step == '2fa':
            otp_in = st.text_input("Código de 6 dígitos enviado por e-mail", max_chars=6)
            if st.button("VERIFICAR CÓDIGO", width="stretch", type="primary"):
                if otp_in == st.session_state.correct_otp:
                    if precisa_trocar_senha(st.session_state.temp_user):
                        st.session_state.auth_step = 'force_password_change'; st.rerun()
                    else:
                        st.session_state.update({'logado': True, 'user': st.session_state.temp_user, 'perfil': st.session_state.temp_perfil, 'display_name': st.session_state.temp_display})
                        st.rerun()
                else:
                    st.error("Código inválido.")

        # CAMADA 3: RECUPERAÇÃO DE SENHA (MARCA O FLAG force_reset)
        elif st.session_state.auth_step == 'recovery':
            st.markdown("#### 🔑 Recuperação")
            email_rec = st.text_input("E-mail cadastrado")
            if st.button("GERAR SENHA TEMPORÁRIA", width="stretch"):
                temp_pwd = iniciar_recuperacao(email_rec)
                if temp_pwd:
                    try:
                        enviar_email("🔐 Nova Senha", f"Senha temporária: {temp_pwd}\nTroca obrigatória no acesso.", email_rec, st.secrets["smtp"])
                        st.success("✅ Verifique seu e-mail!"); st.session_state.auth_step = 'login'; st.rerun()
                    except Exception as e:
                        st.error(f"⚠️ Erro SMTP: {e}")
                else:
                    st.error("E-mail não encontrado.")
            if st.button("Voltar"):
                st.session_state.auth_step = 'login'; st.rerun()

        # CAMADA 4: TROCA OBRIGATÓRIA (INTERCEPTADOR)
        elif st.session_state.auth_step == 'force_password_change':
            st.warning("⚠️ **Ação Obrigatória:** Defina uma nova senha forte (8+ chars, Maiúscula, Número e Especial).")
            with st.form("f_force_pwd"):
                n_pwd = st.text_input("Nova Senha", type="password")
                c_pwd = st.text_input("Confirme a Senha", type="password")
                if st.form_submit_button("✅ ATUALIZAR E ACESSAR", width="stretch"):
                    pattern = r"^(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$"
                    if n_pwd != c_pwd:
                        st.error("Senhas não coincidem.")
                    elif not re.match(pattern, n_pwd):
                        st.error("A senha não atende aos requisitos.")
                    else:
                        definir_nova_senha(st.session_state.temp_user, n_pwd)
                        st.session_state.update({'logado': True, 'user': st.session_state.temp_user, 'perfil': st.session_state.temp_perfil, 'display_name': st.session_state.temp_display})
                        st.rerun()

    st.stop()  # TRAVA FINAL: nenhuma página é montada antes da autenticação.

# --- 4. SIDEBAR (ELEMENTOS COMUNS A TODAS AS PÁGINAS) ---
with st.sidebar:
    st.markdown(f"### 👋 {st.session_state.display_name}")
    st.caption(date.today().strftime('%d/%m/%Y'))
    hoje_iso = date.today().strftime("%Y-%m-%d")
    pend = db_query("SELECT id FROM transacoes WHERE status_liquidacao='PENDENTE' AND data <= ?", (hoje_iso,))
    if pend:
        st.warning(f"⚠️ {len(pend)} conta(s) vencida(s)!")
    rev_pend = db_query(
        "SELECT COUNT(*) FROM transacoes WHERE status_revisao='PENDENTE' AND atribuido_a=?",
        (st.session_state.user,),
    )[0][0] or 0
    if rev_pend:
        st.info(f"⚠️ Você tem {rev_pend} despesa(s) pendente(s) de revisão!")
    st.caption(f"💱 Câmbio BRL/EUR: **{st.session_state.taxa:.4f}**")
    if st.button("🚪 Sair", width="stretch"):
        st.session_state.clear(); st.rerun()
    st.divider()

# --- 5. NAVEGAÇÃO MULTI-PÁGINAS (RESPEITANDO PERMISSÃO DE PERFIL) ---
is_admin = (st.session_state.perfil == "Administrador")
page_defs = get_pages(is_admin)
paginas = [
    st.Page(p["file"], title=p["title"], icon=p["icon"], default=p.get("default", False))
    for p in page_defs
]
st.navigation(paginas, position="sidebar").run()
