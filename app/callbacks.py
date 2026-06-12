from __future__ import annotations

# 核心 callback_data 统一入口。旧代码里仍有大量历史字符串，本文件先覆盖最容易冲突的客服/资源/管理分页，
# 后续新按钮都应优先从这里生成，避免同名、过长或含义混乱。

SUPPORT_START = 'support:start'
SUPPORT_END = 'support:end'

RESOURCE_FINISH = 'resource:finish'
RESOURCE_CONFIRM = 'resource:confirm'
RESOURCE_CANCEL = 'resource:cancel'

ADMIN_LIST = 'admin:list'
ADMIN_SUPPORT_HOLD = 'admin:support_hold'
ADMIN_SUPPORT_CLOSE = 'admin:support_close'
ADMIN_SUPPORT_REPLY = 'admin:support_reply'
ADMIN_UPLOAD_RESOURCE = 'admin:upload_resource'
ADMIN_PREVIEW_PUBLISH_RESOURCE = 'admin:preview_publish_resource'
ADMIN_PUBLISH_RESOURCE = 'admin:publish_resource'


def support_start(source: str = 'generic', ref_id: int | str | None = 0) -> str:
    return f'{SUPPORT_START}:{source}:{int(ref_id or 0)}'


def resource_finish(project_id: int) -> str:
    return f'{RESOURCE_FINISH}:{int(project_id)}'


def resource_confirm(project_id: int) -> str:
    return f'{RESOURCE_CONFIRM}:{int(project_id)}'


def admin_list(list_type: str, page: int = 0) -> str:
    return f'{ADMIN_LIST}:{list_type}:{max(0, int(page or 0))}'


def admin_preview_publish_resource(project_id: int) -> str:
    return f'{ADMIN_PREVIEW_PUBLISH_RESOURCE}:{int(project_id)}'


def admin_publish_resource(project_id: int) -> str:
    return f'{ADMIN_PUBLISH_RESOURCE}:{int(project_id)}'
