from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.db.base import engine


ROOT_DIR = Path(__file__).resolve().parents[2]
CRITICAL_TABLES = (
    'alembic_version',
    'crowdfund_projects',
    'payment_orders',
    'verified_payments',
    'system_metrics',
)


@dataclass(slots=True)
class SchemaPreflightResult:
    ready: bool
    expected_heads: tuple[str, ...] = field(default_factory=tuple)
    current_revisions: tuple[str, ...] = field(default_factory=tuple)
    missing_tables: tuple[str, ...] = field(default_factory=tuple)
    error: str | None = None

    @property
    def short_message(self) -> str:
        if self.error:
            return f'数据库结构检查失败：{self.error}'
        parts: list[str] = []
        expected = ', '.join(self.expected_heads) or '-'
        current = ', '.join(self.current_revisions) or '未记录'
        if set(self.current_revisions) != set(self.expected_heads):
            parts.append(f'Alembic 当前 {current}，代码要求 {expected}')
        if self.missing_tables:
            parts.append('缺少表：' + ', '.join(self.missing_tables))
        return '；'.join(parts) or '数据库结构正常'

    @property
    def admin_warning(self) -> str:
        return (
            '🔴 数据库版本未就绪，支付监听和定时任务已暂停。\n\n'
            f'{self.short_message}\n\n'
            '请在服务器执行：\n'
            'cd /opt/zhongchou_bot\n'
            './venv/bin/alembic upgrade head\n'
            '然后重启机器人。'
        )


def _expected_heads() -> tuple[str, ...]:
    cfg = Config(str(ROOT_DIR / 'alembic.ini'))
    cfg.set_main_option('script_location', str(ROOT_DIR / 'alembic'))
    script = ScriptDirectory.from_config(cfg)
    return tuple(sorted(script.get_heads()))


async def check_database_schema() -> SchemaPreflightResult:
    try:
        expected = _expected_heads()
    except Exception as exc:
        return SchemaPreflightResult(ready=False, error=f'无法读取 Alembic head：{exc}')

    try:
        async with engine.connect() as conn:
            missing: list[str] = []
            for table_name in CRITICAL_TABLES:
                exists = await conn.scalar(
                    text('SELECT to_regclass(:table_name)'),
                    {'table_name': f'public.{table_name}'},
                )
                if exists is None:
                    missing.append(table_name)

            if 'alembic_version' in missing:
                current = tuple()
            else:
                current_rows = await conn.execute(text('SELECT version_num FROM alembic_version'))
                current = tuple(sorted(str(value) for value in current_rows.scalars().all() if value))
    except Exception as exc:
        return SchemaPreflightResult(
            ready=False,
            expected_heads=expected,
            error=str(exc)[:1000],
        )

    return SchemaPreflightResult(
        ready=set(current) == set(expected) and not missing,
        expected_heads=expected,
        current_revisions=current,
        missing_tables=tuple(missing),
    )
