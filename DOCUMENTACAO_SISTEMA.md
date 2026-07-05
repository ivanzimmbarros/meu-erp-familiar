# 📘 Documentação Técnica e Funcional — ERP Familiar (`meu-erp-familiar`)

> Sistema de gestão financeira familiar construído em **Python + Streamlit + SQLite**.
> Arquitetura modular, núcleo desacoplado da interface, segurança com PBKDF2 + 2FA e
> rede de segurança de **135 testes automatizados**.

---

## 1. Introdução e Arquitetura Global

O projeto foi refatorado de um `app.py` monolítico para uma arquitetura **modular em camadas**, separando regras de negócio, dados, segurança e interface. Os módulos de núcleo **não importam Streamlit**, o que permite testá-los diretamente (sem mocks de UI) e reaproveitá-los em scripts/CLI.

### 1.1 Papel de cada arquivo

| Arquivo | Camada | Responsabilidade |
|---------|--------|------------------|
| `database.py` | Dados | Conexão SQLite com **pool/cache** (lock reentrante), schema, migrações, **11 índices**, primitivas de acesso (`db_execute`, `db_query`, `db_df`, `db_execute_many`), normalização de texto, funções de cadastro anti-duplicado, leitura hierárquica de categorias e **backup/restauração**. |
| `auth.py` | Segurança | Hash/verificação **PBKDF2-HMAC-SHA256 + salt** (com retrocompatibilidade SHA-256), OTP/2FA por e-mail (SMTP), autenticação, criação de usuários (com `force_reset`), recuperação e troca obrigatória de senha. |
| `import_parser.py` | Negócio | Leitura pura de extratos **OFX/CSV** para o módulo de importação (sem Streamlit). |
| `finance.py` | Negócio | Cálculos financeiros: parcelamento (offset linear de cartão), `fatura_ref`, saldos (real/comprometido/disponível **com previsão de assinaturas**), transferências (soma zero), liquidação, **travas de exclusão**, **CRUD + lógica preditiva de assinaturas**, **rollover de metas (envelopes)**, **revisão/atribuição para casais** e **importação de extratos (staging, classificação, auditoria)**. |
| `reports.py` | Relatórios | Geração do relatório gerencial **Excel de 3 abas** (`Transacoes`, `Metas`, `Resumo_Saldos`) — puro, sem Streamlit. |
| `ui_state.py` | UI (puro) | `limpar_campos_sessao()`: reset de campos de formulário (por prefixo/chave) após commit, preservando o estado de sessão (login). |
| `pages_config.py` | Navegação | Fonte única das rotas/páginas e regras de permissão por perfil (`get_pages(is_admin)`). Puro, testável. |
| `app.py` | UI / Entrypoint | Configuração global, CSS, bootstrap do banco, **gate de login global**, sidebar comum (incl. **alertas de contas vencidas e de revisões pendentes**) e `st.navigation`. |
| `views/*.py` | UI | Uma página por arquivo (Novos Lançamentos, **Importador**, Histórico, **Revisão**, Saldos, Cartões, **Assinaturas**, Metas, Dashboards, Transferências, Gestão Geral). |
| `emergency_reset.py` | CLI | Ferramenta de recuperação fora do app (reset de senha / admin de emergência) usando o mesmo hash PBKDF2. |
| `test_erp_core.py` | QA | Suíte com **135 testes** cobrindo banco, segurança, regras de negócio, relatórios, permissões, limpeza de formulários, **assinaturas, rollover de metas, revisão de casais** e **importação de extratos**. |

### 1.2 Fluxo de segurança de rotas

1. **Bootstrap (`app.py`):** `init_db()` cria/migra o schema e índices; `seed_admin()` cria o administrador a partir de `st.secrets["initial_setup"]` (idempotente, já com `force_reset=1`).
2. **Gate de login global:** enquanto `st.session_state.logado` for falso, o `app.py` renderiza apenas o "Portal de Acesso" e encerra o script com `st.stop()` — **nenhuma página é montada antes da autenticação**.
3. **Autenticação em camadas:** `login` → `2fa` (OTP de 6 dígitos por e-mail) → checagem de `force_reset` → (se necessário) `force_password_change` exigindo senha forte (regex: 8+ caracteres, maiúscula, número e especial). Há ainda a camada `recovery` (senha temporária por e-mail).
4. **Hash PBKDF2:** senhas nunca são guardadas em texto puro; o formato é `pbkdf2_sha256$<iterações>$<salt_hex>$<hash_hex>` (200.000 iterações, salt de 16 bytes).
5. **Views fora de pasta pública:** as páginas ficam em **`views/`** e **não** em `pages/`. O Streamlit faz descoberta automática de qualquer `pages/` e a exibiria na sidebar **antes** do `st.navigation` — ou seja, antes do gate de login. Usar `views/` elimina essa descoberta e mantém o login íntegro.
6. **Permissão por perfil:** `st.navigation` é montado a partir de `get_pages(is_admin)`; a página **Gestão Geral** (`admin_only`) só aparece para administradores e ainda possui uma trava própria (`st.stop()`) no topo do arquivo.

