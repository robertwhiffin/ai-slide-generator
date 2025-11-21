# Quickstart Folder

This folder contains everything a new developer needs to get the AI Slide Generator running quickly.

## Contents

### 📘 Documentation

- **[QUICKSTART.md](./QUICKSTART.md)** - Get running in 5 minutes (start here!)
- **[PREREQUISITES.md](./PREREQUISITES.md)** - Detailed installation guide for all prerequisites
- **[TROUBLESHOOTING.md](./TROUBLESHOOTING.md)** - Solutions to common issues

### 🔧 Scripts

- **[setup_database.sh](./setup_database.sh)** - Automated database setup script
  - Creates PostgreSQL database
  - Runs migrations
  - Initializes default configuration

### 📄 Configuration Templates

- **[../.env.example](../.env.example)** - Environment configuration template

## Quick Navigation

### I'm brand new → Start here:
1. [PREREQUISITES.md](./PREREQUISITES.md) - Install Python, PostgreSQL, Node.js
2. [QUICKSTART.md](./QUICKSTART.md) - Set up and run the application
3. [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) - If you hit issues

### I have prerequisites installed → Skip to:
1. [QUICKSTART.md](./QUICKSTART.md) - Steps 2-5 only

### Something's broken → Go to:
1. [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) - Find your error message

## Usage

### Automated Setup (Recommended)
```bash
# 1. Copy environment template
cp .env.example .env

# 2. Edit with your credentials
nano .env

# 3. Run database setup
chmod +x quickstart/setup_database.sh
./quickstart/setup_database.sh

# 4. Start application
./start_app.sh
```

### Manual Setup
If you prefer manual control, see [QUICKSTART.md](./QUICKSTART.md) for step-by-step instructions.

## Support

- **Questions about installation?** → [PREREQUISITES.md](./PREREQUISITES.md)
- **Application not working?** → [TROUBLESHOOTING.md](./TROUBLESHOOTING.md)
- **Want to understand the system?** → [../README.md](../README.md)
- **Development guides?** → [../docs/technical/](../docs/technical/)

## Contributing

Found an issue or have a suggestion for the quickstart guides?
1. Check [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) first
2. Review [../docs/](../docs/) for detailed documentation
3. Open an issue or PR with your feedback

---

**Time to first slide: 5 minutes** ⏱️

