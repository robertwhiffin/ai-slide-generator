# Deployment Setup Guide

## Phase A Implementation Complete ✅

The core deployment infrastructure is now in place. Here's what was created:

### Files Created

1. **`config/deployment.example.yaml`** - Template deployment configuration
2. **`infra/__init__.py`** - Package initialization
3. **`infra/config.py`** - YAML configuration loader
4. **`infra/deploy.py`** - Main deployment script
5. **`app.yaml`** - Databricks Apps runtime configuration

### Files Updated

1. **`requirements.txt`** - Pinned versions for production
2. **`src/api/main.py`** - Production frontend serving
3. **`config/deployment.yaml`** - Deployment configuration (version controlled)

## Getting Started

### 1. Configure Databricks CLI

Set up your Databricks credentials:

```bash
databricks configure --token
# Enter your workspace URL and personal access token
```

Or manually edit `~/.databrickscfg`:

```ini
[DEFAULT]
host = https://your-workspace.cloud.databricks.com
token = dapi...

[production]
host = https://prod-workspace.cloud.databricks.com
token = dapi...
```

### 2. Configure Deployment Settings

Edit `config/deployment.yaml` to customize for your workspace:
- Update workspace paths (replace placeholder usernames/paths)
- Configure permissions (users/groups)
- Adjust resource allocations
- Optionally use `--profile` flag instead of environment variables for deployment

**Note**: `config/deployment.yaml` is version controlled and contains no secrets. Use `config/deployment.example.yaml` as a reference for the structure.

**Example customization:**

```yaml
environments:
  development:
    workspace_path: "/Workspace/Users/your.email@company.com/apps/dev/ai-slide-generator"
    databricks_profile: "DEFAULT"
    permissions:
      - user_name: "your.email@company.com"
        permission_level: "CAN_MANAGE"
```

### 3. Test Deployment Script

Validate configuration without deploying:

```bash
python -m db_app_deployment.deploy --create --env development --dry-run
```

## Deployment Commands

### Create New App

```bash
# Deploy to development
python -m db_app_deployment.deploy --create --env development

# Deploy to production
python -m db_app_deployment.deploy --create --env production
```

### Update Existing App

```bash
# Update development app
python -m db_app_deployment.deploy --update --env development

# Update production app
python -m db_app_deployment.deploy --update --env production
```

### Delete App

```bash
python -m db_app_deployment.deploy --delete --env development
```

### Advanced Options

```bash
# Use specific Databricks profile
python -m db_app_deployment.deploy --create --env production --profile my-workspace

# Dry run (validation only)
python -m db_app_deployment.deploy --create --env production --dry-run
```

## What Happens During Deployment

1. **Load Configuration** - Reads `config/deployment.yaml` for environment
2. **Build Python Wheel** - Creates `.whl` package from source using `python -m build`
3. **Build Frontend** - Runs `npm install && npm run build` in `frontend/`
4. **Create Staging** - Organizes wheel, config files, and frontend dist
5. **Upload Files** - Uploads all files to Databricks workspace (maintains directory structure)
6. **Deploy App** - Creates/updates Databricks App (installs wheel on startup)
7. **Set Permissions** - Configures user/group access
8. **Cleanup** - Removes temporary staging directory and build artifacts

## Local Testing (Production Mode)

Test production behavior locally before deploying:

```bash
# Build frontend
cd frontend && npm run build && cd ..

# Set production environment
export ENVIRONMENT=production
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="dapi..."

# Start server (serves frontend from dist/)
uvicorn src.api.main:app --host 0.0.0.0 --port 8080

# Test at http://localhost:8080
```

**What to verify:**
- [ ] Frontend loads from FastAPI (not separate server)
- [ ] API calls work without CORS errors
- [ ] All slides features work
- [ ] No console errors

## Troubleshooting

### Python Wheel Build Fails

```bash
# Install build tool
pip install build

# Or install dev dependencies
pip install -r requirements-dev.txt

# Manually test wheel build
python -m build --wheel
```

### Frontend Build Fails

```bash
# Ensure Node.js and npm are installed
node --version
npm --version

# Install dependencies
cd frontend && npm install
```

### Upload Fails

- Check Databricks token is valid
- Verify workspace path permissions
- Ensure profile exists in `~/.databrickscfg`

### App Won't Start

- Check `app.yaml` is valid
- Verify all dependencies in `requirements.txt` are compatible
- Review app logs in Databricks workspace

### Configuration Not Found

```bash
# Ensure you copied the example
ls -la settings/deployment.yaml

# If missing, copy the example
cp settings/deployment.example.yaml settings/deployment.yaml
```

## Environment Differences

| Setting | Development | Production |
|---------|------------|------------|
| **App Name** | `ai-slide-generator-dev` | `ai-slide-generator` |
| **Location** | Personal workspace | Shared workspace |
| **Compute Size** | MEDIUM | LARGE |
| **Permissions** | Only you | All users |
| **Profile** | DEFAULT | production |

**Compute Size Options:**
- **MEDIUM**: Balanced compute for development/staging
- **LARGE**: More compute for production workloads
- **LIQUID**: Auto-scaling compute (adjusts based on load)

## Next Steps

After Phase A is working:

1. **Phase B: User Authorization**
   - Implement `src/api/middleware/auth.py`
   - Extract user info from headers
   - Update logging with user context

2. **Phase C: Advanced Features**
   - Rollback functionality
   - Multiple deployment targets
   - Automated testing

## Files to Commit

**Do commit:**
- ✅ `config/deployment.example.yaml`
- ✅ `infra/__init__.py`
- ✅ `infra/config.py`
- ✅ `infra/deploy.py`
- ✅ `app.yaml`
- ✅ `requirements.txt`
- ✅ `requirements-dev.txt`
- ✅ `src/api/main.py`
- ✅ `.gitignore`

**Don't commit:**
- ❌ `config/deployment.yaml` (user-specific, gitignored)
- ❌ `frontend/dist/` (built artifacts)
- ❌ `dist/` (Python wheel builds)
- ❌ `build/` (Python build artifacts)
- ❌ `*.whl` (wheel files)

## Support

If you encounter issues:
1. Run with `--dry-run` to validate configuration
2. Check Databricks workspace logs
3. Verify all prerequisites are installed
4. Review this guide and the deployment plan

---

**Phase A Complete!** 🎉

You can now deploy the AI Slide Generator to Databricks Apps with a single command.