---

## 2. Modelagem Relacional (Banco de Dados `finance.db`)

> **Nota sobre case-insensitive:** o schema **não** usa `COLLATE NOCASE`. As colunas de nome possuem `UNIQUE` exato no SQLite, mas a **prevenção inteligente de duplicados** (acentos, caixa, espaços) é feita na **camada de aplicação** via `database.normalizar_texto()` antes de cada inserção. `PRAGMA foreign_keys = ON` é ativado em cada conexão.

### 2.1 Tabelas

#### `usuarios`
| Campo | Tipo | Restrições |
|-------|------|------------|
| `id` | INTEGER | PRIMARY KEY |
| `username` | TEXT | UNIQUE |
| `password` | TEXT | hash PBKDF2 |
| `nome_exibicao` | TEXT | |
| `email` | TEXT | usado no 2FA/recuperação (migração) |
| `perfil` | TEXT | DEFAULT `'Utilizador'` (`'Administrador'` p/ admin) |
| `force_reset` | INTEGER | DEFAULT `0` — `1` força troca de senha no 1º login |

#### `fontes` (contas bancárias)
| Campo | Tipo | Restrições |
|-------|------|------------|
| `id` | INTEGER | PRIMARY KEY |
| `nome` | TEXT | UNIQUE |

#### `saldos_iniciais`
| Campo | Tipo | Restrições |
|-------|------|------------|
| `fonte` | TEXT | PRIMARY KEY |
| `valor_inicial` | REAL | DEFAULT `0.0` |

#### `beneficiarios`
| Campo | Tipo | Restrições |
|-------|------|------------|
| `id` | INTEGER | PRIMARY KEY |
| `nome` | TEXT | UNIQUE |

#### `configuracoes` (chave/valor)
| Campo | Tipo | Restrições |
|-------|------|------------|
| `chave` | TEXT | PRIMARY KEY |
| `valor` | TEXT | |

> Seeds padrão (idempotentes via `INSERT OR IGNORE`): `('taxa_brl_eur', '0.16')` e `('rollover_ativo', '1')`.
>
> **`rollover_ativo`** ativa/desativa **globalmente** o orçamento acumulado de metas (`'1'` = ativo, `'0'` = inativo). É lido/escrito por `finance.rollover_esta_ativo()` e `finance.definir_rollover_ativo()` e alternado pelo toggle da tela de Metas.

#### `categorias` (hierarquia Natureza → Categoria → Subcategoria)
| Campo | Tipo | Restrições |
|-------|------|------------|
| `id` | INTEGER | PRIMARY KEY |
| `nome` | TEXT | UNIQUE (global, sob normalização na app) |
| `pai_id` | INTEGER | **FK → `categorias(id)` ON DELETE RESTRICT** |
| `tipo_categoria` | TEXT | Natureza (`'Receita'`/`'Despesa'`) nas categorias principais; `NULL` nas subcategorias |

> Categorias principais têm `pai_id IS NULL` e `tipo_categoria` preenchido. Subcategorias têm `pai_id` apontando para a principal (a Natureza é herdada do pai). A hierarquia é **estrita de 3 níveis**.

#### `cartoes`
| Campo | Tipo | Restrições |
|-------|------|------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT |
| `nome` | TEXT | UNIQUE |
| `limite` | REAL | |
| `dia_fechamento` | INTEGER | |
| `dia_vencimento` | INTEGER | |
| `conta_pagamento` | TEXT | nome da `fonte` que paga a fatura |

#### `orcamentos` (metas/tetos)
| Campo | Tipo | Restrições |
|-------|------|------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT |
| `mes_ano` | TEXT | formato `YYYY-MM` |
| `categoria_pai` | TEXT | |
| `categoria_filho` | TEXT | DEFAULT `'Geral'` (legado) |
| `valor_previsto` | REAL | |
| `tipo_meta` | TEXT | `'Receita'`/`'Despesa'` |
| — | — | **UNIQUE(`mes_ano`, `categoria_pai`, `categoria_filho`, `tipo_meta`)** |

