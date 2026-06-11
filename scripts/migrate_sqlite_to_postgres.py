from __future__ import annotations

import argparse
from decimal import Decimal
from sqlalchemy import create_engine, MetaData, select, text, func


def sync_pg_url(url: str) -> str:
    return url.replace('postgresql+asyncpg://', 'postgresql+psycopg://')


def main() -> None:
    parser = argparse.ArgumentParser(description='将旧 SQLite 数据导入已执行 Alembic 迁移的 PostgreSQL。')
    parser.add_argument('--sqlite', default='sqlite:///./data/bot.db')
    parser.add_argument('--postgres', required=True)
    parser.add_argument('--allow-nonempty', action='store_true', help='目标库非空时仍继续（不推荐）')
    args = parser.parse_args()

    src_engine = create_engine(args.sqlite)
    dst_engine = create_engine(sync_pg_url(args.postgres))
    src_meta = MetaData()
    dst_meta = MetaData()
    src_meta.reflect(bind=src_engine)
    dst_meta.reflect(bind=dst_engine)

    preferred_order = [
        'crowdfund_projects', 'payment_orders', 'resource_access', 'profit_withdrawals',
        'refund_records', 'risk_logs', 'user_blacklist', 'contact_tickets',
        'resource_claim_logs', 'fund_ledger', 'wishes', 'votes',
    ]
    tables = preferred_order + sorted(set(src_meta.tables) - set(preferred_order))

    with src_engine.connect() as src, dst_engine.begin() as dst:
        if not args.allow_nonempty and 'crowdfund_projects' in dst_meta.tables:
            count = dst.execute(select(func.count()).select_from(dst_meta.tables['crowdfund_projects'])).scalar() or 0
            if count:
                raise SystemExit('目标 PostgreSQL 已有项目数据。请使用空库，或明确传入 --allow-nonempty。')

        for name in tables:
            if name not in src_meta.tables or name not in dst_meta.tables:
                continue
            src_table = src_meta.tables[name]
            dst_table = dst_meta.tables[name]
            common = [c.name for c in src_table.columns if c.name in dst_table.c]
            if not common:
                continue
            rows = [dict(row._mapping) for row in src.execute(select(*[src_table.c[c] for c in common]))]
            if rows:
                dst.execute(dst_table.insert(), rows)
            print(f'{name}: {len(rows)} rows')

        # 为旧项目补一条当前状态历史，后续状态变化全部由状态机记录。
        if 'project_state_history' in dst_meta.tables and 'crowdfund_projects' in dst_meta.tables:
            history = dst_meta.tables['project_state_history']
            projects = dst_meta.tables['crowdfund_projects']
            existing = dst.execute(select(func.count()).select_from(history)).scalar() or 0
            if existing == 0:
                rows = []
                for row in dst.execute(select(projects.c.id, projects.c.status, projects.c.created_at)):
                    rows.append({
                        'project_id': row.id,
                        'from_status': None,
                        'to_status': row.status,
                        'reason': 'SQLite 迁移时补录当前状态',
                        'actor_id': None,
                        'idempotency_key': f'project:{row.id}:migration-initial',
                        'metadata_json': None,
                        'created_at': row.created_at,
                    })
                if rows:
                    dst.execute(history.insert(), rows)
                print(f'project_state_history backfill: {len(rows)} rows')

        # 将旧支付、退款、报销/提现回填到统一资金流水。冷启动/测试订单金额记为 0。
        if 'financial_ledger' in dst_meta.tables:
            ledger = dst_meta.tables['financial_ledger']
            existing = dst.execute(select(func.count()).select_from(ledger)).scalar() or 0
            if existing == 0:
                ledger_rows = []
                if 'payment_orders' in dst_meta.tables:
                    orders = dst_meta.tables['payment_orders']
                    for row in dst.execute(select(orders).where(orders.c.status.in_(['paid', 'refunded']))):
                        m = row._mapping
                        source = m.get('payment_source') or 'real'
                        amount = Decimal('0.00') if source in ('seed', 'test') else Decimal(str(m.get('paid_amount') or m.get('expected_amount') or 0))
                        ledger_rows.append({
                            'idempotency_key': f'payment:{m["id"]}',
                            'direction': 'income', 'category': m.get('order_type') or 'payment',
                            'amount': amount, 'payment_source': source,
                            'project_id': m.get('project_id'), 'order_id': m.get('id'),
                            'refund_id': None, 'payout_id': None, 'user_id': m.get('user_id'),
                            'operator_id': None, 'description': 'SQLite 迁移回填支付流水',
                            'metadata_json': None, 'created_at': m.get('paid_at') or m.get('created_at'),
                        })
                if 'refund_records' in dst_meta.tables:
                    refunds = dst_meta.tables['refund_records']
                    for row in dst.execute(select(refunds).where(refunds.c.status == 'refunded')):
                        m = row._mapping
                        ledger_rows.append({
                            'idempotency_key': f'refund-ledger:{m["id"]}',
                            'direction': 'expense', 'category': 'refund',
                            'amount': m.get('amount') or 0, 'payment_source': 'real',
                            'project_id': m.get('project_id'), 'order_id': m.get('order_id'),
                            'refund_id': m.get('id'), 'payout_id': None, 'user_id': m.get('user_id'),
                            'operator_id': m.get('admin_id'), 'description': 'SQLite 迁移回填退款流水',
                            'metadata_json': None, 'created_at': m.get('refunded_at') or m.get('created_at'),
                        })
                if 'profit_withdrawals' in dst_meta.tables:
                    payouts = dst_meta.tables['profit_withdrawals']
                    for row in dst.execute(select(payouts).where(payouts.c.status == 'paid')):
                        m = row._mapping
                        category = 'reimbursement' if (m.get('payout_type') or 'profit') == 'reimbursement' else 'profit_withdrawal'
                        ledger_rows.append({
                            'idempotency_key': f'payout-ledger:{m["id"]}',
                            'direction': 'expense', 'category': category,
                            'amount': m.get('creator_amount') or 0, 'payment_source': 'real',
                            'project_id': m.get('project_id'), 'order_id': None,
                            'refund_id': None, 'payout_id': m.get('id'), 'user_id': m.get('creator_id'),
                            'operator_id': m.get('admin_id'), 'description': 'SQLite 迁移回填打款流水',
                            'metadata_json': None, 'created_at': m.get('paid_at') or m.get('created_at'),
                        })
                if ledger_rows:
                    dst.execute(ledger.insert(), ledger_rows)
                print(f'financial_ledger backfill: {len(ledger_rows)} rows')

        # PostgreSQL 自增序列同步到当前最大 ID。
        for name, table in dst_meta.tables.items():
            if 'id' not in table.c:
                continue
            dst.execute(text(
                "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
                "GREATEST(COALESCE((SELECT MAX(id) FROM \"" + name + "\"), 1), 1), true)"
            ), {'table_name': name})

    print('迁移完成。请核对项目数、支付单数、退款单数、状态历史和资金流水后再切换正式服务。')


if __name__ == '__main__':
    main()
