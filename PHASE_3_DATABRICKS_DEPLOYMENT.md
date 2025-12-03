# Phase 3: Databricks Apps Deployment

## Goal
Deploy the application to Databricks Apps with proper header handling, logging, and production configuration. Still single-session, but fully operational in the Databricks environment.

## Prerequisites
- ✅ Phase 1 and 2 complete and tested
- ✅ Application working locally
- ✅ Databricks workspace access
- ✅ Databricks Apps enabled

## Success Criteria
- ✅ App deploys to Databricks Apps successfully
- ✅ User authentication via X-Forwarded-* headers works
- ✅ All logs go to stdout/stderr (JSON format)
- ✅ Frontend served from same origin as backend (no CORS issues)
- ✅ Application accessible via Databricks Apps URL
- ✅ All features from Phase 1 & 2 work in production

## Architecture Changes for Phase 3
- **Backend**: Add middleware for header extraction, structured logging
- **Frontend**: Build static assets, serve from FastAPI
- **Deployment**: Create app.yaml, build process
- **Configuration**: Environment-based settings
- **Logging**: JSON format to stdout/stderr

---

## Implementation Steps

### Step 1: Backend - User Middleware (Estimated: 2-3 hours)

#### 1.1 Create Auth Middleware

**`src/api/middleware/auth.py`**

```python
"""
User authentication middleware for Databricks Apps.

Extracts user information from X-Forwarded-* headers in production,
falls back to environment variables in local development.
"""

import os
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Dict

class UserMiddleware(BaseHTTPMiddleware):
    """
    Extract user information from headers and attach to request state.
    
    Production (Databricks Apps): Uses X-Forwarded-* headers
    Development (local): Uses environment variables
    """
    
    async def dispatch(self, request: Request, call_next):
        # Extract user info from headers (Databricks Apps)
        user_id = request.headers.get("x-forwarded-user")
        email = request.headers.get("x-forwarded-email")
        username = request.headers.get("x-forwarded-preferred-username")
        ip_address = request.headers.get("x-real-ip")
        request_id = request.headers.get("x-request-id")
        
        # Fallback for local development
        if not user_id:
            environment = os.getenv("ENVIRONMENT", "development")
            if environment == "development":
                user_id = os.getenv("DEV_USER_ID", "dev_user@local.dev")
                email = os.getenv("DEV_USER_EMAIL", "dev_user@local.dev")
                username = os.getenv("DEV_USERNAME", "Dev User")
                ip_address = "127.0.0.1"
                request_id = "dev-request-id"
            else:
                # Production without headers - should not happen
                user_id = "unknown@databricks.com"
                email = "unknown@databricks.com"
                username = "Unknown User"
        
        # Attach user info to request state
        request.state.user = {
            "user_id": user_id,
            "email": email,
            "username": username,
            "ip_address": ip_address,
        }
        
        request.state.request_id = request_id or "unknown"
        
        response = await call_next(request)
        
        # Add request ID to response headers for tracking
        if request_id:
            response.headers["X-Request-Id"] = request_id
        
        return response
```

#### 1.2 Create Logging Middleware

**`src/api/middleware/logging.py`**

