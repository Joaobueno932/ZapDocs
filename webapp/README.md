# ZapDocs

Converte exportações ZIP do WhatsApp em PDFs com layout visual completo — áudio, vídeo e imagens incluídos.

---

## Requisitos locais

- Python 3.11+
- pip

---

## Setup local

### 1. Instale as dependências

```bash
cd zapdocs/webapp
pip install -r requirements.txt
```

### 2. Configure as variáveis de ambiente

```bash
cp .env.example .env
```

Edite o `.env` e preencha os valores obrigatórios:

| Variável | Obrigatória | Descrição |
|---|---|---|
| `SECRET_KEY` | Sim | Chave secreta do Flask. Gere com: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ADMIN_PASS` | Sim | Senha do usuário admin |
| `ADMIN_USER` | Não | Login do admin (padrão: `admin`) |
| `DATABASE_URL` | Não | URL do banco. Padrão: SQLite local (`users.db`) |
| `TEMP_DIR` | Não | Pasta para PDFs temporários (padrão: `temp_jobs/`) |
| `JOB_RETENTION_HOURS` | Não | Horas até deletar arquivos temporários (padrão: `24`) |
| `MAX_CONTENT_LENGTH_MB` | Não | Limite de upload em MB (padrão: `500`) |
| `FLASK_ENV` | Não | Defina `production` em produção (ativa cookies seguros) |
| `REDIS_URL` | Não | Redis para rate limiting entre workers (opcional) |

### 3. Valide a configuração

```bash
python check_config.py
```

### 4. Inicie o servidor

**Desenvolvimento:**
```bash
python app.py
```

**Produção local (gunicorn):**
```bash
gunicorn app:app
```

Acesse: http://localhost:5000  
Login padrão: o usuário e senha que você definiu em `ADMIN_USER` / `ADMIN_PASS`.

> **Nota:** Se você alterar `ADMIN_PASS` após o primeiro start, a senha no banco NÃO muda automaticamente. Use o painel admin para resetar a senha.

---

## Deploy no Render

### Passo a passo

1. **Crie um repositório Git** com o conteúdo da pasta `zapdocs/` (ou o projeto inteiro).

2. **No Render**, crie um novo **Web Service** e conecte o repositório.

3. **Configure o serviço:**
   - **Root Directory:** `webapp` (se o repo root for `zapdocs/`)
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Runtime:** Python 3

4. **Variáveis de ambiente** (aba Environment no Render):
   | Variável | Valor |
   |---|---|
   | `SECRET_KEY` | Gere um valor aleatório (ou use o botão "Generate") |
   | `ADMIN_PASS` | Sua senha de admin |
   | `ADMIN_USER` | `admin` (ou outro nome de sua escolha) |
   | `FLASK_ENV` | `production` |
   | `DATABASE_URL` | (veja seção PostgreSQL abaixo) |
   | `TEMP_DIR` | (veja seção Persistent Disk abaixo) |

5. **Deploy** — o Render detectará o `Procfile` automaticamente.

---

### PostgreSQL (recomendado para produção)

O Render SQLite usa o sistema de arquivos efêmero e os dados são **perdidos** a cada redeploy.

1. No Render, crie um **PostgreSQL** (aba Databases → New PostgreSQL).
2. Copie a **Internal Database URL**.
3. Adicione como variável de ambiente: `DATABASE_URL=postgresql://...`

O app detecta automaticamente o banco pelo prefixo da URL e usa PostgreSQL ou SQLite conforme configurado.

---

### Persistent Disk (para arquivos temporários)

Por padrão, os PDFs gerados ficam em `temp_jobs/` dentro do container — apagados a cada redeploy.

Para manter os arquivos entre redeploys:

1. No Render, vá em **Disks** e adicione um disco ao seu serviço (ex: mount path `/var/data`, 1 GB).
2. Adicione a variável: `TEMP_DIR=/var/data/temp_jobs`

Sem o disco, os usuários perdem o acesso ao PDF se o servidor restartar antes de fazer o download. O `JOB_RETENTION_HOURS` controla a limpeza automática.

---

## Estrutura do projeto

```
webapp/
├── app.py              # Backend Flask
├── requirements.txt    # Dependências Python
├── Procfile            # Comando de start para Render/Heroku
├── render.yaml         # Config do Render (opcional)
├── check_config.py     # Validador de configuração
├── .env.example        # Template de variáveis de ambiente
├── .gitignore
├── templates/
│   ├── login.html      # Página de login
│   ├── dashboard.html  # Interface de conversão
│   ├── admin.html      # Painel de gerenciamento de usuários
│   └── player.html     # Player de áudio/vídeo
└── static/
    ├── style.css
    ├── app.js
    └── logo.svg
```

---

## Segurança

- Senhas armazenadas com hash bcrypt (via `werkzeug`)
- Rate limiting no login: 10 tentativas/minuto por IP
- Cookies de sessão com `HttpOnly`, `SameSite=Lax` e `Secure` (em produção)
- Uploads validados com `secure_filename`
- Sem cadastro público — apenas admin cadastra usuários

---

## Variáveis geradas automaticamente pelo Render

Se usar o `render.yaml`, o Render pode gerar `SECRET_KEY` automaticamente (`generateValue: true`). A `ADMIN_PASS` deve ser definida manualmente no dashboard por segurança.
