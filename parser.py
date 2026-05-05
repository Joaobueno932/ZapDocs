"""
Parsing do arquivo _chat.txt exportado pelo WhatsApp.
Suporta os dois formatos principais de data/hora e todas as variantes regionais.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from utils import (
    detectar_formato_data,
    extrair_nome_midia,
    is_mensagem_apagada,
    detectar_tipo_midia,
    limpar_invisiveis,
    CHARS_INVISIVEIS,
)

# ─── Modelos ─────────────────────────────────────────────────────────────────

@dataclass
class Midia:
    nome_arquivo: str
    tipo: str          # 'imagem', 'video', 'audio', 'sticker', 'documento'
    dados: bytes       = field(default=None, repr=False)
    caminho: str       = field(default=None, repr=False)  # path no disco após extração


@dataclass
class Mensagem:
    timestamp: datetime
    remetente: Optional[str]   # None = mensagem de sistema
    texto: str
    apagada: bool = False
    midia: Optional[Midia] = None

    @property
    def tipo(self) -> str:
        if self.remetente is None:
            return 'sistema'
        if self.midia:
            return 'midia'
        return 'texto'


# ─── Expressões regulares ─────────────────────────────────────────────────────

_INV = '[' + CHARS_INVISIVEIS + ']*'   # zero ou mais chars invisíveis

# Formato A: [DD/MM/AAAA, HH:MM:SS] Remetente: texto
# Linhas podem começar com caractere invisível (‎)
REGEX_A = re.compile(
    _INV + r'\[(\d{1,2}/\d{1,2}/\d{2,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?)\]\s+'
    r'([^:\[\]]+?):\s+(.*)',
    re.DOTALL
)
REGEX_A_SYS = re.compile(
    _INV + r'\[(\d{1,2}/\d{1,2}/\d{2,4}),?\s+(\d{1,2}:\d{2}(?::\d{2})?)\]\s+(.*)',
    re.DOTALL
)

# Formato B: DD/MM/AAAA HH:MM - Remetente: texto
REGEX_B = re.compile(
    _INV + r'(\d{1,2}/\d{1,2}/\d{2,4}),?\s+(\d{1,2}:\d{2})\s+-\s+'
    r'([^:\-\n]+?):\s+(.*)',
    re.DOTALL
)
REGEX_B_SYS = re.compile(
    _INV + r'(\d{1,2}/\d{1,2}/\d{2,4}),?\s+(\d{1,2}:\d{2})\s+-\s+(.*)',
    re.DOTALL
)

# Detecta se uma linha inicia uma mensagem (qualquer formato)
REGEX_INICIO = re.compile(
    _INV + r'\[?\d{1,2}/\d{1,2}/\d{2,4}'
)


def _parse_datetime(data_str: str, hora_str: str, formato_data: str) -> datetime:
    """Converte strings de data e hora em objeto datetime."""
    partes = data_str.split('/')
    if len(partes) != 3:
        raise ValueError(f"Data inválida: {data_str}")

    if formato_data == 'dmy':
        dia, mes, ano = partes
    else:
        mes, dia, ano = partes

    dia, mes, ano = int(dia), int(mes), int(ano)
    if ano < 100:
        ano += 2000

    partes_hora = hora_str.split(':')
    hora   = int(partes_hora[0])
    minuto = int(partes_hora[1])
    segundo = int(partes_hora[2]) if len(partes_hora) > 2 else 0

    return datetime(ano, mes, dia, hora, minuto, segundo)


def _detectar_formato(linhas: list[str]) -> str:
    """Detecta o formato de data usado no arquivo."""
    for linha in linhas[:50]:
        if REGEX_INICIO.match(linha):
            return detectar_formato_data(linha)
    return 'dmy'


def _parse_linha(linha: str, formato_data: str):
    """
    Tenta interpretar uma linha como início de mensagem.
    Retorna (timestamp, remetente, texto_inicial) ou None.
    """
    # Formato A com remetente
    m = REGEX_A.match(linha)
    if m:
        try:
            ts  = _parse_datetime(m.group(1), m.group(2), formato_data)
            rem = limpar_invisiveis(m.group(3))
            return ts, rem, m.group(4)
        except Exception:
            pass

    # Formato B com remetente
    m = REGEX_B.match(linha)
    if m:
        try:
            ts  = _parse_datetime(m.group(1), m.group(2), formato_data)
            rem = limpar_invisiveis(m.group(3))
            return ts, rem, m.group(4)
        except Exception:
            pass

    # Formato A sem remetente (mensagem de sistema)
    m = REGEX_A_SYS.match(linha)
    if m:
        try:
            ts = _parse_datetime(m.group(1), m.group(2), formato_data)
            return ts, None, m.group(3)
        except Exception:
            pass

    # Formato B sem remetente
    m = REGEX_B_SYS.match(linha)
    if m:
        try:
            ts = _parse_datetime(m.group(1), m.group(2), formato_data)
            return ts, None, m.group(3)
        except Exception:
            pass

    return None


def parsear_chat(conteudo: str, arquivos_zip: dict = None) -> list[Mensagem]:
    """
    Recebe o conteúdo do _chat.txt e um dict {nome_base: bytes} com os arquivos do ZIP.
    Retorna lista de objetos Mensagem.
    """
    if arquivos_zip is None:
        arquivos_zip = {}

    # Mapa case-insensitive para lookup de arquivos
    arq_lower = {k.lower(): (k, v) for k, v in arquivos_zip.items()}

    conteudo = conteudo.lstrip('﻿')   # Remove BOM
    linhas = conteudo.splitlines()

    formato_data = _detectar_formato(linhas)

    mensagens: list[Mensagem] = []
    ts_atual   = None
    rem_atual  = None
    texto_atual: list[str] = []

    def _finalizar():
        nonlocal ts_atual, rem_atual, texto_atual
        if ts_atual is None:
            return

        texto = '\n'.join(texto_atual).strip()
        if not texto:
            ts_atual = None
            return

        apagada = is_mensagem_apagada(texto)
        midia   = None

        # Detecta referência a mídia
        nome_arq, encontrado = extrair_nome_midia(texto)
        if encontrado and nome_arq:
            tipo_midia = detectar_tipo_midia(nome_arq)

            # Busca o arquivo no ZIP (case-insensitive)
            dados = arquivos_zip.get(nome_arq)
            if dados is None:
                chave = arq_lower.get(nome_arq.lower())
                if chave:
                    dados = chave[1]

            midia = Midia(nome_arquivo=nome_arq, tipo=tipo_midia, dados=dados)

            # Remove a marcação de mídia do texto, preserva legenda se houver
            texto_limpo = re.sub(
                r'[' + CHARS_INVISIVEIS + r']*<anexado:[^>]+>',
                '', texto, flags=re.IGNORECASE
            )
            texto_limpo = re.sub(
                r'[' + CHARS_INVISIVEIS + r']*<?[^<>\n]*?\.\w{2,5}>?\s*'
                r'\((?:arquivo anexado|file attached)\)',
                '', texto_limpo, flags=re.IGNORECASE
            )
            texto_limpo = re.sub(
                r'[' + CHARS_INVISIVEIS + r']*<attached:[^>]+>',
                '', texto_limpo, flags=re.IGNORECASE
            )
            texto = texto_limpo.strip()

        msg = Mensagem(
            timestamp=ts_atual,
            remetente=rem_atual,
            texto=texto,
            apagada=apagada,
            midia=midia,
        )
        mensagens.append(msg)
        ts_atual = rem_atual = None
        texto_atual = []

    for linha in linhas:
        resultado = _parse_linha(linha, formato_data)
        if resultado is not None:
            _finalizar()
            ts_atual, rem_atual, primeira_linha = resultado
            texto_atual = [primeira_linha]
        else:
            if ts_atual is not None:
                texto_atual.append(linha)

    _finalizar()
    return mensagens
