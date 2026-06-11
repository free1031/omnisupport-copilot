# OmniSupport Copilot — 工单解决率（Resolution Rate）验收口径 & 风险边界

> 文档定位：新增指标「工单解决率」的验收口径与风险边界声明
> 最后更新：2026-06-09（v1.1：`closed` 计入已解决）

---

## 1. 指标定义

### 1.1 业务口径

| 项目 | 定义 |
|------|------|
| **指标名称** | 工单解决率（Resolution Rate） |
| **业务含义** | 选定时间窗口内创建的工单中，已被解决的占比 |
| **分子** | 窗口内创建的工单中，`status IN ('resolved', 'closed')` 的工单数 |
| **分母** | 窗口内创建的工单总数（以 `created_date` 为准） |
| **聚合方式** | `SUM(resolved_tickets) / SUM(total_tickets)` |
| **默认维度** | `metric_date`（= `created_date`）× `product_line` |
| **可选切片** | `priority`, `category`, `org_id` |
| **单位** | 比率（0–1），可百分比展示 |

### 1.2 字段级口径声明

| 字段 | 来源 | 说明 |
|------|------|------|
| `created_date` | `support_case_mart.created_date` | 工单创建日期（日期截断，不含时间），作为时间窗口锚点 |
| `product_line` | `support_case_mart.product_line` | 产品线，取值见 ticket_contract.v1 |
| `status` | `support_case_mart.status` | 工单当前状态 |
| `is_resolved` | `support_case_mart.is_resolved` ← `stg_tickets.is_resolved` | 标识位：`lower(status) IN ('resolved', 'closed')` |

### 1.3 哪些 status 算「已解决」

| status | 是否计入分子 | 理由 |
|--------|------------|------|
| `resolved` | ✅ | 客服标记已解决，待客户确认 |
| `closed` | ✅ | 客户确认关闭或超时自动关闭，终态 |
| `open` | ❌ | 尚未处理 |
| `pending` | ❌ | 等待客户反馈 |
| `in_progress` | ❌ | 处理中 |
| `escalated` | ❌ | 已升级，未闭环 |

**staging 实现（与上表一致）**

```sql
-- analytics/models/staging/stg_tickets.sql
case when lower(status::text) in ('resolved', 'closed') then true else false end as is_resolved
```

下游 `int_ticket_activity_daily.resolved_ticket_count` 与 `resolution_rate` 分子均依赖该字段。

### 1.4 空值 / 异常处理
| 场景 | 处理方式 |
|------|---------|
| `created_date` 为 NULL | 该工单不参与任何窗口的统计 |
| `status` 为 NULL | 视为未解决，不计入分子 |
| `product_line` 为 NULL 或不在受控枚举内 | 归入 `unknown_product_line`，在结果中标记 |
| 分母为 0（当天无工单创建） | 该天不产出比率值，返回 `null` 而不是 0 |
| `data_release_id` 缺失 | 该行不纳入指标计算 |

---

## 2. PII 分级

### 2.1 聚合指标本身的 PII 等级：**low**

| 因素 | 说明 | 对评级的影响 |
|------|------|------------|
| 聚合层级 | 按 `metric_date × product_line` 聚合，无客户级粒度 | ✅ 降低风险 |
| 分子分母 | 均为计数聚合，不含 PII 字段 | ✅ 降低风险 |
| 反向推断风险 | 若某产品线在某天仅 1 张工单，解决率可反推该工单状态 | ⚠️ 需在工具层做「小基数门禁」 |
| 与客户 ID 联结 | 指标视图中不暴露 `customer_id`，无法与个人关联 | ✅ 降低风险 |

**结论**：`low` 而非 `none`，因为极端稀疏场景下存在有限的反向推断风险（见第 5 节缓解策略）。

### 2.2 Agent 视图的 PII 约束

Agent 通过 `query_support_kpis_v1` 工具拿到的指标数据来自 `agent_tool_input_view`，该视图：

- **不包含** `customer_id`、`customer_name`、`email`、`phone` 等任何客户身份字段
- **不包含** 工单 `description` / `subject` / `comments` 等文本内容
- 仅暴露聚合后的 `metric_value`，不暴露单条工单明细

> 若 Agent 需要诊断解决率异常的根因，必须通过 `get_ticket_status` 等逐单查询工具（受角色权限约束），而非通过指标接口下钻到明细。

---

## 3. 权限与 HITL

### 3.1 角色权限

