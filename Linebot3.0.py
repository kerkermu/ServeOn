from flask import Flask, request, abort
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
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
import logging
import netifaces as ni
from datetime import datetime
import time
from threading import Thread
from ai.assistant import AIAssistant
from ai.sentiment_analyzer import SentimentAnalyzer
from line_config import CHANNEL_SECRET, get_line_bot_api  # 導入共用配置
from ai.ai_recommender import AIRecommender
import pickle
from collections import defaultdict
import logging.handlers
import os
import json

app = Flask(__name__)
db = DatabaseHandler()
ai_assistant = AIAssistant()
sentiment_analyzer = SentimentAnalyzer()
ai_recommender = AIRecommender()

# 使用共用的 handler
handler = WebhookHandler(CHANNEL_SECRET)

# 設定日誌
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# 創建一個用於存儲最近處理過的消息的字典
processed_messages = defaultdict(float)
MESSAGE_EXPIRY_TIME = 30  # 30秒內的重複消息將被忽略

def print_status():
    """定期輸出運行狀態"""
    while True:
        logging.info("LINE Bot 服務正在運行...")
        logging.info("監聽 webhook 在 port 5002...")
        time.sleep(300)

@app.route("/", methods=['GET'])
def hello():
    return 'Hello, LINE Bot!'

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

def reply_message(reply_token, message):
    """發送回應訊息"""
    try:
        messaging_api = get_line_bot_api()
        messaging_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=message)]
            )
        )
        logging.info("回應訊息已發送")
    except Exception as e:
        logging.error(f"發送回應訊息失敗: {str(e)}")
        raise