```python
"""
Structured logging middleware for Databricks Apps.

All logs go to stdout (INFO/DEBUG) or stderr (WARNING/ERROR/CRITICAL)
in JSON format for easy parsing.
"""

import logging
import sys
import json
import time
from datetime import datetime
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

class JSONFormatter(logging.Formatter):
    """Format log records as JSON."""
    
    def format(self, record):
        log_obj = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'message': record.getMessage(),
            'logger': record.name,
        }
        
        # Add extra fields if present
        if hasattr(record, 'request_id'):
            log_obj['request_id'] = record.request_id
        if hasattr(record, 'user_id'):
            log_obj['user_id'] = record.user_id
        if hasattr(record, 'method'):
            log_obj['method'] = record.method
        if hasattr(record, 'path'):
            log_obj['path'] = record.path
        if hasattr(record, 'status_code'):
            log_obj['status_code'] = record.status_code
        if hasattr(record, 'latency_ms'):
            log_obj['latency_ms'] = record.latency_ms
        
        # Add exception info if present
        if record.exc_info:
            log_obj['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_obj)

def setup_logging():
    """Configure structured logging to stdout/stderr."""
    
    # Create handlers
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.addFilter(lambda record: record.levelno < logging.WARNING)
    
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    
    # Apply JSON formatter
    formatter = JSONFormatter()
    stdout_handler.setFormatter(formatter)
    stderr_handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(stdout_handler)
    root_logger.addHandler(stderr_handler)
    
    return root_logger

class LoggingMiddleware(BaseHTTPMiddleware):
    """Log all HTTP requests and responses."""
    
    def __init__(self, app, logger: logging.Logger):
        super().__init__(app)
        self.logger = logger
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Log request
        self.logger.info(
            f"Request started: {request.method} {request.url.path}",
            extra={
                'request_id': getattr(request.state, 'request_id', 'unknown'),
                'user_id': getattr(request.state, 'user', {}).get('user_id', 'unknown'),
                'method': request.method,
                'path': str(request.url.path),
            }
        )
        
        # Process request
        try:
            response = await call_next(request)
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Log response
            self.logger.info(
                f"Request completed: {request.method} {request.url.path} {response.status_code}",
                extra={
                    'request_id': getattr(request.state, 'request_id', 'unknown'),
                    'user_id': getattr(request.state, 'user', {}).get('user_id', 'unknown'),
                    'method': request.method,
                    'path': str(request.url.path),
                    'status_code': response.status_code,
                    'latency_ms': latency_ms,
                }
            )
            
            return response
            
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Log error
            self.logger.error(
                f"Request failed: {request.method} {request.url.path}",
                extra={
                    'request_id': getattr(request.state, 'request_id', 'unknown'),
                    'user_id': getattr(request.state, 'user', {}).get('user_id', 'unknown'),
                    'method': request.method,
                    'path': str(request.url.path),
                    'latency_ms': latency_ms,
                },
                exc_info=True
            )
            raise
```

#### 1.3 Update Settings

**`src/config/settings.py`** (update or create)

Add environment-based configuration:

```python
"""
Application settings with environment-based configuration.
"""

import os
from typing import Literal

class Settings:
    """Application settings."""
    
    def __init__(self):
        self.environment: Literal["development", "production"] = os.getenv("ENVIRONMENT", "development")
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")
        
        # For Phase 4: add session configuration
        # self.session_timeout_minutes: int = int(os.getenv("SESSION_TIMEOUT_MINUTES", "60"))
        # self.max_sessions_per_user: int = int(os.getenv("MAX_SESSIONS_PER_USER", "5"))

def get_settings() -> Settings:
    """Get application settings."""
    return Settings()
```

#### 1.4 Update Main App

**`src/api/main.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from pathlib import Path

from .routes import chat, slides
from .middleware.auth import UserMiddleware
from .middleware.logging import LoggingMiddleware, setup_logging
from src.core.settings import get_settings

# Setup logging first
logger = setup_logging()

settings = get_settings()

app = FastAPI(
    title="AI Slide Generator",
    description="Generate and edit slide decks using AI",
    version="1.0.0"
)

# Add middleware in order (executed bottom to top)
app.add_middleware(LoggingMiddleware, logger=logger)
app.add_middleware(UserMiddleware)

# CORS - only needed for development
if settings.environment == "development":
    logger.info("Enabling CORS for development")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Include API routers
app.include_router(chat.router)
app.include_router(slides.router)

# Serve static files (production only)
# In production, frontend is built and placed in frontend/dist/
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"

if frontend_dist.exists() and settings.environment == "production":
    logger.info("Serving frontend from", extra={"path": str(frontend_dist)})

    # Mount static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")


    # Serve index.html for all other routes (SPA routing)
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # If path starts with /api, it should have been handled by routers
        if full_path.startswith("api/"):
            return {"error": "Not found"}, 404

        # Serve index.html for all other routes
        return FileResponse(str(frontend_dist / "index.html"))


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "environment": settings.environment,
    }


logger.info("Application started", extra={"environment": settings.environment})
```

---

### Step 2: Frontend - Production Build Configuration (Estimated: 1-2 hours)

#### 2.1 Update Vite Config

