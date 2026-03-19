import streamlit as st
import sqlite3
import pandas as pd
import hashlib
from datetime import datetime

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
    .saldo-card .detalhe { font-size: 0.8rem; color: #94a3b8; margin-top: 4px; }
    .saldo-card-positivo { border-left-color: #16a34a; }
    .saldo-card-negativo { border-left-color: #dc2626; }

    .secao-titulo { font-size: 1.1rem; font-weight: 700; color: #1e293b; padding: 8px 0 4px 0; }
    .secao-sub { font-size: 0.85rem; color: #64748b; margin-bottom: 16px; }

    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
#  ESTADO DA SESSÃO
# ─────────────────────────────────────────────
def init_session():
    defaults = {'ver': 0, 'logado': False, 'display_name': None}
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()


# ─────────────────────────────────────────────
#  HELPERS DE BANCO — conexão local por operação
# ─────────────────────────────────────────────
DB_PATH = 'finance.db'

def db_query(sql, params=()):
    """Executa SELECT e retorna fetchall."""
    with sqlite3.connect(DB_PATH) as c:
        return c.execute(sql, params).fetchall()

def db_execute(sql, params=()):
    """Executa INSERT/UPDATE/DELETE com commit automático."""
    with sqlite3.connect(DB_PATH) as c:
        c.execute(sql, params)

def db_execute_many(sqls_params):
    """Executa múltiplas operações numa única conexão."""
    with sqlite3.connect(DB_PATH) as c:
        for sql, params in sqls_params:
            c.execute(sql, params)

def db_df(sql, params=()):
    """Executa SELECT e retorna DataFrame."""
    with sqlite3.connect(DB_PATH) as c:
        return pd.read_sql_query(sql, c, params=params)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


# ─────────────────────────────────────────────
#  INICIALIZAÇÃO DO BANCO
# ─────────────────────────────────────────────
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS usuarios
                     (id INTEGER PRIMARY KEY, username TEXT UNIQUE,
                      password TEXT, nome_exibicao TEXT)''')
        c.execute('CREATE TABLE IF NOT EXISTS fontes (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')
        c.execute('CREATE TABLE IF NOT EXISTS saldos_iniciais (fonte TEXT PRIMARY KEY, valor_inicial REAL DEFAULT 0.0)')
        c.execute('CREATE TABLE IF NOT EXISTS beneficiarios (id INTEGER PRIMARY KEY, nome TEXT UNIQUE)')

        # Migração hierárquica segura
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='categorias'")
        if c.fetchone():
            c.execute("PRAGMA table_info(categorias)")
            cols = [col[1] for col in c.fetchall()]
            if 'pai_id' not in cols:
                c.execute("ALTER TABLE categorias RENAME TO categorias_old")
                c.execute('''CREATE TABLE categorias
                             (id INTEGER PRIMARY KEY, nome TEXT UNIQUE, pai_id INTEGER,
                              FOREIGN KEY(pai_id) REFERENCES categorias(id))''')
                c.execute("INSERT INTO categorias (nome, pai_id) SELECT nome, NULL FROM categorias_old")
                c.execute("DROP TABLE categorias_old")
        else:
            c.execute('''CREATE TABLE IF NOT EXISTS categorias
                         (id INTEGER PRIMARY KEY, nome TEXT UNIQUE, pai_id INTEGER,
                          FOREIGN KEY(pai_id) REFERENCES categorias(id))''')

        c.execute('''CREATE TABLE IF NOT EXISTS transacoes
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      data TEXT, categoria_pai TEXT, categoria_filho TEXT,
                      beneficiario TEXT, fonte TEXT,
                      valor_eur REAL, tipo TEXT, nota TEXT, usuario TEXT)''')

        c.execute("INSERT OR IGNORE INTO usuarios (username, password, nome_exibicao) VALUES (?,?,?)",
                  ("admin", hash_password("123456"), "Administrador"))

init_db()


# ─────────────────────────────────────────────
#  LOGIN
# ─────────────────────────────────────────────
if not st.session_state.logado:
    col_left, col_center, col_right = st.columns([1, 1.4, 1])
    with col_center:
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
                st.error("❌ Usuário ou senha incorretos. Tente novamente.")
    st.stop()


# ─────────────────────────────────────────────
#  BARRA LATERAL
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"### 👋 Olá, {st.session_state.display_name}!")
    st.caption(f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    st.divider()
    st.markdown("**Navegação rápida**")
    st.markdown("➕ **Lançar** → Registrar despesa ou receita")
    st.markdown("📋 **Lançamentos** → Ver e apagar registros")
    st.markdown("💰 **Saldos** → Ver dinheiro disponível")
    st.markdown("⚙️ **Gestão** → Configurar categorias e contas")
    st.divider()
    if st.button("🚪 Sair da conta", use_container_width=True):
        st.session_state.clear()
        st.rerun()


# ─────────────────────────────────────────────
#  ABAS PRINCIPAIS
# ─────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "➕  Novo Lançamento",
    "📋  Todos os Lançamentos",
    "💰  Saldos por Conta",
    "⚙️  Gestão"
])


# ══════════════════════════════════════════════
#  TAB 1 — NOVO LANÇAMENTO
# ══════════════════════════════════════════════
with tab1:
    st.markdown("## ➕ Registrar uma Movimentação")
    st.caption("Registre aqui qualquer entrada ou saída de dinheiro da sua família.")
    st.divider()

    cat_df     = db_df("SELECT id, nome, pai_id FROM categorias")
    pai_opts   = cat_df[cat_df['pai_id'].isna()]['nome'].tolist()
    fontes_row = db_query("SELECT nome FROM fontes")
    fontes_lista = [r[0] for r in fontes_row] if fontes_row else ["Padrão"]
    benef_row  = db_query("SELECT nome FROM beneficiarios")
    benef_opts = [r[0] for r in benef_row] if benef_row else ["Não especificado"]

    with st.form(key=f"f_lanca_{st.session_state.ver}", clear_on_submit=True):
        tipo = st.radio(
            "**Tipo de movimentação**",
            ["💸 Despesa", "💵 Receita"],
            horizontal=True
        )
        tipo_val = "Despesa" if "Despesa" in tipo else "Receita"

        st.markdown("---")
        col1, col2, col3 = st.columns([2, 1.2, 1.5])
        with col1:
            val = st.number_input("**Valor**", min_value=0.0, step=0.01, format="%.2f")
        with col2:
            moeda = st.selectbox("**Moeda**", ["EUR", "BRL"],
                                 help="BRL será convertido para EUR (taxa: 0,16)")
        with col3:
            data_lancamento = st.date_input("**Data**", value=datetime.now())

        st.markdown("---")
        col4, col5 = st.columns(2)

        with col4:
            st.markdown("**📂 Categoria**")
            if pai_opts:
                sel_pai = st.selectbox("Tipo de gasto/recebimento", pai_opts,
                                       label_visibility="collapsed")
                pid = int(cat_df[cat_df['nome'] == sel_pai]['id'].iloc[0])
                filhos = cat_df[cat_df['pai_id'] == pid]['nome'].tolist()
                sel_filho = st.selectbox(
                    "Detalhamento (opcional)",
                    filhos if filhos else ["Geral"]
                )
            else:
                st.warning("⚠️ Cadastre categorias na aba Gestão primeiro.")
                sel_pai   = "Sem categoria"
                sel_filho = "Geral"

        with col5:
            st.markdown("**🏦 De onde vem / Para onde vai este dinheiro?**")
            fonte        = st.selectbox("Conta ou carteira", fontes_lista,
                                        label_visibility="collapsed")
            beneficiario = st.selectbox("Beneficiário (quem recebe ou envia)", benef_opts)

        nota = st.text_input("📝 Observação (opcional)",
                             placeholder="Ex: Supermercado do mês, Salário de março...")

        submitted = st.form_submit_button("✅ Salvar Lançamento",
                                          use_container_width=True,
                                          type="primary")

        if submitted:
            if val == 0:
                st.error("O valor não pode ser zero.")
            else:
                v_eur    = val * 0.16 if moeda == "BRL" else val
                data_str = data_lancamento.strftime("%d/%m/%Y")
                db_execute(
                    """INSERT INTO transacoes
                       (data, categoria_pai, categoria_filho, beneficiario,
                        fonte, valor_eur, tipo, nota, usuario)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (data_str, sel_pai, sel_filho, beneficiario,
                     fonte, v_eur, tipo_val, nota, st.session_state.display_name)
                )
                st.session_state.ver += 1
                st.rerun()


# ══════════════════════════════════════════════
#  TAB 2 — TODOS OS LANÇAMENTOS
# ══════════════════════════════════════════════
with tab2:
    st.markdown("## 📋 Histórico de Lançamentos")
    st.caption("Visualize e remova registros. Marque a caixa e clique em 'Confirmar Remoção'.")
    st.divider()

    fontes_row2 = db_query("SELECT nome FROM fontes")
    fontes_disp = ["Todas"] + [r[0] for r in fontes_row2]

    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        filtro_tipo = st.selectbox("Filtrar por tipo", ["Todos", "Despesa", "Receita"])
    with col_f2:
        filtro_fonte = st.selectbox("Filtrar por conta", fontes_disp)
    with col_f3:
        filtro_busca = st.text_input("🔍 Buscar por nota ou categoria",
                                     placeholder="Digite para filtrar...")

    df = db_df("SELECT * FROM transacoes ORDER BY id DESC")

    if not df.empty:
        if filtro_tipo != "Todos":
            df = df[df['tipo'] == filtro_tipo]
        if filtro_fonte != "Todas":
            df = df[df['fonte'] == filtro_fonte]
        if filtro_busca:
            mask = (df['nota'].str.contains(filtro_busca, case=False, na=False) |
                    df['categoria_pai'].str.contains(filtro_busca, case=False, na=False) |
                    df['categoria_filho'].str.contains(filtro_busca, case=False, na=False))
            df = df[mask]

    st.caption(f"📌 {len(df)} registro(s) encontrado(s)")

    if not df.empty:
        df.insert(0, "Remover", False)
        df_display = df.rename(columns={
            'id': 'ID', 'data': 'Data',
            'categoria_pai': 'Categoria', 'categoria_filho': 'Detalhamento',
            'beneficiario': 'Beneficiário', 'fonte': 'Conta',
            'valor_eur': 'Valor (€)', 'tipo': 'Tipo',
            'nota': 'Observação', 'usuario': 'Registrado por'
        })

        editor = st.data_editor(
            df_display,
            key=f"ed_{st.session_state.ver}",
            use_container_width=True,
            column_config={
                "Remover": st.column_config.CheckboxColumn("🗑️ Remover"),
                "Valor (€)": st.column_config.NumberColumn(format="€ %.2f"),
            }
        )

        if st.button("🗑️ Confirmar Remoção", type="secondary", key="rm_trans"):
            ids_rm = editor[editor["Remover"] == True]["ID"].tolist()
            if ids_rm:
                db_execute(
                    f"DELETE FROM transacoes WHERE id IN ({','.join(['?']*len(ids_rm))})",
                    tuple(ids_rm)
                )
                st.session_state.ver += 1
                st.success(f"{len(ids_rm)} registro(s) removido(s).")
                st.rerun()
            else:
                st.warning("Marque pelo menos um registro para remover.")
    else:
        st.info("Nenhum lançamento encontrado com os filtros aplicados.")


# ══════════════════════════════════════════════
#  TAB 3 — SALDOS
# ══════════════════════════════════════════════
with tab3:
    st.markdown("## 💰 Saldos por Conta")
    st.caption("Veja quanto dinheiro há disponível em cada conta ou carteira.")
    st.divider()

    fontes_saldo = [r[0] for r in db_query("SELECT nome FROM fontes")]

    if not fontes_saldo:
        st.info("💡 Você ainda não tem contas cadastradas. Vá até a aba **Gestão** para adicionar (ex: Banco, Carteira, Poupança).")
    else:
        total_geral  = 0.0
        cols_saldo   = st.columns(min(len(fontes_saldo), 3))

        for i, f in enumerate(fontes_saldo):
            ini_row = db_query("SELECT valor_inicial FROM saldos_iniciais WHERE fonte=?", (f,))
            ini     = ini_row[0][0] if ini_row else 0.0

            rec_row = db_query("SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo='Receita'", (f,))
            rec     = (rec_row[0][0] or 0.0) if rec_row else 0.0

            des_row = db_query("SELECT SUM(valor_eur) FROM transacoes WHERE fonte=? AND tipo='Despesa'", (f,))
            des     = (des_row[0][0] or 0.0) if des_row else 0.0

            saldo = ini + rec - des
            total_geral += saldo

            classe_card  = "saldo-card-positivo" if saldo >= 0 else "saldo-card-negativo"
            classe_valor = "valor-positivo"       if saldo >= 0 else "valor-negativo"
            sinal = "+" if saldo > 0 else ""

            with cols_saldo[i % 3]:
                st.markdown(f"""
                <div class="saldo-card {classe_card}">
                    <h3>🏦 {f}</h3>
                    <div class="{classe_valor}">{sinal}€ {saldo:,.2f}</div>
                    <div class="detalhe">
                        Entradas: € {rec:,.2f} &nbsp;|&nbsp; Saídas: € {des:,.2f}
                        {f' &nbsp;|&nbsp; Saldo inicial: € {ini:,.2f}' if ini != 0 else ''}
                    </div>
                </div>
                """, unsafe_allow_html=True)

        st.divider()
        classe_total = "valor-positivo" if total_geral >= 0 else "valor-negativo"
        sinal_total  = "+" if total_geral > 0 else ""
        st.markdown(f"""
        <div class="saldo-card" style="background:#1e293b; border-left-color:#3b82f6;">
            <h3 style="color:#94a3b8;">📊 TOTAL CONSOLIDADO</h3>
            <div class="{classe_total}" style="font-size:2.4rem;">{sinal_total}€ {total_geral:,.2f}</div>
            <div class="detalhe" style="color:#64748b;">Soma de todas as suas contas</div>
        </div>
        """, unsafe_allow_html=True)

        st.divider()
        st.markdown("#### 🔧 Ajustar Saldo Inicial por Conta")
        st.caption("Use se as contas já tinham dinheiro antes de começar a usar o sistema.")

        for f in fontes_saldo:
            ini_row2 = db_query("SELECT valor_inicial FROM saldos_iniciais WHERE fonte=?", (f,))
            ini_atual = ini_row2[0][0] if ini_row2 else 0.0

            col_si1, col_si2 = st.columns([3, 1])
            with col_si1:
                novo_ini = st.number_input(
                    f"Saldo inicial de **{f}**",
                    value=float(ini_atual), step=10.0, format="%.2f",
                    key=f"ini_{f}"
                )
            with col_si2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("Salvar", key=f"salvar_ini_{f}"):
                    db_execute(
                        "INSERT OR REPLACE INTO saldos_iniciais (fonte, valor_inicial) VALUES (?,?)",
                        (f, novo_ini)
                    )
                    st.success(f"Saldo inicial de '{f}' atualizado!")
                    st.rerun()


# ══════════════════════════════════════════════
#  TAB 4 — GESTÃO
# ══════════════════════════════════════════════
with tab4:
    st.markdown("## ⚙️ Gestão e Configurações")
    st.caption("Configure as categorias, contas e beneficiários do seu sistema.")

    cat_df2   = db_df("SELECT id, nome, pai_id FROM categorias")
    pai_opts2 = cat_df2[cat_df2['pai_id'].isna()]['nome'].tolist()

    # ── SEÇÃO 1: CATEGORIAS ────────────────────
    st.markdown("---")
    st.markdown('<div class="secao-titulo">📂 Seção 1 — Categorias</div>', unsafe_allow_html=True)
    st.markdown('<div class="secao-sub">Organize seus gastos e receitas em categorias e detalhamentos.</div>', unsafe_allow_html=True)

    col_cat1, col_cat2 = st.columns(2)

    with col_cat1:
        st.markdown("**Adicionar Categoria Principal**")
        st.caption("Ex: Alimentação, Transporte, Saúde, Lazer")
        n_pai = st.text_input("Nome da categoria principal", key="inp_pai",
                               placeholder="Ex: Alimentação")
        if st.button("➕ Adicionar Categoria Principal", use_container_width=True):
            if n_pai.strip():
                try:
                    db_execute("INSERT INTO categorias (nome) VALUES (?)", (n_pai.strip(),))
                    st.success(f"Categoria '{n_pai}' adicionada!")
                    st.rerun()
                except Exception:
                    st.error("Já existe uma categoria com esse nome.")
            else:
                st.warning("Digite um nome para a categoria.")

    with col_cat2:
        st.markdown("**Adicionar Detalhamento**")
        st.caption("Ex: Dentro de 'Alimentação' → Supermercado, Restaurante...")
        if pai_opts2:
            pai_sel_gest = st.selectbox("Dentro de qual categoria?", pai_opts2, key="sel_pai_gest")
            n_sub = st.text_input("Nome do detalhamento", key="inp_sub",
                                   placeholder="Ex: Supermercado")
            if st.button("➕ Adicionar Detalhamento", use_container_width=True):
                if n_sub.strip():
                    try:
                        pid2 = int(cat_df2[cat_df2['nome'] == pai_sel_gest]['id'].iloc[0])
                        db_execute("INSERT INTO categorias (nome, pai_id) VALUES (?,?)",
                                   (n_sub.strip(), pid2))
                        st.success(f"Detalhamento '{n_sub}' adicionado em '{pai_sel_gest}'!")
                        st.rerun()
                    except Exception:
                        st.error("Já existe um detalhamento com esse nome.")
                else:
                    st.warning("Digite um nome para o detalhamento.")
        else:
            st.info("Crie uma Categoria Principal primeiro.")

    st.markdown("**Categorias cadastradas:**")
    if not cat_df2.empty:
        cat_view = cat_df2.copy()
        pai_map  = cat_df2[cat_df2['pai_id'].isna()].set_index('id')['nome'].to_dict()
        cat_view['Categoria Principal'] = cat_view['pai_id'].map(pai_map).fillna('— (é principal)')
        cat_view = cat_view.rename(columns={'nome': 'Nome'})
        cat_view.insert(0, "Remover", False)
        cat_display = cat_view[['Remover', 'id', 'Nome', 'Categoria Principal']]

        ed_cat = st.data_editor(
            cat_display,
            key=f"ed_cat_{st.session_state.ver}",
            use_container_width=True,
            column_config={"Remover": st.column_config.CheckboxColumn("🗑️")}
        )
        if st.button("🗑️ Remover Categorias Selecionadas", key="rm_cat"):
            ids_cat = ed_cat[ed_cat["Remover"] == True]["id"].tolist()
            if ids_cat:
                db_execute(
                    f"DELETE FROM categorias WHERE id IN ({','.join(['?']*len(ids_cat))})",
                    tuple(ids_cat)
                )
                st.success(f"{len(ids_cat)} categoria(s) removida(s).")
                st.rerun()
            else:
                st.warning("Selecione pelo menos uma categoria para remover.")
    else:
        st.info("Nenhuma categoria cadastrada ainda.")

    # ── SEÇÃO 2: CONTAS E FONTES ───────────────
    st.markdown("---")
    st.markdown('<div class="secao-titulo">🏦 Seção 2 — Contas e Fontes de Dinheiro</div>', unsafe_allow_html=True)
    st.markdown('<div class="secao-sub">Cadastre as contas onde o dinheiro da sua família fica guardado ou circula.</div>', unsafe_allow_html=True)

    col_f1g, col_f2g = st.columns([2, 1])
    with col_f1g:
        n_fonte = st.text_input("Nome da conta ou carteira", key="inp_fonte",
                                 placeholder="Ex: Banco CGD, Carteira, Poupança, Nubank...")
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
                st.warning("Digite um nome para a conta.")

    fontes_df = db_df("SELECT id, nome FROM fontes")
    st.markdown("**Contas cadastradas:**")
    if not fontes_df.empty:
        fontes_df.insert(0, "Remover", False)
        fontes_df = fontes_df.rename(columns={'nome': 'Nome da Conta'})
        ed_fontes = st.data_editor(
            fontes_df,
            key=f"ed_fontes_{st.session_state.ver}",
            use_container_width=True,
            column_config={"Remover": st.column_config.CheckboxColumn("🗑️")}
        )
        if st.button("🗑️ Remover Contas Selecionadas", key="rm_fontes"):
            ids_f = ed_fontes[ed_fontes["Remover"] == True]["id"].tolist()
            if ids_f:
                nomes_f = ed_fontes[ed_fontes["Remover"] == True]["Nome da Conta"].tolist()
                ops = [(f"DELETE FROM fontes WHERE id IN ({','.join(['?']*len(ids_f))})",
                        tuple(ids_f))]
                for nm in nomes_f:
                    ops.append(("DELETE FROM saldos_iniciais WHERE fonte=?", (nm,)))
                db_execute_many(ops)
                st.success(f"{len(ids_f)} conta(s) removida(s).")
                st.rerun()
            else:
                st.warning("Selecione pelo menos uma conta para remover.")
    else:
        st.info("Nenhuma conta cadastrada ainda. Adicione sua primeira conta acima.")

    # ── SEÇÃO 3: BENEFICIÁRIOS ─────────────────
    st.markdown("---")
    st.markdown('<div class="secao-titulo">👤 Seção 3 — Beneficiários</div>', unsafe_allow_html=True)
    st.markdown('<div class="secao-sub">Registe quem costuma enviar ou receber dinheiro da sua família.</div>', unsafe_allow_html=True)

    col_b1g, col_b2g = st.columns([2, 1])
    with col_b1g:
        n_benef = st.text_input("Nome do beneficiário", key="inp_benef",
                                 placeholder="Ex: Pingo Doce, João Silva, Renda apartamento...")
    with col_b2g:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("➕ Adicionar Beneficiário", use_container_width=True, key="btn_benef"):
            if n_benef.strip():
                try:
                    db_execute("INSERT INTO beneficiarios (nome) VALUES (?)", (n_benef.strip(),))
                    st.success(f"Beneficiário '{n_benef}' adicionado!")
                    st.rerun()
                except Exception:
                    st.error("Já existe um beneficiário com esse nome.")
            else:
                st.warning("Digite um nome para o beneficiário.")

    benef_df = db_df("SELECT id, nome FROM beneficiarios")
    st.markdown("**Beneficiários cadastrados:**")
    if not benef_df.empty:
        benef_df.insert(0, "Remover", False)
        benef_df = benef_df.rename(columns={'nome': 'Nome'})
        ed_benef = st.data_editor(
            benef_df,
            key=f"ed_benef_{st.session_state.ver}",
            use_container_width=True,
            column_config={"Remover": st.column_config.CheckboxColumn("🗑️")}
        )
        if st.button("🗑️ Remover Beneficiários Selecionados", key="rm_benef"):
            ids_b = ed_benef[ed_benef["Remover"] == True]["id"].tolist()
            if ids_b:
                db_execute(
                    f"DELETE FROM beneficiarios WHERE id IN ({','.join(['?']*len(ids_b))})",
                    tuple(ids_b)
                )
                st.success(f"{len(ids_b)} beneficiário(s) removido(s).")
                st.rerun()
            else:
                st.warning("Selecione pelo menos um beneficiário para remover.")
    else:
        st.info("Nenhum beneficiário cadastrado ainda.")

    # ── SEÇÃO 4: UTILIZADORES ──────────────────
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
                        "INSERT INTO usuarios (username, password, nome_exibicao) VALUES (?,?,?)",
                        (n_user.strip(), hash_password(n_pass), n_nome.strip())
                    )
                    st.success(f"Utilizador '{n_nome}' adicionado com sucesso!")
                    st.rerun()
                except Exception:
                    st.error("Já existe um utilizador com esse nome de login.")
        else:
            st.warning("Preencha todos os campos: utilizador, nome e senha.")

    users_df = db_df("SELECT id, username, nome_exibicao FROM usuarios")
    users_df = users_df.rename(columns={'username': 'Login', 'nome_exibicao': 'Nome de Exibição'})
    st.markdown("**Utilizadores cadastrados:**")
    st.dataframe(users_df, use_container_width=True, hide_index=True)
