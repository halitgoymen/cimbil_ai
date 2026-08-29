import os
import uvicorn
from a2wsgi import WSGIMiddleware

# Gerekli path'leri sys.path'e ekleyelim
import sys
# Sadece Chatbotv2'yi ekliyoruz ki "app" klasörü sorunsuz import edilebilsin
# gymble_api dizinini eklememize gerek yok çünkü zaten parent olarak erişilebilir (from gymble_api.app import ...)
# Insert 1 to front to ensure it takes precedence over working directory
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "Chatbotv2"))

# 1. FastAPI Uygulamasını yükle (Chatbotv2)
# Uvicorn ve iç importlar direkt `app.` prefix'i ile import edebilsin diye
from app.main import app as fastapi_app

# 2. Flask Uygulamasını yükle (gymble_api)
from gymble_api.app import app as flask_app

# 3. Flask uygulamasını ASGI wrapper'a çevir
flask_asgi_app = WSGIMiddleware(flask_app)

# 4. FastAPI tarafında asıl (root) işlemleri devret.
# FastAPI varsayılan olarak tanımlanmayan her şeyi Flask'a (fallback) yönlendirecek.
fastapi_app.mount("/", flask_asgi_app)

# 5. Hugging Face portunda ayağa kaldır
if __name__ == "__main__":
    port = int(os.getenv("PORT", 7860))
    # Uvicorn, bu unified fastapi uygulamasını hostlar.
    uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="info")
