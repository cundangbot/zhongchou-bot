"""support admin active private sessions

Revision ID: 0003_support_admin_sessions
Revises: 0002_support_private_bridge
"""
from alembic import op
import sqlalchemy as sa

revision = '0003_support_admin_sessions'
down_revision = '0002_support_private_bridge'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'support_admin_sessions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('admin_id', sa.BigInteger(), nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=True),
        sa.Column('ref_id', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('admin_id', name='uq_support_admin_session_admin'),
    )
    op.create_index('ix_support_admin_sessions_admin_id', 'support_admin_sessions', ['admin_id'])
    op.create_index('ix_support_admin_sessions_ticket_id', 'support_admin_sessions', ['ticket_id'])
    op.create_index('ix_support_admin_sessions_user_id', 'support_admin_sessions', ['user_id'])
    op.create_index('ix_support_admin_sessions_updated_at', 'support_admin_sessions', ['updated_at'])


def downgrade() -> None:
    op.drop_index('ix_support_admin_sessions_updated_at', table_name='support_admin_sessions')
    op.drop_index('ix_support_admin_sessions_user_id', table_name='support_admin_sessions')
    op.drop_index('ix_support_admin_sessions_ticket_id', table_name='support_admin_sessions')
    op.drop_index('ix_support_admin_sessions_admin_id', table_name='support_admin_sessions')
    op.drop_table('support_admin_sessions')
