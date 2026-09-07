-- =====================================================================
-- ShopMind 共享数据模型（MySQL 8）
-- 设计主线：数据资产平台(P1) 供血 → 各 AI 应用(P2~P5) 取数 + 回血
-- 三组表：
--   A. 资产平台元数据（P1 自己管理：源/资产/血缘/采集/清洗/脱敏/审计）
--   B. 业务域（共享数据链：客户/商品/订单/会话/FAQ/知识文档，P2~P5 消费）
--   C. 各 AI 应用的「回血」表（直播切片 / 素材任务 / 评测，写回中台）
-- =====================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ---------------------------------------------------------------------
-- A. 数据资产平台元数据（P1）
-- ---------------------------------------------------------------------

-- 数据源注册表：来自哪里（MySQL/ES/MinIO/CSV/API）
CREATE TABLE IF NOT EXISTS data_source (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(128) NOT NULL COMMENT '数据源名称',
    source_type VARCHAR(32)  NOT NULL COMMENT 'mysql|es|minio|csv|api',
    location    VARCHAR(512) NOT NULL COMMENT '定位信息(连接串/bucket/key/文件路径)',
    config_json JSON         NULL COMMENT '额外配置',
    status      VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT 'active|disabled',
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_source_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数据源注册表';

-- 资产目录：中台统一登记的表/索引/文件/对象
CREATE TABLE IF NOT EXISTS data_asset (
    id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name         VARCHAR(128) NOT NULL COMMENT '资产名，如 orders / faq_kb / 客服会话',
    asset_type   VARCHAR(32)  NOT NULL COMMENT 'table|index|file|object',
    location     VARCHAR(512) NOT NULL COMMENT '物理定位 mysql:db.table / es:index / minio:bucket/key',
    owner        VARCHAR(64)  NULL COMMENT '负责项目 p1..p5',
    sensitivity  VARCHAR(8)   NOT NULL DEFAULT 'L3' COMMENT 'L1公开/L2内部/L3敏感/L4机密',
    description  TEXT         NULL,
    row_count    BIGINT       NOT NULL DEFAULT 0,
    updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_asset_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数据资产目录';

-- 血缘：源资产 → 目标资产（谁从谁派生 / 谁回血给谁）
CREATE TABLE IF NOT EXISTS lineage_edge (
    id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    src_asset_id BIGINT UNSIGNED NOT NULL,
    dst_asset_id BIGINT UNSIGNED NOT NULL,
    relation     VARCHAR(32)     NOT NULL COMMENT 'derives_from|feeds',
    description  VARCHAR(512)    NULL,
    created_at   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_src (src_asset_id),
    KEY idx_dst (dst_asset_id),
    UNIQUE KEY uk_edge (src_asset_id, dst_asset_id, relation)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数据血缘';

-- 采集任务
CREATE TABLE IF NOT EXISTS ingest_job (
    id            BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    source_id     BIGINT UNSIGNED NOT NULL,
    target_asset  VARCHAR(128)    NOT NULL COMMENT '目标资产名',
    status        VARCHAR(16)     NOT NULL DEFAULT 'pending' COMMENT 'pending|running|success|failed',
    rows_ingested BIGINT          NOT NULL DEFAULT 0,
    error         TEXT            NULL,
    started_at    DATETIME        NULL,
    finished_at   DATETIME        NULL,
    created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_source (source_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='采集任务';

-- 清洗规则
CREATE TABLE IF NOT EXISTS cleaning_rule (
    id         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(128) NOT NULL,
    rule_type  VARCHAR(32)  NOT NULL COMMENT 'drop_null|dedup|trim|normalize|range|format',
    params_json JSON        NULL,
    enabled    TINYINT(1)   NOT NULL DEFAULT 1,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_rule_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='清洗规则';

-- 脱敏规则
CREATE TABLE IF NOT EXISTS desensitization_rule (
    id         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(128) NOT NULL,
    field      VARCHAR(64)  NOT NULL COMMENT '目标字段',
    rule_type  VARCHAR(32)  NOT NULL COMMENT 'mask|phone|email|idcard|hash|generalize',
    params_json JSON        NULL,
    enabled    TINYINT(1)   NOT NULL DEFAULT 1,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_desens (name, field)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脱敏规则';

-- 审计日志
CREATE TABLE IF NOT EXISTS audit_log (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    actor       VARCHAR(64)  NOT NULL,
    action      VARCHAR(64)  NOT NULL,
    asset_id    BIGINT UNSIGNED NULL,
    detail_json JSON         NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_asset (asset_id),
    KEY idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='审计日志';

-- ---------------------------------------------------------------------
-- B. 业务域（共享数据链，P2~P5 消费）
-- ---------------------------------------------------------------------

-- 客户（脱敏后落库；原始 PII 只存在于采集 staging，处理后丢弃）
CREATE TABLE IF NOT EXISTS customer (
    id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    customer_no  VARCHAR(32)  NOT NULL COMMENT '脱敏后客户编号',
    name_masked  VARCHAR(32)  NULL COMMENT '姓名脱敏 张**',
    phone_masked VARCHAR(32)  NULL COMMENT '手机脱敏 138****1234',
    email_masked VARCHAR(64)  NULL COMMENT '邮箱脱敏 z***@xx.com',
    city         VARCHAR(32)  NULL,
    level        VARCHAR(16)  NOT NULL DEFAULT 'normal' COMMENT 'normal|silver|gold|platinum',
    created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_customer_no (customer_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='客户(脱敏)';

-- 商品
CREATE TABLE IF NOT EXISTS product (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    sku         VARCHAR(64)  NOT NULL,
    name        VARCHAR(256) NOT NULL,
    category    VARCHAR(64)  NULL,
    brand       VARCHAR(64)  NULL,
    price       DECIMAL(12,2) NOT NULL DEFAULT 0,
    stock       INT          NOT NULL DEFAULT 0,
    description TEXT         NULL,
    specs_json  JSON         NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_sku (sku),
    KEY idx_category (category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品';

-- 订单
CREATE TABLE IF NOT EXISTS orders (
    id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    order_no     VARCHAR(32)  NOT NULL,
    customer_id  BIGINT UNSIGNED NOT NULL,
    status       VARCHAR(32)  NOT NULL DEFAULT 'paid' COMMENT 'paid|shipped|delivered|refunding|refunded|closed',
    total_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
    channel      VARCHAR(16)  NOT NULL DEFAULT 'app',
    created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_order_no (order_no),
    KEY idx_customer (customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单';

-- 订单明细
CREATE TABLE IF NOT EXISTS order_item (
    id         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    order_id   BIGINT UNSIGNED NOT NULL,
    product_id BIGINT UNSIGNED NOT NULL,
    quantity   INT          NOT NULL DEFAULT 1,
    price      DECIMAL(12,2) NOT NULL DEFAULT 0,
    KEY idx_order (order_id),
    KEY idx_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='订单明细';

-- 客服会话
CREATE TABLE IF NOT EXISTS conversation (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    conversation_no VARCHAR(32)  NOT NULL,
    customer_id     BIGINT UNSIGNED NOT NULL,
    channel         VARCHAR(16)  NOT NULL DEFAULT 'online' COMMENT 'online|live|phone',
    intent          VARCHAR(32)  NULL COMMENT '咨询|售后|物流|退款|投诉|其他',
    status          VARCHAR(16)  NOT NULL DEFAULT 'open' COMMENT 'open|resolved',
    satisfaction    TINYINT      NULL COMMENT '1~5 满意度',
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at       DATETIME     NULL,
    UNIQUE KEY uk_conv_no (conversation_no),
    KEY idx_customer (customer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='客服会话';

-- 消息
CREATE TABLE IF NOT EXISTS message (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    conversation_id BIGINT UNSIGNED NOT NULL,
    role            VARCHAR(16)  NOT NULL COMMENT 'customer|agent|bot',
    content         TEXT         NOT NULL,
    intent          VARCHAR(32)  NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_conv (conversation_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='会话消息';

-- 工单
CREATE TABLE IF NOT EXISTS ticket (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    ticket_no       VARCHAR(32)  NOT NULL,
    conversation_id BIGINT UNSIGNED NULL,
    type            VARCHAR(32)  NOT NULL COMMENT '售后|投诉|技术|其他',
    priority        VARCHAR(8)   NOT NULL DEFAULT 'P2' COMMENT 'P0~P3',
    status          VARCHAR(16)  NOT NULL DEFAULT 'open' COMMENT 'open|processing|resolved|closed',
    assignee        VARCHAR(64)  NULL,
    created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at     DATETIME     NULL,
    UNIQUE KEY uk_ticket_no (ticket_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='工单';

-- FAQ（结构化知识，P2 知识库来源之一）
CREATE TABLE IF NOT EXISTS faq (
    id         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    question   VARCHAR(512) NOT NULL,
    answer     TEXT         NOT NULL,
    category   VARCHAR(64)  NULL,
    tags       VARCHAR(256) NULL,
    product_id BIGINT UNSIGNED NULL,
    enabled    TINYINT(1)   NOT NULL DEFAULT 1,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_category (category),
    KEY idx_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='FAQ 知识';

-- 知识文档（非结构化知识：政策/手册/直播转写；正文进 MinIO，元数据在 MySQL）
CREATE TABLE IF NOT EXISTS knowledge_doc (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    title       VARCHAR(256) NOT NULL,
    source_type VARCHAR(32)  NOT NULL COMMENT 'policy|manual|guide|faq|live_transcript',
    object_key  VARCHAR(512) NULL COMMENT 'MinIO 对象 key（正文文件）',
    doc_meta    JSON         NULL,
    chunk_count INT          NOT NULL DEFAULT 0,
    status      VARCHAR(16)  NOT NULL DEFAULT 'staged' COMMENT 'staged|embedded|indexed',
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识文档';

-- 文档切片（元数据在 MySQL，向量在 ES）
CREATE TABLE IF NOT EXISTS chunk (
    id         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    doc_id     BIGINT UNSIGNED NOT NULL,
    seq        INT          NOT NULL COMMENT '切片序号',
    content    TEXT         NOT NULL,
    token_count INT         NULL,
    es_doc_id  VARCHAR(128) NULL COMMENT '对应 ES 文档 _id',
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_doc (doc_id),
    UNIQUE KEY uk_doc_seq (doc_id, seq)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档切片';

-- 向量记录（以 ES 为准，这里登记模型/维度用于对齐审计）
CREATE TABLE IF NOT EXISTS embedding_record (
    id         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    chunk_id   BIGINT UNSIGNED NOT NULL,
    model      VARCHAR(128) NOT NULL,
    dim        INT          NOT NULL,
    es_doc_id  VARCHAR(128) NOT NULL,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_chunk (chunk_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='向量记录';

-- ---------------------------------------------------------------------
-- C. 各 AI 应用的「回血」表
-- ---------------------------------------------------------------------

-- 直播间 / 场次 / 切片（P3）
CREATE TABLE IF NOT EXISTS live_room (
    id         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    room_id    VARCHAR(64)  NOT NULL,
    title      VARCHAR(256) NOT NULL,
    anchor     VARCHAR(64)  NULL,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_room_id (room_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='直播间';

CREATE TABLE IF NOT EXISTS live_session (
    id                BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    room_id           BIGINT UNSIGNED NOT NULL,
    session_no        VARCHAR(64)  NOT NULL,
    started_at        DATETIME     NOT NULL,
    ended_at          DATETIME     NULL,
    duration_sec      INT          NULL,
    asr_status        VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT 'pending|transcribing|done|failed',
    transcript_object_key VARCHAR(512) NULL COMMENT 'MinIO 转写文本 key',
    created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_session_no (session_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='直播场次';

CREATE TABLE IF NOT EXISTS live_segment (
    id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    session_id  BIGINT UNSIGNED NOT NULL,
    seq         INT          NOT NULL,
    start_sec   INT          NOT NULL,
    end_sec     INT          NOT NULL,
    transcript  TEXT         NOT NULL,
    topic       VARCHAR(128) NULL,
    summary     TEXT         NULL,
    sentiment   VARCHAR(16)  NULL COMMENT 'positive|neutral|negative',
    product_ids JSON         NULL COMMENT '关联商品 id 列表',
    clip_object_key VARCHAR(512) NULL,
    status      VARCHAR(16)  NOT NULL DEFAULT 'segmented',
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_session (session_id),
    UNIQUE KEY uk_session_seq (session_id, seq)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='直播语义切片';

-- 素材生产（P4）
CREATE TABLE IF NOT EXISTS material_task (
    id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    task_no        VARCHAR(64)  NOT NULL,
    task_type      VARCHAR(32)  NOT NULL COMMENT 'product_copy|live_highlight|faq_expansion',
    input_json     JSON         NULL,
    state          VARCHAR(32)  NOT NULL DEFAULT 'draft' COMMENT '状态机状态',
    current_step   VARCHAR(32)  NULL,
    assignee       VARCHAR(64)  NULL COMMENT '人工审核人',
    result_json    JSON         NULL,
    compliance     VARCHAR(32)  NULL COMMENT 'pass|fail|review',
    error          TEXT         NULL,
    created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_task_no (task_no),
    KEY idx_state (state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='素材生产任务';

CREATE TABLE IF NOT EXISTS material_review (
    id         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    task_id    BIGINT UNSIGNED NOT NULL,
    reviewer   VARCHAR(64)  NOT NULL,
    decision   VARCHAR(16)  NOT NULL COMMENT 'approve|reject',
    feedback   TEXT         NULL,
    created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='素材审核记录';

CREATE TABLE IF NOT EXISTS material_output (
    id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    task_id      BIGINT UNSIGNED NOT NULL,
    content      TEXT         NULL,
    content_type VARCHAR(32)  NULL COMMENT 'text|image|video',
    object_key   VARCHAR(512) NULL,
    status       VARCHAR(16)  NOT NULL DEFAULT 'draft' COMMENT 'draft|approved|published|rejected',
    created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='素材产出';

-- 评测（P2/P5 共用）
CREATE TABLE IF NOT EXISTS eval_dataset (
    id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name         VARCHAR(128) NOT NULL,
    dataset_type VARCHAR(32)  NOT NULL COMMENT 'retrieval|rag|refusal|humanize',
    size         INT          NOT NULL DEFAULT 0,
    description  TEXT         NULL,
    created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_dataset_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='评测集';

CREATE TABLE IF NOT EXISTS eval_item (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    dataset_id      BIGINT UNSIGNED NOT NULL,
    question        TEXT         NOT NULL,
    ground_truth    TEXT         NULL COMMENT '标准答案/相关文档 id',
    context         TEXT         NULL,
    expected_answer TEXT         NULL,
    meta_json       JSON         NULL,
    KEY idx_dataset (dataset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='评测样本';

CREATE TABLE IF NOT EXISTS eval_run (
    id           BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    dataset_id   BIGINT UNSIGNED NOT NULL,
    model        VARCHAR(128) NOT NULL,
    run_tag      VARCHAR(32)  NULL COMMENT 'before|after|baseline',
    config_json  JSON         NULL,
    metrics_json JSON         NULL,
    created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_dataset (dataset_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='评测运行';

SET FOREIGN_KEY_CHECKS = 1;
