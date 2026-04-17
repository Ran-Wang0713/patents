DROP DATABASE IF EXISTS patent_analysis_platform;
CREATE DATABASE patent_analysis_platform CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE patent_analysis_platform;

-- 1. 技术领域表
CREATE TABLE technology_domains (
    id INT AUTO_INCREMENT PRIMARY KEY,
    domain_name VARCHAR(50) NOT NULL UNIQUE,
    domain_code VARCHAR(10) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO technology_domains (domain_name, domain_code, description) VALUES
('人工智能', 'AI', '机器学习、深度学习、自然语言处理等技术'),
('大数据', 'BD', '数据挖掘、数据分析、数据可视化等技术'),
('物联网', 'IoT', '传感器网络、智能设备、物联网协议等技术'),
('区块链', 'BC', '分布式账本、智能合约、加密算法等技术'),
('5G', '5G', '第五代移动通信技术、网络切片等技术'),
('量子计算', 'QC', '量子比特、量子算法、量子通信等技术'),
('云计算', 'CC', '云服务、虚拟化、分布式计算等技术');

-- 2. 申请人表
CREATE TABLE applicants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(500) NOT NULL,
    applicant_type ENUM('企业', '科研机构', '个人', '高校', '其他') DEFAULT '企业',
    country VARCHAR(100) DEFAULT '中国',
    established_year YEAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_applicant_name (name(100)),
    INDEX idx_applicant_type (applicant_type),
    INDEX idx_country (country)
);

-- 3. 发明人表
CREATE TABLE inventors (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(500) NOT NULL,
    nationality VARCHAR(100) DEFAULT '中国',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_inventor_name (name(100))
);

-- 4. IPC 分类表
CREATE TABLE ipc_classes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ipc_code VARCHAR(50) NOT NULL,
    ipc_section VARCHAR(5),
    ipc_class VARCHAR(10),
    ipc_subclass VARCHAR(15),
    ipc_group VARCHAR(20),
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ipc_code (ipc_code),
    INDEX idx_section (ipc_section),
    INDEX idx_class (ipc_class)
);

-- 5. 专利主表（修复版！无错误！）
CREATE TABLE patents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    公开公告号 VARCHAR(500) NOT NULL,
    公开公告日 VARCHAR(500),
    IPC分类号 TEXT,
    申请专利权人 TEXT,
    发明人 TEXT,
    发明名称 TEXT NOT NULL,
    摘要 TEXT,
    引证 TEXT,

    publication_number VARCHAR(100),
    publication_date DATE,
    application_date DATE,
    technology_domain_id INT NOT NULL,
    patent_type ENUM('发明专利', '实用新型', '外观设计') DEFAULT '发明专利',
    legal_status ENUM('有效', '失效', '审查中', '授权') DEFAULT '审查中',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (technology_domain_id) REFERENCES technology_domains(id) ON DELETE RESTRICT,

    INDEX idx_公开公告号 (公开公告号(100)),
    INDEX idx_publication_date (publication_date),
    INDEX idx_technology_domain (technology_domain_id),
    INDEX idx_patent_type (patent_type),
    INDEX idx_legal_status (legal_status)
);

-- 6. 关联表
CREATE TABLE patent_applicant (
    id INT AUTO_INCREMENT PRIMARY KEY,
    patent_id INT NOT NULL,
    applicant_id INT NOT NULL,
    applicant_sequence INT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patent_id) REFERENCES patents(id) ON DELETE CASCADE,
    FOREIGN KEY (applicant_id) REFERENCES applicants(id) ON DELETE CASCADE,
    UNIQUE KEY unique_patent_applicant (patent_id, applicant_id, applicant_sequence)
);

CREATE TABLE patent_inventor (
    id INT AUTO_INCREMENT PRIMARY KEY,
    patent_id INT NOT NULL,
    inventor_id INT NOT NULL,
    inventor_sequence INT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patent_id) REFERENCES patents(id) ON DELETE CASCADE,
    FOREIGN KEY (inventor_id) REFERENCES inventors(id) ON DELETE CASCADE,
    UNIQUE KEY unique_patent_inventor (patent_id, inventor_id, inventor_sequence)
);

CREATE TABLE patent_ipc (
    id INT AUTO_INCREMENT PRIMARY KEY,
    patent_id INT NOT NULL,
    ipc_class_id INT NOT NULL,
    main_ipc BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patent_id) REFERENCES patents(id) ON DELETE CASCADE,
    FOREIGN KEY (ipc_class_id) REFERENCES ipc_classes(id) ON DELETE CASCADE,
    UNIQUE KEY unique_patent_ipc (patent_id, ipc_class_id)
);