#### `transacoes` (núcleo do sistema)
| Campo | Tipo | Restrições / Notas |
|-------|------|--------------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT |
| `data` | TEXT | `YYYY-MM-DD` |
| `categoria_pai` | TEXT | |
| `categoria_filho` | TEXT | |
| `beneficiario` | TEXT | |
| `fonte` | TEXT | conta ou cartão |
| `valor_eur` | REAL | |
| `tipo` | TEXT | `'Receita'`/`'Despesa'` |
| `nota` | TEXT | |
| `usuario` | TEXT | autor do lançamento |
| `forma_pagamento` | TEXT | DEFAULT `'Dinheiro/Débito'` (ou `'Cartão de Crédito'`) |
| `cartao_id` | INTEGER | referência lógica a `cartoes.id` |
| `fatura_ref` | TEXT | `YYYY-MM` da fatura (cartão) |
| `status_cartao` | TEXT | DEFAULT `'pendente'` (`'pago'`) |
| `status_liquidacao` | TEXT | DEFAULT `'PAGO'` (`PENDENTE`/`PREVISTO`/`RECEBIDO`) |
| `data_liquidacao` | TEXT | preenchida na baixa |
| `parcela_id` | TEXT | agrupador de parcelas |
| `parcela_numero` | INTEGER | DEFAULT `1` |
| `total_parcelas` | INTEGER | DEFAULT `1` |
| `status_revisao` | TEXT | **(migração)** DEFAULT `'REVISADO'` — estados `PENDENTE`/`REVISADO` (revisão para casais) |
| `atribuido_a` | TEXT | **(migração)** `username` do membro designado para revisar o lançamento |

> **Colunas de revisão (migração idempotente):** `status_revisao` e `atribuido_a` são adicionadas em `init_db()` pela lista `MIGRATIONS`, cada `ALTER TABLE` protegido por `try/except` individual (seguro em local e produção; ignora se a coluna já existe). Um lançamento comum nasce `REVISADO`; ao ser enviado para revisão familiar, nasce `PENDENTE` com `atribuido_a` preenchido.

#### `assinaturas` (contas fixas / serviços recorrentes — estilo Rocket Money)
| Campo | Tipo | Restrições |
|-------|------|------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT |
| `nome` | TEXT | UNIQUE (anti-duplicado inteligente sob normalização na app) |
| `valor_eur` | REAL | valor mensal (> 0) |
| `dia_vencimento` | INTEGER | dia do mês `1..31` |
| `conta_padrao` | TEXT | nome da `fonte` que debita a assinatura |
| `categoria_pai` | TEXT | Categoria Principal (obrigatória) |
| `categoria_filho` | TEXT | Subcategoria (obrigatória, hierarquia estrita) |
| `ativa` | INTEGER | DEFAULT `1` — `1` ativa (entra na previsão) / `0` pausada |

#### `importacoes_staging` (buffer de revisão de extratos)
| Campo | Tipo | Restrições / Notas |
|-------|------|--------------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT |
| `raw_descricao` | TEXT | descrição bruta do extrato |
| `data` | TEXT | `YYYY-MM-DD` |
| `valor_eur` | REAL | sempre positivo (natureza define o sinal lógico) |
| `natureza` | TEXT | `'Receita'`/`'Despesa'` |
| `categoria_pai` | TEXT | preenchida na revisão ou pela auto-classificação |
| `categoria_filho` | TEXT | subcategoria |
| `beneficiario` | TEXT | opcional; limpo pelo botão **Analisar** |
| `nota` | TEXT | observação adicional do usuário |
| `fonte_destino` | TEXT | conta bancária de destino |

> Persistido em disco para resistir a reruns/expiração de sessão do Streamlit.

#### `auditoria_sistema` (trilha operacional)
| Campo | Tipo | Restrições |
|-------|------|------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT |
| `timestamp` | TEXT | `YYYY-MM-DD HH:MM:SS` |
| `usuario` | TEXT | autor da ação |
| `acao` | TEXT | ex.: `UPLOAD_EXTRATO`, `EXCLUSAO_STAGING`, `ANALISE_STAGING`, `CONTABILIZACAO_LOTE` |
| `detalhes` | TEXT | resumo textual da operação |

### 2.2 Índices de performance (11)

Criados sobre as consultas mais frequentes (saldos, faturas, auditoria, previsão de assinaturas e fila de revisão):

