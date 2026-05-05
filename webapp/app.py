import sys
import os

from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from flask import (Flask, render_template, request, redirect, url_for,
                   session, send_file, jsonify, abort)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge
from functools import wraps
from sqlalchemy import create_engine, text, inspect as sa_inspect, MetaData, Table
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.exc import IntegrityError
import uuid
import threading
import shutil
import time
import re

from parser import parsear_chat
from renderer import gerar_pdf
from whatsapp2pdf import ler_zip, extrair_midia
from utils import nomes_correspondem

WEBAPP_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── Environment / Configuration ──────────────────────────────────────────────

_secret = os.getenv('SECRET_KEY')
if not _secret:
    raise RuntimeError(
        'SECRET_KEY not set. Copy .env.example to .env and fill in the values.'
    )

_admin_pass = os.getenv('ADMIN_PASS')
if not _admin_pass:
    raise RuntimeError(
        'ADMIN_PASS not set. Copy .env.example to .env and fill in the values.'
    )

ADMIN_USER          = os.getenv('ADMIN_USER', 'admin')
ADMIN_PASS          = _admin_pass
MAX_MB              = int(os.getenv('MAX_CONTENT_LENGTH_MB', '500'))
TEMP_DIR            = os.getenv('TEMP_DIR', os.path.join(WEBAPP_DIR, 'temp_jobs'))
JOB_RETENTION_HOURS = int(os.getenv('JOB_RETENTION_HOURS', '24'))

os.makedirs(TEMP_DIR, exist_ok=True)

# ─── Flask app ────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key                        = _secret
app.config['MAX_CONTENT_LENGTH']      = MAX_MB * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Enable secure flag only when behind HTTPS (set FLASK_ENV=production on Render)
app.config['SESSION_COOKIE_SECURE']   = os.getenv('FLASK_ENV') == 'production'

# ─── Rate limiter ─────────────────────────────────────────────────────────────

# With multiple gunicorn workers, set REDIS_URL for cross-worker rate limiting.
# Without it, limits are enforced per-worker (still provides meaningful protection).
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri=os.getenv('REDIS_URL', 'memory://'),
)

# ─── Database ─────────────────────────────────────────────────────────────────

_raw_db_url = os.getenv('DATABASE_URL',
                        f'sqlite:///{os.path.join(WEBAPP_DIR, "users.db")}')
# Render exports the legacy postgres:// prefix; SQLAlchemy requires postgresql://
if _raw_db_url.startswith('postgres://'):
    _raw_db_url = _raw_db_url.replace('postgres://', 'postgresql://', 1)

_is_sqlite = _raw_db_url.startswith('sqlite')
engine = create_engine(
    _raw_db_url,
    pool_pre_ping=True,
    connect_args=({'check_same_thread': False} if _is_sqlite else {}),
    **({} if _is_sqlite else {'pool_size': 2, 'max_overflow': 3}),
)


def init_db():
    """Create tables and seed admin user. Safe to call on every startup."""
    _meta = MetaData()
    Table('users', _meta,
        Column('id',         Integer,     primary_key=True, autoincrement=True),
        Column('username',   String(255), unique=True,      nullable=False),
        Column('password',   Text,        nullable=False),
        Column('name',       String(255), server_default="''"),
        Column('role',       String(50),  server_default="'user'"),
        Column('active',     Integer,     server_default='1'),
        Column('created_at', DateTime,    server_default=text('CURRENT_TIMESTAMP')),
        Column('pdf_limit',  Integer,     nullable=True),
        Column('pdf_count',  Integer,     server_default='0'),
    )
    _meta.create_all(engine)

    # Migration: add columns that may be absent from older schema versions
    existing_cols = {c['name'] for c in sa_inspect(engine).get_columns('users')}
    for col_name, col_def in [('pdf_limit', 'INTEGER'), ('pdf_count', 'INTEGER DEFAULT 0')]:
        if col_name not in existing_cols:
            try:
                with engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE users ADD COLUMN {col_name} {col_def}'))
            except Exception:
                pass  # concurrent worker may have added it first

    # Seed admin user (silently skip if already exists)
    with engine.begin() as conn:
        try:
            conn.execute(
                text('INSERT INTO users (username, password, name, role) '
                     'VALUES (:u, :p, :n, :r)'),
                {'u': ADMIN_USER, 'p': generate_password_hash(ADMIN_PASS),
                 'n': 'Administrador', 'r': 'admin'}
            )
        except IntegrityError:
            pass


