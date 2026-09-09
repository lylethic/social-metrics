# 🚀 Hướng dẫn khởi chạy & kiểm tra bằng Docker:
```bash
cd social-insight 
```

```bash
.\.venv\Scripts\activate
uvicorn app.main:app --host 127.0.0.1 --port 5032 --reload
```

## 1. Khởi động toàn bộ cụm Container:
```bash
docker-compose up -d --build
```

## 2. Chạy Migration tạo bảng Database:
```bash
docker-compose exec api alembic upgrade head
```

## 3. Kiểm tra API & Swagger Docs:
- Swagger UI Interactive Docs: http://127.0.0.1:5032/docs
- Healthcheck: http://127.0.0.1:5032/health
