# Gymble API Documentation

> **Tek Docker Container** — Nginx reverse proxy + Supervisord  
> Flask API + FastAPI Chatbot tek port üzerinden çalışır.  
> Veri dosyaları ilk startup'ta Google Drive'dan indirilir.

---

## Koyeb Deployment

Koyeb'de **Docker** build type seçin. Aşağıdaki env variables ekleyin:

| Değişken | Zorunlu | Açıklama |
|----------|---------|----------|
| `OPENROUTER_API_KEY` | ✅ | OpenRouter API anahtarı |
| `MODEL_ID` | ❌ | AI model (default: `google/gemini-2.0-flash-001`) |
| `DATABASE_API_URL` | ✅ | Node.js backend URL |
| `API_GATEWAY_URL` | ✅ | Kullanıcı profil API gateway |
| `GDRIVE_FOLDER_ID` | ✅ | Google Drive veri klasörü ID |
| `PORT` | ❌ | Koyeb otomatik set eder |

**Health Check:** `GET /health` (HTTP, port $PORT)

---

## Lokal Çalıştırma

```bash
docker compose up -d --build
# Tek port: http://localhost:8080
```

---

## Endpoint'ler (Tek Port)

### Flask API → `/`

| Method | Endpoint | Content-Type | Body |
|--------|----------|-------------|------|
| POST | `/analyze` | multipart/form-data | `image`, `mealType` |
| POST | `/analyze/text` | application/json | `{"text": "...", "mealType": "lunch"}` |
| POST | `/analyze/barcode` | application/json | `{"barcode": "...", "mealType": "lunch"}` |
| POST | `/analyze/barcode_image` | multipart/form-data | `image`, `mealType` |
| GET | `/health` | — | — |

### Chatbot → `/api/`

| Method | Endpoint | Body |
|--------|----------|------|
| POST | `/api/chat` | `{"messages": [...], "user_id": "uuid"}` |
| GET | `/api/health` | — |

### Response Format (analyze endpoints)
```json
{
  "foodName": "Izgara Tavuk",
  "calories": 280,
  "protein": 35,
  "carbs": 0,
  "fat": 8,
  "fiber": 0,
  "mealType": "lunch",
  "date": "2026-03-02",
  "source": "image",
  "details": [...]
}
```