# Called at module load so gunicorn workers initialize the DB on startup
init_db()

# ─── Background: clean up old temp job directories ────────────────────────────

jobs: dict = {}
jobs_lock  = threading.Lock()


def _cleanup_loop():
    while True:
        try:
            cutoff = time.time() - JOB_RETENTION_HOURS * 3600
            for entry in os.scandir(TEMP_DIR):
                if entry.is_dir() and entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry.path, ignore_errors=True)
                    with jobs_lock:
                        jobs.pop(entry.name, None)
        except Exception:
            pass
        time.sleep(3600)


threading.Thread(target=_cleanup_loop, daemon=True).start()

# ─── Auth decorators ──────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapped


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return wrapped


# ─── Error handlers ───────────────────────────────────────────────────────────

@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(_e):
    return jsonify({'error': f'Arquivo muito grande. Limite: {MAX_MB}MB.'}), 413


# ─── Auth routes ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute')
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        with engine.connect() as conn:
            user = conn.execute(
                text('SELECT * FROM users WHERE username=:u AND active=1'),
                {'u': username}
            ).mappings().fetchone()

        if user and check_password_hash(user['password'], password):
            session.clear()
            session['user_id']  = user['id']
            session['username'] = user['username']
            session['name']     = user['name'] or user['username']
            session['role']     = user['role']
            return redirect(url_for('dashboard'))
        else:
            error = 'Usuário ou senha incorretos.'

    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ─── Main app routes ──────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    with engine.connect() as conn:
        row = conn.execute(
            text('SELECT pdf_count, pdf_limit, role FROM users WHERE id=:id'),
            {'id': session.get('user_id')}
        ).mappings().fetchone()

    pdf_count = (row['pdf_count'] or 0) if row else 0
    pdf_limit = row['pdf_limit']          if row else None
    role      = row['role']               if row else session.get('role')

    if role == 'admin' or pdf_limit is None:
        creditos = None
    else:
        creditos = max(0, pdf_limit - pdf_count)

    return render_template('dashboard.html',
                           user_name=session.get('name', session.get('username')),
                           role=role,
                           pdf_count=pdf_count,
                           pdf_limit=pdf_limit,
                           creditos=creditos)


@app.route('/admin')
@admin_required
def admin():
    with engine.connect() as conn:
        users = conn.execute(
            text('SELECT id, username, name, role, created_at, active, '
                 'pdf_count, pdf_limit FROM users ORDER BY id')
        ).mappings().fetchall()
    return render_template('admin.html',
                           users=users,
                           user_name=session.get('name', session.get('username')),
                           current_id=session.get('user_id'))


# ─── Admin API ────────────────────────────────────────────────────────────────