def get_db_connection():
    """獲取資料庫連接"""
    try:
        conn = db.get_connection()
        if not conn or not conn.is_connected():
            logging.warning("資料庫連接無效，嘗試重新連接...")
            conn = db.get_connection()
        return conn
    except Exception as e:
        logging.error(f"資料庫連接失敗: {str(e)}")
        raise

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    """處理接收到的訊息"""
    try:
        # 獲取訊息內容
        message_text = event.message.text.strip()
        user_id = event.source.user_id
        
        # 判斷是否為群組訊息
        is_group = event.source.type == 'group'
        group_id = event.source.group_id if is_group else None
        
        logging.info(f"\n=== 開始處理{'群組' if is_group else '個人'}消息 ===")
        logging.info(f"用戶ID: {user_id}")
        logging.info(f"消息內容: {message_text}")
        
        # 進行情感分析和向量嵌入
        sentiment_result = sentiment_analyzer.analyze_sentiment_only(message_text)
        embedding = ai_assistant.get_embedding(message_text)
        logging.info(f"情感分析結果: {sentiment_result}")
        
        # 儲存訊息記錄
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                if is_group:
                    # 儲存群組訊息
                    cursor.execute("""
                        INSERT INTO group_chat_history 
                        (group_id, user_id, message_text, sentiment_score, 
                         sentiment_label, created_at)
                        VALUES (%s, %s, %s, %s, %s, NOW())
                    """, (
                        group_id,
                        user_id,
                        message_text,
                        sentiment_result['score'],
                        sentiment_result['label']
                    ))
                    chat_id = cursor.lastrowid
                    
                    # 儲存群組訊息向量
                    cursor.execute("""
                        INSERT INTO group_chat_embeddings 
                        (chat_id, embedding_vector, created_at)
                        VALUES (%s, %s, NOW())
                    """, (
                        chat_id,
                        json.dumps(embedding)
                    ))
                    conn.commit()
                    return  # 群組訊息不回應
                
                # 處理個人訊息
                # 確保用戶存在於資料庫中
                if not db.user_exists(user_id):
                    logging.info("新用戶，正在添加到資料庫...")
                    db.add_user(user_id)
                
                  # 儲存個人訊息
                cursor.execute("""
                    INSERT INTO personal_chat_history 
                    (user_id, user_message, sentiment_score, 
                     sentiment_label, created_at)
                    VALUES (%s, %s, %s, %s, NOW())
                """, (
                    user_id,
                    message_text,
                    sentiment_result['score'],
                    sentiment_result['label']
                ))
                chat_id = cursor.lastrowid
                
                # 儲存個人訊息向量
                cursor.execute("""
                    INSERT INTO personal_chat_embeddings 
                    (chat_id, embedding_vector, created_at)
                    VALUES (%s, %s, NOW())
                """, (
                    chat_id,
                    json.dumps(embedding)
                ))
                
                # 處理不同類型的請求
                response = None
                if message_text == "貨物狀況":
                    packages = db.get_user_packages(user_id)
                    if packages:
                        package_list = []
                        for p in packages:
                            package_info = (
                                f"📦 商品：{p['package_name']}\n"
                                f"📝 追蹤碼：{p['tracking_code']}\n"
                                f"📊 狀態：{p['status']}\n"
                            )
                            if p['shipping_date']:
                                package_info += f"🚚 出貨時間：{p['shipping_date'].strftime('%Y-%m-%d %H:%M')}\n"
                            if p['delivery_date']:
                                package_info += f"📅 預計到貨：{p['delivery_date'].strftime('%Y-%m-%d %H:%M')}\n"
                            package_info += "─────────────"
                            package_list.append(package_info)
                        response = f"您好，以下是您的貨物狀況：\n\n" + "\n\n".join(package_list)
                    else:
                        response = "您目前沒有進行中的包裹"
                
                elif any(keyword in message_text for keyword in ["找", "搜尋", "查詢", "推薦", "有賣", "有沒有"]):
                    # 處理產品搜索
                    product_categories = check_product_category(message_text)
                    if product_categories:
                        # 使用產品類別進行相關推薦
                        similar_products = ai_assistant.search_products_by_context(
                            message_text, 
                            categories=list(product_categories.keys())
                        )
                    else:
                        # 一般搜索
                        similar_products = ai_assistant.search_products_by_context(message_text)
                    
                    if similar_products:
                        product_list = []
                        for product in similar_products[:5]:  # 限制顯示前5個結果
                            product_info = (
                                f"📦 商品編號：{product['product_no']}\n"
                                f"🏷️ 商品名稱：{product['product_name']}\n"
                                f"💰 價格：{product['price_original']}\n"
                                f"🔗 商品連結：{product['product_url']}\n"
                                f"📝 商品描述：{product['product_description'][:100]}...\n"
                                f"─────────────"
                            )
                            product_list.append(product_info)
                        response = "以下是您可能感興趣的商品：\n\n" + "\n\n".join(product_list)
                    else:
                        response = "抱歉，目前沒有找到符合的商品。您可以試試其他關鍵字。"
                
                else:
                    # 一般對話處理
                    response = ai_assistant.get_response(user_id, message_text)
                
                # 儲存機器人回應並發送
                if response:
                    reply_message(event.reply_token, response)
                    logging.info("回應已發送")
                
                conn.commit()
                logging.info("使用者對話記錄已保存")
        except Exception as db_error:
            conn.rollback()
            logging.error(f"資料庫操作失敗: {str(db_error)}")
            if not is_group:
                reply_message(event.reply_token, "抱歉，處理您的訊息時發生錯誤，請稍後再試。")
        finally:
            conn.close()
            
    except Exception as e:
        error_msg = f"處理訊息時發生錯誤: {str(e)}"
        logging.error(error_msg, exc_info=True)
        if not is_group:
            try:
                reply_message(event.reply_token, "抱歉，系統暫時無法處理您的請求，請稍後再試。")
            except Exception as reply_error:
                logging.error(f"發送錯誤通知失敗: {str(reply_error)}")
    finally:
        logging.info("=== 消息處理完成 ===\n")

def get_recommendation_prefix(trigger_reason):
    """根據觸發原因生成推薦前綴"""
    if trigger_reason == "近期多次正面評論":
        return "看來您最近對我們的商品評價很好！這裡有一些您可能感興趣的商品：\n\n"
    elif trigger_reason == "近三個月多次購買":
        return "感謝您持續支持我們的商品！為您推薦以下商品：\n\n"
    return ""

