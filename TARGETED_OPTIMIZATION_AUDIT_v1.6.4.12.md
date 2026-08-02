# v1.6.4.12 定向小优化检查报告

## 修改边界

本版以用户上传、当前可运行的 v1.6.4.11 为基线，只修改用户明确指定的六项内容。主菜单、会员购买、四种支付商品、发起人白名单双车位、资源上传/交付、账本、报销/分润、旧命令清理以及“启动不扫描历史项目”规则均保持不变。

## 1. 启动数据库结构检查

- 在启动 Telethon 支付监听和 APScheduler 之前，检查 Alembic 当前 revision 是否等于代码 head。
- 同时检查 `alembic_version`、`crowdfund_projects`、`payment_orders`、`verified_payments`、`system_metrics`。
- 结构不匹配时：机器人保留基础轮询与后台入口，但暂停支付监听和定时任务，避免半启动后持续报错。
- 向管理群发送一条简短修复告警；同一结构错误使用 `system_metrics` 去重，避免 systemd 反复重启时刷屏。
- 修复命令明确为 `./venv/bin/alembic upgrade head`。

## 2. 系统健康中的支付核验情况

新增支付核验红绿灯：

- `🟢 正常`：数据库结构正常、应运行的监听已连接且无付款积压。
- `🟡 注意`：存在等待本地处理、等待用户选择、人工关注付款，或最近一次 faka 查询失败后尚无新的成功记录。
- `🔴 异常`：数据库结构未就绪、Telethon 未连接或自动核验监听未运行。

同时显示等待本地处理数量、等待用户选择数量、人工关注数量、最后 faka 成功查询、最后成功验票及最近付款异常。

## 3. 异常付款五个管理员动作

所有使用异常付款操作键盘的通知现在提供：

- `🔍 查看 faka 核验结果`
- `🎫 查看匹配待付车票`
- `🚗 选择项目绑定`
- `🔄 重新执行本地绑定`
- `💬 联系付款用户`

优先复用 `verified_payments.raw_response`；只有异常发生在保存核验记录之前，查看结果或联系用户时才允许回退查询 faka。管理员绑定车票或项目仍经过现有商品、金额、用户、项目状态与重复资源权限校验。

## 4. 频道项目面板防抖

- 同一项目短时间连续触发更新时，取消前一待执行更新并重新计时。
- 默认静默窗口为 3 秒，由 `PROJECT_PANEL_DEBOUNCE_SECONDS` 控制。
- 到期后重新从数据库读取项目最终状态，只编辑一次该项目已有频道面板。
- 启动和重启不调用该流程，不扫描旧项目，不修改历史频道模板。

## 5. 退款详情和开放条件

退款详情统一显示退款单、项目、博主、描述、退款原因、状态、原支付金额、退款金额、车票、VP、支付单号、支付方式、支付时间、退款记录时间、收款资料和完成时间。

用户申请退款在按钮入口和资料提交阶段进行两次校验。仅以下情况开放：

- 项目被取消；
- 项目已过期；
- 资源上传超时后项目被系统取消。

普通用户仅因个人临时不想参加不能申请退款。

## 6. 客服首条业务上下文

每个未关闭客服会话仅第一条用户消息向管理员附带：

- 来源页面；
- 相关项目当前状态；
- 相关车票状态；
- 相关 VP 状态；
- 最后一次错误；
- 用户最近三个业务操作。

通过 `support_bridge_messages` 判断本会话是否已经转发过用户消息，无需新增数据库字段。会话未结束前，后续消息只转发原始内容；关闭后重新打开的新会话会再次在第一条附带上下文。长错误和整条管理员消息均做 Telegram 长度保护。

## 数据库与配置

- 本版没有新增 Alembic migration，当前数据库保持 `0005_verified_payments (head)` 即可。
- `.env` 可选显式配置：`PROJECT_PANEL_DEBOUNCE_SECONDS=3`；不配置时默认也是 3 秒。

## 检查结果

已通过：

- `python -m compileall -q app scripts`
- `python scripts/check_fstring_compat.py`
- `python scripts/check_flow_closure.py`
- `python scripts/check_unified_payment_flow.py`
- `python scripts/check_creator_virtual_prepay.py`
- `python scripts/check_targeted_optimizations.py`
- 启动模块静态循环依赖检查

当前检查容器未安装 `aiogram` 和 `asyncpg`，所以 `scripts/check_startup_imports.py` 的完整运行时导入阶段无法在本环境完成。真实 Telegram、faka 与 PostgreSQL 在线联调需在服务器部署后观察日志确认。
