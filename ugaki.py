import os
import time
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from requests.exceptions import SSLError
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
ALBUM_ID = "AKIE58x36-StaOKhek0qSdoOrCpQVJxwToWXh4Q8lWPa_OX0xQcdfB-YZKdmwomG6t4-Jvt22A-9"

# 認証処理
def get_credentials():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                # トークンが無効な場合は再認証
                print("トークンが無効です。再認証を行います...")
                if os.path.exists('token.pickle'):
                    os.remove('token.pickle')
                creds = None
        
        if not creds:
            # 新規認証または再認証
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
def upload_photo(file_path, creds, album_id, deleting_files=None):
    if deleting_files is None:
        deleting_files = set()
    
    headers = {"Authorization": "Bearer " + creds.token}
    upload_url = "https://photoslibrary.googleapis.com/v1/uploads"

    # ファイルが存在するまで待機（最大5秒）
    for i in range(10):
        if os.path.exists(file_path):
            break
        time.sleep(0.5)
    else:
        print("ファイルが見つかりませんでした:", file_path)
        return False

    # ファイル読み込み
    try:
        with open(file_path, 'rb') as f:
            img_bytes = f.read()
    except Exception as e:
        print(f"ファイル読み込みエラー: {file_path}, {e}")
        return False

    upload_token = safe_post(upload_url, img_bytes, headers={
        "Authorization": "Bearer " + creds.token,
        "Content-type": "application/octet-stream",
        "X-Goog-Upload-File-Name": os.path.basename(file_path),
        "X-Goog-Upload-Protocol": "raw",
    })

    if not upload_token:
        print("アップロードトークンの取得に失敗しました:", file_path)
        return False

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
        response_data = response.json()
        
        # レスポンスのstatusを厳密に確認
        if response.status_code == 200:
            # newMediaItemResultsの中のstatusを確認
            if 'newMediaItemResults' in response_data:
                for result in response_data['newMediaItemResults']:
                    status = result.get('status', {})
                    if status.get('message') == 'Success':
                        media_item = result.get('mediaItem', {})
                        media_id = media_item.get('id', 'N/A')
                        print(f"✓ アップロード成功: {os.path.basename(file_path)} (ID: {media_id})")
                        
                        # アップロード成功したファイルのみを削除
                        delete_uploaded_file(file_path, deleting_files)
                        return True
                    else:
                        print(f"✗ アップロード失敗: {file_path}, Status: {status}")
                        return False
            else:
                print(f"✗ レスポンス形式が不正: {response_data}")
                return False
        else:
            print(f"✗ アップロードに失敗しました: {file_path}, Status: {response.status_code}, Response: {response_data}")
            return False
    except Exception as e:
        print(f"アルバム追加時にエラー: {file_path}, {e}")
        return False

# アップロード成功したファイルを削除
def delete_uploaded_file(file_path, deleting_files):
    if not os.path.exists(file_path):
        return
    
    # 削除中リストに追加（再検知を防ぐ）
    deleting_files.add(file_path)
    try:
        os.remove(file_path)
        print(f"削除しました: {os.path.basename(file_path)}")
    except Exception as e:
        print(f"削除に失敗しました: {file_path}, {e}")
        # エラー時は削除中リストから除外
        deleting_files.discard(file_path)

# フォルダ監視イベント
class PhotoHandler(FileSystemEventHandler):
    def __init__(self, creds, album_id):
        self.creds = creds
        self.album_id = album_id
        self.processed_files = set()  # 処理済みファイルを記録
        self.deleting_files = set()  # 削除中のファイルを記録

    def on_created(self, event):
        if not event.is_directory and not event.src_path.endswith(".crdownload"):
            file_path = event.src_path
            # 既に処理済みまたは削除中のファイルは無視
            if file_path in self.processed_files or file_path in self.deleting_files:
                return
            
            print("New file detected:", file_path)
            if wait_for_complete(file_path):
                # 処理開始前に記録
                self.processed_files.add(file_path)
                upload_photo(file_path, self.creds, self.album_id, self.deleting_files)
            else:
                print("ファイルの書き込みが完了しませんでした:", file_path)
    
    def on_deleted(self, event):
        # 削除イベントは無視（自分で削除したファイルの検知を防ぐ）
        pass

if __name__ == "__main__":
    print("スクリプト起動中...")
    time.sleep(5)  # 起動直後のネット安定化待ち
    creds = get_credentials()

    # ALBUM_ID = create_album(creds, "宇垣美里")
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