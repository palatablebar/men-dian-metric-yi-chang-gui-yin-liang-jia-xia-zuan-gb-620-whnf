-- 核心表结构参考（MySQL 8.0 语法；运行时不执行，建表由 SQLAlchemy create_all 完成）

CREATE TABLE users (
  id             BIGINT PRIMARY KEY AUTO_INCREMENT,
  email          VARCHAR(160) NOT NULL UNIQUE,
  password_hash  VARCHAR(255) NOT NULL,
  display_name   VARCHAR(80)  NOT NULL,
  role           VARCHAR(20)  NOT NULL,
  org            VARCHAR(120),
  created_at     DATETIME     NOT NULL
);

CREATE TABLE stores (
  id          BIGINT PRIMARY KEY AUTO_INCREMENT,
  code        VARCHAR(40) NOT NULL UNIQUE,
  name        VARCHAR(120) NOT NULL,
  region      VARCHAR(40) NOT NULL,
  city        VARCHAR(40) NOT NULL,
  brand       VARCHAR(40) NOT NULL,
  room_count  INT NOT NULL DEFAULT 200,
  manager     VARCHAR(60),
  status      VARCHAR(20) NOT NULL DEFAULT 'open',
  note        TEXT,
  created_at  DATETIME NOT NULL,
  updated_at  DATETIME NOT NULL,
  INDEX ix_stores_region (region),
  INDEX ix_stores_status (status)
);

CREATE TABLE metric_points (
  id               BIGINT PRIMARY KEY AUTO_INCREMENT,
  store_id         BIGINT NOT NULL,
  stat_date        DATE   NOT NULL,
  channel          VARCHAR(20) NOT NULL,
  rooms_available  INT NOT NULL DEFAULT 0,
  rooms_sold       INT NOT NULL DEFAULT 0,
  occupancy        DOUBLE NOT NULL DEFAULT 0,
  adr              DOUBLE NOT NULL DEFAULT 0,
  revenue          DOUBLE NOT NULL DEFAULT 0,
  is_weekend       BOOLEAN NOT NULL DEFAULT FALSE,
  room_type_mix    JSON,
  created_at       DATETIME NOT NULL,
  CONSTRAINT uq_metric_store_date_channel UNIQUE (store_id, stat_date, channel),
  CONSTRAINT fk_metric_store FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE
);

CREATE TABLE runs (
  id             BIGINT PRIMARY KEY AUTO_INCREMENT,
  run_no         VARCHAR(40) NOT NULL UNIQUE,
  store_id       BIGINT NULL,
  trigger_kind   VARCHAR(20) NOT NULL,
  status         VARCHAR(20) NOT NULL,
  operator_email VARCHAR(160) NOT NULL,
  store_count    INT NOT NULL DEFAULT 0,
  point_count    INT NOT NULL DEFAULT 0,
  anomaly_count  INT NOT NULL DEFAULT 0,
  params         JSON,
  metrics        JSON,
  log_text       TEXT,
  seed_key       VARCHAR(120) UNIQUE,
  started_at     DATETIME NOT NULL,
  finished_at    DATETIME
);

CREATE TABLE anomalies (
  id             BIGINT PRIMARY KEY AUTO_INCREMENT,
  run_id         BIGINT NULL,
  store_id       BIGINT NOT NULL,
  metric_date    DATE NOT NULL,
  metric_key     VARCHAR(12) NOT NULL,
  observed       DOUBLE NOT NULL DEFAULT 0,
  baseline       DOUBLE NOT NULL DEFAULT 0,
  mad            DOUBLE NOT NULL DEFAULT 0,
  robust_z       DOUBLE NOT NULL DEFAULT 0,
  direction      VARCHAR(8) NOT NULL,
  severity       VARCHAR(12) NOT NULL,
  impact_amount  DOUBLE NOT NULL DEFAULT 0,
  status         VARCHAR(16) NOT NULL DEFAULT 'pending',
  reviewer       VARCHAR(160),
  review_note    TEXT,
  reviewed_at    DATETIME,
  payload        JSON,
  created_at     DATETIME NOT NULL,
  updated_at     DATETIME NOT NULL,
  CONSTRAINT uq_anomaly_store_date_metric UNIQUE (store_id, metric_date, metric_key),
  CONSTRAINT fk_anomaly_store FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE
);

CREATE TABLE attributions (
  id           BIGINT PRIMARY KEY AUTO_INCREMENT,
  anomaly_id   BIGINT NOT NULL,
  store_id     BIGINT NOT NULL,
  method       VARCHAR(60) NOT NULL,
  status       VARCHAR(16) NOT NULL,
  base_rev     DOUBLE NOT NULL DEFAULT 0,
  cur_rev      DOUBLE NOT NULL DEFAULT 0,
  total_delta  DOUBLE NOT NULL DEFAULT 0,
  adr_part     DOUBLE NOT NULL DEFAULT 0,
  occ_part     DOUBLE NOT NULL DEFAULT 0,
  rooms_part   DOUBLE NOT NULL DEFAULT 0,
  adr_share    DOUBLE,
  occ_share    DOUBLE,
  rooms_share  DOUBLE,
  residual     DOUBLE NOT NULL DEFAULT 0,
  drivers      JSON,
  dimensions   JSON,
  narrative    TEXT,
  created_at   DATETIME NOT NULL,
  CONSTRAINT uq_attribution_anomaly UNIQUE (anomaly_id),
  CONSTRAINT fk_attribution_anomaly FOREIGN KEY (anomaly_id) REFERENCES anomalies(id) ON DELETE CASCADE
);

