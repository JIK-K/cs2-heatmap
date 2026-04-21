# Dockerfile
FROM python:3.10-slim

# 시스템 의존성 설치 (필요한 경우)
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# 8000번 포트 개방
EXPOSE 8000

# 실행 명령어 (Production 환경에 맞게 uvicorn 실행)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
