"""
whatsapp2pdf — Converte exportação ZIP do WhatsApp para PDF com layout visual fiel.

Uso:
    python whatsapp2pdf.py conversa.zip
    python whatsapp2pdf.py conversa.zip --output saida.pdf
    python whatsapp2pdf.py conversa.zip --eu "Meu Nome"
"""

import argparse
import io
import os
import sys
import zipfile

# Garante saída UTF-8 no Windows
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from parser import parsear_chat, Mensagem
from renderer import gerar_pdf


ARQUIVO_CHAT = '_chat.txt'
ENCODINGS = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']


def ler_zip(caminho_zip: str) -> tuple[str, dict]:
    """
    Abre o ZIP, extrai o _chat.txt e retorna os demais arquivos como {nome: bytes}.
    """
    if not os.path.exists(caminho_zip):
        sys.exit(f'Erro: arquivo não encontrado: {caminho_zip}')

    try:
        with zipfile.ZipFile(caminho_zip, 'r') as z:
            nomes = z.namelist()

            arquivo_chat = None
            for nome in nomes:
                if os.path.basename(nome).lower() == ARQUIVO_CHAT:
                    arquivo_chat = nome
                    break

            if arquivo_chat is None:
                for nome in nomes:
                    if os.path.basename(nome).lower().endswith('.txt'):
                        arquivo_chat = nome
                        break

            if arquivo_chat is None:
                sys.exit(
                    f'Erro: o ZIP não contém "{ARQUIVO_CHAT}" nem nenhum arquivo .txt.\n'
                    'Certifique-se de que é um ZIP exportado pelo WhatsApp.'
                )

            dados_chat = z.read(arquivo_chat)
            conteudo = None
            for enc in ENCODINGS:
                try:
                    conteudo = dados_chat.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if conteudo is None:
                sys.exit('Erro: não foi possível decodificar o _chat.txt.')

            arquivos = {}
            for nome in nomes:
                if nome == arquivo_chat:
                    continue
                try:
                    arquivos[os.path.basename(nome)] = z.read(nome)
                except Exception:
                    pass

            return conteudo, arquivos

    except zipfile.BadZipFile:
        sys.exit(f'Erro: "{caminho_zip}" não é um arquivo ZIP válido.')


def extrair_midia(mensagens: list[Mensagem], pasta_midia: str) -> int:
    """
    Salva no disco todos os arquivos de mídia (audio/video/doc/sticker) que
    vieram no ZIP. Preenche midia.caminho em cada mensagem.
    Retorna o número de arquivos extraídos.
    """
    os.makedirs(pasta_midia, exist_ok=True)
    extraidos = 0
    for msg in mensagens:
        if not msg.midia or not msg.midia.dados:
            continue
        caminho = os.path.join(pasta_midia, msg.midia.nome_arquivo)
        try:
            with open(caminho, 'wb') as f:
                f.write(msg.midia.dados)
            msg.midia.caminho = caminho
            extraidos += 1
        except Exception:
            pass
    return extraidos


def main():
    parser = argparse.ArgumentParser(
        description='Converte exportação ZIP do WhatsApp em PDF com layout visual.'
    )
    parser.add_argument('zip', help='Caminho para o arquivo ZIP exportado pelo WhatsApp')
    parser.add_argument('--output', '-o', default=None,
                        help='Caminho do PDF de saída (padrão: mesmo nome do ZIP com .pdf)')
    parser.add_argument('--eu', default=None,
                        help='Seu nome na conversa (mensagens ficam no lado direito)')
    args = parser.parse_args()

    caminho_saida = args.output
    if caminho_saida is None:
        base = os.path.splitext(os.path.basename(args.zip))[0]
        caminho_saida = base + '.pdf'

    nome_conversa = os.path.splitext(os.path.basename(args.zip))[0]

    # Pasta de mídia ao lado do PDF
    pasta_midia = os.path.splitext(caminho_saida)[0] + '_arquivos'

    print(f'Lendo arquivo: {args.zip}')
    conteudo_chat, arquivos_zip = ler_zip(args.zip)

    print('Parseando conversa...')
    mensagens = parsear_chat(conteudo_chat, arquivos_zip)

    if not mensagens:
        sys.exit('Erro: nenhuma mensagem encontrada no _chat.txt.')

    print('Extraindo arquivos de mídia...')
    n_extraidos = extrair_midia(mensagens, pasta_midia)

    print(f'Gerando PDF ({len(mensagens)} mensagens)...')
    stats = gerar_pdf(mensagens, caminho_saida, nome_conversa, eu=args.eu)

    inicio = stats['periodo_inicio']
    fim    = stats['periodo_fim']
    fmt    = '%d/%m/%Y'

    print()
    print(f'PDF gerado: {caminho_saida}')
    print(f'Total de mensagens: {stats["total_mensagens"]:,}')
    if inicio and fim:
        print(f'Período: {inicio.strftime(fmt)} até {fim.strftime(fmt)}')
    print(f'Páginas: {stats["paginas"]}')
    if n_extraidos:
        print(f'Arquivos de midia: {n_extraidos} extraídos em "{pasta_midia}"')
        print('  (clique nos balões de áudio/vídeo no PDF para abrir)')


if __name__ == '__main__':
    main()
