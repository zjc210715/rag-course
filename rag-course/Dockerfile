FROM python:3.13-slim

WORKDIR /app

# 先装依赖：依赖不变时 Docker 会复用这一层缓存，重建很快
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 再复制代码和数据
COPY app/ ./app/
COPY data/ ./data/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]