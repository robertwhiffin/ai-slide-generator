#!/usr/bin/env python3
"""
tellr CLI - Simple command-line interface for managing the tellr app.

Usage:
    tellr          # Start the app (default)
    tellr start    # Start the app
    tellr stop     # Stop the app  
    tellr status   # Check if running
    tellr init     # Initialize database (first run)
    tellr reset    # Reset configuration

This CLI is installed by Homebrew and wraps the existing shell scripts.
"""

import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import click

# Determine TELLR_HOME - where the app is installed
TELLR_HOME = Path(os.environ.get("TELLR_HOME", Path(__file__).parent.parent))
TELLR_CONFIG_PATH = Path.home() / ".tellr" / "config.yaml"


def get_pid_file(name: str) -> Path:
    """Get path to PID file."""
    return TELLR_HOME / "logs" / f"{name}.pid"


def is_process_running(pid: int) -> bool:
    """Check if a process with given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_pid(name: str) -> int | None:
    """Read PID from file, return None if not found or invalid."""
    pid_file = get_pid_file(name)
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text().strip())
        return pid if is_process_running(pid) else None
    except (ValueError, IOError):
        return None


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """tellr - AI-powered slide generator for Databricks.
    
    Run 'tellr' to start the app, or 'tellr --help' for more commands.
    """
    if ctx.invoked_subcommand is None:
        # Default action: start
        ctx.invoke(start)


@cli.command()
@click.option("--no-browser", is_flag=True, help="Don't open browser automatically")
def start(no_browser: bool):
    """Start the tellr application."""
    
    # Check if already running
    backend_pid = read_pid("backend")
    if backend_pid:
        click.echo(f"tellr is already running (PID: {backend_pid})")
        click.echo("Visit http://localhost:3000 in your browser")
        if not no_browser:
            webbrowser.open("http://localhost:3000")
        return
    
    click.echo("Starting tellr...")
    
    # Ensure logs directory exists
    logs_dir = TELLR_HOME / "logs"
    logs_dir.mkdir(exist_ok=True)
    
    # Ensure PostgreSQL is running (for Homebrew installations)
    try:
        result = subprocess.run(
            ["brew", "services", "list"],
            capture_output=True,
            text=True,
        )
        if "postgresql" in result.stdout and "started" not in result.stdout:
            click.echo("Starting PostgreSQL...")
            subprocess.run(["brew", "services", "start", "postgresql@14"], capture_output=True)
            time.sleep(2)  # Give PostgreSQL time to start
    except FileNotFoundError:
        # Homebrew not installed, assume PostgreSQL is managed differently
        pass
    
    # Check if database needs initialization
    if not (TELLR_HOME / ".db_initialized").exists():
        click.echo("Initializing database (first run)...")
        init_result = subprocess.run(
            [sys.executable, str(TELLR_HOME / "scripts" / "init_database.py")],
            cwd=TELLR_HOME,
            capture_output=True,
            text=True,
        )
        if init_result.returncode == 0:
            (TELLR_HOME / ".db_initialized").touch()
        else:
            click.echo(f"Warning: Database initialization may have failed: {init_result.stderr}")
    
    # Run the start script
    start_script = TELLR_HOME / "start_app.sh"
    if start_script.exists():
        env = os.environ.copy()
        env["TELLR_HOME"] = str(TELLR_HOME)
        
        result = subprocess.run(
            ["bash", str(start_script)],
            cwd=TELLR_HOME,
            env=env,
        )
        
        if result.returncode == 0:
            click.echo("")
            click.echo("✓ tellr is running!")
            click.echo("")
            
            # Check if this is first run (no config)
            if not TELLR_CONFIG_PATH.exists():
                click.echo("First run detected. Opening browser for setup...")
                click.echo("Enter your Databricks workspace URL to get started.")
            
            click.echo("Visit http://localhost:3000 in your browser")
            
            if not no_browser:
                time.sleep(2)  # Give frontend time to start
                webbrowser.open("http://localhost:3000")
        else:
            click.echo("Failed to start tellr. Check logs/backend.log for details.", err=True)
            sys.exit(1)
    else:
        click.echo(f"Start script not found: {start_script}", err=True)
        sys.exit(1)


@cli.command()
def stop():
    """Stop the tellr application."""
    click.echo("Stopping tellr...")
    
    stop_script = TELLR_HOME / "stop_app.sh"
    if stop_script.exists():
        subprocess.run(["bash", str(stop_script)], cwd=TELLR_HOME)
        click.echo("tellr stopped.")
    else:
        # Manual cleanup
        for name in ["backend", "frontend"]:
            pid = read_pid(name)
            if pid:
                try:
                    os.kill(pid, 15)  # SIGTERM
                    click.echo(f"Stopped {name} (PID: {pid})")
                except OSError:
                    pass
                get_pid_file(name).unlink(missing_ok=True)
        click.echo("tellr stopped.")


@cli.command()
def status():
    """Check if tellr is running."""
    backend_pid = read_pid("backend")
    frontend_pid = read_pid("frontend")
    
    if backend_pid:
        click.echo(f"Backend:  running (PID: {backend_pid})")
    else:
        click.echo("Backend:  not running")
    
    if frontend_pid:
        click.echo(f"Frontend: running (PID: {frontend_pid})")
    else:
        click.echo("Frontend: not running")
    
    if backend_pid:
        click.echo("")
        click.echo("Visit http://localhost:3000 in your browser")
    
    # Show config status
    click.echo("")
    if TELLR_CONFIG_PATH.exists():
        import yaml
        with open(TELLR_CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        host = config.get("databricks", {}).get("host", "Not configured")
        click.echo(f"Workspace: {host}")
    else:
        click.echo("Workspace: Not configured (will prompt on first use)")


@cli.command()
def init():
    """Initialize the database (usually done automatically on first start)."""
    click.echo("Initializing database...")
    
    result = subprocess.run(
        [sys.executable, str(TELLR_HOME / "scripts" / "init_database.py")],
        cwd=TELLR_HOME,
    )
    
    if result.returncode == 0:
        (TELLR_HOME / ".db_initialized").touch()
        click.echo("Database initialized successfully.")
    else:
        click.echo("Database initialization failed.", err=True)
        sys.exit(1)


@cli.command()
def reset():
    """Reset tellr configuration (removes saved workspace URL)."""
    if TELLR_CONFIG_PATH.exists():
        TELLR_CONFIG_PATH.unlink()
        click.echo("Configuration reset. You'll be prompted for workspace URL on next start.")
    else:
        click.echo("No configuration to reset.")


@cli.command()
def logs():
    """Show recent logs."""
    log_file = TELLR_HOME / "logs" / "backend.log"
    if log_file.exists():
        # Show last 50 lines
        result = subprocess.run(
            ["tail", "-50", str(log_file)],
            capture_output=True,
            text=True,
        )
        click.echo(result.stdout)
    else:
        click.echo("No logs found.")


if __name__ == "__main__":
    cli()
