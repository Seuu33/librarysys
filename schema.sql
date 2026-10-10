-- 图书馆管理系统 数据库结构（MySQL 8.0+）

CREATE DATABASE IF NOT EXISTS library
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE library;

-- 用户表：读者 + 管理员
CREATE TABLE IF NOT EXISTS users (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  username      VARCHAR(50)  NOT NULL UNIQUE COMMENT '登录账号',
  password_hash VARCHAR(255) NOT NULL COMMENT '密码哈希',
  role          ENUM('reader','admin') NOT NULL DEFAULT 'reader',
  points        INT NOT NULL DEFAULT 0 COMMENT '累计积分',
  banned_until  DATETIME NULL COMMENT '预约封禁截止时间',
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- 图书表
CREATE TABLE IF NOT EXISTS books (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  title      VARCHAR(200) NOT NULL COMMENT '书名',
  author     VARCHAR(100) NOT NULL COMMENT '作者',
  publisher  VARCHAR(100) NOT NULL COMMENT '出版社',
  total      INT NOT NULL DEFAULT 1 COMMENT '总数量',
  remaining  INT NOT NULL DEFAULT 1 COMMENT '余量',
  location   VARCHAR(100) NOT NULL COMMENT '馆藏位置',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT chk_rem CHECK (remaining >= 0),
  CONSTRAINT chk_rem2 CHECK (remaining <= total)
) ENGINE=InnoDB;

-- 借阅记录表
CREATE TABLE IF NOT EXISTS borrows (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  user_id     INT NOT NULL,
  book_id     INT NOT NULL,
  borrow_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  return_time DATETIME NULL,
  status      ENUM('borrowed','returned') NOT NULL DEFAULT 'borrowed',
  CONSTRAINT fk_b1 FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_b2 FOREIGN KEY (book_id) REFERENCES books(id)
) ENGINE=InnoDB;

-- 座位表
CREATE TABLE IF NOT EXISTS seats (
  id      INT AUTO_INCREMENT PRIMARY KEY,
  seat_no VARCHAR(20) NOT NULL UNIQUE,
  area    VARCHAR(50) NOT NULL,
  seat_code    VARCHAR(16) NULL COMMENT '座位暗码（贴在座位上的二维码内容）'
) ENGINE=InnoDB;

-- 座位预约表（状态流转：reserved→checked_in→left；超时→expired；主动→cancelled）
CREATE TABLE IF NOT EXISTS seat_reservations (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  user_id      INT NOT NULL,
  seat_id      INT NOT NULL,
  start_time   DATETIME NOT NULL,
  expire_time  DATETIME NOT NULL COMMENT '签到截止=预约后1小时',
  checkin_time DATETIME NULL,
  leave_time   DATETIME NULL,
  status       ENUM('reserved','checked_in','left','expired','cancelled')
               NOT NULL DEFAULT 'reserved',
  CONSTRAINT fk_s1 FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_s2 FOREIGN KEY (seat_id) REFERENCES seats(id)
) ENGINE=InnoDB;

-- 积分流水表（周/月/年榜的统计依据）
CREATE TABLE IF NOT EXISTS points_log (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  user_id    INT NOT NULL,
  points     INT NOT NULL,
  reason     VARCHAR(100) NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_p1 FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;

-- 荣誉称号表（UNIQUE 约束防重复授予）
CREATE TABLE IF NOT EXISTS honors (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  user_id      INT NOT NULL,
  period_type  ENUM('week','month','year') NOT NULL,
  period_start DATE NOT NULL,
  title        VARCHAR(50) NOT NULL,
  created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_honor (user_id, period_type, period_start),
  CONSTRAINT fk_h1 FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB;

-- 初始座位：三个区，每区10个
INSERT INTO seats (seat_no, area)
SELECT CONCAT('A-', LPAD(n, 2, '0')), '一楼自习区' FROM (
  SELECT 1 n UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5
  UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9 UNION ALL SELECT 10
) t
WHERE NOT EXISTS (SELECT 1 FROM seats WHERE area = '一楼自习区');

INSERT INTO seats (seat_no, area)
SELECT CONCAT('B-', LPAD(n, 2, '0')), '二楼自习区' FROM (
  SELECT 1 n UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5
  UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9 UNION ALL SELECT 10
) t
WHERE NOT EXISTS (SELECT 1 FROM seats WHERE area = '二楼自习区');

INSERT INTO seats (seat_no, area)
SELECT CONCAT('C-', LPAD(n, 2, '0')), '三楼阅览室' FROM (
  SELECT 1 n UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4 UNION ALL SELECT 5
  UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9 UNION ALL SELECT 10
) t
WHERE NOT EXISTS (SELECT 1 FROM seats WHERE area = '三楼阅览室');