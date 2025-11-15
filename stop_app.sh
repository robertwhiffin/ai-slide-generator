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

kill_port_processes() {
    local port=$1
    local label=$2

    local pids
    pids=$(lsof -ti:$port 2>/dev/null | tr '\n' ' ')

    if [ -n "$pids" ]; then
        echo -e "${YELLOW}⚠️  Found process on port $port (PID: $pids), killing...${NC}"
        echo "$pids" | xargs kill 2>/dev/null || true
        sleep 1

        local remaining
        remaining=$(lsof -ti:$port 2>/dev/null | tr '\n' ' ')

        if [ -n "$remaining" ]; then
            echo -e "${RED}⚠️  Force killing $label on port $port (PID: $remaining)...${NC}"
            echo "$remaining" | xargs kill -9 2>/dev/null || true
        else
            echo -e "${GREEN}✅ $label port $port cleared${NC}"
        fi
    fi
}

kill_pattern_processes() {
    local pattern=$1
    local label=$2

    local pids
    pids=$(pgrep -f "$pattern" 2>/dev/null | tr '\n' ' ')

    if [ -n "$pids" ]; then
        echo -e "${YELLOW}⚠️  Found $label process (PID: $pids), killing...${NC}"
        echo "$pids" | xargs kill 2>/dev/null || true
        sleep 1
        local remaining
        remaining=$(pgrep -f "$pattern" 2>/dev/null | tr '\n' ' ')
        if [ -n "$remaining" ]; then
            echo -e "${RED}⚠️  Force killing $label (PID: $remaining)...${NC}"
            echo "$remaining" | xargs kill -9 2>/dev/null || true
        else
            echo -e "${GREEN}✅ $label stopped${NC}"
        fi
    fi
}

# Stop backend
stop_process "Backend" "logs/backend.pid"

# Stop frontend
stop_process "Frontend" "logs/frontend.pid"

# Also kill any remaining processes on ports 8000 and 3000
echo ""
echo -e "${YELLOW}🔍 Checking for any remaining processes...${NC}"

# Kill any stray processes on backend/frontend ports
kill_port_processes 8000 "Backend"
kill_pattern_processes "uvicorn.*src.api.main:app" "Backend watcher"
kill_port_processes 3000 "Frontend"

echo ""
echo -e "${GREEN}✨ AI Slide Generator stopped${NC}"
echo ""