1. `idx_transacoes_fonte` → `transacoes(fonte)`
2. `idx_transacoes_cartao_id` → `transacoes(cartao_id)`
3. `idx_transacoes_status_liquidacao` → `transacoes(status_liquidacao)`
4. `idx_transacoes_fatura_ref` → `transacoes(fatura_ref)`
5. `idx_transacoes_data` → `transacoes(data)`
6. `idx_transacoes_fonte_tipo_status` → `transacoes(fonte, tipo, status_liquidacao)` (índice composto p/ cálculo de saldos)
7. `idx_assinaturas_conta_ativa` → `assinaturas(conta_padrao, ativa)` (previsão de assinaturas ativas por conta)
8. `idx_transacoes_revisao` → `transacoes(atribuido_a, status_revisao)` (fila de revisão por usuário)
9. `idx_transacoes_data_nota` → `transacoes(data, nota)` (motor de auto-classificação)
10. `idx_transacoes_nota` → `transacoes(nota)` (busca por descrição bruta)
11. `idx_staging_fonte` → `importacoes_staging(fonte_destino)` (buffer filtrado por conta)

---

## 3. Mapa Completo de Funcionalidades e Interações

### a) Novos Lançamentos (`views/novos_lancamentos.py`)
- **Entradas:** Natureza (radio), Meio de Pagamento (Dinheiro/Débito ou Cartão), Categoria Principal, Subcategoria (todos obrigatórios e em **cascata reativa** sem vazamento), Origem/Destino (conta ou cartão), Data, Valor, Nº de Parcelas, Beneficiário e Observação.
- **Processamento:**
  - A hierarquia é carregada por `database.listar_categorias_principais(natureza)` e `listar_subcategorias(pai_id)`; ao salvar, `subcategoria_pertence(pai_id, sub)` revalida o vínculo (defesa contra vazamento).
  - `finance.calcular_parcelas(...)` gera as parcelas. Para **cartão**, aplica offset: compra após o fechamento joga a 1ª fatura para o mês seguinte; e a **1ª parcela nunca vence antes da compra** (se cair antes, empurra +1 mês). As demais seguem o offset **linearmente**. Centavos residuais vão para a última parcela. Datas inválidas (ex.: dia 31 em fevereiro) são ajustadas ao último dia do mês.
  - `finance.calcular_fatura_ref(...)` define a `fatura_ref` para compras de cartão; `determinar_status_operacao(...)` define o status (1ª parcela à vista = `PAGO`/`RECEBIDO`; demais e cartão = `PENDENTE`).
- **Saída:** uma linha por parcela em `transacoes` (via `db_execute_many`). Após o commit, exibe sucesso e **limpa o formulário** (`clear_on_submit`) e reseta os seletores reativos (`ui_state.limpar_campos_sessao`).
- **Revisão cooperativa (opcional):** a seção **"⚠️ Enviar para Revisão Familiar"** (checkbox + seletor com os usuários de `usuarios`) permite delegar a classificação do lançamento a outro membro. Quando ativada, todas as parcelas são gravadas com `status_revisao='PENDENTE'` e `atribuido_a=<username do parceiro>`; quando inativa, o lançamento nasce `status_revisao='REVISADO'` e `atribuido_a=NULL` (comportamento padrão).
- **Conexões:** `database` (leitura de categorias/contas/cartões/usuários e escrita), `finance` (parcelas/fatura/status), `ui_state` (reset).

### a2) Importador de Extratos (`views/importador.py`)
- **Entradas:** Conta de Destino (obrigatória), upload `.OFX`/`.CSV`, revisão linha a linha com cascata Natureza → Categoria → Subcategoria → Beneficiário.
- **Trava de conta (Req. 1):** sem conta selecionada, o upload exibe `st.error` e não processa o arquivo.
- **Buffer persistente (Req. 2/3):** linhas ficam em `importacoes_staging` até contabilização ou exclusão — sobrevivem a reruns do Streamlit.
- **Processamento:**
  - `import_parser.parse_arquivo_extrato` normaliza OFX/CSV para linhas padronizadas.
  - `finance.inserir_upload_no_staging` grava no buffer e aplica **auto-classificação** (`finance.classificar_por_descricao`) buscando a transação mais recente com a mesma descrição em `nota`.
  - **Analisar:** `finance.analisar_staging` varre o histórico com correspondência exata e por padrão normalizado; preenche categorias e **limpa beneficiário**.
  - **Contabilizar Selecionados:** `finance.contabilizar_staging` insere em `transacoes` preservando a descrição bruta em `nota` (Req. 4), **sem apagar** lançamentos pré-existentes na mesma data (Req. 5).