@handler.add(FollowEvent)
def handle_follow(event):
    """處理加入好友事件"""
    user_id = event.source.user_id
    try:
        # 使用共用的 LINE API
        messaging_api = get_line_bot_api()
        profile = messaging_api.get_profile(user_id)
        display_name = profile.display_name

        # 添加用戶到資料庫
        if not db.user_exists(user_id):
            db.add_user(line_user_id=user_id, display_name=display_name)
            logging.info(f"新用戶加入並已添加到資料庫 - ID: {user_id}, 名稱: {display_name}")
        else:
            # 更新用戶的 display_name
            db.add_user(line_user_id=user_id, display_name=display_name)
            logging.info(f"更新用戶資料 - ID: {user_id}, 名稱: {display_name}")
            
        # 發送歡迎訊息
        welcome_message = (
            f"Hi {display_name}！歡迎加入！😊\n\n"
            "我是您的智能助理，可以協助您：\n"
            "1️⃣ 查詢商品狀態（輸入「貨物狀況」）\n"
            "2️⃣ 搜尋/推薦商品\n"
            "3️⃣ 回答您的問題\n\n"
            "請問有什麼我可以幫您的嗎？"
        )
        reply_message(event.reply_token, welcome_message)
        
    except Exception as e:
        logging.error(f"處理追蹤事件時發生錯誤: {str(e)}")
        logging.error("錯誤詳情:", exc_info=True)
@handler.add(MemberJoinedEvent)
def handle_member_joined(event):
    """處理新成員加入群組事件"""
    try:
        # 使用共用的 LINE API
        messaging_api = get_line_bot_api()
        
        for user in event.joined.members:
            try:
                profile = messaging_api.get_profile(user.user_id)
                display_name = profile.display_name

                # 添加用戶到資料庫
                if not db.user_exists(user.user_id):
                    db.add_user(line_user_id=user.user_id, display_name=display_name)
                    logging.info(f"新成員加入群組並已添加到資料庫 - ID: {user.user_id}, 名稱: {display_name}")
                else:
                    # 更新用戶的 display_name
                    db.add_user(line_user_id=user.user_id, display_name=display_name)
                    logging.info(f"更新成員資料 - ID: {user.user_id}, 名稱: {display_name}")
                    
            except Exception as e:
                logging.error(f"處理成員加入事件時發生錯誤: {str(e)}")
                logging.error("錯誤詳情:", exc_info=True)
    except Exception as e:
        logging.error(f"初始化 LINE API 時發生錯誤: {str(e)}")
        logging.error("錯誤詳情:", exc_info=True)

def get_system_status():
    try:
        network_interface = 'enp0s3'
        ni.ifaddresses(network_interface)
        ip_address = ni.ifaddresses(network_interface)[ni.AF_INET][0]['addr']
        logging.info(f"取得 IP 地址: {ip_address}")
    except Exception as e:
        ip_address = "無法取得 IP 地址"
        logging.error(f"取得 IP 時發生錯誤: {e}")

    system_status = f"""系統狀態回報:\n程式啟動時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nIP 地址: {ip_address}"""
    logging.info("系統狀態回報完成")
    return system_status

def send_broadcast_message():
    try:
        system_status = get_system_status()
        # 使用共用的 LINE API
        messaging_api = get_line_bot_api()
        messaging_api.broadcast(
            TextMessage(text=system_status)
        )
        logging.info("訊息成功廣播至所有使用者")
    except Exception as e:
        logging.error(f"訊息廣播失敗: {e}")

