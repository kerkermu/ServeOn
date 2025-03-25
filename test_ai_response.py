from ai.assistant import AIAssistant
import logging
from dotenv import load_dotenv

# 配置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def test_ai_response():
    """測試 AI 助手的回應功能"""
    try:
        # 載入環境變數
        load_dotenv()
        
        # 初始化 AI 助手
        logging.info("正在初始化 AI 助手...")
        ai_assistant = AIAssistant()
        
        # 測試用戶 ID
        test_user_id = "test_user_123"
        
        # 測試消息
        test_messages = [
            "你好",
            "今天天氣如何？",
            "請問你是誰？"
        ]
        
        # 測試每個消息
        for msg in test_messages:
            logging.info(f"\n=== 測試消息: {msg} ===")
            try:
                response = ai_assistant.get_response(test_user_id, msg)
                if response:
                    logging.info(f"AI 回應: {response}")
                else:
                    logging.error("AI 沒有產生回應")
                    return False
            except Exception as e:
                logging.error(f"處理消息 '{msg}' 時發生錯誤: {str(e)}")
                return False
        
        logging.info("\n所有測試完成！")
        return True
        
    except Exception as e:
        logging.error(f"測試過程中發生錯誤: {str(e)}")
        return False

if __name__ == "__main__":
    logging.info("開始測試 AI 助手...")
    result = test_ai_response()
    if result:
        logging.info("✅ 所有測試通過！")
    else:
        logging.error("❌ 測試失敗，請檢查日誌了解詳情。") 