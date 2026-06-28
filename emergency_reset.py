"""
╔══════════════════════════════════════════════════════════════╗
║         ERP FAMILIAR — FERRAMENTA DE RECUPERAÇÃO            ║
║               emergency_reset.py  (v1.0)                    ║
║                                                              ║
║  USO: python emergency_reset.py                              ║
║  REQUISITO: Executar na mesma pasta onde está finance.db     ║
╚══════════════════════════════════════════════════════════════╝
"""
import sqlite3, getpass, sys, os

# Usa o MESMO formato de hash (PBKDF2) do sistema principal, garantindo que
# senhas redefinidas por esta ferramenta sejam aceitas no login do app.
from auth import hash_password

DB_PATH = "finance.db"

def conectar():
    if not os.path.exists(DB_PATH):
        print(f"\n❌ ERRO: Arquivo '{DB_PATH}' não encontrado.")
        print("   Execute este script na mesma pasta do banco de dados.")
        sys.exit(1)
    return sqlite3.connect(DB_PATH)

def listar_usuarios(conn):
    rows = conn.execute("SELECT id, username, nome_exibicao, email, perfil FROM usuarios").fetchall()
    if not rows:
        print("\n⚠️  Nenhum usuário encontrado no banco.")
        return []
    print("\n┌─────────────────────────────────────────────────────────────┐")
    print("│                   USUÁRIOS CADASTRADOS                      │")
    print("├────┬──────────────────┬──────────────────┬──────────────────┤")
    print("│ ID │ Login (username) │ Nome de Exibição │ Perfil           │")
    print("├────┼──────────────────┼──────────────────┼──────────────────┤")
    for r in rows:
        print(f"│ {r[0]:<2} │ {r[1]:<16} │ {r[2]:<16} │ {r[4]:<16} │")
    print("└────┴──────────────────┴──────────────────┴──────────────────┘")
    return rows

def redefinir_senha(conn):
    rows = listar_usuarios(conn)
    if not rows:
        return

    print("\n[REDEFINIR SENHA]")
    username = input("Digite o login (username) do utilizador: ").strip()

    user = conn.execute("SELECT id, nome_exibicao FROM usuarios WHERE username=?", (username,)).fetchone()
    if not user:
        print(f"\n❌ Utilizador '{username}' não encontrado.")
        return

    print(f"\n✅ Utilizador encontrado: {user[1]}")
    nova_senha = getpass.getpass("Nova senha (não será exibida ao digitar): ")
    confirmar  = getpass.getpass("Confirme a senha: ")

    if nova_senha != confirmar:
        print("\n❌ As senhas não coincidem. Operação cancelada.")
        return
    if len(nova_senha) < 6:
        print("\n❌ Senha muito curta (mínimo 6 caracteres).")
        return

    pwd_hash = hash_password(nova_senha)
    conn.execute(
        "UPDATE usuarios SET password=?, force_reset=0 WHERE username=?",
        (pwd_hash, username)
    )
    conn.commit()
    print(f"\n✅ Senha de '{username}' redefinida com sucesso!")
    print("   force_reset foi zerado — o utilizador não será forçado a trocar a senha.")

def criar_admin_emergencia(conn):
    print("\n[CRIAR ADMIN DE EMERGÊNCIA]")
    print("⚠️  Isso criará/substituirá um utilizador 'admin_emergencia'.")
    confirmar = input("Confirma? (s/N): ").strip().lower()
    if confirmar != 's':
        print("Operação cancelada.")
        return

    senha = getpass.getpass("Senha para o admin de emergência: ")
    email = input("E-mail (pode ser fictício, ex: admin@local.dev): ").strip()
    pwd_hash = hash_password(senha)

    # Tenta INSERT, se já existe faz UPDATE
    existing = conn.execute("SELECT id FROM usuarios WHERE username='admin_emergencia'").fetchone()
    if existing:
        conn.execute(
            "UPDATE usuarios SET password=?, email=?, perfil='Administrador', force_reset=0 WHERE username='admin_emergencia'",
            (pwd_hash, email)
        )
        print("\n✅ Conta 'admin_emergencia' atualizada.")
    else:
        conn.execute(
            "INSERT INTO usuarios (username, password, nome_exibicao, email, perfil, force_reset) VALUES (?,?,?,?,?,?)",
            ('admin_emergencia', pwd_hash, 'Admin Emergência', email, 'Administrador', 0)
        )
        print("\n✅ Conta 'admin_emergencia' criada.")

    conn.commit()
    print("   Login: admin_emergencia")
    print("   ⚠️  Acesse o sistema e depois remova esta conta na aba Gestão Geral.")

def menu():
    conn = conectar()
    print("\n╔══════════════════════════════════════════════╗")
    print("║     ERP Familiar — Recuperação de Emergência ║")
    print("╚══════════════════════════════════════════════╝")

    while True:
        print("\n┌─ MENU ─────────────────────────────────────┐")
        print("│  1. Listar todos os utilizadores            │")
        print("│  2. Redefinir senha de um utilizador        │")
        print("│  3. Criar conta Admin de emergência         │")
        print("│  4. Sair                                    │")
        print("└─────────────────────────────────────────────┘")

        opcao = input("Escolha (1-4): ").strip()

        if opcao == "1":
            listar_usuarios(conn)
        elif opcao == "2":
            redefinir_senha(conn)
        elif opcao == "3":
            criar_admin_emergencia(conn)
        elif opcao == "4":
            print("\n👋 Encerrando.\n")
            conn.close()
            sys.exit(0)
        else:
            print("❌ Opção inválida.")

if __name__ == "__main__":
    menu()
