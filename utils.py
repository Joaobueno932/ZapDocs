"""
Funções auxiliares para o whatsapp2pdf.
"""

import os
import re
import unicodedata
from datetime import datetime

MESES_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"
}

DIAS_SEMANA_PT = {
    0: "Segunda-feira", 1: "Terça-feira", 2: "Quarta-feira",
    3: "Quinta-feira", 4: "Sexta-feira", 5: "Sábado", 6: "Domingo"
}

# Caracteres invisíveis/formatação que o WhatsApp injeta
CHARS_INVISIVEIS = '‎‏‪‫‬‭‮﻿'

# Extensões de mídia por tipo
EXTENSOES_IMAGEM  = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
EXTENSOES_VIDEO   = {'.mp4', '.avi', '.mov', '.mkv', '.3gp', '.webm'}
EXTENSOES_AUDIO   = {'.opus', '.mp3', '.ogg', '.m4a', '.aac', '.wav', '.oga'}
EXTENSOES_STICKER = {'.webp'}


def limpar_invisiveis(texto: str) -> str:
    """Remove caracteres de formatação invisíveis que o WhatsApp injeta."""
    return texto.strip(CHARS_INVISIVEIS).strip()


def formatar_data_pt(dt: datetime) -> str:
    """Retorna string no formato 'Segunda-feira, 3 de abril de 2024'."""
    dia_semana = DIAS_SEMANA_PT[dt.weekday()]
    mes = MESES_PT[dt.month]
    return f"{dia_semana}, {dt.day} de {mes} de {dt.year}"


def detectar_tipo_midia(nome_arquivo: str) -> str:
    """Retorna 'imagem', 'video', 'audio', 'sticker' ou 'documento'."""
    nome_lower = nome_arquivo.lower()
    ext = os.path.splitext(nome_arquivo)[1].lower()

    # Detecta por padrão no nome (formato dos arquivos do WhatsApp Android)
    if '-STICKER-' in nome_arquivo or 'sticker' in nome_lower:
        return 'sticker'
    if '-PHOTO-' in nome_arquivo:
        return 'imagem'
    if '-AUDIO-' in nome_arquivo or '-PTT-' in nome_arquivo:
        return 'audio'
    if '-VIDEO-' in nome_arquivo:
        return 'video'

    # Fallback por extensão
    if ext in EXTENSOES_STICKER:
        return 'sticker'
    if ext in EXTENSOES_IMAGEM:
        return 'imagem'
    if ext in EXTENSOES_VIDEO:
        return 'video'
    if ext in EXTENSOES_AUDIO:
        return 'audio'
    return 'documento'


# ── Padrões de detecção de mídia ──────────────────────────────────────────────

# Formato real Android BR atual:  ‎<anexado: 00000034-AUDIO-....opus>
_PADRAO_ANEXADO = re.compile(
    r'[' + CHARS_INVISIVEIS + r']*<anexado:\s*([^>]+)>',
    re.IGNORECASE
)

# Formato antigo / iOS / Windows:  <arquivo.ext (arquivo anexado)>
_PADRAO_PARENTESES = re.compile(
    r'[' + CHARS_INVISIVEIS + r']*<?([^<>\n]+?\.\w{2,5})>?\s*'
    r'\((?:arquivo anexado|file attached)\)',
    re.IGNORECASE
)

# Formato sem colchetes (algumas versões):  arquivo.ext (arquivo anexado)
_PADRAO_SEM_COLCHETES = re.compile(
    r'[' + CHARS_INVISIVEIS + r']*([^\s\n<>]+\.\w{2,5})\s*'
    r'\((?:arquivo anexado|file attached)\)',
    re.IGNORECASE
)

# Formato iOS: <attached: arquivo.ext>
_PADRAO_ATTACHED = re.compile(
    r'[' + CHARS_INVISIVEIS + r']*<attached:\s*([^>]+)>',
    re.IGNORECASE
)


def extrair_nome_midia(texto: str):
    """
    Extrai o nome do arquivo de mídia do texto da mensagem.
    Suporta todos os formatos conhecidos do WhatsApp (Android BR, iOS, legado).
    Retorna (nome_arquivo, True) se encontrado, ou (None, False).
    """
    for padrao in (_PADRAO_ANEXADO, _PADRAO_ATTACHED,
                   _PADRAO_PARENTESES, _PADRAO_SEM_COLCHETES):
        m = padrao.search(texto)
        if m:
            nome = limpar_invisiveis(m.group(1))
            if nome:
                return nome, True
    return None, False


def is_mensagem_apagada(texto: str) -> bool:
    """Detecta mensagens apagadas."""
    frases = [
        "você apagou esta mensagem",
        "esta mensagem foi apagada",
        "you deleted this message",
        "this message was deleted",
    ]
    lower = limpar_invisiveis(texto).lower()
    return any(lower == f or lower.startswith(f) for f in frases)


def detectar_formato_data(linha: str) -> str:
    """
    Detecta se o arquivo usa DD/MM/AAAA ou MM/DD/AAAA.
    Retorna 'dmy' ou 'mdy'.
    """
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', linha)
    if m:
        primeiro = int(m.group(1))
        segundo  = int(m.group(2))
        if primeiro > 12:
            return 'dmy'
        if segundo > 12:
            return 'mdy'
    return 'dmy'


def _normalizar_nome(s: str) -> str:
    """
    Normaliza um nome para comparação: remove invisíveis, acentos,
    converte para minúsculas e colapsa espaços múltiplos.
    Assim 'Joao Lucas' == 'João Lucas' == 'JOÃO LUCAS'.
    """
    s = limpar_invisiveis(s)
    # Decomposição NFD: separa letra base do acento; remove os acentos
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', s).strip().lower()


def nomes_correspondem(nome_chat: str, nome_usuario: str) -> bool:
    """
    Compara nomes de forma flexível:
    - Ignora maiúsculas/minúsculas
    - Ignora acentos (João == Joao)
    - Ignora caracteres invisíveis do WhatsApp
    - Aceita correspondência parcial (o nome digitado está contido no nome do chat)
    """
    nc = _normalizar_nome(nome_chat)
    nu = _normalizar_nome(nome_usuario)
    if not nu:
        return False
    return nc == nu or nu in nc


def formatar_horario(dt: datetime) -> str:
    """Retorna horário no formato HH:MM."""
    return dt.strftime('%H:%M')
