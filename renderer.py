"""
Geração do PDF com layout visual estilo WhatsApp usando ReportLab.
"""

import io
import os
from datetime import datetime, date
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

pt = 1  # ReportLab usa pontos como unidade nativa; 1pt = 1 unidade
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from parser import Mensagem, Midia
from utils import formatar_data_pt, formatar_horario, detectar_tipo_midia, nomes_correspondem

# ─── Cores ────────────────────────────────────────────────────────────────────

COR_FUNDO_PAGINA   = colors.HexColor('#E5DDD5')
COR_BALAO_EU       = colors.HexColor('#DCF8C6')
COR_BALAO_OUTRO    = colors.HexColor('#FFFFFF')
COR_HORA           = colors.HexColor('#999999')
COR_SEPARADOR_BG   = colors.HexColor('#E1F0D8')
COR_SEPARADOR_TEXTO= colors.HexColor('#6B6B6B')
COR_SISTEMA_TEXTO  = colors.HexColor('#6B6B6B')
COR_SISTEMA_BG     = colors.HexColor('#FFFFFFCC')  # branco semi-transparente
COR_APAGADA        = colors.HexColor('#AAAAAA')
COR_NOME_REMETENTE = [
    colors.HexColor('#E91E63'), colors.HexColor('#9C27B0'),
    colors.HexColor('#2196F3'), colors.HexColor('#009688'),
    colors.HexColor('#FF5722'), colors.HexColor('#795548'),
    colors.HexColor('#607D8B'), colors.HexColor('#3F51B5'),
]

# ─── Medidas ──────────────────────────────────────────────────────────────────

MARGEM_LATERAL    = 15 * pt
MARGEM_TOPO       = 60 * pt   # espaço para o cabeçalho
MARGEM_RODAPE     = 20 * pt
PADDING_H         = 8 * pt    # padding horizontal interno do balão
PADDING_V         = 5 * pt    # padding vertical interno do balão
ESPACO_ENTRE_MSGS = 4 * pt
LARGURA_MAX_BALAO = 0.75      # fração da largura útil
ALTURA_MAX_IMAGEM = 200 * pt
RAIO_CANTO        = 8 * pt
FONTE_NORMAL      = 'Helvetica'
FONTE_NEGRITO     = 'Helvetica-Bold'
FONTE_ITALICO     = 'Helvetica-Oblique'
TAMANHO_TEXTO     = 10 * pt
TAMANHO_HORA      = 8 * pt
TAMANHO_NOME      = 9 * pt
TAMANHO_SISTEMA   = 9 * pt
ALTURA_CABECALHO  = 40 * pt


# ─── Helpers de cor de nome ───────────────────────────────────────────────────

_cache_cor_nome: dict[str, object] = {}

def _cor_para_nome(nome: str):
    if nome not in _cache_cor_nome:
        idx = hash(nome) % len(COR_NOME_REMETENTE)
        _cache_cor_nome[nome] = COR_NOME_REMETENTE[idx]
    return _cache_cor_nome[nome]


# ─── Wrapper de texto ─────────────────────────────────────────────────────────

def _quebrar_texto(c: rl_canvas.Canvas, texto: str, fonte: str, tamanho: float,
                   largura_max: float) -> list[str]:
    """Quebra o texto em linhas que cabem dentro de largura_max."""
    linhas_entrada = texto.split('\n')
    linhas_saida = []
    for linha_orig in linhas_entrada:
        palavras = linha_orig.split(' ')
        linha_atual = ''
        for palavra in palavras:
            candidato = (linha_atual + ' ' + palavra).strip() if linha_atual else palavra
            w = c.stringWidth(candidato, fonte, tamanho)
            if w <= largura_max:
                linha_atual = candidato
            else:
                if linha_atual:
                    linhas_saida.append(linha_atual)
                # Palavra maior que a largura: forçar quebra por caractere
                while c.stringWidth(palavra, fonte, tamanho) > largura_max:
                    for i in range(len(palavra), 0, -1):
                        if c.stringWidth(palavra[:i], fonte, tamanho) <= largura_max:
                            linhas_saida.append(palavra[:i])
                            palavra = palavra[i:]
                            break
                linha_atual = palavra
        if linha_atual:
            linhas_saida.append(linha_atual)
    return linhas_saida if linhas_saida else ['']


