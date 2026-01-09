# Beacon Innovations - Deployment Guide

This guide covers deploying Beacon Innovations to Railway.

---

## Overview

| Item | Value |
|------|-------|
| **Platform** | Railway |
| **Domain** | https://beacon-innovation.com |
| **Database** | PostgreSQL (Railway managed) |
| **File Storage** | Cloudinary |
| **Python Version** | See `runtime.txt` |

---

## Environment Variables

Set these in Railway dashboard:

### Required

```bash
# Django
SECRET_KEY=generate-a-secure-random-key
DEBUG=False
ALLOWED_HOSTS=beacon-innovation.com,www.beacon-innovation.com,.up.railway.app

# Database (auto-set by Railway PostgreSQL)
DATABASE_URL=postgresql://...

# Cloudinary
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

# Admin Console
CLAUDE_API_KEY=your-secure-api-key
```

### Optional

```bash
# Finance module
FINANCE_TAX_ALERT_THRESHOLD=1000
FINANCE_RECEIPT_MAX_SIZE_MB=10
```

---

## Railway Configuration

### Procfile

```
web: gunicorn beaconinnovation.wsgi --log-file -
```

### runtime.txt

```
python-3.12.x
```

### nixpacks.toml

For Tesseract OCR support:

```toml
[phases.setup]
nixPkgs = ["tesseract", "tesseract-data-eng"]

[phases.install]
cmds = ["pip install -r requirements.txt"]
```

---

## Deployment Process

### Automatic (GitHub Integration)

1. Railway watches the `main` branch
2. Push to `main` triggers automatic deploy
3. Railway runs:
   - Install dependencies
   - Collect static files
   - Run migrations (if configured)
   - Start Gunicorn

### Manual Deploy

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Deploy
railway up
```

---

## Database Migrations

### Automatic

Add to `railway.json` or use Railway's deploy command:

```json
{
  "deploy": {
    "startCommand": "python manage.py migrate && gunicorn beaconinnovation.wsgi"
  }
}
```

### Manual

```bash
# Via Railway CLI
railway run python manage.py migrate

# Or via Railway shell
railway shell
python manage.py migrate
```

---

## Static Files

Static files are collected during deploy:

```bash
python manage.py collectstatic --noinput
```

### Configuration in settings.py

```python
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Whitenoise for serving static files
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Add this
    # ... rest of middleware
]

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
```

---

## Domain Configuration

### Railway Custom Domain

1. Go to Railway project settings
2. Add custom domain: `beacon-innovation.com`
3. Add CNAME record at your DNS provider:
   - Name: `@` or `beacon-innovation.com`
   - Value: `<your-railway-app>.up.railway.app`

### SSL

Railway provides automatic SSL via Let's Encrypt.

### HTTPS Redirect

In `settings.py` (production):

```python
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

---

## Monitoring

### Railway Logs

```bash
# Via CLI
railway logs

# Or in Railway dashboard
```

### Health Check

Create a simple health endpoint:

```python
# views.py
from django.http import JsonResponse

def health_check(request):
    return JsonResponse({'status': 'ok'})

# urls.py
path('health/', health_check, name='health_check'),
```

---

## Rollback

If a deployment fails:

1. Go to Railway dashboard
2. Select the project
3. Go to Deployments
4. Click on previous successful deployment
5. Click "Rollback"

---

## Troubleshooting Deployment

### Build Fails

1. Check Railway build logs
2. Common causes:
   - Missing dependency in `requirements.txt`
   - Python version mismatch
   - System dependency missing (add to nixpacks.toml)

### App Crashes on Start

1. Check Railway runtime logs
2. Common causes:
   - Missing environment variable
   - Database connection failed
   - Import error in code

### Static Files 404

1. Verify `collectstatic` ran during deploy
2. Check `STATIC_ROOT` and `STATIC_URL` settings
3. Verify Whitenoise is configured

### Database Connection Refused

1. Check `DATABASE_URL` is set
2. Verify PostgreSQL service is running
3. Check for connection limit issues

---

## Scheduled Tasks

For recurring transaction generation and tax alert calculation:

### Option 1: Railway Cron (Recommended)

Create a separate service in Railway with cron schedule:

```bash
# Generate recurring transactions daily at 6 AM UTC
0 6 * * * python manage.py generate_recurring

# Calculate tax alerts on 1st of each month
0 0 1 * * python manage.py calculate_tax_alerts
```

### Option 2: Django-APScheduler

Add scheduler to run within the Django process (less reliable for production).

---

## Backup Strategy

### Database

Railway PostgreSQL includes automatic backups. To create manual backup:

```bash
railway run pg_dump $DATABASE_URL > backup.sql
```

### Receipts

Cloudinary handles backup for uploaded files. Configure Cloudinary backup settings in their dashboard.

---

*Last updated: 2026-01-08*
