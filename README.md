---
title: Gymble V1
emoji: 🚀
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
---

# Gymble API & Chatbot

Beslenme takibi için AI destekli API — yemek fotoğrafı, barkod veya metinden kalori/makro
analizi çıkarır, ayrıca RAG tabanlı bir diyet chatbot'u sunar. Tek Docker container'da
Nginx reverse proxy + Supervisord ile Flask API ve FastAPI chatbot aynı port üzerinden
çalışır. Hugging Face Docker Space ve Koyeb'de deploy edilebilir.

## Özellikler

- **Gıda analizi:** fotoğraf, metin veya barkoddan kalori/protein/karbonhidrat/yağ/lif
  çıkarımı (`/analyze`, `/analyze/text`, `/analyze/barcode`, `/analyze/barcode_image`)
- **RAG chatbot:** Türkçe/yerel tarif ve besin bilgi tabanlarına (USDA FoodData Central,
  Türkçe tarifler, sivrihisar tarifleri, tuber knowledge base) dayalı sohbet arayüzü
  (`/api/chat`)
- Küfür/+18 içerik filtresi
- Veri dosyaları (dataset'ler) ilk startup'ta Google Drive'dan indirilir, repo'ya
  commitlenmez

## Teknoloji

- Flask (gıda analiz API), FastAPI (RAG chatbot)
- OpenRouter (LLM), RAG (vector store + knowledge base)
- Nginx + Supervisord (tek container'da iki servis)
- Docker, Koyeb / Hugging Face Spaces deploy

## Kurulum

`.env` dosyasına ekle (repo'ya commitlenmez):

```
OPENROUTER_API_KEY=
MODEL_ID=google/gemini-2.0-flash-001   # opsiyonel
DATABASE_API_URL=
API_GATEWAY_URL=
GDRIVE_FOLDER_ID=
```

## Çalıştırma

```
docker compose up -d --build
# Tek port: http://localhost:8080
```

Endpoint detayları, örnek istek/yanıt formatları için [API_DOCS.md](API_DOCS.md).