- **Auditoria:** cada upload, exclusão, análise e contabilização grava em `auditoria_sistema` via `finance.registrar_auditoria`.
- **Atalhos (Req. 8):** caption orientando abrir **Gestão Geral** para cadastrar beneficiários/categorias sem perder o buffer.
- **Menu:** página **📥 Importador** visível a todos os perfis logados.
- **Conexões:** `import_parser`, `database` (categorias/contas), `finance` (staging, classificação, auditoria).

### b) Histórico e Auditoria (`views/historico.py`)
- **Entradas/Filtros:** Tipo (Todos/Despesa/Receita), Conta/Cartão, Busca livre (nota/beneficiário), Categoria e Subcategoria (cascata reativa filtrada por Natureza).
- **Processamento:** monta uma visão **híbrida** unindo lançamentos comuns e **faturas de cartão consolidadas** (agrupadas por `fatura_ref` + cartão). Os filtros são aplicados sobre o DataFrame.
- **Saída:** tabela filtrada + **tabela técnica de auditoria** (com `status`, parcelas e nota detalhada) e exclusão direta de registros por seleção (`DELETE ... WHERE id IN (...)`).
- **Conexões:** `database` (consultas e exclusão), `cartoes` (JOIN para consolidar faturas).

### c) Saldos e Patrimônio (`views/saldos.py`)
- **Cálculos (`finance.py`):**
  - **Saldo Real** = saldo inicial + receitas `RECEBIDO` − despesas `PAGO`, **ignorando** movimentos de Cartão de Crédito.
  - **Comprometido** = despesas `PENDENTE/PREVISTO` (não-cartão) − receitas previstas + faturas de cartão `pendente` cuja `conta_pagamento` é a conta **+ previsão de assinaturas ativas ainda não pagas no mês** (ver Módulo de Assinaturas). Essa parcela preditiva **desaparece automaticamente** assim que o pagamento da assinatura é registrado no mês corrente.
  - **Disponível** = Saldo Real − Comprometido.
- **Saídas:** cards por conta, totais consolidados e alerta de **insolvência** ou **disponibilidade positiva**.
- **Painel "Contas a Liquidar":** lista pendentes/previstas (não-cartão); o botão chama `finance.liquidar_transacao(id, tipo)`, que marca `PAGO`/`RECEBIDO` e grava `data_liquidacao` (refletindo imediatamente no Saldo Real).
- **Conexões:** `database` (consultas), `finance` (cálculos + liquidação).

### d) Cartões de Crédito (`views/cartoes.py`)
- **Cadastro:** nome, limite, conta de pagamento, dia de fechamento e vencimento — via `database.criar_cartao()` (anti-duplicado).
- **Faturas:** agrupa `transacoes` por `fatura_ref`; exibe limite, usado (`status_cartao='pendente'`) e composição da fatura.
- **Pagamento de fatura:** se o **Saldo Real** da conta de pagamento cobre o total, marca as transações da fatura como `pago`/`PAGO` e cria um débito consolidado (`Despesa`/`PAGO`) na conta — sem dupla contagem (os lançamentos de cartão são excluídos do Saldo Real).
- **Trava de exclusão associada:** `finance.verificar_bloqueio_delecao('fontes', id)` impede excluir uma conta usada como `conta_pagamento` de algum cartão.
- **Conexões:** `database`, `finance` (saldo + travas).

### e) Metas e Orçamentos + Rollover (`views/metas.py`)
- **Entradas:** Mês de referência, Natureza, Categoria, Subcategoria (obrigatórias, cascata reativa) e Valor planejado.
- **Processamento:** grava em `orcamentos` (UNIQUE por mês+categoria+subcategoria+tipo, via `INSERT OR REPLACE`). O progresso compara o previsto com o realizado (soma de `transacoes` do mês/categoria/subcategoria), com indicador 🔴/🟢 e barra de progresso.
- **Pós-commit:** sucesso + reset dos seletores reativos (`ui_state`); o mês de referência é preservado.
- **Rollover de Metas (orçamento acumulado — modelo de envelopes YNAB):** um **toggle** "🔄 Acumular saldo do mês anterior" (estado persistido em `configuracoes.rollover_ativo`) ativa/desativa dinamicamente a visualização acumulada. Quando **ativo**, cada meta exibe a **Meta Base**, o **Rollover herdado** (com selo colorido: ➕ verde se positivo, ➖ vermelho se negativo) e o **Orçamento Ajustado** (= base + rollover); a barra passa a comparar o realizado contra o **ajustado**. Quando **inativo**, mantém a comparação contra a meta base original.
- **Conexões:** `database`, `finance` (rollover/progresso), `ui_state`.