@app.route('/admin/users', methods=['POST'])
@admin_required
def create_user():
    data     = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    name     = data.get('name', '').strip()
    role     = data.get('role', 'user')

    if not username or not password:
        return jsonify({'error': 'Usuário e senha são obrigatórios.'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Senha deve ter no mínimo 6 caracteres.'}), 400
    if role not in ('user', 'admin'):
        role = 'user'

    try:
        with engine.begin() as conn:
            conn.execute(
                text('INSERT INTO users (username, password, name, role) '
                     'VALUES (:u, :p, :n, :r)'),
                {'u': username, 'p': generate_password_hash(password), 'n': name, 'r': role}
            )
        return jsonify({'success': True})
    except IntegrityError:
        return jsonify({'error': 'Nome de usuário já existe.'}), 400


@app.route('/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    if user_id == session.get('user_id'):
        return jsonify({'error': 'Não é possível desativar sua própria conta.'}), 400
    with engine.begin() as conn:
        conn.execute(text('UPDATE users SET active=0 WHERE id=:id'), {'id': user_id})
    return jsonify({'success': True})


@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def permanent_delete_user(user_id):
    if user_id == session.get('user_id'):
        return jsonify({'error': 'Não é possível excluir sua própria conta.'}), 400
    with engine.begin() as conn:
        conn.execute(text('DELETE FROM users WHERE id=:id'), {'id': user_id})
    return jsonify({'success': True})


@app.route('/admin/users/<int:user_id>/activate', methods=['POST'])
@admin_required
def activate_user(user_id):
    with engine.begin() as conn:
        conn.execute(text('UPDATE users SET active=1 WHERE id=:id'), {'id': user_id})
    return jsonify({'success': True})


@app.route('/admin/users/<int:user_id>/reset', methods=['POST'])
@admin_required
def reset_password(user_id):
    data     = request.get_json() or {}
    new_pass = data.get('password', '').strip()
    if not new_pass or len(new_pass) < 6:
        return jsonify({'error': 'Senha deve ter no mínimo 6 caracteres.'}), 400
    with engine.begin() as conn:
        conn.execute(
            text('UPDATE users SET password=:p WHERE id=:id'),
            {'p': generate_password_hash(new_pass), 'id': user_id}
        )
    return jsonify({'success': True})


@app.route('/admin/users/<int:user_id>/limit', methods=['POST'])
@admin_required
def set_limit(user_id):
    data   = request.get_json() or {}
    action = data.get('action', 'set')
    value  = data.get('value')

    with engine.connect() as conn:
        user = conn.execute(
            text('SELECT pdf_limit FROM users WHERE id=:id'), {'id': user_id}
        ).mappings().fetchone()
    if not user:
        return jsonify({'error': 'Usuário não encontrado.'}), 404

    if action == 'set':
        new_limit = None if (value is None or str(value).strip() == '') else int(value)
    else:
        add_n     = int(value) if value else 0
        current   = user['pdf_limit']
        new_limit = add_n if current is None else current + add_n

    with engine.begin() as conn:
        conn.execute(
            text('UPDATE users SET pdf_limit=:lim WHERE id=:id'),
            {'lim': new_limit, 'id': user_id}
        )
    return jsonify({'success': True, 'new_limit': new_limit})


# ─── Conversion API ───────────────────────────────────────────────────────────

@app.route('/convert', methods=['POST'])
@login_required
def convert():
    if 'file' not in request.files:
        return jsonify({'error': 'Nenhum arquivo enviado.'}), 400

    f = request.files['file']
    original_name = f.filename or ''
    # secure_filename validates the filename without altering nome_conversa used for display
    if not secure_filename(original_name).lower().endswith('.zip'):
        return jsonify({'error': 'Apenas arquivos .zip são aceitos.'}), 400

    user_id = session.get('user_id')

    with engine.connect() as conn:
        row = conn.execute(
            text('SELECT pdf_limit, pdf_count, role FROM users WHERE id=:id'),
            {'id': user_id}
        ).mappings().fetchone()
    if row and row['role'] != 'admin' and row['pdf_limit'] is not None:
        if (row['pdf_count'] or 0) >= row['pdf_limit']:
            return jsonify({'error': f'Limite de {row["pdf_limit"]} PDF(s) atingido. '
                                      'Contate o administrador.'}), 403

    job_id        = str(uuid.uuid4())
    job_dir       = os.path.join(TEMP_DIR, job_id)
    os.makedirs(job_dir)

    zip_path      = os.path.join(job_dir, 'upload.zip')
    nome_conversa = os.path.splitext(original_name)[0]
    f.save(zip_path)

    url_root = request.url_root

    with jobs_lock:
        jobs[job_id] = {
            'status':   'processing',
            'message':  'Iniciando...',
            'pdf_path': None,
            'stats':    None,
            'error':    None,
            'nome':     nome_conversa,
        }

    # TODO: migrate to Celery/RQ when scaling to multiple workers
    threading.Thread(
        target=_run_conversion,
        args=(job_id, zip_path, job_dir, nome_conversa, url_root, user_id),
        daemon=True
    ).start()

    return jsonify({'job_id': job_id})


def _set_job(job_id, **kwargs):
    with jobs_lock:
        jobs[job_id].update(kwargs)


# WhatsApp export filename patterns (PT and EN)
_PADROES_OUTRO = [
    r'^whatsapp\s+(?:chat|conversation|conversa)\s*[-–]\s*(.+?)(?:\s*\(\d+\))*\s*$',
    r'^conversa(?:\s+do\s+whatsapp)?\s+com\s+(.+?)(?:\s*\(\d+\))*\s*$',
    r'^whatsapp\s+chat\s+with\s+(.+?)(?:\s*\(\d+\))*\s*$',
]


def _auto_detect_eu(nome_conversa: str, mensagens) -> str | None:
    """
    Detects which participant is 'eu' in a 2-person chat.
    WhatsApp export filenames always name the OTHER participant, so we find
    the sender who doesn't match the filename and treat them as 'eu'.
    """
    remetentes = list({m.remetente for m in mensagens if m.remetente})
    if len(remetentes) != 2:
        return None

    nome_lower = nome_conversa.strip().lower()
    outro = None
    for padrao in _PADROES_OUTRO:
        m = re.match(padrao, nome_lower)
        if m:
            outro = m.group(1).strip()
            outro = re.sub(r'\s*\(\d+\)\s*$', '', outro).strip()
            break

    if not outro:
        outro = re.sub(r'\s*\(\d+\)\s*$', '', nome_conversa.strip()).strip()

    for rem in remetentes:
        if nomes_correspondem(rem, outro):
            eu_candidato = [r for r in remetentes if r != rem]
            return eu_candidato[0] if eu_candidato else None

    return None


def _run_conversion(job_id, zip_path, job_dir, nome_conversa, url_root, user_id):
    try:
        _set_job(job_id, message='Lendo arquivo ZIP...')
        conteudo, arquivos_zip = ler_zip(zip_path)

        _set_job(job_id, message='Parseando mensagens...')
        mensagens = parsear_chat(conteudo, arquivos_zip)

        if not mensagens:
            _set_job(job_id, status='error',
                     error='Nenhuma mensagem encontrada no arquivo.')
            return

        eu = _auto_detect_eu(nome_conversa, mensagens)

        _set_job(job_id, message=f'Processando mídia ({len(mensagens):,} mensagens)...')
        pasta_midia = os.path.join(job_dir, 'midia')
        n_ext = extrair_midia(mensagens, pasta_midia)

        _set_job(job_id, message='Gerando PDF...')
        pdf_path       = os.path.join(job_dir, nome_conversa + '.pdf')
        media_url_base = f'{url_root}player/{job_id}/'
        stats          = gerar_pdf(mensagens, pdf_path, nome_conversa,
                                   eu=eu, media_url_base=media_url_base)

        try:
            with engine.begin() as conn:
                conn.execute(
                    text('UPDATE users SET pdf_count = COALESCE(pdf_count, 0) + 1 '
                         'WHERE id=:id'),
                    {'id': user_id}
                )
        except Exception:
            pass

        _set_job(job_id,
                 status='done',
                 message='Concluído!',
                 pdf_path=pdf_path,
                 stats={
                     'total_mensagens': stats['total_mensagens'],
                     'paginas':         stats['paginas'],
                     'periodo_inicio':  stats['periodo_inicio'].strftime('%d/%m/%Y') if stats['periodo_inicio'] else '',
                     'periodo_fim':     stats['periodo_fim'].strftime('%d/%m/%Y') if stats['periodo_fim'] else '',
                     'n_extraidos':     n_ext,
                     'nome':            nome_conversa,
                 })

    except (Exception, SystemExit) as e:
        _set_job(job_id, status='error', error=str(e))


@app.route('/status/<job_id>')
@login_required
def job_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job não encontrado.'}), 404
    return jsonify({
        'status':  job['status'],
        'message': job['message'],
        'stats':   job['stats'],
        'error':   job['error'],
    })


@app.route('/media/<job_id>/<path:filename>')
@login_required
def serve_media(job_id, filename):
    filename = os.path.basename(filename)
    filepath = os.path.join(TEMP_DIR, job_id, 'midia', filename)
    if not os.path.exists(filepath):
        abort(404)
    return send_file(filepath)


@app.route('/player/<job_id>/<path:filename>')
@login_required
def media_player(job_id, filename):
    filename  = os.path.basename(filename)
    filepath  = os.path.join(TEMP_DIR, job_id, 'midia', filename)
    ext       = os.path.splitext(filename)[1].lower()

    AUDIO_EXTS = {'.opus', '.mp3', '.ogg', '.m4a', '.aac', '.wav', '.oga'}
    VIDEO_EXTS = {'.mp4', '.avi', '.mov', '.mkv', '.3gp', '.webm'}

    if ext in AUDIO_EXTS:
        media_type = 'audio'
    elif ext in VIDEO_EXTS:
        media_type = 'video'
    else:
        media_type = 'audio'

    file_exists = os.path.exists(filepath)
    media_src   = url_for('serve_media', job_id=job_id, filename=filename) if file_exists else None

    return render_template('player.html',
                           filename=filename,
                           media_type=media_type,
                           media_src=media_src,
                           file_exists=file_exists)


@app.route('/download/<job_id>')
@login_required
def download(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job or job['status'] != 'done':
        abort(404)
    return send_file(job['pdf_path'],
                     as_attachment=True,
                     download_name=job['nome'] + '.pdf')


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print('\n' + '='*50)
    print('  ZapDocs — Iniciando servidor')
    print(f'  URL: http://localhost:{port}')
    print(f'  Login: {ADMIN_USER}')
    print('='*50 + '\n')
    app.run(debug=False, host='0.0.0.0', port=port)
