"""
ZapDocs config validator — run before deploying to catch missing env vars.

Usage:
    python check_config.py
"""
import os
import sys

from dotenv import load_dotenv
load_dotenv()

errors = []


def require(var, hint=''):
    val = os.getenv(var)
    if not val:
        errors.append(f'  MISSING  {var}  {hint}')
    else:
        print(f'  OK       {var}')


def optional(var, default='', hint=''):
    val = os.getenv(var) or default
    note = f'  (default: {default!r})' if not os.getenv(var) else ''
    print(f'  --       {var} = {val!r}{note}  {hint}')


print('\n=== ZapDocs Config Check ===\n')

print('Required:')
require('SECRET_KEY',
        '(generate: python -c "import secrets; print(secrets.token_hex(32))")')
require('ADMIN_PASS', '(your admin login password)')

print('\nOptional:')
optional('ADMIN_USER',            'admin')
optional('DATABASE_URL',          'sqlite:///users.db',
         '(set to PostgreSQL URL for production)')
optional('TEMP_DIR',              'webapp/temp_jobs',
         '(use /var/data/temp_jobs on Render with Persistent Disk)')
optional('JOB_RETENTION_HOURS',   '24')
optional('MAX_CONTENT_LENGTH_MB', '500')
optional('FLASK_ENV',             '',
         '(set to "production" on Render to enable secure cookies)')
optional('REDIS_URL',             '',
         '(optional, enables cross-worker rate limiting)')

if errors:
    print('\nErrors found:')
    for e in errors:
        print(e)
    print('\nFix the above before starting the server.\n')
    sys.exit(1)

print('\nAll required variables present.')

print('\nTesting database connection...')
try:
    db_url = os.getenv('DATABASE_URL',
                       'sqlite:///check_test.db')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    from sqlalchemy import create_engine, text
    eng = create_engine(db_url, pool_pre_ping=True,
                        connect_args=({'check_same_thread': False}
                                      if db_url.startswith('sqlite') else {}))
    with eng.connect() as c:
        c.execute(text('SELECT 1'))
    eng.dispose()
    print('  OK  Database reachable')
    # Clean up test SQLite file
    if db_url == 'sqlite:///check_test.db' and os.path.exists('check_test.db'):
        try:
            os.remove('check_test.db')
        except OSError:
            pass
except Exception as exc:
    print(f'  WARN  DB connection failed: {exc}')
    print('  (normal if the DB does not exist yet — it is created on first run)')

print('\nConfig check passed!\n')
