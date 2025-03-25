from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    FollowEvent,
    MemberJoinedEvent
)
from linebot.v3.messaging import (
    ReplyMessageRequest,
    TextMessage,
    PushMessageRequest
)
from database.db_handler import DatabaseHandler
from google.cloud import language_v1
import logging
import netifaces as ni
from datetime import datetime
import time
from threading import Thread
from ai.assistant import AIAssistant
from ai.sentiment_analyzer import SentimentAnalyzer
from line_config import CHANNEL_SECRET, get_line_bot_api
from ai.ai_recommender import AIRecommender
from openai import OpenAI
import pickle
from collections import defaultdict
import logging.handlers
import os
import json

# 初始化 Flask 和其他客戶端
app = Flask(__name__)
db = DatabaseHandler()
ai_assistant = AIAssistant()
sentiment_analyzer = SentimentAnalyzer()
ai_recommender = AIRecommender()

# 初始化 OpenAI 客戶端
openai_client = OpenAI(
    api_key="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"
)

# 使用共用的 handler
handler = WebhookHandler(CHANNEL_SECRET)

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()
    
    try:
        logging.info(f"\n=== 開始處理用戶消息 ===")
        logging.info(f"用戶ID: {user_id}")
        logging.info(f"消息內容: {text}")
        
        # 區分個人和群組訊息的處理
        is_group = event.source.type == 'group'
        if is_group:
            group_id = event.source.group_id
            logging.info(f"群組訊息，群組ID: {group_id}")
            
            # 進行情感分析
            sentiment_result = sentiment_analyzer.analyze_sentiment_only(text)
            
            # 生成向量嵌入
            embedding = ai_assistant.get_embedding(text)
            
            # 儲存群組訊息
            conn = db.get_connection()
            try:
                with conn.cursor() as cursor:
                    # 先插入主要聊天記錄
                    cursor.execute("""
                        INSERT INTO group_chat_history 
                        (group_id, user_id, message_text, sentiment_score, sentiment_label)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (
                        group_id,
                        user_id,
                        text,
                        sentiment_result['score'],
                        sentiment_result['label']
                    ))
                    
                    # 獲取插入的聊天記錄 ID
                    chat_id = cursor.lastrowid
                    
                    # 插入向量嵌入資料
                    cursor.execute("""
                        INSERT INTO group_chat_embeddings 
                        (chat_id, embedding)
                        VALUES (%s, %s)
                    """, (
                        chat_id,
                        json.dumps(embedding)
                    ))
                    
                conn.commit()
                logging.info(f"群組訊息已儲存，chat_id: {chat_id}")
            except Exception as db_error:
                conn.rollback()
                logging.error(f"儲存群組訊息失敗: {str(db_error)}")
            finally:
                conn.close()
            return
        
        # 個人訊息處理
        max_retries = 3
        retry_delay = 1
        
        # 進行情感分析
        sentiment_result = sentiment_analyzer.analyze_sentiment_only(text)
        
        # 生成向量嵌入
        embedding = ai_assistant.get_embedding(text)
        
        # 儲存個人訊息
        conn = db.get_connection()
        try:
            with conn.cursor() as cursor:
                # 先插入主要聊天記錄
                cursor.execute("""
                    INSERT INTO personal_chat_history 
                    (user_id, message_text, sentiment_score, sentiment_label)
                    VALUES (%s, %s, %s, %s)
                """, (
                    user_id,
                    text,
                    sentiment_result['score'],
                    sentiment_result['label']
                ))
                
                # 獲取插入的聊天記錄 ID
                chat_id = cursor.lastrowid
                
                # 插入向量嵌入資料
                cursor.execute("""
                    INSERT INTO personal_chat_embeddings 
                    (chat_id, embedding)
                    VALUES (%s, %s)
                """, (
                    chat_id,
                    json.dumps(embedding)
                ))
                
            conn.commit()
            logging.info(f"個人訊息已儲存，chat_id: {chat_id}")
            
        except Exception as db_error:
            conn.rollback()
            logging.error(f"儲存個人訊息失敗: {str(db_error)}")
        finally:
            conn.close()

        for attempt in range(max_retries):
            try:
                # 使用 OpenAI 生成回應
                response = openai_client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "user", "content": text}
                    ]
                )
                ai_reply = response.choices[0].message.content.strip()
                logging.info(f"OpenAI 回應生成完成: {ai_reply}")
                
                # 發送回應
                messaging_api = get_line_bot_api()
                messaging_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=ai_reply)]
                    )
                )
                break  # 成功後跳出重試循環
                
            except Exception as retry_error:
                if attempt < max_retries - 1:
                    logging.warning(f"處理消息失敗，正在重試 ({attempt + 1}/{max_retries}): {str(retry_error)}")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise retry_error
        
    except Exception as e:
        error_msg = f"處理訊息時發生錯誤: {str(e)}"
        logging.error(error_msg, exc_info=True)
        
        try:
            messaging_api = get_line_bot_api()
            messaging_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="抱歉，系統暫時無法處理您的請求，請稍後再試。")]
                )
            )
        except Exception as e2:
            logging.error(f"發送錯誤通知失敗: {str(e2)}")
    finally:
        logging.info("=== 消息處理完成 ===\n")

@app.route("/callback", methods=['POST'])
def callback():
    """處理 LINE Webhook"""
    logging.info("收到 webhook 請求")
    
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    
    try:
        # 解析請求體以獲取更多信息
        event_data = json.loads(body)
        if 'events' in event_data and len(event_data['events']) > 0:
            event = event_data['events'][0]
            if 'source' in event and 'message' in event:
                user_id = event['source'].get('userId', '')
                message = event['message'].get('text', '')
                timestamp = event.get('timestamp', '')
                
                # 使用更可靠的方式生成消息標識
                message_key = f"{user_id}:{message}:{timestamp}"
                current_time = time.time()
                
                # 清理過期的消息記錄
                expired_messages = [msg for msg, t in processed_messages.items() 
                                 if current_time - t > MESSAGE_EXPIRY_TIME]
                for msg in expired_messages:
                    del processed_messages[msg]
                
                # 檢查是否是重複消息
                if message_key in processed_messages:
                    logging.info(f"偵測到重複請求，已忽略 - 用戶: {user_id}")
                    return 'OK'
                
                # 記錄新消息
                processed_messages[message_key] = current_time
        
        handler.handle(body, signature)
        return 'OK'
    
    except InvalidSignatureError:
        logging.error("無效的簽名")
        abort(400)
    except Exception as e:
        logging.error(f"處理 webhook 時發生錯誤: {str(e)}")
        return str(e), 200

def print_status():
    """定期輸出服務狀態"""
    while True:
        try:
            # 獲取網絡接口信息
            interfaces = ni.interfaces()
            ip_info = []
            for iface in interfaces:
                if iface != 'lo':  # 排除 loopback 接口
                    try:
                        addr = ni.ifaddresses(iface).get(ni.AF_INET)
                        if addr:
                            ip_info.append(f"{iface}: {addr[0]['addr']}")
                    except ValueError:
                        continue
            
            # 獲取記憶體使用情況
            with open('/proc/meminfo') as f:
                mem_total = 0
                mem_free = 0
                for line in f:
                    if line.startswith('MemTotal'):
                        mem_total = int(line.split()[1])
                    elif line.startswith('MemFree'):
                        mem_free = int(line.split()[1])
                    if mem_total and mem_free:
                        break
            
            mem_used_percent = ((mem_total - mem_free) / mem_total) * 100
            
            # 輸出狀態信息
            logging.info(f"""
=== 系統狀態 ===
時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
IP: {', '.join(ip_info)}
記憶體使用: {mem_used_percent:.1f}%
===============
            """)
            
        except Exception as e:
            logging.error(f"狀態輸出錯誤: {str(e)}")
        
        time.sleep(300)  # 每 5 分鐘輸出一次

if __name__ == "__main__":
    # 確保日誌目錄存在
    os.makedirs('logs', exist_ok=True)
    
    # 配置文件日誌
    file_handler = logging.handlers.TimedRotatingFileHandler(
        'logs/linebot.log',
        when='midnight',
        interval=1,
        backupCount=7,
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'
    ))
    
    # 配置控制台輸出
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    ))
    
    # 設置根日誌記錄器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # 定義消息過期時間（秒）
    MESSAGE_EXPIRY_TIME = 60
    
    # 用於追踪處理過的消息
    processed_messages = {}
    
    logging.info("正在啟動 LINE Bot 服務...")
    
    # 啟動狀態輸出執行緒
    status_thread = Thread(target=print_status, daemon=True)
    status_thread.start()
    
    # 啟動 Flask 服務
    logging.info("LINE Bot 服務已啟動")
    app.run(host='0.0.0.0', port=5004, debug=False)        