CREATE TABLE reports (
  id             BIGINT PRIMARY KEY AUTO_INCREMENT,
  report_no      VARCHAR(40) NOT NULL UNIQUE,
  kind           VARCHAR(12) NOT NULL,
  period_start   DATE NOT NULL,
  period_end     DATE NOT NULL,
  title          VARCHAR(200) NOT NULL,
  status         VARCHAR(16) NOT NULL DEFAULT 'draft',
  generated_by   VARCHAR(160) NOT NULL,
  anomaly_count  INT NOT NULL DEFAULT 0,
  impact_total   DOUBLE NOT NULL DEFAULT 0,
  note           TEXT,
  snapshot       JSON,
  seed_key       VARCHAR(120) UNIQUE,
  created_at     DATETIME NOT NULL,
  updated_at     DATETIME NOT NULL
);

CREATE TABLE audit_logs (
  id           BIGINT PRIMARY KEY AUTO_INCREMENT,
  actor_email  VARCHAR(160) NOT NULL,
  actor_role   VARCHAR(20) NOT NULL,
  action       VARCHAR(64) NOT NULL,
  entity       VARCHAR(40) NOT NULL,
  entity_id    VARCHAR(64),
  detail       JSON,
  layer        VARCHAR(16) NOT NULL DEFAULT 'domain',
  ip           VARCHAR(64),
  seed_key     VARCHAR(120) UNIQUE,
  created_at   DATETIME NOT NULL
);

-- ---- 运营日历（特殊日不进常态基线）----
CREATE TABLE operating_calendar (
  id                BIGINT PRIMARY KEY AUTO_INCREMENT,
  store_id          BIGINT NOT NULL,
  day_type          VARCHAR(20) NOT NULL,          -- promo / renovating / closed
  start_date        DATE NOT NULL,
  end_date          DATE NOT NULL,
  label             VARCHAR(120) NOT NULL DEFAULT '',
  note              TEXT,
  active            BOOLEAN NOT NULL DEFAULT TRUE,
  calendar_version  INT NOT NULL DEFAULT 0,
  created_by        VARCHAR(160) NOT NULL DEFAULT '',
  seed_key          VARCHAR(120) UNIQUE,
  created_at        DATETIME NOT NULL,
  updated_at        DATETIME NOT NULL,
  CONSTRAINT uq_calendar_store_type_span UNIQUE (store_id, day_type, start_date, end_date),
  CONSTRAINT fk_calendar_store FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE
);

CREATE TABLE calendar_revisions (
  id           BIGINT PRIMARY KEY AUTO_INCREMENT,
  version      INT NOT NULL UNIQUE,
  action       VARCHAR(20) NOT NULL,
  actor_email  VARCHAR(160) NOT NULL DEFAULT '',
  summary      VARCHAR(200) NOT NULL DEFAULT '',
  scope        JSON,
  seed_key     VARCHAR(120) UNIQUE,
  created_at   DATETIME NOT NULL
);

CREATE TABLE generation_jobs (
  id                BIGINT PRIMARY KEY AUTO_INCREMENT,
  job_no            VARCHAR(48) NOT NULL UNIQUE,
  kind              VARCHAR(20) NOT NULL DEFAULT 'recompute',
  calendar_version  INT NOT NULL DEFAULT 0,
  status            VARCHAR(20) NOT NULL DEFAULT 'running',
  stage             VARCHAR(20) NOT NULL DEFAULT 'staged',
  payload           JSON,
  staging           JSON,
  progress          JSON,
  recovered_from    INT NULL,
  idempotent_hit    BOOLEAN NOT NULL DEFAULT FALSE,
  log_text          TEXT,
  created_at        DATETIME NOT NULL,
  updated_at        DATETIME NOT NULL
);

-- 已有表的增量列（新库由 SQLAlchemy 直接建全；旧库由启动时轻量补列）
ALTER TABLE runs ADD COLUMN calendar_version INT NOT NULL DEFAULT 0;
ALTER TABLE anomalies
  ADD COLUMN calendar_version INT NOT NULL DEFAULT 0,
  ADD COLUMN invalidated BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN invalidated_reason VARCHAR(60) NULL,
  ADD COLUMN invalidated_by_version INT NULL;
ALTER TABLE attributions
  ADD COLUMN calendar_version INT NOT NULL DEFAULT 0,
  ADD COLUMN sample_key VARCHAR(64) NOT NULL DEFAULT '',
  ADD COLUMN updated_at DATETIME NULL;
ALTER TABLE reports
  ADD COLUMN calendar_version INT NOT NULL DEFAULT 0,
  ADD COLUMN invalidated BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN invalidated_reason VARCHAR(60) NULL,
  ADD COLUMN invalidated_by_version INT NULL,
  ADD COLUMN superseded_by INT NULL;