| 角色 | 可查询解决率 | 备注 |
|------|------------|------|
| `support_ops` | ✅ | 运营团队日常监控 |
| `instructor` | ✅ | 课程讲师用于演示与教学 |
| `admin` | ✅ | 系统管理员，可查所有产品线 |
| `end_user` | ❌ | 终端用户无权限查看聚合 KPI |

### 3.2 HITL（人工介入）触发节点

| 触发条件 | 原因 | 动作 |
|---------|------|------|
| 某 `product_line` + 某天分母 ≤ 3 | 小基数可能反向推断单工单状态 | 返回 `null` 并提示「数据量过小无法展示」，同时记录审计日志 |
| 解决率较前 7 天均值骤降 > 30% | 可能表明系统性问题或数据异常 | 返回结果 + 追加提示：「该指标异常，建议联系 support_ops 确认」 |
| 查询窗口超过 31 天 | 大窗口下聚合可能掩盖日均波动，且涉及性能边界 | 工具层拦截，要求缩小窗口（复用 `max_window_days: 31` 约束） |
| 查询涉及 `org_id` 且请求角色非 `admin` | 跨租户数据隔离控制 | 非 admin 角色只能查自身 org_id 的数据 |

---

## 4. 安全红线

### ❌ 不可执行

| 红线 | 说明 |
|------|------|
| **不允许直接拼 SQL 访问原始工单表** | Agent 不得生成 SQL 直连 `ticket_fact` 或 `stg_tickets`。所有指标查询必须通过 `query_support_kpis_v1` 工具 + `agent_tool_input_view` |
| **不允许按 customer_id 下钻** | 指标视图不暴露 `customer_id`，Agent 无法（也不应）追问「某个客户的解决率」 |
| **不允许返回单行工单明细** | 解决率接口只输出聚合值，不输出参与计算的工单 ID 列表 |
| **不允许无权限角色查看** | `end_user` 角色即使通过 prompt 注入也无法绕权查询 |

---

## 5. 已知风险与缓解策略

| 风险 | 影响 | 缓解策略 |
|------|------|---------|
| 小基数（某产品线某天工单 ≤ 3）下解决率反向推断 | 泄露单工单状态 | 分母 ≤ 3 时不返回具体比率，返回 `null` |
| 解决率随工单时间推移而变化（新工单尚未解决） | 最近几天的解决率系统性偏低 | 在响应中注明数据延迟：「解决率为截至数据构建时的快照值」 |
| 跨天对比忽略产品线差异 | 误导性结论 | 强制要求按 `product_line` 维度展示，不允许聚合为全量单一数字 |
| 分母为 0 时返回 0 或除零错误 | API 异常 | 返回 `null`，前端/Agent 显示「当天无工单」 |

---

## 6. 验收标准

### ✅ 通过条件

| 检查项 | 标准 |
|--------|------|
| **口径无歧义** | 分子分母字段来源、status 枚举范围、空值处理均有明确声明 |
| **PII 等级有结论且给了理由** | 结论为 `low`，给出分级理由和小基数门禁设计 |
| **角色与 HITL 节点明确** | 列出 4 种角色的权限矩阵，4 个 HITL 触发条件 |
| **安全红线书面化** | 明确 4 条「不可执行」红线 |
| **与现有契约一致** | 复用 `support_case_mart.is_resolved`、`product_line` 枚举、`max_window_days` 约束 |
| **工具层可验证** | 新增指标在 `metric_registry_v1.yml` 注册后，`query_support_kpis_v1` 可直接返回 |

---

## 7. 附录：metric_registry 注册样板

建议在 `analytics/metric_registry_v1.yml` 中追加以下条目：

```yaml
  - name: resolution_rate
    label: "Resolution Rate"
    business_name_zh: "工单解决率"
    description: "Tickets resolved or closed divided by tickets created in the selected date window."
    business_definition_zh: "选定时间窗口内创建的工单中，status 为 resolved 或 closed 的工单占比。"
    owner: support_ops
    metric_type: ratio
    formula: "resolved_ticket_count / ticket_count"
    numerator: resolved_ticket_count
    denominator: ticket_count
    aggregation: avg
    unit: ratio
    sensitivity: low
    definition_status: production
    version: 1.1.0
    allowed_roles: ["support_ops", "instructor", "admin"]
    quality_tests: ["between_0_and_1", "denominator_not_zero_when_reported"]
    tags: ["resolution", "kpi", "week08"]
```