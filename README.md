# 门店指标异常归因与量价下钻（`anomalyattr`）

> 数据工程 · 数据分析与数据应用。原生 HTML/CSS/JS 前端 + Python FastAPI 后端 + Celery worker + MySQL 8.0 + Redis，5 个容器一键起。

## 1. 场景

- **模拟客户**：蓝湾酒店集团 · 经营分析组（8 人），120 家门店（华东/华南/华北/西南/华中 5 个区域，3 个品牌），日报 + 周会决策。
- **现有工作流**：每天 07:00 PMS 与 3 个 OTA 渠道导出前一营业日数据 → 分析师把 120 行日报粘进 Excel → 看到总营收跌了，再手工按门店/渠道筛 → 周会上口头解释「大概是 OTA 掉了量」。
- **三个痛点**：
  1. **跌了不知道哪家店、哪个渠道**：只有总数，没有贡献分解，靠经验猜。
  2. **同比环比混用**：本周比上周、工作日比周末、节假日比平时，基线口径每次都不一样。
  3. **只看总数，量价混在一起**：营收跌了 8%，是房价降了、出租率掉了，还是有房停售，说不清。
- **上下游**：PMS / OTA 渠道 → **本系统（指标接入 → 异常检测 → 量价分解 → 维度归因 → 结论与报告）** → 区域经理复盘 + 经营周会。
- **一天的工作剧本**：
  1. 07:10 worker 定时复检（`DT20261114-0001`），对 120 家门店的营收序列跑一遍稳健检测。
  2. 07:20 分析师打开总览：`37 起异常 / 影响 -194.6 万 / 34 起待处理`。
  3. 07:25 进「异常清单」，按严重度筛 `高`，看到 `蓝湾·外滩店 2026-11-03 rev z=-4.20 影响 -85,960 元`。
  4. 07:30 点开详情 → 抽屉里核对基线三元组与当期三元组，写处理结论。
  5. 07:35 跳「归因下钻」：LMDI 拆出 `ADR -62.3% / OCC -31.1% / 可售房量 -7.8%`，渠道维度 `OTA 渠道 -71.0%`；页面同时列出这组样本的 28 个日期与被日历排除的特殊日。
  6. 07:40 把结论一句话贴进周会材料（导出 `attributions.csv`）。
  7. 07:45 管理员生成 `2026-10-26 ~ 2026-11-01 周报` 并发布，区域经理收到 `RP20261114-0001.csv`。
  8. 08:00 审计页回查「谁在什么时候导了哪份明细」。
  9. 08:10 运营发现华东某店 9 月做过停业改造、11-11 是双十一大促 → 在「运营日历」按门店登记特殊日；系统递增日历版本，相关待处理异常与草稿报告失效重算，已发布周报保留原引用。

## 2. 角色与权限

| 角色 | 账号 | 权限 | 典型动作 |
|---|---|---|---|
| 经营管理员 `admin` | `admin@anomalyattr.io` | 只读 + 门店维护 + 运营日历 + 检测 + 处理 + 报告生成 + 导出 + 审计 | 登记门店、维护特殊日、生成/发布报告、导出明细、查审计 |
| 经营分析师 `analyst` | `analyst@anomalyattr.io` | 只读 + 检测 + 处理异常 + 导出 | 发起检测、写归因结论、导出异常清单 |
| 区域只读 `viewer` | `viewer@anomalyattr.io` | 只读总览/门店/日历/异常/归因/报告 | 看数、看结论、看纳入/排除日期，不能写、不能导出、不能看审计 |

密码统一 `Demo@2026`。低权角色调用高权接口返回**真实 HTTP 403**（`GET /api/exports/anomalies.csv`、`GET /api/audit`、`PATCH /api/anomalies/{id}/review`、`POST /api/reports`、`POST /api/calendar`），无 token 401，非法参数 422，重复自然键 409。

## 3. 业务模块（7 个，可串成一条链路）

