# Dockerfile
# 這份檔案描述「如何把這個 Django 專案打包成一個 Docker image」。
# 建置流程：抓一個乾淨的 Python 環境 -> 裝套件 -> 把程式碼複製進去 -> 設定啟動指令。

FROM python:3.12-slim

# 讓 Python 的 log 即時輸出（不要被緩衝住），方便用 docker logs 看到即時訊息
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 容器內的工作目錄，之後所有指令都是以這裡為基準
WORKDIR /app

# 先只複製 requirements.txt 並安裝套件。
# 這樣只要程式碼變動、requirements.txt 沒變，Docker 就能重用快取，不用每次重新 pip install。
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# 再把整個專案複製進容器
COPY . /app/

EXPOSE 8000

# 容器啟動時執行 docker-entrypoint.sh：先跑資料庫遷移，再啟動開發伺服器
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
