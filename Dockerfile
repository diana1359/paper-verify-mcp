FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sources.py server.py ./

# 호스팅 플랫폼(Render/Railway/Fly 등)이 넣어주는 PORT 를 사용.
ENV PORT=8000
EXPOSE 8000

CMD ["python", "server.py"]
