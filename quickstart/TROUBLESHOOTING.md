# Troubleshooting Guide

Common issues and solutions for the AI Slide Generator.

## Table of Contents

- [Installation Issues](#installation-issues)
- [Database Issues](#database-issues)
- [Databricks Connection Issues](#databricks-connection-issues)
- [Frontend Issues](#frontend-issues)
- [Backend Issues](#backend-issues)
- [Performance Issues](#performance-issues)

---

## Installation Issues

### "No .env file found" Warning

**Problem:** Application can't find environment configuration.

**Solution:**
```bash
# Copy template and edit
cp .env.example .env
nano .env  # Add your Databricks credentials
```

### "Virtual environment not found"

**Problem:** Python virtual environment hasn't been created.

**Solution:**
```bash
# Create virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### "Command not found: alembic"

**Problem:** Dependencies not installed in virtual environment.

**Solution:**
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Database Issues

### "Database connection failed"

**Problem:** Can't connect to PostgreSQL database.

**Diagnosis:**
```bash
# Check if PostgreSQL is running
pg_isready

# Check if database exists
psql -l | grep ai_slide_generator

# Test connection manually
psql -d ai_slide_generator -c "\conninfo"
```

**Solutions:**

**1. PostgreSQL not running:**
```bash
# macOS
brew services start postgresql@14

# Linux
sudo systemctl start postgresql
sudo systemctl enable postgresql  # Start on boot
```

**2. Database doesn't exist:**
```bash
# Run setup script
./quickstart/setup_database.sh

# Or manually
createdb ai_slide_generator
```

**3. Permission issues:**
```bash
# Create PostgreSQL user (if needed)
createuser -s $(whoami)

# Or with sudo (Linux)
sudo -u postgres createuser -s $(whoami)
```

**4. Wrong DATABASE_URL:**
Check `.env` file has correct format:
```
DATABASE_URL=postgresql://localhost:5432/ai_slide_generator
```

### "Alembic migrations failed"

**Problem:** Database schema migration errors.

**Solution:**
```bash
source .venv/bin/activate

# Check current migration state
alembic current

# See migration history
alembic history

# Try upgrading again
alembic upgrade head

# If still fails, reset and retry
alembic downgrade base
alembic upgrade head
```

### "Default profile already exists"

**Problem:** Database already initialized.

**Solution:** This is normal! The database is already set up. If you need to reset:
```bash
# Reset database (WARNING: deletes all data)
dropdb ai_slide_generator
./quickstart/setup_database.sh
```

---

## Databricks Connection Issues

### "DATABRICKS_HOST and DATABRICKS_TOKEN environment variables not set"

**Problem:** Missing Databricks credentials.

**Solution:**

1. **Check .env file exists:**
   ```bash
   ls -la .env
   cat .env
   ```

2. **Verify values are set correctly:**
   ```bash
   # .env should contain (no quotes):
   DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
   DATABRICKS_TOKEN=dapi...your-token-here
   ```

3. **Test credentials:**
   ```bash
   source .env
   curl -H "Authorization: Bearer $DATABRICKS_TOKEN" \
        "$DATABRICKS_HOST/api/2.0/clusters/list"
   ```

### "DATABRICKS_HOST should start with https://"

**Problem:** Invalid workspace URL format.

**Solution:** Ensure your `.env` has:
```bash
# Correct
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com

# Wrong
DATABRICKS_HOST=your-workspace.cloud.databricks.com
DATABRICKS_HOST=http://your-workspace.cloud.databricks.com
```

### "Authentication failed"

**Problem:** Invalid or expired Databricks token.

**Solution:**

1. **Generate new token:**
   - Go to Databricks workspace
   - Click User icon → Settings
   - Developer → Access Tokens
   - Generate New Token
   - Copy and update `.env`

2. **Check token format:**
   - Should start with `dapi`
   - No spaces or quotes
   - Full token copied

### "Genie space not found"

**Problem:** Configured Genie space doesn't exist or you don't have access.

**Solution:**

1. **Verify Genie space ID:**
   ```bash
   # Check config in database
   psql -d ai_slide_generator -c "SELECT space_id, space_name FROM config_genie_spaces;"
   ```

2. **List available spaces:**
   ```bash
   source .venv/bin/activate
   python scripts/test_endpoint.py
   ```

3. **Update space ID:**
   - Find correct space ID in Databricks workspace
   - Update in web UI (Settings → Genie Spaces)
   - Or update database directly

---

## Frontend Issues

### "Frontend won't start"

**Problem:** npm/node issues.

**Solution:**
```bash
cd frontend

# Clear and reinstall
rm -rf node_modules package-lock.json
npm install

# Try starting
npm run dev
```

### "Port 3000 already in use"

**Problem:** Another process using port 3000.

**Solution:**
```bash
# Find and kill process
lsof -ti:3000 | xargs kill -9

# Or use different port
cd frontend
npm run dev -- --port 3001
```

### "Failed to fetch from backend"

**Problem:** Frontend can't reach backend API.

**Diagnosis:**
```bash
# Check backend is running
curl http://localhost:8000/api/health

# Check backend logs
tail -f logs/backend.log
```

**Solutions:**

1. **Backend not running:**
   ```bash
   ./start_app.sh
   ```

2. **CORS issues:**
   Check `src/api/main.py` has correct CORS configuration

3. **Wrong API URL:**
   Check `frontend/.env` or `vite.config.ts`

### "Slides not rendering"

**Problem:** Chart.js or HTML issues.

**Solutions:**

1. **Check browser console** for JavaScript errors
2. **View raw HTML** to see what AI generated
3. **Check backend logs** for parsing errors
4. **Try regenerating** slides with simpler prompt

---

## Backend Issues

### "Port 8000 already in use"

**Problem:** Another process using port 8000.

**Solution:**
```bash
# Find and kill process
lsof -ti:8000 | xargs kill -9

# Or start on different port
source .venv/bin/activate
uvicorn src.api.main:app --reload --port 8001
```

### "Import errors" or "Module not found"

**Problem:** Dependencies not installed or virtual environment not activated.

**Solution:**
```bash
# Activate virtual environment
source .venv/bin/activate

# Verify it's activated (should show .venv in prompt)
which python

# Reinstall dependencies
pip install -r requirements.txt
```

### "MLflow connection errors"

**Problem:** MLflow tracking issues.

**Solution:**

1. **Check MLflow configuration:**
   ```bash
   psql -d ai_slide_generator -c "SELECT experiment_name FROM config_mlflow;"
   ```

2. **Verify experiment path exists** in Databricks workspace

3. **Test MLflow connection:**
   ```bash
   source .venv/bin/activate
   python -c "import mlflow; print(mlflow.get_tracking_uri())"
   ```

### "Agent generation timeout"

**Problem:** LLM calls taking too long.

**Solutions:**

1. **Check model endpoint** is running in Databricks
2. **Reduce max_slides** (try 5 instead of 10)
3. **Simplify prompt** (less complex requests)
4. **Check backend logs** for specific errors:
   ```bash
   tail -f logs/backend.log
   ```

---

## Performance Issues

### "Slow slide generation"

**Causes & Solutions:**

1. **Large number of slides:**
   - Reduce `max_slides` to 5-8
   - Split into multiple requests

2. **Complex Genie queries:**
   - Check Genie query performance in Databricks
   - Simplify data requests

3. **Model endpoint throttling:**
   - Check Databricks model serving metrics
   - Consider using higher-tier endpoint

### "High memory usage"

**Solutions:**

1. **Restart application:**
   ```bash
   ./stop_app.sh
   ./start_app.sh
   ```

2. **Clear MLflow artifacts:**
   ```bash
   rm -rf mlruns/
   ```

3. **Check for memory leaks** in logs

### "Database growing large"

**Solution:**
```bash
# Check database size
psql -d ai_slide_generator -c "SELECT pg_size_pretty(pg_database_size('ai_slide_generator'));"

# Vacuum database
psql -d ai_slide_generator -c "VACUUM FULL;"

# Archive old config history
psql -d ai_slide_generator -c "DELETE FROM config_history WHERE timestamp < NOW() - INTERVAL '30 days';"
```

---

## Advanced Debugging

### Enable Debug Logging

**Backend:**
```python
# In src/utils/logging_config.py, change level:
logging.basicConfig(level=logging.DEBUG)
```

**Frontend:**
```typescript
// In src/services/api.ts, add console logs
console.log('API request:', request);
console.log('API response:', response);
```

### Database Query Debugging

```bash
# Connect to database
psql -d ai_slide_generator

# Check current profile
SELECT * FROM config_profiles WHERE is_default = true;

# Check all configuration
SELECT p.name, ai.llm_endpoint, g.space_name
FROM config_profiles p
JOIN config_ai_infra ai ON p.id = ai.profile_id
JOIN config_genie_spaces g ON p.id = g.profile_id;

# View recent config changes
SELECT * FROM config_history ORDER BY timestamp DESC LIMIT 10;
```

### Network Debugging

```bash
# Test Databricks connection
curl -v -H "Authorization: Bearer $DATABRICKS_TOKEN" \
     "$DATABRICKS_HOST/api/2.0/clusters/list"

# Test backend API
curl -v http://localhost:8000/api/health

# Test with actual chat request
curl -v -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Create 3 slides about testing", "max_slides": 3}'
```

---

## Getting More Help

If you're still stuck:

1. **Check logs:**
   - Backend: `logs/backend.log`
   - Frontend: `logs/frontend.log`
   - Browser console (F12)

2. **Run tests:**
   ```bash
   source .venv/bin/activate
   pytest -v
   ```

3. **Verify installation:**
   ```bash
   # Check all services
   ./start_app.sh
   curl http://localhost:8000/api/health
   curl http://localhost:3000
   ```

4. **Review documentation:**
   - [README.md](../README.md)
   - [Backend Overview](../docs/technical/backend-overview.md)
   - [Frontend Overview](../docs/technical/frontend-overview.md)

5. **Open an issue** on GitHub with:
   - Error messages
   - Relevant logs
   - Steps to reproduce
   - Environment details (OS, Python version, etc.)

