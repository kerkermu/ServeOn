-- 先刪除資料庫（如果存在）並重新創建
DROP DATABASE IF EXISTS Package;
CREATE DATABASE Package;
USE Package;

-- 確保使用正確的字符集
ALTER DATABASE Package CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 按照相依性順序刪除表（先刪除有外鍵依賴的表）
DROP TABLE IF EXISTS recommendation_cooldown;
DROP TABLE IF EXISTS chat_embeddings;
DROP TABLE IF EXISTS chat_history;
DROP TABLE IF EXISTS recommendation_history;
DROP TABLE IF EXISTS package_tracking;
DROP TABLE IF EXISTS product_details;
DROP TABLE IF EXISTS line_users;

-- 創建 line_users 表（基礎表）
CREATE TABLE IF NOT EXISTS line_users (
    line_user_id VARCHAR(50) PRIMARY KEY,
    display_name VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 原有的包裹追蹤表
CREATE TABLE IF NOT EXISTS package_tracking (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tracking_code VARCHAR(20) NOT NULL UNIQUE,    -- 貨物隨機碼
    customer_name VARCHAR(100) NOT NULL,          -- 消費者姓名
    package_name VARCHAR(100) NOT NULL,           -- 新增：貨物名稱
    line_user_id VARCHAR(50) NOT NULL,            -- LINE 用戶 ID
    shipping_date DATETIME,                       -- 出貨時間
    delivery_date DATETIME,                       -- 預計到貨時間
    actual_delivery_date DATETIME,                -- 實際到貨時間
    status ENUM('待出貨', '已出貨', '運送中', '已送達') DEFAULT '待出貨',  -- 貨物狀態
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (line_user_id) REFERENCES line_users(line_user_id),
    INDEX idx_package_tracking_user_date (line_user_id, created_at),
    INDEX idx_package_tracking_name (package_name)
);

-- 商品詳情表
CREATE TABLE IF NOT EXISTS product_details (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_no VARCHAR(10) NOT NULL,              -- 商品編號
    product_name VARCHAR(255) NOT NULL,           -- 商品名稱
    price_original TEXT,                          -- 原始價格字串
    product_url VARCHAR(255) NOT NULL,            -- 商品連結
    product_description TEXT NOT NULL,            -- 商品描述
    embedding JSON,                               -- 商品描述的向量嵌入
    embedding_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- 向量更新時間
    is_active BOOLEAN DEFAULT TRUE,               -- 商品是否有效
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_product_no (product_no),
    INDEX idx_product_name (product_name),
    INDEX idx_embedding_updated (embedding_updated_at),
    INDEX idx_is_active (is_active),
    FULLTEXT INDEX idx_description (product_description),     -- 全文索引用於描述搜索
    FULLTEXT INDEX idx_name_description (product_name, product_description)  -- 組合全文索引
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 創建向量相似度搜索函數
DELIMITER //
CREATE FUNCTION IF NOT EXISTS cosine_similarity(v1 JSON, v2 JSON) 
RETURNS FLOAT DETERMINISTIC
BEGIN
    DECLARE dot_product FLOAT DEFAULT 0;
    DECLARE norm1 FLOAT DEFAULT 0;
    DECLARE norm2 FLOAT DEFAULT 0;
    DECLARE i INT DEFAULT 0;
    DECLARE v1_size INT;
    
    -- 獲取向量大小
    SET v1_size = JSON_LENGTH(v1);
    
    -- 計算點積和向量範數
    WHILE i < v1_size DO
        SET dot_product = dot_product + (
            JSON_EXTRACT(v1, CONCAT('$[', i, ']')) * 
            JSON_EXTRACT(v2, CONCAT('$[', i, ']'))
        );
        SET norm1 = norm1 + POW(JSON_EXTRACT(v1, CONCAT('$[', i, ']')), 2);
        SET norm2 = norm2 + POW(JSON_EXTRACT(v2, CONCAT('$[', i, ']')), 2);
        SET i = i + 1;
    END WHILE;
    
    -- 計算餘弦相似度
    IF norm1 = 0 OR norm2 = 0 THEN
        RETURN 0;
    END IF;
    
    RETURN dot_product / (SQRT(norm1) * SQRT(norm2));
END //
DELIMITER ;

-- 創建向量搜索存儲過程
DELIMITER //
CREATE PROCEDURE search_similar_products(IN query_embedding JSON, IN limit_count INT)
BEGIN
    SELECT 
        product_no,
        product_name,
        price_original,
        product_url,
        product_description,
        cosine_similarity(embedding, query_embedding) as similarity
    FROM product_details
    WHERE embedding IS NOT NULL
    ORDER BY similarity DESC
    LIMIT limit_count;
END //
DELIMITER ;

-- 創建更新向量的存儲過程
DELIMITER //
CREATE PROCEDURE update_product_embedding(
    IN p_product_no VARCHAR(10),
    IN p_embedding JSON
)
BEGIN
    UPDATE product_details
    SET 
        embedding = p_embedding,
        embedding_updated_at = CURRENT_TIMESTAMP
    WHERE product_no = p_product_no;
END //
DELIMITER ;

-- 聊天記錄表
CREATE TABLE IF NOT EXISTS chat_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    line_user_id VARCHAR(50) NOT NULL,
    message_text TEXT NOT NULL,
    sentiment_score FLOAT,
    sentiment_label VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (line_user_id) REFERENCES line_users(line_user_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    INDEX idx_chat_history_user (line_user_id),
    INDEX idx_chat_history_sentiment (sentiment_score),
    INDEX idx_chat_history_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 向量資料表（存儲嵌入向量）
CREATE TABLE IF NOT EXISTS chat_embeddings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    chat_id INT NOT NULL,
    embedding LONGBLOB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chat_id) REFERENCES chat_history(id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    INDEX idx_chat_embeddings_chat (chat_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 推薦冷卻時間表
CREATE TABLE IF NOT EXISTS recommendation_cooldown (
    id INT AUTO_INCREMENT PRIMARY KEY,
    line_user_id VARCHAR(50) NOT NULL,
    category VARCHAR(50) NOT NULL,
    last_recommendation_time TIMESTAMP NOT NULL,
    product_no VARCHAR(10) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_user_category (line_user_id, category),
    FOREIGN KEY (line_user_id) REFERENCES line_users(line_user_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (product_no) REFERENCES product_details(product_no)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    INDEX idx_cooldown_user (line_user_id),
    INDEX idx_cooldown_category (category),
    INDEX idx_cooldown_time (last_recommendation_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 推薦歷史表
CREATE TABLE IF NOT EXISTS recommendation_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    line_user_id VARCHAR(50) NOT NULL,
    category VARCHAR(50) NOT NULL,
    product_no VARCHAR(10) NOT NULL,
    recommendation_content TEXT NOT NULL,
    is_clicked BOOLEAN DEFAULT FALSE,
    is_purchased BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (line_user_id) REFERENCES line_users(line_user_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    FOREIGN KEY (product_no) REFERENCES product_details(product_no)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    INDEX idx_recommendation_user (line_user_id),
    INDEX idx_recommendation_category (category),
    INDEX idx_recommendation_product (product_no),
    INDEX idx_recommendation_created (created_at),
    INDEX idx_recommendation_status (is_clicked, is_purchased)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS group_chat_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    group_id VARCHAR(50) NOT NULL,
    user_id VARCHAR(50) NOT NULL,
    message_text TEXT NOT NULL,
    sentiment_score FLOAT,
    sentiment_label VARCHAR(20),
    embedding JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_group_id (group_id),
    INDEX idx_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
