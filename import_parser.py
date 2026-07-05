# -*- coding: utf-8 -*-
"""
============================================================================
 PARSER DE EXTRATOS — ERP FAMILIAR (import_parser.py)
============================================================================
Lógica pura de leitura de arquivos OFX e CSV para o módulo de importação.

Não importa Streamlit. Retorna listas de dicts padronizados:
  {raw_descricao, data, valor_eur, natureza}
"""
import io
import re
from datetime import datetime
from typing import Optional

import pandas as pd


def _parse_data_bruta(valor) -> Optional[str]:
    """Converte diversos formatos de data para YYYY-MM-DD."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d")
    s = str(valor).strip()
    if not s:
        return None
    # OFX compacto: YYYYMMDD ou YYYYMMDDHHMMSS
    if re.fullmatch(r"\d{8}(\d{6})?", s):
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _natureza_de_valor(valor: float) -> str:
    """Despesa para valores negativos; Receita para positivos."""
    return "Receita" if valor >= 0 else "Despesa"


def _normalizar_valor(valor) -> Optional[float]:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, (int, float)):
        return abs(float(valor))
    s = str(valor).strip().replace("€", "").replace("EUR", "").strip()
    # Formato europeu: 1.234,56
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return abs(float(s))
    except ValueError:
        return None


def _achar_coluna(df, candidatos):
    """Localiza coluna por nomes alternativos (case-insensitive)."""
    mapa = {c.lower().strip(): c for c in df.columns}
    for cand in candidatos:
        if cand.lower() in mapa:
            return mapa[cand.lower()]
    return None


def parse_csv(data_bytes: bytes) -> list[dict]:
    """Lê CSV bancário e devolve linhas normalizadas para staging."""
    text = data_bytes.decode("utf-8-sig", errors="replace")
    sep = ";" if text.count(";") > text.count(",") else ","
    df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False)
    if df.empty:
        raise ValueError("O arquivo CSV está vazio.")

    col_data = _achar_coluna(df, ("data", "date", "dt", "data_movimento", "data movimento"))
    col_desc = _achar_coluna(df, (
        "descricao", "descrição", "description", "memo", "historico",
        "histórico", "detalhe", "lancamento", "lançamento",
    ))
    col_valor = _achar_coluna(df, (
        "valor", "valor_eur", "amount", "montante", "value", "importe",
    ))
    col_tipo = _achar_coluna(df, ("tipo", "natureza", "type", "debito_credito"))

    if not col_data or not col_desc or not col_valor:
        raise ValueError(
            "CSV inválido: são necessárias colunas de data, descrição e valor."
        )

    linhas = []
    for _, row in df.iterrows():
        data = _parse_data_bruta(row[col_data])
        desc = str(row[col_desc]).strip()
        raw_val = row[col_valor]
        if not data or not desc:
            continue
        valor = _normalizar_valor(raw_val)
        if valor is None or valor <= 0:
            continue
        # Natureza explícita na coluna tipo, senão infere pelo sinal.
        natureza = None
        if col_tipo:
            t = str(row[col_tipo]).strip().lower()
            if t in ("receita", "credito", "crédito", "c", "credit"):
                natureza = "Receita"
            elif t in ("despesa", "debito", "débito", "d", "debit"):
                natureza = "Despesa"
        if natureza is None:
            try:
                v_signed = float(str(raw_val).replace(",", ".").replace("€", "").strip())
            except ValueError:
                v_signed = valor
            natureza = _natureza_de_valor(v_signed)
        linhas.append({
            "raw_descricao": desc,
            "data": data,
            "valor_eur": valor,
            "natureza": natureza,
        })
    if not linhas:
        raise ValueError("Nenhuma transação válida encontrada no CSV.")
    return linhas


def parse_ofx(data_bytes: bytes) -> list[dict]:
    """Lê arquivo OFX (SGML/XML) e devolve linhas normalizadas."""
    text = data_bytes.decode("latin-1", errors="replace")
    blocos = re.findall(r"<STMTTRN>.*?</STMTTRN>", text, re.DOTALL | re.IGNORECASE)
    if not blocos:
        raise ValueError("Nenhuma transação OFX (<STMTTRN>) encontrada no arquivo.")

    linhas = []
    for bloco in blocos:
        dt_m = re.search(r"<DTPOSTED>(\d{8})", bloco, re.IGNORECASE)
        amt_m = re.search(r"<TRNAMT>([-\d.,]+)", bloco, re.IGNORECASE)
        memo_m = re.search(r"<MEMO>([^<\r\n]+)", bloco, re.IGNORECASE)
        name_m = re.search(r"<NAME>([^<\r\n]+)", bloco, re.IGNORECASE)
        if not dt_m or not amt_m:
            continue
        data = _parse_data_bruta(dt_m.group(1))
        try:
            v_signed = float(amt_m.group(1).replace(",", "."))
        except ValueError:
            continue
        valor = abs(v_signed)
        if valor <= 0 or not data:
            continue
        desc = (memo_m.group(1).strip() if memo_m else "") or (
            name_m.group(1).strip() if name_m else ""
        )
        if not desc:
            desc = "Transação OFX"
        linhas.append({
            "raw_descricao": desc,
            "data": data,
            "valor_eur": valor,
            "natureza": _natureza_de_valor(v_signed),
        })
    if not linhas:
        raise ValueError("Nenhuma transação válida encontrada no OFX.")
    return linhas


def parse_arquivo_extrato(nome_arquivo: str, data_bytes: bytes) -> list[dict]:
    """Despacha para o parser correto conforme a extensão do arquivo."""
    nome = (nome_arquivo or "").lower()
    if nome.endswith(".csv"):
        return parse_csv(data_bytes)
    if nome.endswith(".ofx"):
        return parse_ofx(data_bytes)
    raise ValueError("Formato não suportado. Use arquivos .CSV ou .OFX.")
