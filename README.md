# 🚀 Docker Setup & Testing Guide

```bash
cd social-insight
```

```bash
.\.venv\Scripts\activate
uvicorn app.main:app --host 127.0.0.1 --port 5032 --reload
```

## 1. Start the Entire Container Stack

```bash
docker-compose up -d --build
```

### Terminal 1: Run the Celery Worker (Task Execution)

```powershell
celery -A app.workers.celery_app.celery_app worker --loglevel=info -P solo
```

### Terminal 2: Run Celery Beat (Periodic Task Scheduler)

```powershell
celery -A app.workers.celery_app.celery_app beat --loglevel=info
```

## 2. Run Database Migrations

Create and update the database tables by running:

```bash
docker-compose exec api alembic upgrade head
```

## 3. Check the API & Swagger Documentation

* **Swagger UI – Interactive API Documentation:** http://127.0.0.1:5032/docs
* **Health Check:** http://127.0.0.1:5032/health