| # | 模块 | 对应页面 | 对应 services + controller | 主要 API |
|---|---|---|---|---|
| ① | 门店与指标接入 | `#/stores` 门店与指标 | `store_service` + `metric_service` / `store_controller` | `GET/POST /api/stores`、`PATCH /api/stores/{id}`、`GET /api/stores/{id}/series`、`GET /api/metrics` |
| ② | 运营日历（特殊日基线口径） | `#/calendar` 运营日历 | `calendar_service` + `generation_service` / `calendar_controller` | `GET/POST /api/calendar`、`PATCH/DELETE /api/calendar/{id}`、`GET /api/calendar/store/{store_id}`、`GET /api/calendar/version`、`GET /api/calendar/revisions`、`GET /api/calendar/jobs`、`POST /api/calendar/jobs/{id}/resume` |
| ③ | 异常检测（算法 A） | `#/anomalies` 异常清单 | `detection` + `run_service` / `run_controller` | `POST /api/runs`、`POST /api/runs/{id}/resume`、`GET /api/runs`、`GET /api/anomalies` |
| ④ | 量价分解（算法 B） | `#/attribution` 归因下钻 | `decompose` + `attribution_service` / `attribution_controller` | `GET /api/attributions/anomaly/{anomaly_id}` |
| ⑤ | 维度下钻归因 | `#/attribution` 归因下钻 | `attribution_service`（门店/渠道/房型三维，同一组样本） | 同上（`dimensions` + `sample` 字段） |
| ⑥ | 结论与处理工单 | `#/anomalies` 异常清单（抽屉） | `anomaly_service` / `anomaly_controller` | `PATCH /api/anomalies/{id}/review` |
| ⑦ | 报告与导出 | `#/reports` 报告与导出 | `report_service` + `export_service` / `report_controller` + `export_controller` | `POST/PATCH /api/reports`、`POST /api/reports/{id}/reassess`、`GET /api/reports/impact/invalidation`、`GET /api/exports/{anomalies,attributions,channels,reports}.csv` |

> 登录、审计、限流属于横切能力，不计入业务模块。总览页 `#/overview` 是这几个模块的汇总视图。

## 4. 快速启动

```bash
cp .env.example .env
docker compose up -d --build   # 等 5/5 healthy
open http://localhost:18209
```

首次启动 backend 自动建表并执行一次 seed（`SEED_DEMO=true`）。seed 幂等，可重复执行：

```bash
docker compose exec -T backend python -m scripts.seed_demo
docker compose exec -T backend python -m pytest tests -q
```

## 5. 本地开发

```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
uvicorn src.main:app --reload --port 8000      # 需要本机 MySQL/Redis，或用 compose 里的
cd frontend/site && python -m http.server 5173  # 纯静态站，接口走 /api
```

## 6. 访问地址

| 服务 | 地址 |
|---|---|
| 前端 | http://localhost:18209 |
| 后端 API 文档 | http://localhost:19209/docs |
| 健康检查 | http://localhost:19209/api/health |
| 数据库映射 | localhost:17709（MySQL 8.0） |

## 7. 技术栈

| 层 | 选型 |
|---|---|
| 前端 | 原生 HTML5 + CSS（oklch 令牌）+ ES Modules；无框架、无打包器、无 CDN 脚本（仅 Google Fonts） |
| 后端 | Python 3.11、FastAPI 0.115、SQLAlchemy 2.0、PyJWT、passlib(bcrypt) |
| 异步 | Celery 5.4 + Redis（worker 心跳、每日 07:40 复检） |
| 数据库 | MySQL 8.0（utf8mb4） |
| 部署 | Docker Compose，恰好 5 服务 |

## 8. 目录

```text
backend/
  src/{config,constants,controllers,middlewares,models,routes,schemas,services,utils}
       services/{detection.py,decompose.py,calendar_service.py,generation_service.py,...}  # 算法与日历独立可单测
  scripts/{demo_data.py,demo_config.py,seed_demo.py,worker_healthcheck.sh}
  migrations/001_core_tables.sql                    # 表结构参考（运行时不执行）
  tests/{test_detection.py,test_decompose.py,test_seed_data.py,test_permissions.py,test_security.py,test_calendar.py,test_calendar_api.py}
frontend/site/{index.html,css/{tokens,app}.css,js/{config,api,store,ui,app}.js,js/pages/*.js}
docker-compose.yml  .env  README.md
```

## 9. 核心算法与口径

### 算法 A｜稳健异常检测（`backend/src/services/detection.py`）

