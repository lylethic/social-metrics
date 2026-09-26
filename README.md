# 🚀 Docker Setup & Testing Guide in Development

```bash
cd social-insight
```

```bash
.\.venv\Scripts\activate
uvicorn app.main:app --host 127.0.0.1 --port 5032 --reload
```

## 1. Start the Entire Container Stack

### 1.1. Build docker image
```bash
docker-compose up --build
```

### 1.2. Run docker
```
docker-compose up db redis worker beat
```


### 1.3. Start ngrok for backend url
```powershell
.\ngrok.exe http 127.0.0.1:5032 --url https://either-negative-botanist.ngrok-free.dev
```

- Stop ngrok
```powershell
taskkill /f /im ngrok.exe
```

## 2. Run Database Migrations

Create and update the database tables by running:

```bash
docker-compose exec api alembic upgrade head
```

## 3. Check the API & Swagger Documentation

* **Swagger UI – Interactive API Documentation:** http://127.0.0.1:5032/docs
* **Health Check:** http://127.0.0.1:5032/health
