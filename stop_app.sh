#!/bin/bash

# AI Slide Generator - Stop Script
# Stops both backend and frontend servers gracefully

set -e

echo "🛑 Stopping AI Slide Generator..."
echo ""

# Color codes for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Function to stop a process
stop_process() {
    local name=$1
    local pid_file=$2
    
    if [ -f "$pid_file" ]; then
        PID=$(cat "$pid_file")
        if ps -p $PID > /dev/null 2>&1; then
            echo -e "${YELLOW}⏳ Stopping $name (PID: $PID)...${NC}"
            kill $PID
            
            # Wait for process to stop (max 10 seconds)
            for i in {1..10}; do
                if ! ps -p $PID > /dev/null 2>&1; then
                    echo -e "${GREEN}✅ $name stopped${NC}"
                    rm "$pid_file"
                    return 0
                fi
                sleep 1
            done
            
            # Force kill if still running
            if ps -p $PID > /dev/null 2>&1; then
                echo -e "${RED}⚠️  Force killing $name...${NC}"
                kill -9 $PID
                rm "$pid_file"
            fi
        else
            echo -e "${YELLOW}⚠️  $name not running (stale PID file)${NC}"
            rm "$pid_file"
        fi
    else
        echo -e "${YELLOW}⚠️  $name PID file not found${NC}"
    fi
}

# Stop backend
stop_process "Backend" "logs/backend.pid"

# Stop frontend
stop_process "Frontend" "logs/frontend.pid"

# Also kill any remaining processes on ports 8000 and 3000
echo ""
echo -e "${YELLOW}🔍 Checking for any remaining processes...${NC}"

# Kill any process on port 8000 (backend)
BACKEND_PORT_PID=$(lsof -ti:8000 2>/dev/null || true)
if [ ! -z "$BACKEND_PORT_PID" ]; then
    echo -e "${YELLOW}⚠️  Found process on port 8000 (PID: $BACKEND_PORT_PID), killing...${NC}"
    kill $BACKEND_PORT_PID 2>/dev/null || true
fi

# Kill any process on port 3000 (frontend)
FRONTEND_PORT_PID=$(lsof -ti:3000 2>/dev/null || true)
if [ ! -z "$FRONTEND_PORT_PID" ]; then
    echo -e "${YELLOW}⚠️  Found process on port 3000 (PID: $FRONTEND_PORT_PID), killing...${NC}"
    kill $FRONTEND_PORT_PID 2>/dev/null || true
fi

echo ""
echo -e "${GREEN}✨ AI Slide Generator stopped${NC}"
echo ""

