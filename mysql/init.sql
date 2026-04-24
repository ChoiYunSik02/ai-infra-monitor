-- AI Infra Monitor DB 초기화

CREATE DATABASE IF NOT EXISTS infra_monitor;
USE infra_monitor;

-- 시스템 메트릭 테이블 (Node-RED가 여기에 데이터 저장)
CREATE TABLE IF NOT EXISTS system_metrics (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    hostname    VARCHAR(100) NOT NULL DEFAULT 'zorin-vm',
    cpu_usage   FLOAT        NOT NULL COMMENT 'CPU 사용률 (%)',
    mem_total   BIGINT       NOT NULL COMMENT '전체 메모리 (bytes)',
    mem_used    BIGINT       NOT NULL COMMENT '사용 중인 메모리 (bytes)',
    mem_percent FLOAT        NOT NULL COMMENT '메모리 사용률 (%)',
    disk_total  BIGINT       NOT NULL COMMENT '전체 디스크 (bytes)',
    disk_used   BIGINT       NOT NULL COMMENT '사용 중인 디스크 (bytes)',
    disk_percent FLOAT       NOT NULL COMMENT '디스크 사용률 (%)',
    net_bytes_sent   BIGINT  NOT NULL DEFAULT 0 COMMENT '네트워크 송신 (bytes)',
    net_bytes_recv   BIGINT  NOT NULL DEFAULT 0 COMMENT '네트워크 수신 (bytes)',
    recorded_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_recorded_at (recorded_at),
    INDEX idx_hostname (hostname)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- AI 분석 결과 테이블 (Ollama 분석 결과 저장)
CREATE TABLE IF NOT EXISTS ai_analysis (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    metric_id   BIGINT       REFERENCES system_metrics(id),
    severity    ENUM('info', 'warning', 'critical') NOT NULL DEFAULT 'info',
    title       VARCHAR(200) NOT NULL,
    analysis    TEXT         NOT NULL COMMENT 'Ollama AI 분석 내용',
    suggestion  TEXT         COMMENT 'AI 개선 제안',
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_severity (severity),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 알림 이력 테이블 (N8N 트리거 기록)
CREATE TABLE IF NOT EXISTS alert_history (
    id          BIGINT AUTO_INCREMENT PRIMARY KEY,
    alert_type  VARCHAR(50)  NOT NULL COMMENT 'cpu_high, mem_high, disk_high 등',
    threshold   FLOAT        NOT NULL COMMENT '임계값',
    actual_value FLOAT       NOT NULL COMMENT '실제 측정값',
    message     TEXT         NOT NULL,
    triggered_at DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_alert_type (alert_type),
    INDEX idx_triggered_at (triggered_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 샘플 데이터 (테스트용)
INSERT INTO system_metrics (cpu_usage, mem_total, mem_used, mem_percent, disk_total, disk_used, disk_percent)
VALUES
    (15.2, 4294967296, 1073741824, 25.0, 21474836480, 5368709120, 25.0),
    (45.8, 4294967296, 2147483648, 50.0, 21474836480, 8589934592, 40.0),
    (72.1, 4294967296, 3221225472, 75.0, 21474836480, 12884901888, 60.0);