**`frontend/vite.config.ts`**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  
  // Build configuration
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false, // Set to true for debugging
    
    // Optimize bundle
    rollupOptions: {
      output: {
        manualChunks: {
          // Separate vendor chunks
          'react-vendor': ['react', 'react-dom'],
          'editor': ['@monaco-editor/react'],
          'dnd': ['@dnd-kit/core', '@dnd-kit/sortable', '@dnd-kit/utilities'],
        },
      },
    },
  },
  
  // Development server
  server: {
    port: 3000,
    proxy: {
      // Proxy API requests to backend in development
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
```

#### 2.2 Update Environment Variables

**`frontend/.env.production`**

```
# In production, API is served from same origin
VITE_API_URL=
```

**`frontend/.env.development`**

```
# In development, API runs on different port
VITE_API_URL=http://localhost:8000
```

#### 2.3 Update API Client

**`frontend/src/services/api.ts`**

Update base URL logic:

```typescript
// In production (Databricks Apps), API is on same origin
// In development, API is on different port
const API_BASE_URL = import.meta.env.VITE_API_URL || '';
```

---

### Step 3: Create Databricks Apps Configuration (Estimated: 1 hour)

#### 3.1 Create app.yaml

**`app.yaml`**

```yaml
# Databricks Apps Configuration
name: ai-slide-generator
display_name: "AI Slide Generator"
description: "Generate and edit slide decks using AI and Databricks Genie"

# Command to start the application
command: ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8080"]

# Environment variables
env:
  - name: ENVIRONMENT
    value: production
  - name: LOG_LEVEL
    value: INFO
  - name: MLFLOW_TRACKING_URI
    value: databricks

# Compute resources
compute:
  size: SMALL  # Start small, scale up if needed

# Permissions
permissions:
  - level: CAN_USE
    group_name: users  # Adjust based on your workspace
```

#### 3.2 Create Build Script

**`build.sh`**

```bash
#!/bin/bash
set -e

echo "Building AI Slide Generator for Databricks Apps..."

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf deploy/
mkdir -p deploy

# Build frontend
echo "Building frontend..."
cd frontend
npm install
npm run build
cd ..

# Copy files to deploy directory
echo "Copying files to deploy..."

# Backend
cp -r src/ deploy/src/
cp -r settings/ deploy/settings/
cp requirements.txt deploy/
cp app.yaml deploy/

# Frontend (built assets)
cp -r frontend/dist/ deploy/frontend/dist/

# Create README for deployment
cat > deploy/README.md << 'EOF'
# AI Slide Generator - Deployment Package

This package contains the built application ready for Databricks Apps deployment.

## Contents
- `src/` - Backend Python code
- `config/` - Configuration files
- `frontend/dist/` - Built frontend static assets
- `requirements.txt` - Python dependencies
- `app.yaml` - Databricks Apps configuration

## Deployment
1. Upload this directory to Databricks workspace
2. Deploy using Databricks Apps UI or CLI
3. Configure permissions in app.yaml

## Environment Variables
Set in Databricks Apps:
- ENVIRONMENT=production
- LOG_LEVEL=INFO
- MLFLOW_TRACKING_URI=databricks

## Logs
All logs go to stdout/stderr in JSON format.
View in Databricks Apps logs viewer.
EOF

echo "Build complete! Deploy directory ready at: deploy/"
echo ""
echo "Next steps:"
echo "1. Review deploy/app.yaml configuration"
echo "2. Deploy to Databricks Apps"
echo "3. Test the application"
```

Make executable:
```bash
chmod +x build.sh
```

---

### Step 4: Local Testing with Production Mode (Estimated: 2-3 hours)

#### 4.1 Test Production Build Locally

```bash
# Build frontend
cd frontend
npm run build
cd ..

# Set production environment
export ENVIRONMENT=production
export LOG_LEVEL=INFO

# Simulate Databricks headers
export DEV_USER_ID="test.user@databricks.com"
export DEV_USER_EMAIL="test.user@databricks.com"
export DEV_USERNAME="Test User"

# Run backend (it will serve frontend from dist/)
uvicorn src.api.main:app --host 0.0.0.0 --port 8080
```

**Open:** http://localhost:8080 (not :3000!)

**Test:**
1. Verify app loads
2. Check logs are in JSON format
3. Test all features
4. Check browser console for errors

#### 4.2 Test Header Extraction

Test with curl to simulate Databricks headers:

```bash
# Test with Databricks-like headers
curl -H "X-Forwarded-User: testuser@example.com" \
     -H "X-Forwarded-Email: testuser@example.com" \
     -H "X-Forwarded-Preferred-Username: Test User" \
     -H "X-Real-Ip: 192.168.1.1" \
     -H "X-Request-Id: test-request-123" \
     http://localhost:8080/api/health
```

Check logs - should see:
```json
{
  "timestamp": "2024-11-11T10:00:00Z",
  "level": "INFO",
  "message": "Request started: GET /api/health",
  "request_id": "test-request-123",
  "user_id": "testuser@example.com",
  "method": "GET",
  "path": "/api/health"
}
```

#### 4.3 Test Logging

Watch logs in separate terminal:
```bash
# Watch stdout (INFO logs)
uvicorn ... 2>/dev/null | jq .

# Watch stderr (ERROR logs)
uvicorn ... 2>&1 >/dev/null | jq .
```

**Verify:**
- All logs are valid JSON
- Request IDs are present
- User IDs are extracted
- Latency is measured
- Errors go to stderr

---

### Step 5: Deploy to Databricks Apps (Estimated: 2-3 hours)

#### 5.1 Build Deployment Package

```bash
./build.sh
```

#### 5.2 Upload to Databricks

**Option A: Using Databricks CLI**

```bash
# Install Databricks CLI
pip install databricks-cli

# Configure (if not already)
databricks configure --token

# Upload deployment package
databricks workspace import_dir deploy/ /Users/<your-email>/apps/ai-slide-generator/
```

**Option B: Using Databricks UI**

1. Go to Workspace in Databricks UI
2. Navigate to your user folder
3. Create folder: `apps/ai-slide-generator`
4. Upload all files from `deploy/` directory

#### 5.3 Create Databricks App

**Using Databricks Apps UI:**

1. Navigate to "Apps" in Databricks workspace
2. Click "Create App"
3. Select uploaded `app.yaml` file
4. Configure settings:
   - Name: AI Slide Generator
   - Compute: Small
   - Permissions: Add users/groups
5. Click "Deploy"

**Using Databricks CLI:**

```bash
# Create app
databricks apps create \
  --app-name ai-slide-generator \
  --app-settings /Users/<your-email>/apps/ai-slide-generator/app.yaml
```

#### 5.4 Monitor Deployment

```bash
# Check app status
databricks apps get --app-name ai-slide-generator

# View logs
databricks apps logs --app-name ai-slide-generator --follow
```

---

### Step 6: Production Testing (Estimated: 2-3 hours)

#### 6.1 Access Application

Get app URL from Databricks Apps UI or CLI:
```bash
databricks apps get --app-name ai-slide-generator --output json | jq -r '.url'
```

Open URL in browser.

#### 6.2 Test Checklist

**Authentication:**
- [ ] User info appears in header
- [ ] X-Forwarded-* headers are extracted
- [ ] User ID in logs matches actual user

**Core Features:**
- [ ] Send chat message → slides generate
- [ ] Chat history displays correctly
- [ ] Slides render properly
- [ ] Drag-and-drop works
- [ ] Edit HTML works
- [ ] Duplicate/delete works

**Performance:**
- [ ] Initial load time reasonable
- [ ] Slide generation completes
- [ ] No timeout errors
- [ ] Smooth interactions

**Logging:**
- [ ] Logs appear in Databricks Apps logs
- [ ] JSON format is correct
- [ ] Request IDs present
- [ ] Errors properly logged

**Security:**
- [ ] No CORS errors (same-origin)
- [ ] User isolation (test with multiple users)
- [ ] No sensitive data in logs

#### 6.3 Test with Multiple Users

1. Access app from different accounts
2. Verify users can't see each other's sessions
3. Verify user IDs in logs are different

**Known Issue in Phase 3:**
- Single global session means all users share same slides
- This will be fixed in Phase 4 with multi-session support
- Document this limitation clearly

---

### Step 7: Monitoring and Observability (Estimated: 1 hour)

#### 7.1 Create Log Queries

Use Databricks log analysis to create queries:

**Error Rate Query:**
```sql
SELECT 
  date_trunc('hour', timestamp) as hour,
  count(*) as error_count
FROM logs
WHERE app_name = 'ai-slide-generator'
  AND level IN ('ERROR', 'CRITICAL')
GROUP BY hour
ORDER BY hour DESC
```

**Latency Query:**
```sql
SELECT 
  path,
  avg(latency_ms) as avg_latency,
  max(latency_ms) as max_latency,
  count(*) as request_count
FROM logs
WHERE app_name = 'ai-slide-generator'
  AND latency_ms IS NOT NULL
GROUP BY path
ORDER BY avg_latency DESC
```

**User Activity:**
```sql
SELECT 
  user_id,
  count(*) as request_count,
  count(DISTINCT date(timestamp)) as active_days
FROM logs
WHERE app_name = 'ai-slide-generator'
GROUP BY user_id
ORDER BY request_count DESC
```

#### 7.2 Set Up Alerts

Create alerts for:
- Error rate > threshold
- Average latency > 5 seconds
- App downtime
- Memory usage high

---

### Step 8: Documentation (Estimated: 1 hour)

**`README_PHASE3.md`**

```markdown
# AI Slide Generator - Phase 3 Databricks Deployment

## Deployment Status
- ✅ Deployed to Databricks Apps
- ✅ User authentication via headers
- ✅ Structured JSON logging
- ✅ All features from Phase 1 & 2 working

## Architecture

### Production Setup
- **Backend**: FastAPI serving both API and frontend
- **Frontend**: React built to static assets
- **Hosting**: Databricks Apps
- **Authentication**: X-Forwarded-* headers
- **Logging**: JSON format to stdout/stderr

### URLs
- **Production**: https://<workspace>.cloud.databricks.com/apps/ai-slide-generator
- **Development**: http://localhost:8080

## Deployment Process

### Prerequisites
- Databricks workspace access
- Databricks Apps enabled
- Python 3.9+
- Node.js 18+

### Build and Deploy
```bash
# Build deployment package
./build.sh

# Deploy to Databricks (CLI)
databricks apps create \
  --app-name ai-slide-generator \
  --app-config deploy/app.yaml

# Or use Databricks UI to deploy
```

### Configuration

**Environment Variables:**
- `ENVIRONMENT=production`
- `LOG_LEVEL=INFO`
- `MLFLOW_TRACKING_URI=databricks`

**Phase 4 additions:**
- `SESSION_TIMEOUT_MINUTES=60`
- `MAX_SESSIONS_PER_USER=5`

## Logging

All logs in JSON format:
```json
{
  "timestamp": "2024-11-11T10:00:00Z",
  "level": "INFO",
  "request_id": "abc-123",
  "user_id": "user@databricks.com",
  "method": "POST",
  "path": "/api/chat",
  "status_code": 200,
  "latency_ms": 1500,
  "message": "Request completed"
}
```

**View logs:**
- Databricks Apps UI → Logs tab
- Databricks SQL queries on logs table

## Known Limitations (Phase 3)

### Single Session (Fixed in Phase 4)
- All users currently share same session
- No session isolation
- Workaround: Document as "shared workspace"

### No Persistence
- Sessions lost on app restart
- No saved slide decks

### User Isolation
- User info logged but not used for session separation
- Phase 4 will add proper multi-user support

## Monitoring

**Key Metrics:**
- Request latency
- Error rate
- Active users
- Slide generation time

**Dashboards:**
- See Databricks Apps monitoring dashboard
- Custom SQL queries for log analysis

## Troubleshooting

### App Won't Start
- Check logs for startup errors
- Verify requirements.txt dependencies
- Check app.yaml configuration

### Authentication Issues
- Verify X-Forwarded-* headers present
- Check middleware is enabled
- Review user logs

### Features Not Working
- Check browser console errors
- Verify API endpoints responding
- Check CORS not an issue (same-origin)

## Next Steps

Phase 4 will add:
- Multi-session support
- Per-user session isolation
- Session cleanup
- Session persistence options
```

---

## Phase 3 Complete Checklist

### Backend
- [ ] User middleware extracts headers
- [ ] Logging middleware generates JSON logs
- [ ] Environment-based configuration works
- [ ] Static file serving configured
- [ ] Health check includes environment

### Frontend
- [ ] Production build generates static assets
- [ ] API client works with same-origin
- [ ] Environment variables configured
- [ ] Bundle size optimized

### Deployment
- [ ] app.yaml created and configured
- [ ] Build script automates deployment
- [ ] Deployed to Databricks Apps
- [ ] App accessible via URL
- [ ] Logs visible in Databricks

### Testing
- [ ] Local production mode tested
- [ ] Header extraction tested
- [ ] Logging format verified
- [ ] All features work in production
- [ ] Multiple users tested (shared session noted)

### Monitoring
- [ ] Log queries created
- [ ] Alerts configured
- [ ] Dashboard set up
- [ ] Error tracking working

### Documentation
- [ ] Deployment guide complete
- [ ] Known limitations documented
- [ ] Troubleshooting guide written
- [ ] Monitoring setup documented

---

## Estimated Total Time: 12-17 hours

- Backend Middleware: 2-3 hours
- Frontend Build Config: 1-2 hours
- Databricks Configuration: 1 hour
- Local Production Testing: 2-3 hours
- Deployment: 2-3 hours
- Production Testing: 2-3 hours
- Monitoring Setup: 1 hour
- Documentation: 1-2 hours

---

## Next Steps

After Phase 3 is complete:
1. Verify app is stable in production
2. Gather user feedback
3. Monitor usage patterns
4. Proceed to **Phase 4**: Multi-session support

