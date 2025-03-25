from flask import Flask, request, jsonify, render_template, flash, redirect, url_for
from database.db_handler import DatabaseHandler
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    PushMessageRequest,
    TextMessage
)
import logging
import time
from threading import Thread
from line_config import get_line_bot_api
import json
import os
import re

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # 用於 flash 訊息
db = DatabaseHandler()

@app.route('/api/')
def api_home():
    return 'Line Bot Package Tracking System API is running!'

@app.route('/api/package/status/<tracking_code>', methods=['GET'])
def get_package_status(tracking_code):
    """查詢包裹狀態"""
    try:
        status = db.get_package_status(tracking_code)
        if status:
            return jsonify(status), 200
        return jsonify({"error": "找不到包裹"}), 404
    except Exception as e:
        logging.error(f"查詢包裹狀態時發生錯誤: {e}")
        return jsonify({"error": "系統錯誤"}), 500

@app.route('/api/user/packages/<line_user_id>', methods=['GET'])
def get_user_packages(line_user_id):
    """查詢用戶的所有包裹"""
    try:
        packages = db.get_user_packages(line_user_id)
        if packages:
            return jsonify(packages), 200
        return jsonify({"message": "沒有找到包裹記錄"}), 404
    except Exception as e:
        logging.error(f"查詢用戶包裹時發生錯誤: {e}")
        return jsonify({"error": "系統錯誤"}), 500

@app.route('/api/package/status/update', methods=['POST'])
def update_package_status():
    """更新包裹狀態"""
    try:
        data = request.get_json()
        tracking_code = data.get('tracking_code')
        status = data.get('status')
        
        if not tracking_code or not status:
            return jsonify({"error": "缺少必要參數"}), 400
            
        success = db.update_package_status(tracking_code, status)
        if success:
            return jsonify({"message": "狀態更新成功"}), 200
        return jsonify({"error": "更新失敗"}), 400
    except Exception as e:
        logging.error(f"更新包裹狀態時發生錯誤: {e}")
        return jsonify({"error": "系統錯誤"}), 500

def print_status():
    """定期輸出服務狀態"""
    while True:
        logging.info("API 服務正在運行...")
        logging.info("資料庫連接狀態：正常")
        time.sleep(300)

@app.route('/')
def home():
    """首頁重定向到管理面板"""
    logging.info("訪問首頁")
    try:
        return redirect(url_for('admin_panel'))
    except Exception as e:
        logging.error(f"重定向時發生錯誤: {e}")
        return "系統錯誤", 500

@app.route('/admin', methods=['GET', 'POST'])
def admin_panel():
    """管理面板 - 處理包裹管理"""
    logging.info("訪問管理面板")
    try:
        if request.method == 'POST':
            package_name = request.form.get('package_name')
            customer_name = request.form.get('customer_name')
            line_user_id = request.form.get('line_user_id')
            status = request.form.get('status')
            
            # 生成追蹤碼並儲存包裹資訊
            tracking_code = db.add_package(
                customer_name=customer_name,
                package_name=package_name,
                line_user_id=line_user_id,
                status=status
            )
            
            if tracking_code:
                # 根據狀態準備不同的訊息
                if status == '已出貨':
                    message = f"您的包裹「{package_name}」已開始出貨\n追蹤碼：{tracking_code}"
                elif status == '已送達':
                    message = f"您的包裹「{package_name}」已送達目的地\n追蹤碼：{tracking_code}"
                else:
                    message = f"您的包裹「{package_name}」狀態更新為：{status}\n追蹤碼：{tracking_code}"
                
                try:
                    # 使用 LINE Messaging API 發送訊息
                    line_bot_api = get_line_bot_api()
                    line_bot_api.push_message(
                        PushMessageRequest(
                            to=line_user_id,
                            messages=[TextMessage(text=message)]
                        )
                    )
                    logging.info(f"成功發送 LINE 通知給用戶 {line_user_id}")
                    flash('包裹資訊已成功儲存並發送通知', 'success')
                except Exception as e:
                    logging.error(f"發送 LINE 通知時發生錯誤: {str(e)}")
                    flash('包裹資訊已儲存，但 LINE 通知發送失敗', 'warning')
            else:
                flash('儲存失敗，請稍後再試', 'error')
            
            return redirect(url_for('admin_panel'))
            
        return render_template('admin_panel.html')
    except Exception as e:
        logging.error(f"管理面板發生錯誤: {e}")
        flash('系統錯誤，請稍後再試', 'error')
        return render_template('admin_panel.html')

@app.route('/admin/users')
def user_list():
    """顯示所有 LINE 使用者清單"""
    logging.info("訪問使用者清單")
    try:
        users = db.get_all_line_users()
        return render_template('user_list.html', users=users)
    except Exception as e:
        logging.error(f"獲取使用者清單時發生錯誤: {e}")
        flash('獲取使用者清單失敗', 'error')
        return redirect(url_for('admin_panel'))

@app.route('/admin/product-management')
def product_management():
    """商品管理頁面"""
    logging.info("訪問商品管理頁面")
    try:
        # 從資料庫獲取所有商品
        products = db.get_all_products()
        return render_template('product_management.html', products=products)
    except Exception as e:
        logging.error(f"獲取商品列表時發生錯誤: {e}")
        flash('獲取商品列表失敗', 'error')
        return redirect(url_for('admin_panel'))