- **输入**：门店日序列（`revenue / adr / occupancy / rooms_available / rooms_sold / is_weekend`），由 `metric_service.series_points` 一次聚合查询得到，渠道行 `revenue = adr × rooms_sold`，门店汇总 `adr = Σrev/Σsold`、`occ = Σsold/rooms`。
- **基线**：当前点之前、**同一周末/工作日分层**的最后 28 个观测；`median` 与 `MAD = median(|x − median|)`。
- **运营日历**：停业改造 / 临时闭店 / 大促日等特殊日**不进入常态基线**，也不算作方向延续的前一观测；命中项在 `payload.window_dates` 回填实际参与样本的日期，`payload.excluded_special_days` 列出被排除日期，`sample_key` 是这组样本的指纹。特殊日当日的真实经营结果仍会进入当期说明（不做平滑或回填）。
- **统计量**：`robust_z = 0.6745 × (x − median) / MAD`。
- **触发**：`|z| ≥ 3.5` **且**前一观测（跳过特殊日）同方向且 `|z_prev| ≥ 1.5`（「方向一致 2 天」）。
- **严重度**：`|z| ≥ 5.0 或 |影响| ≥ 80,000` → `high`；`|z| ≥ 4.2 或 |影响| ≥ 30,000` → `medium`；否则 `low`。
- **影响金额**：rev → `Δ营收`；adr → `Δadr × 当期已售房晚`；occ → `Δocc × 当期可售房量 × 当期adr`。
- **失败态**：`MAD == 0` 退化为平均绝对偏差，仍为 0 → `degenerate_baseline` 跳过；窗口样本 `< 10` → `insufficient_baseline` 跳过；未延续 → `no_direction_persist` 跳过（均写入 run.metrics.skipped）。
- **可复现**：纯函数、无网络、无随机；同输入两次输出逐字段一致（`test_detection.py::test_deterministic_output`）。

### 算法 B｜LMDI 量价分解 + 维度贡献（`backend/src/services/decompose.py`）

- **恒等式**：`revenue = adr × occupancy × rooms_available`。
- **变动**：`Δrev = rev_cur − rev_base`（base 取算法 A 同一窗口的中位数三元组）。
- **分解**：`L = Δrev / (ln rev_cur − ln rev_base)`，`part_adr = L·ln(adr_cur/adr_base)`，occ/rooms 同理；三项与 `Δrev` 的差额如实写进 `residual`，不摊派。
- **占比**：`share_i = part_i / Δrev`；`Δrev` 为 0 → `status="flat"`、占比 null。
- **维度下钻**：`contribution = 该组 Δ / 总 Δ`，输出 `top_negative` / `top_positive` 各 3 条；维度 = 门店（同区域横向对比）/ 渠道（OTA、直连、协议）/ 房型（按 `room_type_mix` 结构分摊）。
- **样本一致性**：量价三项、渠道下钻、门店下钻**只使用异常 `payload.window_dates` 这一组日期**（特殊日已剔除）；归因记录 `sample_key` 与 `calendar_version`，样本或版本变化时自动重建（`attribution_service._needs_rebuild`）。
- **失败态**：任一因子 ≤ 0 或营收 ≤ 0 → `status="degenerate"`，只回原始三元组与原因。
- **确定性**：同输入同输出（`test_decompose.py::test_deterministic_output`）。

### 运营日历与失效重算（`calendar_service` + `generation_service`）

- **规则**：门店 × 特殊日类型（`promo` 大促 / `renovating` 停业改造 / `closed` 临时闭店）× 生效区间 `[start_date, end_date]`（含端点）；同门店同类型同区间唯一（409）。
- **版本**：每次新增/修改/停用规则产生一条 `CalendarRevision`，`version` 全局单调递增；异常、归因、报告、检测批次都记录生成时的 `calendar_version`。
- **失效范围**：规则变更后，受影响门店的待处理异常标记 `invalidated`（不删除，保留审计痕迹），落在影响区间的草稿报告失效重算；**已发布报告保留原引用**，快照与 `calendar_version` 不改写。可按版本回看：`GET /api/reports/impact/invalidation?version=N`。
- **重算任务**：`GenerationJob` 三阶段（`staged` → `applying` → `committed`）。开始前把受影响异常全部字段与草稿快照存进 `staging.baseline`，每处理一家门店提交一次 checkpoint。
- **中断恢复**：任务中断后 `POST /api/calendar/jobs/{id}/resume` **先用 baseline 把受影响对象恢复成完整旧版**（删除半途新增异常与归因、还原被改写字段与草稿快照），再从第 2 阶段续跑；日历版本已变化时拒绝续跑（409），避免新旧口径混算。
- **幂等**：同一日历版本重复执行直接复用已成功任务（`idempotent_hit=true`）；异常按自然键 upsert、归因按 `sample_key` 复用，不新增重复结果，也不让已复核异常退回待处理。
- **检测批次续跑**：`POST /api/runs/{id}/resume` 同样先恢复 `run.metrics.staging` 中的完整旧版再续算。

