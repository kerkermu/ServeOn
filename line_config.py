from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi
)

CHANNEL_ACCESS_TOKEN = "twEdRjxTfwDx/tbxQffPJ6p+O8/O7z0hOkiPQuvMQIF1l09SwrjJ6kMUAbsjAbPE1npWPvmVQjWnZvmeB3DzpjNE54rSS1jkXjHukOu8WM2JAxTY1SPqKlwuL0FceFOX0DA2O1EV+b9TOxaQlYul1wdB04t89/1O/w1cDnyilFU="
CHANNEL_SECRET = "a5cabbeb1a7c28d2f58c9f5dfc4a2965"

def get_line_bot_api():
    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
    api_client = ApiClient(configuration)
    return MessagingApi(api_client) 