> **Lógica do Rollover (`finance.py`):**
> - `mes_anterior(mes_ano)` resolve o mês precedente tratando a virada de ano (`2024-01` → `2023-12`).
> - `calcular_rollover_categoria(categoria_pai, categoria_filho, tipo_meta, mes_ano)` acumula de forma **linear e cumulativa** o saldo residual dos meses anteriores (o saldo de um mês já herda o do mês que o precede), com **janela máxima de 12 meses** para evitar loops/lentidão.
> - Saldo residual por natureza: **Despesa** = Planejado − Realizado (sobra positiva, estouro negativo); **Receita** = Realizado − Planejado.
> - `calcular_orcamento_ajustado(base, rollover)` e `fracao_progresso(realizado, ajustado)` — esta última **robusta a orçamento ajustado ≤ 0** (estouro massivo herdado): nunca divide por zero, devolvendo `1.0` se há realizado e `0.0` caso contrário.

### f) Dashboards de BI (`views/dashboard.py`)
- **Filtros:** período, contas/cartões, beneficiários, categorias e subcategorias (cascata).
- **KPIs:** Receita Total, Despesa Paga, Comprometido e Balanço Líquido (+ margem %).
- **Gráficos Plotly:** tendência Receita×Despesa / Execução / Peso por categoria; treemap de estrutura de gastos; Top 10 beneficiários; sunburst por fonte. Todos com **guardas para dados vazios** (sem quebra quando o filtro não retorna despesas).
- **Exportação Excel (3 abas) via `reports.gerar_relatorio_excel_bytes()`:** `Transacoes` (base bruta), `Metas` (orçamentos) e `Resumo_Saldos` (consolidação por conta: real, comprometido e disponível). Robusto a banco vazio (sempre 3 abas com cabeçalho).
- **Conexões:** `database` (dados), `reports` → `finance` (resumo de saldos).

### g) Transferências (`views/transferencias.py`)
- **Entradas:** conta de origem, destino (filtrado para ≠ origem), valor (mín. 0,01), data e nota.
- **Processamento (`finance.realizar_transferencia`):** operação de **soma zero** — grava uma Despesa `PAGO` na origem e uma Receita `RECEBIDO` no destino, de forma atômica (`db_execute_many`). **Valida**: origem ≠ destino e valor > 0 (`ValueError` com feedback amigável na UI).
- **Histórico/Estorno:** agrupa as duas pernas por data/valor/nota; o estorno apaga ambas as linhas do par.
- **Conexões:** `database`, `finance`.

### h) Gestão Geral (`views/gestao.py`, apenas Admin)
- **Taxa de câmbio:** atualiza `configuracoes.taxa_brl_eur`.
- **Cadastro de entidades** com **proteção anti-duplicados inteligente** (`database.normalizar_texto` + funções `criar_fonte`, `criar_beneficiario`, `criar_categoria_principal`, `criar_subcategoria`): bloqueia nomes equivalentes (acentos/caixa/espaços), inclusive para categorias em naturezas diferentes (unicidade global). Erros sobem como `DuplicadoError` com mensagem amigável.
- **Categorias:** criação de principais (com Natureza) e subcategorias (exclusivas do pai; sem 4º nível).
- **Usuários:** `auth.criar_usuario` (login case-insensitive via normalização; `force_reset=1` por padrão); remoção com trava de auto-exclusão.
- **Travas de exclusão (`finance.verificar_bloqueio_delecao`):** contas com lançamentos/saldo/cartão; categorias com filhas/transações/orçamentos; beneficiários com transações.
- **Backup/Restauração (`database`):** `export_db_bytes()` gera snapshot consistente (API `backup` do SQLite); `validar_backup()` checa cabeçalho SQLite, `PRAGMA integrity_check` e presença de tabelas essenciais (`usuarios`, `transacoes`); `restaurar_db()` só sobrescreve após validação, fechando conexões e limpando arquivos auxiliares (WAL/SHM/journal).
- **Limpeza pós-commit:** todos os formulários usam `clear_on_submit=True`.

