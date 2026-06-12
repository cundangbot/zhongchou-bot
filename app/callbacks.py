from __future__ import annotations

# 先把最容易冲突的 callback 前缀集中到这里，后续新增按钮优先复用这些函数。

SUPPORT_START_PREFIX = 'support:start'
ADMIN_LIST_PREFIX = 'admin:list'
RESOURCE_FINISH_PREFIX = 'resource:finish'
RESOURCE_CANCEL_PREFIX = 'resource:cancel'


def support_start(source: str = 'generic', ref_id: int = 0) -> str:
    return f'{SUPPORT_START_PREFIX}:{source}:{int(ref_id or 0)}'


def admin_list(list_type: str, page: int = 0) -> str:
    return f'{ADMIN_LIST_PREFIX}:{list_type}:{max(0, int(page or 0))}'


def resource_finish(project_id: int) -> str:
    return f'{RESOURCE_FINISH_PREFIX}:{int(project_id)}'


def resource_cancel(project_id: int) -> str:
    return f'{RESOURCE_CANCEL_PREFIX}:{int(project_id)}'