def check_product_category(message_text):
    """檢查消息屬於哪個產品類別"""
    try:
        message_text = message_text.strip()  # 只去除空白，不转换大小写
        matched_results = {}
        
        logging.info(f"\n=== 開始檢查產品類別 ===")
        logging.info(f"評論內容: {message_text}")
        
        # 检查 ai_recommender 是否正确初始化
        if not hasattr(ai_recommender, 'keyword_categories'):
            logging.error("AI推薦器未正確初始化: keyword_categories 不存在")
            return {}
            
        # 打印完整的配置信息
        logging.info("=== AI推薦器配置信息 ===")
        logging.info(f"所有類別: {list(ai_recommender.keyword_categories.keys())}")
        for cat, keywords in ai_recommender.keyword_categories.items():
            logging.info(f"\n類別 '{cat}' 的配置:")
            logging.info(f"複合產品: {keywords.get('複合產品', [])}")
            logging.info(f"單一產品: {keywords.get('單一產品', [])}")
            
        logging.info("\n=== 評價詞配置 ===")
        for cat, words in ai_recommender.category_specific_keywords.items():
            logging.info(f"類別 '{cat}' 的特定評價詞: {words}")
        logging.info(f"通用評價詞: {ai_recommender.common_keywords}")

        def check_evaluation_word(word, text):
            # 基本匹配
            if word in text:
                return True
            # 常见变体匹配（如：很+词，非常+词，真的+词）
            variations = [
                f"很{word}", f"非常{word}", f"真的{word}",
                f"超{word}", f"特別{word}", f"十分{word}",
                f"{word}的", f"很{word}的", f"非常{word}的"
            ]
            return any(var in text for var in variations)
        
        # 开始匹配过程
        for category, keywords in ai_recommender.keyword_categories.items():
            try:
                logging.info(f"\n開始檢查類別: {category}")
                
                # 獲取該類別的所有產品關鍵詞
                complex_products = keywords.get("複合產品", [])
                single_products = keywords.get("單一產品", [])
                
                logging.info(f"複合產品關鍵詞: {complex_products}")
                logging.info(f"單一產品關鍵詞: {single_products}")
                
                # 檢查產品關鍵詞匹配
                matched_products = []
                
                # 先檢查複合產品
                for product in complex_products:
                    logging.info(f"檢查複合產品關鍵詞: {product}")
                    is_match = product in message_text
                    logging.info(f"是否存在於評論中: {is_match}")
                    if is_match:
                        matched_products.append(product)
                        logging.info(f"匹配到複合產品: {product}")
                
                # 如果沒有匹配到複合產品，再檢查單一產品
                if not matched_products:
                    for product in single_products:
                        logging.info(f"檢查單一產品關鍵詞: {product}")
                        is_match = product in message_text
                        logging.info(f"是否存在於評論中: {is_match}")
                        if is_match:
                            matched_products.append(product)
                            logging.info(f"匹配到單一產品: {product}")
                
                # 獲取評價詞
                specific_words = ai_recommender.category_specific_keywords.get(category, [])
                common_words = ai_recommender.common_keywords
                
                logging.info(f"特定評價詞: {specific_words}")
                logging.info(f"通用評價詞: {common_words}")
                
                # 檢查評價詞匹配
                matched_specific = []
                matched_common = []
                
                # 檢查特定評價詞
                for word in specific_words:
                    logging.info(f"檢查特定評價詞: {word}")
                    is_match = check_evaluation_word(word, message_text)
                    logging.info(f"是否存在於評論中: {is_match}")
                    if is_match:
                        matched_specific.append(word)
                        logging.info(f"匹配到特定評價詞: {word}")
                
                # 檢查通用評價詞
                for word in common_words:
                    logging.info(f"檢查通用評價詞: {word}")
                    is_match = check_evaluation_word(word, message_text)
                    logging.info(f"是否存在於評論中: {is_match}")
                    if is_match:
                        matched_common.append(word)
                        logging.info(f"匹配到通用評價詞: {word}")
                
                # 記錄匹配結果
                if matched_products:
                    matched_results[category] = {
                        'matched_products': matched_products,
                        'matched_specific': matched_specific,
                        'matched_common': matched_common
                    }
                    
                    # 添加詳細日誌
                    logging.info(f"\n=== 類別匹配結果: {category} ===")
                    logging.info(f"匹配到的產品: {matched_products}")
                    logging.info(f"匹配到的特定評價詞: {matched_specific}")
                    logging.info(f"匹配到的通用評價詞: {matched_common}")
                    
            except Exception as category_error:
                logging.error(f"處理類別 '{category}' 時發生錯誤: {str(category_error)}")
                continue
        
        if not matched_results:
            logging.info("未匹配到任何產品類別")
        else:
            logging.info(f"最終匹配結果: {matched_results}")
        
        return matched_results
        
    except Exception as e:
        logging.error(f"檢查產品類別時發生錯誤: {str(e)}")
        return {}

if __name__ == "__main__":
    # 创建日志目录
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # 配置日志
    log_file = os.path.join(log_dir, 'linebot.log')
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    ))
    
    # 配置控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    ))
    
    # 设置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    logging.info("正在啟動 LINE Bot 服務...")
    
    # 启动状态输出线程
    status_thread = Thread(target=print_status, daemon=True)
    status_thread.start()
    
    # 启动 Flask 服务，关闭 debug 模式
    logging.info("LINE Bot 服務已啟動")
    app.run(host='0.0.0.0', port=5004, debug=False)