"""store linked discussion comment message mapping

Revision ID: 0004_channel_discussion
Revises: 0003_support_admin_sessions
"""
from alembic import op
import sqlalchemy as sa

revision = '0004_channel_discussion'
down_revision = '0003_support_admin_sessions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column['name'] for column in inspector.get_columns('crowdfund_projects')}
    if 'discussion_chat_id' not in columns:
        op.add_column('crowdfund_projects', sa.Column('discussion_chat_id', sa.BigInteger(), nullable=True))
    if 'discussion_root_message_id' not in columns:
        op.add_column('crowdfund_projects', sa.Column('discussion_root_message_id', sa.BigInteger(), nullable=True))
    if 'discussion_detail_message_id' not in columns:
        op.add_column('crowdfund_projects', sa.Column('discussion_detail_message_id', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column['name'] for column in inspector.get_columns('crowdfund_projects')}
    if 'discussion_detail_message_id' in columns:
        op.drop_column('crowdfund_projects', 'discussion_detail_message_id')
    if 'discussion_root_message_id' in columns:
        op.drop_column('crowdfund_projects', 'discussion_root_message_id')
    if 'discussion_chat_id' in columns:
        op.drop_column('crowdfund_projects', 'discussion_chat_id')
