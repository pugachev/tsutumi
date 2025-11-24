import os
import time
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle
from requests.exceptions import SSLError

# GoogleフォトAPIのスコープ
SCOPES = [
    'https://www.googleapis.com/auth/photoslibrary.appendonly',
    'https://www.googleapis.com/auth/photoslibrary.readonly',
    'https://www.googleapis.com/auth/photoslibrary.sharing'
]

# フォルダ監視対象
WATCH_FOLDER = r"C:\tsutumi"

# ★ここに有効なアルバムIDを固定で設定（create_albumで取得したもの）
ALBUM_ID = "AKIE58zAZLkeLUv2usOFGJMpk71lFz5oGHvHWAuwxqsNqiX3Qp9bweUS7ldoa6TPjPEA4K9hNX-T"

# 認証処理
def get_credentials():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    return creds

# 書き込み完了を待つ
def wait_for_complete(file_path, timeout=30):
    prev_size = -1
    for _ in range(timeout * 2):  # 最大30秒待機
        try:
            curr_size = os.path.getsize(file_path)
            if curr_size == prev_size and curr_size > 0:
                return True
            prev_size = curr_size
        except FileNotFoundError:
            pass
        time.sleep(0.5)
    return False

# SSLリトライ付きPOST
def safe_post(url, data, headers, retries=3):
    for i in range(retries):
        try:
            return requests.post(url, data=data, headers=headers).text
        except SSLError as e:
            print(f"[SSLエラー] {i+1}回目: {e}")
            time.sleep(2)
    print("SSLエラーが解消されませんでした")
    return None

# Googleフォトにアップロード
def upload_photo(file_path, creds, album_id):
    headers = {"Authorization": "Bearer " + creds.token}
    upload_url = "https://photoslibrary.googleapis.com/v1/uploads"

    # ファイルが存在するまで待機（最大5秒）
    for i in range(10):
        if os.path.exists(file_path):
            break
        time.sleep(0.5)
    else:
        print("ファイルが見つかりませんでした:", file_path)
        return

    # ファイル読み込み
    with open(file_path, 'rb') as f:
        img_bytes = f.read()

    upload_token = safe_post(upload_url, img_bytes, headers={
        "Authorization": "Bearer " + creds.token,
        "Content-type": "application/octet-stream",
        "X-Goog-Upload-File-Name": os.path.basename(file_path),
        "X-Goog-Upload-Protocol": "raw",
    })

    if not upload_token:
        print("アップロードトークンの取得に失敗しました:", file_path)
        return

    # アルバムに追加
    create_url = "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate"
    body = {
        "albumId": album_id,
        "newMediaItems": [{
            "description": "Uploaded by script",
            "simpleMediaItem": {"uploadToken": upload_token}
        }]
    }
    try:
        response = requests.post(create_url, headers=headers, json=body)
        print("Uploaded:", file_path, response.json())
    except Exception as e:
        print("アルバム追加時にエラー:", e)

# フォルダ監視イベント
class PhotoHandler(FileSystemEventHandler):
    def __init__(self, creds, album_id):
        self.creds = creds
        self.album_id = album_id

    def on_created(self, event):
        if not event.is_directory and not event.src_path.endswith(".crdownload"):
            print("New file detected:", event.src_path)
            if wait_for_complete(event.src_path):
                upload_photo(event.src_path, self.creds, self.album_id)
            else:
                print("ファイルの書き込みが完了しませんでした:", event.src_path)

if __name__ == "__main__":
    print("スクリプト起動中...")
    time.sleep(5)  # 起動直後のネット安定化待ち
    creds = get_credentials()
    event_handler = PhotoHandler(creds, ALBUM_ID)
    observer = Observer()
    observer.schedule(event_handler, WATCH_FOLDER, recursive=False)
    observer.start()
    print("Watching folder:", WATCH_FOLDER)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()