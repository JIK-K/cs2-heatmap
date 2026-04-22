# Dockerfile
FROM python:3.11-slim

# 시스템 의존성 설치
# 라이브러리 컴파일에 필요한 build-essential 등 포함
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 설치
COPY requirements.txt .
# pip 자체도 최신으로 업데이트하는 것이 패키지 설치 시 유리합니다
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# 8000번 포트 개방
EXPOSE 8000

# 실행 명령어
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]