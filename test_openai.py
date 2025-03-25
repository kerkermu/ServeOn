from openai import OpenAI
import os
from dotenv import load_dotenv
import logging

# 配置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def test_openai_api():
    """測試 OpenAI API 連接和功能"""
    try:
        # 載入環境變數
        load_dotenv()
        
        # 獲取 API Key
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            logging.error("未找到 OPENAI_API_KEY 環境變數")
            return False
            
        logging.info("正在初始化 OpenAI 客戶端...")
        client = OpenAI(api_key=api_key)
        
        # 測試 1: 測試 API 連接
        logging.info("測試 1: 測試 API 連接...")
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": "你好"}],
                max_tokens=5
            )
            logging.info("✓ API 連接測試成功")
        except Exception as e:
            logging.error(f"✗ API 連接測試失敗: {str(e)}")
            return False
            
        # 測試 2: 測試 Embeddings API
        logging.info("測試 2: 測試 Embeddings API...")
        try:
            response = client.embeddings.create(
                model="text-embedding-ada-002",
                input="測試文本"
            )
            logging.info("✓ Embeddings API 測試成功")
            logging.info(f"向量維度: {len(response.data[0].embedding)}")
        except Exception as e:
            logging.error(f"✗ Embeddings API 測試失敗: {str(e)}")
            return False
            
        # 測試 3: 測試完整對話
        logging.info("測試 3: 測試完整對話...")
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "你是一個測試助手。"},
                    {"role": "user", "content": "請用繁體中文回答：1+1等於多少？"}
                ],
                temperature=0.7,
                max_tokens=100
            )
            logging.info("✓ 完整對話測試成功")
            logging.info(f"回應內容: {response.choices[0].message.content}")
        except Exception as e:
            logging.error(f"✗ 完整對話測試失敗: {str(e)}")
            return False
            
        logging.info("所有測試完成！API Key 有效且功能正常。")
        return True
        
    except Exception as e:
        logging.error(f"測試過程中發生錯誤: {str(e)}")
        return False

if __name__ == "__main__":
    logging.info("開始測試 OpenAI API...")
    result = test_openai_api()
    if result:
        logging.info("✅ 所有測試通過！")
    else:
        logging.error("❌ 測試失敗，請檢查 API Key 和網路連接。") 