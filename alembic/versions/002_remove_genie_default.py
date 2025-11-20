"""Remove is_default from genie spaces and enforce one space per profile

Revision ID: 002_remove_genie_default
Revises: 001_initial_schema
Create Date: 2025-11-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_remove_genie_default'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Remove is_default concept from genie spaces.
    
    Changes:
    1. Drop the trigger and function that enforced single default (PostgreSQL only)
    2. Drop the is_default index
    3. Remove the is_default column
    4. Add unique constraint on profile_id (one space per profile)
    """
    # Drop trigger and function for single default genie space (PostgreSQL only)
    try:
        op.execute("DROP TRIGGER IF EXISTS enforce_single_default_genie_space ON config_genie_spaces;")
        op.execute("DROP FUNCTION IF EXISTS check_single_default_genie_space();")
    except Exception:
        # SQLite doesn't have triggers/functions from initial migration
        pass
    
    # Drop the is_default index (may not exist in SQLite)
    try:
        op.drop_index('idx_config_genie_spaces_default', table_name='config_genie_spaces')
    except Exception:
        pass
    
    # Check if is_default column exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('config_genie_spaces')]
    has_is_default = 'is_default' in columns
    
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('config_genie_spaces') as batch_op:
        # Remove the is_default column (only if it exists)
        if has_is_default:
            batch_op.drop_column('is_default')
        
        # Add unique constraint to enforce one genie space per profile
        batch_op.create_unique_constraint(
            'uq_config_genie_spaces_profile',
            ['profile_id']
        )


def downgrade() -> None:
    """
    Restore is_default concept (for rollback).
    
    Warning: If multiple genie spaces exist per profile after upgrade,
    this rollback will fail. Manual intervention required.
    """
    # Use batch mode for SQLite compatibility
    with op.batch_alter_table('config_genie_spaces') as batch_op:
        # Drop unique constraint
        batch_op.drop_constraint('uq_config_genie_spaces_profile', type_='unique')
        
        # Add back is_default column (default to False, then set first one to True per profile)
        batch_op.add_column(sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'))
    
    # Set first space for each profile as default
    # Use SQLite-compatible syntax (no DISTINCT ON)
    op.execute("""
        UPDATE config_genie_spaces
        SET is_default = 1
        WHERE id IN (
            SELECT MIN(id)
            FROM config_genie_spaces
            GROUP BY profile_id
        );
    """)
    
    # Recreate the is_default index (without PostgreSQL-specific partial index)
    op.create_index(
        'idx_config_genie_spaces_default',
        'config_genie_spaces',
        ['profile_id', 'is_default'],
        unique=False
    )
    
    # Recreate trigger and function to enforce single default (PostgreSQL only)
    try:
        op.execute("""
            CREATE OR REPLACE FUNCTION check_single_default_genie_space()
            RETURNS TRIGGER AS $$
            BEGIN
                IF NEW.is_default = TRUE THEN
                    IF EXISTS (SELECT 1 FROM config_genie_spaces 
                              WHERE profile_id = NEW.profile_id 
                              AND is_default = TRUE 
                              AND id != NEW.id) THEN
                        RAISE EXCEPTION 'Only one Genie space can be default per profile';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """)
        
        op.execute("""
            CREATE TRIGGER enforce_single_default_genie_space
            BEFORE INSERT OR UPDATE ON config_genie_spaces
            FOR EACH ROW EXECUTE FUNCTION check_single_default_genie_space();
        """)
    except Exception:
        # SQLite doesn't support PostgreSQL functions/triggers
        pass

