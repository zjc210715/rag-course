FROM python:3.13-slim

WORKDIR /app

# 前端只需要 streamlit + requests（后端依赖全在 backend 镜像里，这里保持精简）
COPY ui-requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --timeout 120 --retries 5 -r ui-requirements.txt

COPY app/ui.py ./app/ui.py
COPY assets/ ./assets/
COPY .streamlit/ ./.streamlit/

EXPOSE 8501

CMD ["streamlit", "run", "app/ui.py", "--server.address", "0.0.0.0", "--server.port", "8501", "--server.headless", "true"]