@app.route('/admin/product/add', methods=['POST'])
def add_product():
    """新增商品"""
    try:
        # 檢查是否是 JSON 格式的請求
        if request.is_json:
            json_data = request.get_json()
            # 轉換 JSON 格式到系統格式
            product_data = {
                'product_no': json_data.get('No'),
                'product_name': json_data.get('name'),
                'price': json_data.get('price'),
                'product_url': json_data.get('url'),
                'product_description': json_data.get('description', '').strip()
            }
        else:
            # 表單提交的格式
            product_data = {
                'product_no': request.form.get('product_no'),
                'product_name': request.form.get('name'),
                'price': request.form.get('price'),
                'product_url': request.form.get('url'),
                'product_description': request.form.get('description', '').strip()
            }
        
        # 驗證必要欄位
        if not all(product_data.values()):
            error_msg = '所有欄位都是必填的'
            if request.is_json:
                return jsonify({"error": error_msg}), 400
            flash(error_msg, 'error')
            return redirect(url_for('product_management'))
        
        # 處理價格
        price_str = product_data['price']
        try:
            # 移除貨幣符號和其他非數字字符
            price_str = price_str.replace('$', '').replace(',', '').strip()
            # 提取第一個數字（處理如 "建議價：$418,優惠價：$390" 的情況）
            price_match = re.search(r'\d+(?:\.\d+)?', price_str)
            if price_match:
                product_data['price_numeric'] = float(price_match.group())
            else:
                product_data['price_numeric'] = None
        except (ValueError, AttributeError):
            product_data['price_numeric'] = None
        
        # 判斷商品類別
        def determine_category(name, description):
            # 食物相關關鍵字（擴充）
            food_keywords = ['食物', '飲料', '咖啡', '茶', '魚', '肉', '餐具', '廚房', '烤肉', 
                           '削皮器', '食品', '零食', '調味料', '飲品', '麵包', '蛋糕', '餅乾',
                           '巧克力', '糖果', '果汁', '酵素', '營養', '補充品', '保健', '食用']
            
            # 生活用品相關關鍵字（擴充）
            household_keywords = ['牙刷', '牙膏', '洗髮', '護髮', '沐浴', '衛生紙', '清潔', '毛巾', 
                                '垃圾袋', '洗碗', '海綿', '抹布', '洗衣', '衣架', '拖把', '掃把',
                                '保鮮膜', '鋁箔紙', '浴巾', '拖鞋', '香皂', '面膜', '居家', '日用品']
            
            # 電子產品相關關鍵字
            electronics_keywords = ['智慧', '電子', '藍牙', '充電', '電池', 'USB', '無線', 'LED',
                                 '螢幕', '手機', '電腦', '攝影機', '投影機', '音響', '喇叭']

            # 轉換為小寫進行比對
            text = (name + ' ' + description).lower()
            
            # 檢查特定產品類型的關鍵字組合
            if '酵素' in text and ('營養' in text or '保健' in text or '食用' in text):
                return '食物'
            elif '麵包' in text or '蛋糕' in text or '餅乾' in text:
                return '食物'
            elif any(keyword in text for keyword in food_keywords):
                return '食物'
            elif any(keyword in text for keyword in household_keywords):
                return '生活用品'
            elif any(keyword in text for keyword in electronics_keywords):
                return '電子產品'
            
            # 進一步檢查商品描述中的關鍵詞
            if any(word in text for word in ['食用', '飲用', '食品', '營養', 'DHA', 'EPA']):
                return '食物'
            elif any(word in text for word in ['清潔', '保養', '居家']):
                return '生活用品'
            
            return '其他'

        # 設置商品類別
        product_data['category'] = determine_category(
            product_data['product_name'], 
            product_data['product_description']
        )
        
        logging.info(f"準備新增商品: {product_data['product_name']}")
        logging.info(f"類別: {product_data['category']}")
        logging.info(f"價格: {product_data['price']} (數值: {product_data.get('price_numeric')})")
            
        # 新增商品到資料庫
        success = db.add_product(product_data)
        
        if success:
            if request.is_json:
                return jsonify({"message": "商品新增成功"}), 200
            flash('商品新增成功', 'success')
        else:
            if request.is_json:
                return jsonify({"error": "商品新增失敗"}), 400
            flash('商品新增失敗', 'error')
            
        if not request.is_json:
            return redirect(url_for('product_management'))
        
    except Exception as e:
        logging.error(f"新增商品時發生錯誤: {e}")
        if request.is_json:
            return jsonify({"error": str(e)}), 500
        flash('系統錯誤，請稍後再試', 'error')
        return redirect(url_for('product_management'))

@app.route('/admin/product/export', methods=['GET'])
def export_products():
    """導出商品資料為 JSON 格式"""
    try:
        products = db.get_all_products()
        return jsonify(products)
    except Exception as e:
        logging.error(f"導出商品資料時發生錯誤: {e}")
        return jsonify({"error": "系統錯誤"}), 500


if __name__ == '__main__':
    # 設定詳細的日誌格式
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    logging.info("正在啟動 API 服務...")
    
    # 啟動狀態輸出線程
    status_thread = Thread(target=print_status, daemon=True)
    status_thread.start()
    
    # 確保服務正確啟動
    try:
        logging.info("API 服務已啟動，監聽端口 5000")
        app.run(host='0.0.0.0', debug=True, port=5000)
    except Exception as e:
        logging.error(f"服務啟動失敗: {e}")
