"""Run database migrations for session permissions.

This script applies the SQL migration to add ownership and permissions
to the session management system.

Usage:
    python scripts/run_migration.py
"""
import argparse
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from src.core.database import get_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def run_migration(migration_file: Path, dry_run: bool = False):
    """Run a SQL migration file.
    
    Args:
        migration_file: Path to SQL migration file
        dry_run: If True, print SQL but don't execute
    """
    if not migration_file.exists():
        logger.error(f"Migration file not found: {migration_file}")
        return False
    
    logger.info(f"Loading migration: {migration_file.name}")
    sql = migration_file.read_text()
    
    if dry_run:
        logger.info("DRY RUN - SQL to be executed:")
        print(sql)
        return True
    
    engine = get_engine()
    
    try:
        with engine.connect() as conn:
            # Execute migration in a transaction
            trans = conn.begin()
            try:
                # Split by statement (simple approach - may need adjustment for complex SQL)
                statements = [s.strip() for s in sql.split(';') if s.strip()]
                
                for i, statement in enumerate(statements, 1):
                    if statement:
                        logger.info(f"Executing statement {i}/{len(statements)}...")
                        conn.execute(text(statement))
                
                trans.commit()
                logger.info(f"Migration completed successfully: {migration_file.name}")
                return True
                
            except Exception as e:
                trans.rollback()
                logger.error(f"Migration failed, rolled back: {e}")
                return False
                
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run database migrations")
    parser.add_argument(
        "--migration",
        default="scripts/migrations/001_add_session_permissions.sql",
        help="Path to migration file (default: 001_add_session_permissions.sql)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SQL without executing",
    )
    
    args = parser.parse_args()
    
    migration_file = Path(args.migration)
    success = run_migration(migration_file, dry_run=args.dry_run)
    
    if success:
        logger.info("✓ Migration completed")
        if not args.dry_run:
            logger.info("\nNext steps:")
            logger.info("1. Restart your application")
            logger.info("2. Test session creation and permission management")
            logger.info("3. See docs/access-control.md for usage guide")
        sys.exit(0)
    else:
        logger.error("✗ Migration failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
