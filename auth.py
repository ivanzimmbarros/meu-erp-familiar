# -*- coding: utf-8 -*-
"""
============================================================================
 CAMADA DE AUTENTICAÇÃO E SEGURANÇA — ERP FAMILIAR (auth.py)
============================================================================
Responsabilidades:
  - Hash e verificação de senha com PBKDF2-HMAC-SHA256 + salt (nativo, sem
    dependências externas de compilação).
  - Geração/envio de OTP (2FA) por SMTP.
  - Autenticação, criação de usuários e fluxo de recuperação de senha.

Não importa Streamlit. A configuração SMTP é recebida como parâmetro
(`smtp` dict), mantendo este módulo desacoplado da UI.
"""
import os
import hmac
import random
import hashlib
import smtplib
from email.mime.text import MIMEText

from database import db_query, db_execute, normalizar_texto, DuplicadoError

# ---------------------------------------------------------------------------
# PARÂMETROS DE HASH (PBKDF2)
# ---------------------------------------------------------------------------
PBKDF2_ALGO = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16


def hash_password(password: str, salt: bytes = None, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Gera um hash PBKDF2 no formato:  pbkdf2_sha256$<iter>$<salt_hex>$<hash_hex>"""
    if salt is None:
        salt = os.urandom(SALT_BYTES)
    if isinstance(salt, str):
        salt = bytes.fromhex(salt)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PBKDF2_ALGO}${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verifica a senha contra o hash armazenado.

    Suporta:
      - Formato PBKDF2 novo (pbkdf2_sha256$...).
      - Hash SHA-256 legado (64 caracteres hex, sem '$') para retrocompatibilidade
        com bases criadas antes desta migração — assim ninguém fica trancado fora.
    """
    if not stored:
        return False

    # Retrocompatibilidade: SHA-256 simples (formato antigo).
    if "$" not in stored:
        legado = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(legado, stored)

    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != PBKDF2_ALGO:
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def is_legacy_hash(stored: str) -> bool:
    """True se o hash armazenado ainda está no formato SHA-256 antigo."""
    return bool(stored) and "$" not in stored and len(stored) == 64


# ---------------------------------------------------------------------------
# OTP / 2FA
# ---------------------------------------------------------------------------
def gerar_otp() -> str:
    return str(random.randint(100000, 999999))


def gerar_senha_temporaria(tamanho: int = 10) -> str:
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(chars) for _ in range(tamanho))


def enviar_email(assunto: str, conteudo: str, destino: str, smtp: dict) -> bool:
    """Envia um e-mail simples via SMTP. Levanta exceção em caso de falha
    (a UI decide como exibir o erro)."""
    msg = MIMEText(conteudo)
    msg["Subject"] = assunto
    msg["From"] = smtp["user"]
    msg["To"] = destino
    with smtplib.SMTP(smtp["server"], smtp["port"]) as server:
        server.starttls()
        server.login(smtp["user"], smtp["password"])
        server.sendmail(smtp["user"], destino, msg.as_string())
    return True


# ---------------------------------------------------------------------------
# AUTENTICAÇÃO / GESTÃO DE CONTAS
# ---------------------------------------------------------------------------
def autenticar(username: str, password: str):
    """Retorna dict com dados do usuário se as credenciais forem válidas,
    senão None."""
    res = db_query(
        "SELECT email, perfil, nome_exibicao, password FROM usuarios WHERE username=?",
        (username,),
    )
    if not res:
        return None
    email, perfil, nome, stored = res[0]
    if verify_password(password, stored):
        return {"username": username, "email": email, "perfil": perfil, "nome": nome}
    return None


def seed_admin(username: str, password: str, email: str):
    """Cria o administrador mestre se ainda não existir (idempotente).

    A conta nasce com `force_reset=1`: a senha inicial DEVE ser trocada no
    primeiro login."""
    db_execute(
        "INSERT OR IGNORE INTO usuarios (username, password, nome_exibicao, email, perfil, force_reset) "
        "VALUES (?,?,?,?,'Administrador',1)",
        (username, hash_password(password), "Administrador Mestre", email),
    )


def username_em_uso(username: str) -> bool:
    """True se já existir um username equivalente sob normalização
    (case/acento-insensível). Evita logins duplicados como 'Joao' e 'joao'."""
    alvo = normalizar_texto(username)
    if not alvo:
        return False
    existentes = db_query("SELECT username FROM usuarios")
    return any(normalizar_texto(u[0]) == alvo for u in existentes)


def criar_usuario(username, password, nome, email, perfil="Utilizador", force_reset=1):
    """Cria um novo usuário. Levanta sqlite3.IntegrityError se o username já existir.

    Por política de segurança, TODO usuário recém-cadastrado nasce com
    `force_reset=1` (troca obrigatória da senha inicial no primeiro login).

    Bloqueia logins equivalentes (DuplicadoError) sob normalização, antes mesmo
    da restrição UNIQUE do banco — assim 'Joao' e 'joao' não coexistem."""
    username = (username or "").strip()
    if username_em_uso(username):
        raise DuplicadoError(
            f"Já existe um usuário com login equivalente a “{username}”."
        )
    db_execute(
        "INSERT INTO usuarios (username, password, nome_exibicao, email, perfil, force_reset) "
        "VALUES (?,?,?,?,?,?)",
        (username, hash_password(password), nome, email, perfil, force_reset),
    )


def precisa_trocar_senha(username: str) -> bool:
    res = db_query("SELECT force_reset FROM usuarios WHERE username=?", (username,))
    return bool(res and res[0][0] == 1)


def definir_nova_senha(username: str, nova_senha: str):
    """Define uma nova senha e zera a flag de troca obrigatória."""
    db_execute(
        "UPDATE usuarios SET password=?, force_reset=0 WHERE username=?",
        (hash_password(nova_senha), username),
    )


def iniciar_recuperacao(email: str):
    """Gera uma senha temporária para o e-mail informado, marca troca
    obrigatória e retorna a senha em texto (para envio). Retorna None se o
    e-mail não existir."""
    user = db_query("SELECT username FROM usuarios WHERE email=?", (email,))
    if not user:
        return None
    temp = gerar_senha_temporaria()
    db_execute(
        "UPDATE usuarios SET password=?, force_reset=1 WHERE email=?",
        (hash_password(temp), email),
    )
    return temp
