# Beacon Innovations - Troubleshooting Guide

**READ THIS FIRST** when something isn't working.

---

## Quick Checks

Before diving into specific issues:

1. **Is the virtual environment activated?**
   ```bash
   source venv/bin/activate  # Mac/Linux
   venv\Scripts\activate     # Windows
   ```

2. **Are migrations up to date?**
   ```bash
   python manage.py migrate
   ```

3. **Does the .env file exist with required variables?**
   ```bash
   cat .env  # Check contents
   ```

4. **Are there any syntax errors?**
   ```bash
   python manage.py check
   ```

---

## Known Issues

### Issue #1: ModuleNotFoundError for new app

**Symptom:**
```
ModuleNotFoundError: No module named 'finance'
```

**Cause:** App not added to INSTALLED_APPS.

**Solution:**
Add the app to `beaconinnovation/settings.py`:
```python
INSTALLED_APPS = [
    # ... existing apps
    'finance',
]
```

---

### Issue #2: Cloudinary upload fails

**Symptom:**
```
cloudinary.exceptions.Error: Must supply cloud_name
```

**Cause:** Cloudinary environment variables not set.

**Solution:**
Add to `.env`:
```bash
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret
```

---

### Issue #3: Tesseract not found

**Symptom:**
```
pytesseract.pytesseract.TesseractNotFoundError: tesseract is not installed
```

**Cause:** Tesseract OCR engine not installed on system.

**Solution:**
```bash
# Mac
brew install tesseract

# Ubuntu/Debian
sudo apt-get install tesseract-ocr

# Windows
# Download installer from https://github.com/UB-Mannheim/tesseract/wiki
```

---

### Issue #4: Database migration conflicts

**Symptom:**
```
django.db.migrations.exceptions.InconsistentMigrationHistory
```

**Cause:** Migration applied out of order or deleted.

**Solution:**
1. Check migration status: `python manage.py showmigrations`
2. If local dev, can reset: `rm db.sqlite3` then `python manage.py migrate`
3. For production, manually resolve with `--fake` flags

---

### Issue #5: CSRF verification failed

**Symptom:**
```
Forbidden (403) CSRF verification failed.
```

**Cause:** CSRF_TRUSTED_ORIGINS not configured for domain.

**Solution:**
Add to `settings.py`:
```python
CSRF_TRUSTED_ORIGINS = [
    'https://beacon-innovation.com',
    'https://www.beacon-innovation.com',
]
```

---

### Issue #6: Static files not loading

**Symptom:**
CSS/JS files return 404 in production.

**Cause:** Static files not collected.

**Solution:**
```bash
python manage.py collectstatic --noinput
```

Verify `STATIC_ROOT` and `STATIC_URL` in settings.

---

### Issue #7: Railway deployment fails

**Symptom:**
Build fails on Railway with dependency errors.

**Cause:** Missing system dependencies or incorrect Python version.

**Solution:**
1. Check `runtime.txt` has correct Python version
2. For Tesseract, add to `nixpacks.toml`:
   ```toml
   [phases.setup]
   nixPkgs = ["tesseract"]
   ```

---

### Issue #8: API returns 401 Unauthorized

**Symptom:**
```
{"error": "Invalid API key"}
```

**Cause:** Claude API key header missing or incorrect.

**Solution:**
Include header in request:
```bash
curl -H "X-Claude-API-Key: your-api-key" https://...
```

Verify key matches `CLAUDE_API_KEY` environment variable.

---

### Issue #9: Receipt OCR returns empty text

**Symptom:**
OCR processes but returns no text.

**Cause:** Image quality too low or wrong format.

**Solution:**
1. Check image is not corrupted
2. Verify image has sufficient resolution (300 DPI recommended)
3. Try preprocessing: convert to grayscale, increase contrast
4. Check Tesseract can read file type

---

### Issue #10: Decimal precision errors

**Symptom:**
```
decimal.InvalidOperation: quantize result has too many digits
```

**Cause:** Amount field receiving too many decimal places.

**Solution:**
Round before saving:
```python
from decimal import Decimal, ROUND_HALF_UP
amount = amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
```

---

## Adding New Issues

When you encounter a new issue:

1. Document the symptom (exact error message)
2. Identify the cause
3. Provide the solution
4. Add to this file with next issue number

---

## Getting Help

If an issue isn't listed here:

1. Check Django documentation: https://docs.djangoproject.com/
2. Check error message in search engine
3. Review recent changelog entries for related changes
4. Add new issue to this file once resolved

---

*Last updated: 2026-01-08*
