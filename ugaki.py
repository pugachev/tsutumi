import os
import time
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle

# GoogleフォトAPIのスコープ
SCOPES = [
    'https://www.googleapis.com/auth/photoslibrary.appendonly',
    'https://www.googleapis.com/auth/photoslibrary.readonly',
    'https://www.googleapis.com/auth/photoslibrary.sharing'
]

# フォルダ監視対象
WATCH_FOLDER = r"/Users/ikefuku40/ugaki"

# ★ここに有効なアルバムIDを固定で設定（create_albumで取得したもの）
ALBUM_ID = "AKIE58y8eZ2Gtsz5k-GKSUwtko9i97_lCl4ji-PFTZBYdYvn6_-eNtu-umZbL1WVo-kFCUlSlbuc"

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

def create_album(creds, title):
    url = "https://photoslibrary.googleapis.com/v1/albums"
    headers = {"Authorization": "Bearer " + creds.token}
    body = {"album": {"title": title}}
    response = requests.post(url, headers=headers, json=body)
    album = response.json()
    print("Created album:", album.get("title"), "ID:", album.get("id"))
    return album.get("id")


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

    upload_token = requests.post(upload_url, data=img_bytes, headers={
        "Authorization": "Bearer " + creds.token,
        "Content-type": "application/octet-stream",
        "X-Goog-Upload-File-Name": os.path.basename(file_path),
        "X-Goog-Upload-Protocol": "raw",
    }).text

    # アルバムに追加
    create_url = "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate"
    body = {
        "albumId": album_id,
        "newMediaItems": [{
            "description": "Uploaded by script",
            "simpleMediaItem": {"uploadToken": upload_token}
        }]
    }
    response = requests.post(create_url, headers=headers, json=body)
    print("Uploaded:", file_path, response.json())

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
    creds = get_credentials()

    ALBUM_ID = create_album(creds, "宇垣美里")
    print("ALBUM_ID:", ALBUM_ID)
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