from database.db_handler import DatabaseHandler
import logging

logging.basicConfig(level=logging.INFO)

def test_database():
    try:
        # 初始化數據庫處理器
        db = DatabaseHandler()
        
        # 測試添加用戶
        test_user_id = "test_user_123"
        test_display_name = "Test User"
        
        print("測試添加用戶...")
        if db.add_user(test_user_id, test_display_name):
            print("添加用戶成功！")
        else:
            print("添加用戶失敗！")
        
        # 測試檢查用戶是否存在
        print("\n測試檢查用戶是否存在...")
        if db.user_exists(test_user_id):
            print("用戶存在！")
        else:
            print("用戶不存在！")
        
        # 測試獲取所有用戶
        print("\n測試獲取所有用戶...")
        users = db.get_all_line_users()
        print(f"用戶列表: {users}")
        
    except Exception as e:
        print(f"測試過程中發生錯誤: {str(e)}")
        logging.error("錯誤詳情:", exc_info=True)

if __name__ == "__main__":
    test_database() 