## 10. 共享枚举出现位置

| 枚举 | 后端 | 前端 |
|---|---|---|
| 角色 `admin/analyst/viewer` | `constants/enums.py::Role`、`constants/roles.py` | `js/config.js::ROLE_LABELS / PERMISSIONS` |
| 渠道 `ota/direct/corp` | `constants/enums.py::Channel`、`CHANNEL_LABELS` | `js/config.js::ENUMS.channel` |
| 指标 `rev/adr/occ` | `constants/enums.py::MetricKey`、`METRIC_LABELS` | `js/config.js::ENUMS.metric / ENUMS.factor` |
| 严重度 `high/medium/low` | `constants/enums.py::Severity`、`SEVERITY_LABELS` | `js/config.js::ENUMS.severity`、`badgeTone()` |
| 处理状态 `pending/confirmed/dismissed` | `constants/enums.py::ReviewStatus` | `js/config.js::ENUMS.review`、`reviewTone()` |
| 方向 `up/down` | `constants/enums.py::Direction` | `js/config.js::ENUMS.direction` |
| 运行状态 `queued/running/success/partial/failed` | `constants/enums.py::RunStatus` | `js/config.js::ENUMS.runStatus` |
| 报告类型/状态 `daily/weekly`、`draft/published` | `constants/enums.py::ReportKind/ReportStatus` | `js/config.js::ENUMS.reportKind / reportStatus` |
| 特殊日类型 `promo/renovating/closed` | `constants/enums.py::CalendarDayType`、`CALENDAR_DAY_TYPE_LABELS` | `js/config.js::ENUMS.calendarDayType` |
| 失效重算状态 `running/success/failed` | `constants/enums.py::RunStatus` + `GenerationJob.status` | `js/config.js::ENUMS.jobStatus` |

## 11. 业务实体（7 个领域实体 + 2 个执行记录）

| 实体 | 表 | 自然键 | 贯穿链路 |
|---|---|---|---|
| `Store` 门店 | `stores` | `code` | model → schema → `store_service` → `store_controller`/`routes/stores` → `api.stores` → 门店页 |
| `MetricPoint` 指标点 | `metric_points` | `(store_id, stat_date, channel)` | model → `metric_service` → `routes/stores#series`/`routes/metrics` → `api.stores.series` → 门店抽屉 |
| `OperatingCalendar` 运营日历 | `operating_calendar` | `(store_id, day_type, start_date, end_date)` | model → `calendar_service` → `calendar_controller` → `api.calendar` → 运营日历页 / 异常抽屉 |
| `CalendarRevision` 日历版本 | `calendar_revisions` | `version` | model → `calendar_service` → `api.calendar/revisions` → 运营日历页 |
| `Anomaly` 异常 | `anomalies` | `(store_id, metric_date, metric_key)` | model → schema → `anomaly_service` → `anomaly_controller` → `api.anomalies` → 异常清单 |
| `Attribution` 归因 | `attributions` | `anomaly_id` | model → `attribution_service` → `attribution_controller` → `api.attributions` → 归因页 |
| `Report` 报告 | `reports` | `report_no` | model → schema → `report_service` → `report_controller` → `api.reports` → 报告页 |
| `Run` 检测批次 | `runs` | `run_no` / `seed_key` | model → `run_service` → `run_controller` → 异常清单「发起检测」 |
| `GenerationJob` 失效重算任务 | `generation_jobs` | `job_no` | model → `generation_service` → `calendar_controller` → `api.calendar/jobs` → 运营日历页 |

> `anomalies` / `reports` 上的 `calendar_version` + `invalidated*` 字段用于记录「哪个日历版本产出、是否因规则变更失效」；`attributions.sample_key` 用于校验三项与下钻引用同一组样本。

## 12. Docker 说明

- 5 个服务：`frontend`(nginx 静态站) / `backend`(uvicorn) / `worker`(Celery) / `db`(MySQL 8.0) / `redis`，全部带 healthcheck，`depends_on: service_healthy`。
- 命名卷：`db_data`、`redis_data`；端口 `${FRONTEND_PORT:-18209}` / `${BACKEND_PORT:-19209}` / `${DB_PORT:-17709}`。
- Nginx：`location /api/ { proxy_pass http://backend:8000/; }`（剥掉 `/api` 前缀）+ SPA 回落。
- 收尾：`docker compose down -v --remove-orphans`。

## License

内部演示项目，仅用于评测与教学。
