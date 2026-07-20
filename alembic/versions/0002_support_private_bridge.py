"""support private bridge message mapping

Revision ID: 0002_support_private_bridge
Revises: 0001_postgresql
"""
from alembic import op
import sqlalchemy as sa

revision = '0002_support_private_bridge'
down_revision = '0001_postgresql'
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'support_bridge_messages' in inspector.get_table_names():
        return
    op.create_table(
        'support_bridge_messages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('admin_id', sa.BigInteger(), nullable=False),
        sa.Column('admin_chat_id', sa.BigInteger(), nullable=True),
        sa.Column('admin_message_id', sa.BigInteger(), nullable=False),
        sa.Column('user_message_id', sa.BigInteger(), nullable=True),
        sa.Column('direction', sa.String(length=16), nullable=False, server_default='user_to_admin'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('admin_id', 'admin_message_id', name='uq_support_bridge_admin_message'),
    )
    op.create_index('ix_support_bridge_messages_ticket_id', 'support_bridge_messages', ['ticket_id'])
    op.create_index('ix_support_bridge_messages_user_id', 'support_bridge_messages', ['user_id'])
    op.create_index('ix_support_bridge_messages_admin_id', 'support_bridge_messages', ['admin_id'])
    op.create_index('ix_support_bridge_messages_admin_message_id', 'support_bridge_messages', ['admin_message_id'])
    op.create_index('ix_support_bridge_ticket_created', 'support_bridge_messages', ['ticket_id', 'created_at'])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'support_bridge_messages' not in inspector.get_table_names():
        return
    op.drop_index('ix_support_bridge_ticket_created', table_name='support_bridge_messages')
    op.drop_index('ix_support_bridge_messages_admin_message_id', table_name='support_bridge_messages')
    op.drop_index('ix_support_bridge_messages_admin_id', table_name='support_bridge_messages')
    op.drop_index('ix_support_bridge_messages_user_id', table_name='support_bridge_messages')
    op.drop_index('ix_support_bridge_messages_ticket_id', table_name='support_bridge_messages')
    op.drop_table('support_bridge_messages')