### i) Assinaturas e Contas Fixas (`views/assinaturas.py`, estilo Rocket Money)
- **Cadastro:** Nome, Valor mensal (> 0), Dia de vencimento (1–31), Conta de débito padrão e hierarquia estrita de 3 níveis (Natureza → Categoria → Subcategoria, cascata reativa sem vazamento). O cadastro usa `finance.criar_assinatura`, que aplica a **prevenção inteligente de duplicados** (`normalizar_texto`/`DuplicadoError`) e valida o domínio; o formulário usa `clear_on_submit` + reset de seletores reativos (`ui_state`).
- **Métricas do mês:** Total **Previsto**, Total **já Pago** e **Pendente a pagar**.
- **Cronograma visual:** lista as assinaturas ativas **ordenadas cronologicamente pelo dia de vencimento (1→31)**, cada uma em um card com Nome, Categoria, Valor, Conta de débito, Dia e selo visual ✅ **PAGO** / ⏳ **PENDENTE** referente ao mês corrente.
- **Lançamento em 1-clique ("Dar Baixa"):** registra automaticamente uma transação `Despesa`/`PAGO` com a data de hoje, herdando os dados da assinatura (categoria, valor, conta, beneficiário/nota), refletindo nos saldos na hora. Há também **baixa em lote** de todas as pendentes, além de pausar/excluir.
- **Lógica preditiva (`finance.py`):**
  - `listar_assinaturas`, `criar_assinatura`, `atualizar_assinatura`, `definir_status_assinatura`, `excluir_assinatura` (CRUD seguro).
  - `assinatura_tem_pagamento_no_mes(id, ano_mes)` detecta se já há um lançamento correspondente no mês (casando por **nome** na nota/beneficiário **ou** pela **hierarquia de categoria**, restrito à conta de débito).
  - `previsao_assinaturas_pendentes(fonte)` soma as assinaturas ativas da conta ainda **não pagas** no mês; esse valor é integrado ao **Comprometido** em `calcular_comprometido(fonte)` (previsão de caixa futuro) e some após a baixa.
  - `registrar_pagamento_assinatura(id)` e `registrar_pagamentos_assinaturas(ids)` (unitária e em lote).
- **Conexões:** `database` (categorias/contas/usuários), `finance` (CRUD + previsão + baixa), `ui_state`.

### j) Revisão e Atribuição para Casais (`views/revisao.py`, estilo Monarch Money)
- **Objetivo:** permitir que um membro lance uma despesa e **delegue a classificação/revisão** a outro membro da família.
- **Fila de revisão:** `finance.listar_transacoes_pendentes_revisao(username)` retorna apenas as transações `status_revisao='PENDENTE'` **atribuídas ao usuário ativo** (isolamento por usuário; A nunca vê as pendências de B). A métrica do topo mostra a contagem (`finance.contar_pendencias_revisao`).
- **Cards de revisão:** cada pendência é exibida em card limpo (Data, Quem lançou, Valor, Conta/Cartão, Forma de pagamento e Nota original) com seletores de **Categoria Principal** e **Subcategoria** em **cascata reativa, obrigatória e sem vazamento** (filtrados pela Natureza da transação e pré-selecionados na categoria atual) e um campo para editar a nota.
- **Concluir Revisão:** `finance.concluir_revisao_transacao(trans_id, pai, filho, nota, usuario_revisor)` valida a hierarquia via `database.subcategoria_pertence`, grava as novas categorias/nota e altera `status_revisao` para `'REVISADO'` — o item sai da fila e a métrica é atualizada no rerun.
- **Alerta na sidebar (`app.py`):** indicador discreto "⚠️ Você tem X despesa(s) pendente(s) de revisão!" exibido para o usuário logado que tiver pendências atribuídas.
- **Menu (`pages_config.py`):** página **🔍 Revisão** visível a **todos os perfis** logados.
- **Conexões:** `database` (categorias/atualização), `finance` (listagem/conclusão), `app.py` (alerta).

---

## 4. Modelo de Recuperação de Emergência (`emergency_reset.py`)

Utilitário **CLI** executado fora do app (`python emergency_reset.py`), na mesma pasta do `finance.db`. Funções:
- **Listar usuários** cadastrados.
- **Redefinir senha** de um usuário: gera o hash com `auth.hash_password` (mesmo **PBKDF2-HMAC-SHA256 + salt** do app, garantindo compatibilidade no login) e zera `force_reset`.
- **Criar/atualizar admin de emergência** (`admin_emergencia`) como `Administrador`.

Como reutiliza `auth.hash_password`, qualquer senha redefinida por aqui é aceita normalmente pelo fluxo de login do sistema. Recomenda-se remover contas de emergência pela Gestão Geral após o acesso.

---

## 5. Cobertura da Suíte de Testes (`test_erp_core.py`)

A rede de segurança possui **135 testes** que isolam o banco em um SQLite temporário por teste (sem tocar o `finance.db` real) e validam o núcleo sem depender da UI:

