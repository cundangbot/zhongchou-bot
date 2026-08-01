# v1.6.4.8 发起人双车位白名单虚拟自动核验

## 目的

保留原冷启动/虚拟验票能力，同时避免纯自动支付模式下必须由发起人手动发送暗号。管理员可在 `.env` 配置允许虚拟核验的发起人 Telegram 数字 ID。

## 配置

```env
CREATOR_PREPAY_AUTO_VERIFY_ENABLED=true
CREATOR_PREPAY_AUTO_VERIFY_IDS=111111111,222222222
```

`CREATOR_PREPAY_AUTO_VERIFY_IDS` 填发起人的 Telegram 数字用户 ID，不填项目 ID、用户名或频道 ID。

## 生效范围

仅处理：

```text
order_type = crowdfunding_creator_prepay
```

不会处理：

- 普通 30/60 元车位；
- 满员后补票；
- 非白名单用户；
- 非本人发起的项目；
- 不处于“等待发起人预付”的项目。

## 流程

```text
管理员审核通过项目
→ 创建/读取发起人双车位待付订单
→ 判断发起人 Telegram ID 是否在 .env 白名单
├─ 在白名单：本地虚拟核验 → 锁定双车位 → 项目进入 active/full → 发送车主成功卡片
└─ 不在白名单或核验失败：继续发送真实 60/120 元支付链接
```

部署前已经处于“等待发起人预付”的白名单项目，会在启动时扫描并幂等恢复。

## 账本

虚拟订单保留应付金额 60/120 元用于订单和成功卡片展示，但资金账本写入：

```text
payment_source = virtual
ledger amount = 0.00
```

因此不会增加真实收入，也不会影响按日资金对账。

## 原冷启动暗号

以下配置和 `/seed_status` 继续保留：

```env
SEED_MODE_ENABLED=false
ADMIN_VERIFY_SECRET=...
SEEDER_IDS=...
```

它们作为人工应急/冷启动填充方式，不影响新的发起人自动白名单。

## 幂等与安全

- 每张双车位订单使用 `virtual-creator-prepay:{order_id}` 幂等键；
- 重启不会重复增加两个座位；
- 已支付订单再次处理会直接返回已完成；
- 虚拟系统单号、支付单号按项目和车票生成唯一值；
- 白名单核验失败会退回真实支付流程，不会卡住项目；
- 普通自动支付仍使用“购买成功通知 → VP → faka”链路。

## 检查结果

已通过：

- Python 全项目编译；
- f-string 兼容检查；
- 全项目交互闭环检查；
- 纯自动支付流程检查；
- 发起人双车位白名单专项静态检查；
- 配置 ID 解析测试；
- 顶层循环导入静态检查。

当前检查环境缺少 `aiogram`，未执行真实 Telegram、PostgreSQL 和 faka 在线联调。

## 部署

本次不新增数据库字段，不需要 Alembic 迁移。更新代码与 `.env` 后重建容器即可。
