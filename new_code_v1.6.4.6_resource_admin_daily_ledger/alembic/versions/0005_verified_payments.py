"""store verified automatic payments before local project binding

Revision ID: 0005_verified_payments
Revises: 0004_channel_discussion
"""
from alembic import op
import sqlalchemy as sa

revision = '0005_verified_payments'
down_revision = '0004_channel_discussion'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'verified_payments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('system_no', sa.String(length=96), nullable=False),
        sa.Column('pay_no', sa.String(length=128), nullable=True),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('buyer_name', sa.String(length=255), nullable=True),
        sa.Column('amount', sa.Numeric(14, 2), nullable=False),
        sa.Column('product_name', sa.String(length=255), nullable=False),
        sa.Column('product_kind', sa.String(length=32), nullable=False),
        sa.Column('pay_channel', sa.String(length=64), nullable=True),
        sa.Column('pay_method', sa.String(length=64), nullable=True),
        sa.Column('order_bot', sa.String(length=128), nullable=True),
        sa.Column('raw_response', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='verified_unbound'),
        sa.Column('selected_project_id', sa.Integer(), nullable=True),
        sa.Column('bound_order_id', sa.Integer(), nullable=True),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('user_notice_sent_at', sa.DateTime(), nullable=True),
        sa.Column('user_notice_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('system_no', name='uq_verified_payments_system_no'),
    )
    op.create_index('ix_verified_payments_system_no', 'verified_payments', ['system_no'])
    op.create_index('ix_verified_payments_user_id', 'verified_payments', ['user_id'])
    op.create_index('ix_verified_payments_product_kind', 'verified_payments', ['product_kind'])
    op.create_index('ix_verified_payments_status', 'verified_payments', ['status'])
    op.create_index('ix_verified_payments_selected_project_id', 'verified_payments', ['selected_project_id'])
    op.create_index('ix_verified_payments_bound_order_id', 'verified_payments', ['bound_order_id'])
    op.create_index('ix_verified_payments_created_at', 'verified_payments', ['created_at'])
    op.create_index('ix_verified_payments_updated_at', 'verified_payments', ['updated_at'])


def downgrade() -> None:
    op.drop_table('verified_payments')