def _altura_texto(linhas: list[str], tamanho: float, espaco_linha: float = 1.2) -> float:
    return len(linhas) * tamanho * espaco_linha


# ─── Classe principal do renderizador ────────────────────────────────────────

class RendererPDF:
    def __init__(self, caminho_saida: str, nome_conversa: str, eu: Optional[str] = None,
                 media_url_base: Optional[str] = None):
        self.caminho_saida  = caminho_saida
        self.nome_conversa  = nome_conversa
        self.eu             = eu
        self.media_url_base = media_url_base  # se definido, usa links HTTP em vez de file://

        self.largura_pagina, self.altura_pagina = A4
        self.largura_util = self.largura_pagina - 2 * MARGEM_LATERAL
        self.largura_max_balao = self.largura_util * LARGURA_MAX_BALAO

        self.c = rl_canvas.Canvas(caminho_saida, pagesize=A4)
        self.y = self.altura_pagina - MARGEM_TOPO
        self.pagina_atual = 1
        self.data_ultima_msg: Optional[date] = None
        self.periodo_inicio: Optional[datetime] = None
        self.periodo_fim: Optional[datetime] = None

        self._desenhar_cabecalho()
        self._desenhar_fundo()

    # ─── Fundo e cabeçalho ───────────────────────────────────────────────────

    def _desenhar_fundo(self):
        """Preenche o fundo da página atual."""
        self.c.setFillColor(COR_FUNDO_PAGINA)
        self.c.rect(0, 0, self.largura_pagina, self.altura_pagina, fill=1, stroke=0)

    def _desenhar_cabecalho(self):
        """Desenha cabeçalho fixo no topo de cada página."""
        self.c.setFillColor(colors.HexColor('#075E54'))
        self.c.rect(0, self.altura_pagina - ALTURA_CABECALHO,
                    self.largura_pagina, ALTURA_CABECALHO, fill=1, stroke=0)

        self.c.setFillColor(colors.white)
        self.c.setFont(FONTE_NEGRITO, 13)
        self.c.drawString(MARGEM_LATERAL, self.altura_pagina - 25,
                          self.nome_conversa)
        self.c.setFont(FONTE_NORMAL, 8)
        self.c.drawString(MARGEM_LATERAL, self.altura_pagina - 38,
                          f'Página {self.pagina_atual}')

    def _nova_pagina(self):
        """Finaliza a página atual e inicia uma nova."""
        self.c.showPage()
        self.pagina_atual += 1
        self.y = self.altura_pagina - MARGEM_TOPO
        self._desenhar_fundo()
        self._desenhar_cabecalho()

    def _garantir_espaco(self, altura_necessaria: float):
        """Garante que há espaço suficiente na página; caso contrário, vira a página."""
        if self.y - altura_necessaria < MARGEM_RODAPE:
            self._nova_pagina()

    # ─── Separador de data ───────────────────────────────────────────────────

    def _desenhar_separador_data(self, dt: datetime):
        texto = formatar_data_pt(dt)
        largura_texto = self.c.stringWidth(texto, FONTE_NORMAL, TAMANHO_SISTEMA)
        padding = 10 * pt
        largura_caixa = largura_texto + 2 * padding
        altura_caixa = TAMANHO_SISTEMA + 2 * padding * 0.6

        self._garantir_espaco(altura_caixa + ESPACO_ENTRE_MSGS * 2)

        x_caixa = (self.largura_pagina - largura_caixa) / 2
        y_topo = self.y

        self.c.setFillColor(COR_SEPARADOR_BG)
        self.c.roundRect(x_caixa, y_topo - altura_caixa, largura_caixa,
                         altura_caixa, 8, fill=1, stroke=0)

        self.c.setFillColor(COR_SEPARADOR_TEXTO)
        self.c.setFont(FONTE_NORMAL, TAMANHO_SISTEMA)
        self.c.drawCentredString(self.largura_pagina / 2,
                                 y_topo - altura_caixa + padding * 0.5,
                                 texto)

        self.y -= altura_caixa + ESPACO_ENTRE_MSGS * 2

    # ─── Mensagem de sistema ─────────────────────────────────────────────────

    def _desenhar_mensagem_sistema(self, msg: Mensagem):
        texto = msg.texto.strip()
        if not texto:
            return

        largura_max = self.largura_util * 0.8
        linhas = _quebrar_texto(self.c, texto, FONTE_NORMAL, TAMANHO_SISTEMA, largura_max)
        altura_texto = _altura_texto(linhas, TAMANHO_SISTEMA)
        padding = 6 * pt
        largura_caixa = min(
            max(self.c.stringWidth(l, FONTE_NORMAL, TAMANHO_SISTEMA) for l in linhas)
            + 2 * padding,
            largura_max + 2 * padding
        )
        altura_caixa = altura_texto + 2 * padding

        self._garantir_espaco(altura_caixa + ESPACO_ENTRE_MSGS)

        x_caixa = (self.largura_pagina - largura_caixa) / 2
        y_topo = self.y

        self.c.setFillColor(COR_SISTEMA_BG)
        self.c.roundRect(x_caixa, y_topo - altura_caixa, largura_caixa,
                         altura_caixa, 6, fill=1, stroke=0)

        self.c.setFillColor(COR_SISTEMA_TEXTO)
        self.c.setFont(FONTE_NORMAL, TAMANHO_SISTEMA)
        espaco_linha = TAMANHO_SISTEMA * 1.2
        y_texto = y_topo - padding - TAMANHO_SISTEMA
        for linha in linhas:
            self.c.drawCentredString(self.largura_pagina / 2, y_texto, linha)
            y_texto -= espaco_linha

        self.y -= altura_caixa + ESPACO_ENTRE_MSGS

    # ─── Balão de mensagem ───────────────────────────────────────────────────

    def _eh_meu(self, remetente: str) -> bool:
        if self.eu is None:
            return False
        return nomes_correspondem(remetente, self.eu)

    # ─── Helpers visuais para mídia ──────────────────────────────────────────

    def _desenhar_play_icon(self, cx: float, cy: float, raio: float, cor_circulo,
                             cor_triangulo=None):
        """Círculo preenchido com triângulo de play."""
        if cor_triangulo is None:
            cor_triangulo = colors.white
        self.c.setFillColor(cor_circulo)
        self.c.setStrokeColor(cor_circulo)
        self.c.circle(cx, cy, raio, fill=1, stroke=0)
        off = raio * 0.12   # compensa peso visual do triângulo
        tam = raio * 0.45
        self.c.setFillColor(cor_triangulo)
        self.c.setStrokeColor(cor_triangulo)
        p = self.c.beginPath()
        p.moveTo(cx - tam + off,        cy + tam * 1.1)
        p.lineTo(cx - tam + off,        cy - tam * 1.1)
        p.lineTo(cx + tam * 1.1 + off,  cy)
        p.close()
        self.c.drawPath(p, fill=1, stroke=0)

    def _desenhar_waveform(self, x0: float, y_centro: float, largura: float,
                            nome_arquivo: str, n_barras: int = 22):
        """Barras de waveform com alturas determinísticas baseadas no nome do arquivo."""
        seed = sum(ord(c) * (i + 1) for i, c in enumerate(nome_arquivo[:20]))
        alturas = []
        v = seed
        for _ in range(n_barras):
            v = (v * 1103515245 + 12345) & 0x7fffffff
            alturas.append(3 + (v % 9))   # 3..11 pt de altura
        espaco = largura / n_barras
        self.c.setFillColor(colors.HexColor('#8BC4C0'))
        for i, h in enumerate(alturas):
            x = x0 + i * espaco
            self.c.roundRect(x, y_centro - h / 2, espaco * 0.65, h, 1, fill=1, stroke=0)

    def _link_arquivo(self, caminho: str, x1: float, y1: float, x2: float, y2: float):
        """Cria anotação clicável. Usa link HTTP quando media_url_base está definido."""
        if not caminho:
            return
        if self.media_url_base:
            filename = os.path.basename(caminho)
            url = self.media_url_base + filename
        else:
            if not os.path.exists(caminho):
                return
            url = 'file:///' + caminho.replace('\\', '/')
        self.c.linkURL(url, (x1, y1, x2, y2), relative=0)

    def _calcular_largura_balao(self, linhas_texto: list[str],
                                 largura_nome: float = 0,
                                 largura_hora: float = 0,
                                 tem_imagem: bool = False,
                                 largura_imagem: float = 0) -> float:
        """Calcula a largura ideal do balão dado seu conteúdo."""
        max_linha = max(
            (self.c.stringWidth(l, FONTE_NORMAL, TAMANHO_TEXTO) for l in linhas_texto),
            default=0
        )
        # Rodapé: hora + check duplo
        largura_rodape = largura_hora + 20 * pt

        largura_conteudo = max(max_linha, largura_nome, largura_rodape)

        if tem_imagem:
            largura_conteudo = max(largura_conteudo, largura_imagem)

        return min(largura_conteudo + 2 * PADDING_H, self.largura_max_balao)

    def _desenhar_balao(self, msg: Mensagem, eh_grupo: bool = False):
        """Renderiza um balão de mensagem, roteando para o visual adequado."""
        tipo_midia = msg.midia.tipo if msg.midia else None

        if tipo_midia == 'audio':
            self._balao_audio(msg, eh_grupo)
        elif tipo_midia == 'video':
            self._balao_video(msg, eh_grupo)
        else:
            self._balao_generico(msg, eh_grupo)

    # ── Balão genérico (texto, imagem, documento, sticker) ───────────────────

    def _balao_generico(self, msg: Mensagem, eh_grupo: bool):
        meu = self._eh_meu(msg.remetente) if msg.remetente else False
        cor_fundo = COR_BALAO_EU if meu else COR_BALAO_OUTRO

        texto = msg.texto or ''
        fonte_texto = FONTE_ITALICO if msg.apagada else FONTE_NORMAL
        cor_texto   = COR_APAGADA if msg.apagada else colors.black

        # Rótulo para mídia sem preview visual
        texto_midia = ''
        if msg.midia and msg.midia.tipo not in ('imagem', 'sticker'):
            texto_midia = '[ Documento ]  ' + msg.midia.nome_arquivo

        largura_interna = self.largura_max_balao - 2 * PADDING_H
        linhas_texto = _quebrar_texto(self.c, texto, fonte_texto, TAMANHO_TEXTO,
                                      largura_interna) if texto else []
        linhas_midia = _quebrar_texto(self.c, texto_midia, FONTE_ITALICO, TAMANHO_TEXTO,
                                      largura_interna) if texto_midia else []

        hora_str = formatar_horario(msg.timestamp)
        if meu:
            hora_str += '  vv'
        largura_hora = self.c.stringWidth(hora_str, FONTE_NORMAL, TAMANHO_HORA)

        nome_str   = ''
        largura_nome = 0
        if eh_grupo and not meu and msg.remetente:
            nome_str   = msg.remetente
            largura_nome = self.c.stringWidth(nome_str, FONTE_NEGRITO, TAMANHO_NOME)

        # Imagem / sticker embutido
        img_reader  = None
        img_largura = 0
        img_altura  = 0
        if msg.midia and msg.midia.tipo in ('imagem', 'sticker') and msg.midia.dados:
            try:
                from PIL import Image as PILImage
                pil = PILImage.open(io.BytesIO(msg.midia.dados))
                orig_w, orig_h = pil.size
                escala = min(
                    (self.largura_max_balao - 2 * PADDING_H) / orig_w,
                    ALTURA_MAX_IMAGEM / orig_h,
                    1.0
                )
                img_largura = orig_w * escala
                img_altura  = orig_h * escala
                img_reader  = ImageReader(io.BytesIO(msg.midia.dados))
            except Exception:
                texto_midia = '[ Imagem nao disponivel ]'
                linhas_midia = _quebrar_texto(self.c, texto_midia, FONTE_ITALICO,
                                              TAMANHO_TEXTO, largura_interna)

        altura_nome        = (TAMANHO_NOME * 1.4) if nome_str else 0
        altura_texto_total = _altura_texto(linhas_texto, TAMANHO_TEXTO) if linhas_texto else 0
        altura_midia_texto = _altura_texto(linhas_midia, TAMANHO_TEXTO) if linhas_midia else 0
        altura_img         = (img_altura + 4 * pt) if img_reader else 0
        altura_hora        = TAMANHO_HORA * 1.5

        altura_balao = (PADDING_V + altura_nome + altura_texto_total
                        + altura_midia_texto + altura_img + altura_hora + PADDING_V)

        if img_reader:
            largura_balao = min(img_largura + 2 * PADDING_H, self.largura_max_balao)
        else:
            largura_balao = self._calcular_largura_balao(
                linhas_texto + linhas_midia, largura_nome, largura_hora
            )

        self._garantir_espaco(altura_balao + ESPACO_ENTRE_MSGS)
        x_balao = (self.largura_pagina - MARGEM_LATERAL - largura_balao
                   if meu else MARGEM_LATERAL)
        y_topo = self.y

        self._desenhar_fundo_balao(x_balao, y_topo, largura_balao, altura_balao,
                                    cor_fundo, meu)

        cursor_y = y_topo - PADDING_V

        if nome_str:
            cursor_y -= TAMANHO_NOME
            self.c.setFillColor(_cor_para_nome(msg.remetente))
            self.c.setFont(FONTE_NEGRITO, TAMANHO_NOME)
            self.c.drawString(x_balao + PADDING_H, cursor_y, nome_str)
            cursor_y -= TAMANHO_NOME * 0.4

        if img_reader:
            cursor_y -= img_altura
            self.c.drawImage(img_reader, x_balao + PADDING_H, cursor_y,
                             width=img_largura, height=img_altura,
                             preserveAspectRatio=True)
            cursor_y -= 4 * pt

        self.c.setFillColor(cor_texto)
        self.c.setFont(fonte_texto, TAMANHO_TEXTO)
        for linha in linhas_texto:
            cursor_y -= TAMANHO_TEXTO
            self.c.drawString(x_balao + PADDING_H, cursor_y, linha)
            cursor_y -= TAMANHO_TEXTO * 0.3

        if linhas_midia:
            self.c.setFillColor(COR_SISTEMA_TEXTO)
            self.c.setFont(FONTE_ITALICO, TAMANHO_TEXTO)
            for linha in linhas_midia:
                cursor_y -= TAMANHO_TEXTO
                self.c.drawString(x_balao + PADDING_H, cursor_y, linha)
                cursor_y -= TAMANHO_TEXTO * 0.3

        x_hora = x_balao + largura_balao - PADDING_H - largura_hora
        self.c.setFillColor(COR_HORA)
        self.c.setFont(FONTE_NORMAL, TAMANHO_HORA)
        self.c.drawString(x_hora, y_topo - altura_balao + PADDING_V, hora_str)

        self.y -= altura_balao + ESPACO_ENTRE_MSGS

    # ── Balão de áudio ────────────────────────────────────────────────────────

    def _balao_audio(self, msg: Mensagem, eh_grupo: bool):
        """
        Layout:   [play]  |||waveform|||   00:00
                  nome_do_arquivo.opus      HH:MM vv
        Clicável: abre o arquivo .opus no player padrão do sistema.
        """
        meu = self._eh_meu(msg.remetente) if msg.remetente else False
        cor_fundo  = COR_BALAO_EU if meu else COR_BALAO_OUTRO
        largura_balao = self.largura_max_balao

        nome_str   = ''
        if eh_grupo and not meu and msg.remetente:
            nome_str = msg.remetente

        hora_str  = formatar_horario(msg.timestamp) + ('  vv' if meu else '')
        largura_hora = self.c.stringWidth(hora_str, FONTE_NORMAL, TAMANHO_HORA)

        # Trunca o nome do arquivo para caber na largura
        nome_arq = msg.midia.nome_arquivo or 'audio.opus'
        largura_interna = largura_balao - 2 * PADDING_H
        while (self.c.stringWidth(nome_arq, FONTE_NORMAL, TAMANHO_SISTEMA) > largura_interna
               and len(nome_arq) > 10):
            nome_arq = nome_arq[:len(nome_arq) - 4] + '...'

        RAIO_PLAY   = 12 * pt
        ALTURA_WAVE = RAIO_PLAY * 2 + 6 * pt   # área da waveform
        ALTURA_NOME = TAMANHO_SISTEMA * 1.4

        altura_nome_rem = (TAMANHO_NOME * 1.4) if nome_str else 0
        altura_balao = (PADDING_V + altura_nome_rem + ALTURA_WAVE
                        + ALTURA_NOME + TAMANHO_HORA * 1.2 + PADDING_V)

        self._garantir_espaco(altura_balao + ESPACO_ENTRE_MSGS)
        x_balao = (self.largura_pagina - MARGEM_LATERAL - largura_balao
                   if meu else MARGEM_LATERAL)
        y_topo = self.y

        self._desenhar_fundo_balao(x_balao, y_topo, largura_balao, altura_balao,
                                    cor_fundo, meu)

        cursor_y = y_topo - PADDING_V

        # Nome do remetente (grupo)
        if nome_str:
            cursor_y -= TAMANHO_NOME
            self.c.setFillColor(_cor_para_nome(msg.remetente))
            self.c.setFont(FONTE_NEGRITO, TAMANHO_NOME)
            self.c.drawString(x_balao + PADDING_H, cursor_y, nome_str)
            cursor_y -= TAMANHO_NOME * 0.4

        # Linha do play + waveform
        y_wave = cursor_y - ALTURA_WAVE / 2 - RAIO_PLAY * 0.3
        cx_play = x_balao + PADDING_H + RAIO_PLAY + 2
        self._desenhar_play_icon(cx_play, y_wave, RAIO_PLAY,
                                  colors.HexColor('#00BFA5'))

        x_wave_inicio = cx_play + RAIO_PLAY + 8 * pt
        x_wave_fim    = x_balao + largura_balao - PADDING_H - 30 * pt
        largura_wave  = max(x_wave_fim - x_wave_inicio, 20)
        self._desenhar_waveform(x_wave_inicio, y_wave, largura_wave,
                                 msg.midia.nome_arquivo or '')

        cursor_y -= ALTURA_WAVE

        # Nome do arquivo
        self.c.setFillColor(COR_SISTEMA_TEXTO)
        self.c.setFont(FONTE_NORMAL, TAMANHO_SISTEMA)
        self.c.drawString(x_balao + PADDING_H, cursor_y - TAMANHO_SISTEMA, nome_arq)
        cursor_y -= ALTURA_NOME

        # Horário
        x_hora = x_balao + largura_balao - PADDING_H - largura_hora
        self.c.setFillColor(COR_HORA)
        self.c.setFont(FONTE_NORMAL, TAMANHO_HORA)
        self.c.drawString(x_hora, cursor_y - TAMANHO_HORA * 0.5, hora_str)

        # Anotação clicável sobre o balão inteiro
        self._link_arquivo(
            msg.midia.caminho,
            x_balao, y_topo - altura_balao,
            x_balao + largura_balao, y_topo
        )

        self.y -= altura_balao + ESPACO_ENTRE_MSGS

    # ── Balão de vídeo ────────────────────────────────────────────────────────

    def _balao_video(self, msg: Mensagem, eh_grupo: bool):
        """
        Layout:  área escura com botão de play centralizado + legenda.
        Clicável: abre o arquivo .mp4 no player padrão do sistema.
        """
        meu = self._eh_meu(msg.remetente) if msg.remetente else False
        cor_fundo  = COR_BALAO_EU if meu else COR_BALAO_OUTRO
        largura_balao = self.largura_max_balao

        nome_str = ''
        if eh_grupo and not meu and msg.remetente:
            nome_str = msg.remetente

        hora_str    = formatar_horario(msg.timestamp) + ('  vv' if meu else '')
        largura_hora = self.c.stringWidth(hora_str, FONTE_NORMAL, TAMANHO_HORA)

        nome_arq = msg.midia.nome_arquivo or 'video.mp4'
        largura_interna = largura_balao - 2 * PADDING_H
        while (self.c.stringWidth(nome_arq, FONTE_NORMAL, TAMANHO_SISTEMA) > largura_interna
               and len(nome_arq) > 10):
            nome_arq = nome_arq[:len(nome_arq) - 4] + '...'

        ALTURA_THUMB  = 80 * pt
        RAIO_PLAY_VID = 18 * pt
        ALTURA_NOME   = TAMANHO_SISTEMA * 1.6

        altura_nome_rem = (TAMANHO_NOME * 1.4) if nome_str else 0
        altura_balao = (PADDING_V + altura_nome_rem + ALTURA_THUMB
                        + ALTURA_NOME + TAMANHO_HORA * 1.2 + PADDING_V)

        self._garantir_espaco(altura_balao + ESPACO_ENTRE_MSGS)
        x_balao = (self.largura_pagina - MARGEM_LATERAL - largura_balao
                   if meu else MARGEM_LATERAL)
        y_topo = self.y

        self._desenhar_fundo_balao(x_balao, y_topo, largura_balao, altura_balao,
                                    cor_fundo, meu)

        cursor_y = y_topo - PADDING_V

        # Nome do remetente (grupo)
        if nome_str:
            cursor_y -= TAMANHO_NOME
            self.c.setFillColor(_cor_para_nome(msg.remetente))
            self.c.setFont(FONTE_NEGRITO, TAMANHO_NOME)
            self.c.drawString(x_balao + PADDING_H, cursor_y, nome_str)
            cursor_y -= TAMANHO_NOME * 0.4

        # Área de thumbnail (fundo escuro arredondado)
        thumb_x = x_balao + PADDING_H
        thumb_y = cursor_y - ALTURA_THUMB
        thumb_w = largura_balao - 2 * PADDING_H
        self.c.setFillColor(colors.HexColor('#2C2C2C'))
        self.c.roundRect(thumb_x, thumb_y, thumb_w, ALTURA_THUMB, 6, fill=1, stroke=0)

        # Botão de play centralizado
        cx_play = thumb_x + thumb_w / 2
        cy_play = thumb_y + ALTURA_THUMB / 2
        self._desenhar_play_icon(cx_play, cy_play, RAIO_PLAY_VID,
                                  colors.HexColor('#FFFFFF40'),  # branco translúcido
                                  colors.white)
        # Segundo círculo menor (borda)
        self.c.setFillColor(colors.HexColor('#00000000'))
        self.c.setStrokeColor(colors.white)
        self.c.setLineWidth(1.5)
        self.c.circle(cx_play, cy_play, RAIO_PLAY_VID + 3, fill=0, stroke=1)
        self.c.setLineWidth(1)

        cursor_y -= ALTURA_THUMB + 3 * pt

        # Nome do arquivo
        self.c.setFillColor(COR_SISTEMA_TEXTO)
        self.c.setFont(FONTE_NORMAL, TAMANHO_SISTEMA)
        self.c.drawString(x_balao + PADDING_H, cursor_y - TAMANHO_SISTEMA, nome_arq)
        cursor_y -= ALTURA_NOME

        # Horário
        x_hora = x_balao + largura_balao - PADDING_H - largura_hora
        self.c.setFillColor(COR_HORA)
        self.c.setFont(FONTE_NORMAL, TAMANHO_HORA)
        self.c.drawString(x_hora, cursor_y - TAMANHO_HORA * 0.5, hora_str)

        # Anotação clicável sobre a área de thumbnail
        self._link_arquivo(
            msg.midia.caminho,
            thumb_x, thumb_y,
            thumb_x + thumb_w, thumb_y + ALTURA_THUMB
        )

        self.y -= altura_balao + ESPACO_ENTRE_MSGS

    # ── Fundo comum do balão ──────────────────────────────────────────────────

    def _desenhar_fundo_balao(self, x_balao, y_topo, largura_balao, altura_balao,
                               cor_fundo, meu: bool):
        """Desenha o roundRect + pontinha triangular."""
        self.c.setFillColor(cor_fundo)
        self.c.setStrokeColor(cor_fundo)
        self.c.roundRect(x_balao, y_topo - altura_balao, largura_balao,
                         altura_balao, RAIO_CANTO, fill=1, stroke=0)

        pontinha_y       = y_topo - RAIO_CANTO * 1.5
        tamanho_pontinha = 8 * pt
        self.c.setFillColor(cor_fundo)
        if meu:
            px = x_balao + largura_balao
            p = self.c.beginPath()
            p.moveTo(px, pontinha_y)
            p.lineTo(px + tamanho_pontinha, pontinha_y - tamanho_pontinha * 0.5)
            p.lineTo(px, pontinha_y - tamanho_pontinha)
            p.close()
            self.c.drawPath(p, fill=1, stroke=0)
        else:
            px = x_balao
            p = self.c.beginPath()
            p.moveTo(px, pontinha_y)
            p.lineTo(px - tamanho_pontinha, pontinha_y - tamanho_pontinha * 0.5)
            p.lineTo(px, pontinha_y - tamanho_pontinha)
            p.close()
            self.c.drawPath(p, fill=1, stroke=0)

    # ─── Ponto de entrada principal ──────────────────────────────────────────

    def renderizar(self, mensagens: list[Mensagem]):
        """Renderiza todas as mensagens no PDF."""
        # Detecta se é conversa de grupo (mais de 2 remetentes distintos)
        remetentes = {m.remetente for m in mensagens if m.remetente}
        eh_grupo = len(remetentes) > 2

        for msg in mensagens:
            # Atualiza período
            if self.periodo_inicio is None or msg.timestamp < self.periodo_inicio:
                self.periodo_inicio = msg.timestamp
            if self.periodo_fim is None or msg.timestamp > self.periodo_fim:
                self.periodo_fim = msg.timestamp

            # Separador de data
            data_msg = msg.timestamp.date()
            if self.data_ultima_msg != data_msg:
                self._desenhar_separador_data(msg.timestamp)
                self.data_ultima_msg = data_msg

            if msg.tipo == 'sistema':
                self._desenhar_mensagem_sistema(msg)
            else:
                self._desenhar_balao(msg, eh_grupo=eh_grupo)

        return self.pagina_atual

    def salvar(self):
        """Salva o PDF no disco."""
        self.c.save()


def gerar_pdf(mensagens: list[Mensagem], caminho_saida: str,
              nome_conversa: str, eu: Optional[str] = None,
              media_url_base: Optional[str] = None) -> dict:
    """
    Gera o PDF e retorna estatísticas.
    media_url_base: prefixo HTTP para links de mídia (ex: "http://localhost:5000/media/job123/").
    Se None, usa links file:// locais (comportamento padrão da CLI).
    """
    renderer = RendererPDF(caminho_saida, nome_conversa, eu, media_url_base=media_url_base)
    total_paginas = renderer.renderizar(mensagens)
    renderer.salvar()

    return {
        'total_mensagens': len(mensagens),
        'periodo_inicio': renderer.periodo_inicio,
        'periodo_fim': renderer.periodo_fim,
        'paginas': total_paginas,
    }