-- 7. 引用关系表
CREATE TABLE patent_citations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    citing_patent_id INT NOT NULL,
    cited_patent_id INT NOT NULL,
    citation_type ENUM('直接引用', '间接引用', '审查引用') DEFAULT '直接引用',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (citing_patent_id) REFERENCES patents(id) ON DELETE CASCADE,
    FOREIGN KEY (cited_patent_id) REFERENCES patents(id) ON DELETE CASCADE,
    UNIQUE KEY unique_citation (citing_patent_id, cited_patent_id),
    INDEX idx_citing_patent (citing_patent_id),
    INDEX idx_cited_patent (cited_patent_id)
);

-- 8. 触发器
DELIMITER $$

CREATE TRIGGER before_insert_ipc_classes
BEFORE INSERT ON ipc_classes
FOR EACH ROW
BEGIN
    IF NEW.ipc_code IS NOT NULL THEN
        SET NEW.ipc_section = SUBSTRING(NEW.ipc_code, 1, 1);
        SET NEW.ipc_class = SUBSTRING(NEW.ipc_code, 1, 3);
        SET NEW.ipc_subclass = SUBSTRING(NEW.ipc_code, 1, 4);
        IF LOCATE('/', NEW.ipc_code) > 0 THEN
            SET NEW.ipc_group = SUBSTRING(NEW.ipc_code, 1, LOCATE('/', NEW.ipc_code)-1);
        END IF;
    END IF;
END $$

CREATE TRIGGER before_insert_patents
BEFORE INSERT ON patents
FOR EACH ROW
BEGIN
    IF NEW.公开公告号 IS NOT NULL THEN
        SET NEW.publication_number = TRIM(SUBSTRING_INDEX(NEW.公开公告号, ';', 1));
    END IF;

    IF NEW.公开公告日 IS NOT NULL THEN
        BEGIN
            DECLARE date_str VARCHAR(50);
            SET date_str = TRIM(SUBSTRING_INDEX(NEW.公开公告日, ';', 1));
            IF date_str REGEXP '^[0-9]{4}\\.[0-9]{2}\\.[0-9]{2}$' THEN
                SET NEW.publication_date = STR_TO_DATE(date_str, '%Y.%m.%d');
            ELSEIF date_str REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN
                SET NEW.publication_date = STR_TO_DATE(date_str, '%Y-%m-%d');
            END IF;
        END;
    END IF;

    IF NEW.publication_date IS NOT NULL THEN
        IF NEW.publication_date < DATE_SUB(CURDATE(), INTERVAL 20 YEAR) THEN
            SET NEW.legal_status = '失效';
        ELSEIF NEW.publication_date > CURDATE() THEN
            SET NEW.legal_status = '审查中';
        ELSE
            SET NEW.legal_status = '有效';
        END IF;
    END IF;
END $$

CREATE TABLE domain_statistics (
    domain_id INT PRIMARY KEY,
    patent_count INT DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (domain_id) REFERENCES technology_domains(id)
);

CREATE TRIGGER after_insert_patents
AFTER INSERT ON patents
FOR EACH ROW
BEGIN
    INSERT INTO domain_statistics (domain_id, patent_count)
    VALUES (NEW.technology_domain_id, 1)
    ON DUPLICATE KEY UPDATE
        patent_count = patent_count + 1,
        last_updated = CURRENT_TIMESTAMP;
END $$

DELIMITER ;

-- 9. 导入历史表（只创建一次！）
DROP TABLE IF EXISTS import_history;
CREATE TABLE import_history (
    id INT PRIMARY KEY AUTO_INCREMENT,
    file_name VARCHAR(255) NULL,
    count INT NOT NULL,
    type VARCHAR(20) NOT NULL,
    create_time DATETIME DEFAULT NOW()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 10. 初始化统计数据（必须加！）
INSERT IGNORE INTO domain_statistics (domain_id, patent_count)
SELECT id, 0 FROM technology_domains;

-- 测试数据
INSERT INTO ipc_classes (ipc_code, description) VALUES
('H04L9/00', '保密通信装置'),
('G06F16/00', '信息检索数据库结构');

-- 查看结果
SELECT * FROM technology_domains;
SELECT * FROM ipc_classes;
SHOW TABLES;

USE patent_analysis_platform;

-- 先删除旧表（避免冲突）
DROP TABLE IF EXISTS import_history;

-- 创建正确的导入历史表
CREATE TABLE import_history (
    id INT PRIMARY KEY AUTO_INCREMENT,
    file_name VARCHAR(255) NULL,
    count INT NOT NULL,
    type VARCHAR(20) NOT NULL,
    create_time DATETIME DEFAULT NOW()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 验证表是否创建成功
SHOW TABLES;
SELECT * FROM import_history;

USE patent_analysis_platform;


USE patent_analysis_platform;
ALTER TABLE patents ADD COLUMN file_name VARCHAR(255) NULL;

SELECT * FROM patents LIMIT 10;
SELECT * FROM patent_citations LIMIT 10;