- **Inicialização do banco:** tabelas (incl. `importacoes_staging` e `auditoria_sistema`), coluna `force_reset`, taxa padrão e os **11 índices**.
- **Usuário e senha (PBKDF2):** formato do hash, salt aleatório, verificação correta/incorreta, retrocompatibilidade SHA-256, e `force_reset` (admin semente e novos usuários).
- **Gestão de contas e recuperação:** duplicidade de login, troca obrigatória, recuperação por e-mail.
- **Parcelas e cartão:** distribuição de centavos, datas mensais, offset do cartão, **1ª parcela nunca antes da compra**, ano bissexto/dia 31, parcelas=0 e valor inválido.
- **`fatura_ref` e status de operação.**
- **Saldos:** real, comprometido, disponível e isolamento de movimentos de cartão.
- **Transferências:** soma zero, duas pernas, **bloqueio de mesma conta e de valor ≤ 0**.
- **Liquidação:** baixa de despesa/receita e reflexo no Saldo Real.
- **Travas de exclusão extras:** conta usada por cartão; categoria com orçamento.
- **Pool de conexões:** reutilização e limpeza do cache.
- **Backup/Restauração:** export válido, rejeição de arquivos inválidos/incompletos, round-trip e restauração não destrutiva.
- **Relatório Excel:** exatamente 3 abas, funcionamento com banco vazio e `Resumo_Saldos` correto.
- **Normalização e duplicados:** acentos/caixa/espaços para todas as entidades (fontes, beneficiários, cartões, categorias/subcategorias e usuários), inclusive unicidade global entre naturezas.
- **Hierarquia estrita:** filtragem por Natureza, subcategorias só do pai, não-vazamento entre pais e proibição de 4º nível.
- **Páginas e permissões:** visibilidade de Gestão (Admin × Utilizador), página padrão única e existência dos arquivos de página.
- **Arquitetura:** núcleo sem `import streamlit`, login único e uso de `st.navigation`/`st.Page` (sem `st.tabs`); smoke test de import do `app.py`.
- **UX — limpeza de formulários (`ui_state.py`):** reset por prefixo/chave preservando o login; e verificação de fonte de que **todo `st.form` declara `clear_on_submit=True`** (incl. a view de Assinaturas) e que Lançamentos/Metas resetam os seletores reativos após o commit.
- **Assinaturas e Contas Fixas (12 testes):** criação do schema no `init_db`; persistência de campos; **não-duplicidade sob normalização** (acentos/caixa/espaços); validações de domínio (valor ≤ 0, dia fora de 1–31); ordenação por dia de vencimento; **lógica preditiva** do comprometido (assinatura não paga soma; **some após o pagamento**); pausa removendo da previsão; isolamento por conta; **baixa unitária** (cria `Despesa`/`PAGO` herdando dados) e **em lote**; registro da página no menu.
- **Rollover de Metas (12 testes):** saldo residual de **Despesa** (sobra positiva / estouro negativo) e de **Receita** (positivo / negativo); virada de ano no cálculo do mês anterior; **propagação linear cumulativa em 3 meses**; ausência de dados → 0; **janela máxima de 12 meses**; soma do orçamento ajustado; **robustez a divisão por zero / ajustado ≤ 0**; estouro massivo gerando ajustado negativo seguro; seed e alternância de `rollover_ativo`.
- **Revisão e Atribuição para Casais (7 testes):** **migração** das colunas `status_revisao`/`atribuido_a` e default `REVISADO`; lançamento pendente atribuído entrando na fila; **filtragem isolada por usuário** (A não vê pendências de B); **conclusão da revisão** (recategoriza, salva nota, marca `REVISADO` e sai da fila); rejeição de subcategoria de outro pai (trava de hierarquia); página visível para todos os perfis.
- **Importação de Extratos (6 testes):** trava de conta obrigatória; **herança de classificação** em importações consecutivas; **preservação de lançamentos manuais** na mesma data; botão **Analisar** (mapeamento retroativo + beneficiário em branco); gravação de logs em `auditoria_sistema`; página registrada no menu.

---

### Como executar

```bash
pip install -r requirements.txt
streamlit run app.py            # aplicação
python -m pytest -q test_erp_core.py   # suíte de testes (135)
python emergency_reset.py       # recuperação de emergência (CLI)
```

> Pré-requisito: `.streamlit/secrets.toml` com `[initial_setup]` (admin) e `[smtp]` (envio do 2FA). Veja `.streamlit/secrets.toml.example`.
