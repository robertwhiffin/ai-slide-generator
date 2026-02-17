# Prerequisites Installation Guide

Detailed guide for installing all prerequisites needed to run the AI Slide Generator.

## Overview

You'll need:
- Python 3.10 or higher
- PostgreSQL 14 or higher
- Node.js 18 or higher
- Databricks workspace with access

**Estimated setup time:** 15-30 minutes

---

## Python Installation

### Check Current Version
```bash
python3 --version
# Should show: Python 3.10.x or higher
```

### macOS
```bash
# Using Homebrew (recommended)
brew install python@3.11

# Verify installation
python3.11 --version
```

### Ubuntu/Debian
```bash
# Update package list
sudo apt-get update

# Install Python 3.11
sudo apt-get install -y python3.11 python3.11-venv python3-pip

# Set as default (optional)
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# Verify
python3 --version
```

### Windows
1. Download installer from [python.org](https://www.python.org/downloads/)
2. Run installer
3. ✅ Check "Add Python to PATH"
4. Verify in PowerShell:
   ```powershell
   python --version
   ```

---

## PostgreSQL Installation

### Check Current Version
```bash
psql --version
# Should show: psql (PostgreSQL) 14.x or higher
```

### macOS

**Option 1: Homebrew (Recommended)**
```bash
# Install PostgreSQL 14
brew install postgresql@14

# Start PostgreSQL service
brew services start postgresql@14

# Verify it's running
pg_isready

# Add to PATH (add to ~/.zshrc or ~/.bash_profile)
echo 'export PATH="/opt/homebrew/opt/postgresql@14/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

**Option 2: Postgres.app**
1. Download from [postgresapp.com](https://postgresapp.com/)
2. Move to Applications folder
3. Open and click "Initialize"
4. Add to PATH:
   ```bash
   echo 'export PATH="/Applications/Postgres.app/Contents/Versions/14/bin:$PATH"' >> ~/.zshrc
   source ~/.zshrc
   ```

### Ubuntu/Debian
```bash
# Add PostgreSQL repository
sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list'
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | sudo apt-key add -

# Update and install
sudo apt-get update
sudo apt-get install -y postgresql-14 postgresql-contrib-14

# Start PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql  # Start on boot

# Create user for your account
sudo -u postgres createuser -s $(whoami)

# Verify
pg_isready
```

### Windows
1. Download installer from [postgresql.org/download/windows](https://www.postgresql.org/download/windows/)
2. Run installer (use default port 5432)
3. Remember the password you set for `postgres` user
4. Install pgAdmin (recommended for GUI management)
5. Verify in PowerShell:
   ```powershell
   psql --version
   ```

### Docker Alternative (All Platforms)
```bash
# Run PostgreSQL in Docker
docker run -d \
  --name postgres-ai-slides \
  -e POSTGRES_PASSWORD=mysecretpassword \
  -e POSTGRES_DB=ai_slide_generator \
  -p 5432:5432 \
  postgres:14

# Verify
docker ps | grep postgres

# Connection string for .env:
# DATABASE_URL=postgresql://postgres:mysecretpassword@localhost:5432/ai_slide_generator
```

---

## Node.js & npm Installation

### Check Current Version
```bash
node --version
# Should show: v18.x.x or higher

npm --version
# Should show: 9.x.x or higher
```

### macOS
```bash
# Using Homebrew
brew install node@18

# Or install latest LTS
brew install node

# Verify
node --version
npm --version
```

### Ubuntu/Debian
```bash
# Install from NodeSource repository (recommended)
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

# Verify
node --version
npm --version
```

### Windows
1. Download installer from [nodejs.org](https://nodejs.org/)
2. Choose LTS version (recommended)
3. Run installer with defaults
4. Verify in PowerShell:
   ```powershell
   node --version
   npm --version
   ```

### Alternative: nvm (Version Manager)

**macOS/Linux:**
```bash
# Install nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash

# Reload shell
source ~/.zshrc  # or ~/.bashrc

# Install Node.js 18
nvm install 18
nvm use 18
nvm alias default 18

# Verify
node --version
```

**Windows:**
Use [nvm-windows](https://github.com/coreybutler/nvm-windows)

---

## Databricks Workspace Setup

### Account Requirements
- Active Databricks workspace (AWS, Azure, or GCP)
- Admin or appropriate permissions to:
  - Create model serving endpoints
  - Create Genie spaces
  - Generate personal access tokens

### 1. Authenticate with Databricks

**Option A — Browser SSO (recommended, no PAT needed):**
When you first open the app at http://localhost:3000, a welcome screen will ask for your workspace URL. Enter it, and sign in via your browser using your normal Databricks credentials (SSO). No access token or `.env` file required.

**Option B — Personal Access Token (traditional):**
1. **Login** to your Databricks workspace
2. **Click** your user icon (top right)
3. **Go to** Settings → Developer
4. **Click** "Access Tokens" or "Manage" under Access Tokens
5. **Click** "Generate New Token"
6. **Set** comment (e.g., "AI Slide Generator")
7. **Set** lifetime (e.g., 90 days or no lifetime)
8. **Click** "Generate"
9. **Copy** the token immediately (you won't see it again!)
10. **Save** to `.env` file as `DATABRICKS_TOKEN`

### 2. Verify Model Serving Endpoint

The application needs access to an LLM endpoint:

1. **Go to** Serving → Model Serving
2. **Verify** you have access to an endpoint (e.g., `databricks-claude-sonnet-4-5`)
3. **Note** the endpoint name for configuration

Default endpoints in Databricks:
- `databricks-claude-sonnet-4-5`
- `databricks-llama-3-1-70b-instruct`
- `databricks-mixtral-8x7b-instruct`

### 3. Create/Access Genie Space

Genie provides natural language SQL queries:

1. **Go to** Data Intelligence → Genie
2. **Create** or select a Genie space
3. **Note** the Space ID:
   - Found in URL: `...databricks.com/genie/spaces/{space-id}`
   - Or use existing space ID

### 4. Get Workspace URL

Your workspace URL format:
- AWS: `https://dbc-xxxxx.cloud.databricks.com`
- Azure: `https://adb-xxxxx.azuredatabricks.net`
- GCP: `https://xxxxx.gcp.databricks.com`

**Find it:**
- Browser address bar when logged in
- Invitation email
- Databricks account console

---

## Verification

Once everything is installed, verify:

### Python
```bash
python3 --version
# ✅ Python 3.10.x or higher

python3 -m pip --version
# ✅ pip 23.x or higher

python3 -m venv --help
# ✅ Should show venv help
```

### PostgreSQL
```bash
psql --version
# ✅ psql (PostgreSQL) 14.x or higher

pg_isready
# ✅ Shows "accepting connections"

createdb test_db
psql -l | grep test_db
dropdb test_db
# ✅ Can create and drop databases
```

### Node.js
```bash
node --version
# ✅ v18.x.x or higher

npm --version
# ✅ 9.x.x or higher

npm install -g npm  # Update npm (optional)
```

### Databricks
```bash
# Test connection (replace with your values)
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="dapi...your-token"

curl -H "Authorization: Bearer $DATABRICKS_TOKEN" \
     "$DATABRICKS_HOST/api/2.0/clusters/list"

# ✅ Should return JSON (even if empty list)
# ❌ If error, check token and URL
```

---

## Common Installation Issues

### Python: "command not found: python3"
- **macOS:** Install via Homebrew
- **Linux:** Install via apt/yum
- **Windows:** Add Python to PATH during installation

### PostgreSQL: "role 'username' does not exist"
```bash
# Create role
sudo -u postgres createuser -s $(whoami)
```

### PostgreSQL: "could not connect to server"
```bash
# Check if running
pg_isready

# Start service
# macOS: brew services start postgresql@14
# Linux: sudo systemctl start postgresql
```

### Node: "EACCES: permission denied"
```bash
# Fix npm permissions
mkdir ~/.npm-global
npm settings set prefix '~/.npm-global'
echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.zshrc
source ~/.zshrc
```

### Databricks: "Authentication failed"
- Verify token is correct (no spaces/quotes)
- Ensure token hasn't expired
- Check workspace URL format (must include `https://`)

---

## Next Steps

Once all prerequisites are installed:

1. **Continue to Quick Start:** [QUICKSTART.md](./QUICKSTART.md)
2. **Or jump directly to setup:**
   ```bash
   cd ai-slide-generator
   cp .env.example .env
   # Edit .env with your credentials
   ./quickstart/setup_database.sh
   ./start_app.sh
   ```

---

## Additional Tools (Optional)

### Database Management
- **pgAdmin:** GUI for PostgreSQL ([pgadmin.org](https://www.pgadmin.org/))
- **DBeaver:** Universal database tool ([dbeaver.io](https://dbeaver.io/))

### Development Tools
- **VS Code:** Recommended editor ([code.visualstudio.com](https://code.visualstudio.com/))
- **Git:** Version control ([git-scm.com](https://git-scm.com/))
- **uv:** Fast Python package manager ([astral.sh/uv](https://astral.sh/uv))

### Python Virtual Environment Managers
- **pyenv:** Python version manager ([github.com/pyenv/pyenv](https://github.com/pyenv/pyenv))
- **pipenv:** Package and venv manager
- **poetry:** Dependency management

