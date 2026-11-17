# Office-Travel

公司旅遊人數填寫表單（Streamlit）。員工填寫大人／小孩人數，管理員可編輯資料、查看統計，
資料會加密備份到 GitHub，Streamlit app 重開機後自動還原。

線上網址：https://office-travel-gbilfvtnk6wkuybcvec983.streamlit.app/

## 檔案

| 檔案 | 用途 |
| --- | --- |
| `travel.py` | 主程式 |
| `travel_data.json` | 加密備份（由 app 自動寫入，請勿手動修改） |
| `keep_alive.py` | 由 GitHub Actions 定期造訪 app，必要時點擊喚醒按鈕 |
| `tests/` | 自動測試（備份安全、統計、管理員登入） |
| `requirements.txt` | app 需要的套件 |
| `requirements-test.txt` | 只給測試用的套件 |

## Secrets 設定（Streamlit Cloud → Settings → Secrets）

```toml
[admin]
password = "管理員密碼"

[github]
token          = "有 Contents 讀寫權限的 token"
owner          = "Shoukon"
repo           = "Office-Travel"
branch         = "main"
data_file      = "travel_data.json"
encryption_key = "備份加密金鑰（Fernet key）"
```

另有 `[default_settings]`（旅遊地點等預設值）。**請勿更換或遺失 `encryption_key`**，
否則 GitHub 上的舊備份將無法解密。

## 資料如何保存

Streamlit Cloud 的本機磁碟在重開機或重新部署後會清空，所以：

- 每次新增或修改填寫資料，都會把加密備份寫回 GitHub。
- app 重開機後發現本機是空的，會先從 GitHub 還原。
- **還原失敗時 app 會停在錯誤畫面並提供「重試還原」**，不會用空資料開始，
  也不會把 GitHub 上的備份蓋掉。
- 本機資料為空、但 GitHub 備份有資料時，拒絕上傳。

管理員頁面可以看到最後一次同步時間與筆數。

## 管理員登入

連續輸入錯誤 5 次會鎖定 60 秒。

## 本機測試

```
python -m pip install pytest pandas
python -m pytest tests -q
```

測試只抽出 `travel.py` 裡的函式執行，不會啟動 Streamlit，也不會連到真正的 GitHub。

## keep_alive

預設網址寫在 `keep_alive.py`。若 app 網址改變，可在 GitHub → Settings → Secrets and variables →
Actions → Variables 新增 `APP_URL`，不必改程式。腳本在 app 沒有載入時會讓 Actions 顯示失敗。
