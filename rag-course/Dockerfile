FROM python:3.13-slim

WORKDIR /app

# 先装依赖：依赖不变时 Docker 会复用这一层缓存，重建很快
COPY requirements.txt .
# 国内网络用阿里云镜像加速；公司内网有私有 PyPI 源的话换成自己的
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --timeout 120 --retries 5 -r requirements.txt

# 再复制代码和数据
COPY app/ ./app/
COPY data/ ./data/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
