FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    default-libmysqlclient-dev \
    gcc \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["bash", "-c", "python manage.py migrate --database=default 2>/dev/null || true && python manage.py migrate --database=local 2>/dev/null || true && python manage.py runserver 0.0.0.0:8000"]
