FROM python:3.10-slim

# 設定工作目錄
WORKDIR /app

# 複製並安裝套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 建立必要資料夾
RUN mkdir -p /app/outputs

# 複製應用程式原始碼
COPY app ./app

# 使用 uvicorn 啟動 FastAPI 應用
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
