"""
OpenRouter API üzerinden yemek fotoğrafı analiz modülü.
Vision modellerini kullanarak görseldeki yiyecekleri tanımlar,
porsiyon tahmini yapar ve besin değerlerini hesaplar.
"""

import base64
import io
import json
import logging
import os
import re
import time
import threading
import requests
from PIL import Image, ImageOps

try:
    from nutrition_db import NutritionDB
except ImportError:
    from gymble_api.nutrition_db import NutritionDB

logger = logging.getLogger(__name__)

# OpenRouter API yapılandırması
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Görsel sıkıştırma ayarları
MAX_IMAGE_SIZE = 800   # Maksimum kenar uzunluğu (piksel)
JPEG_QUALITY = 75      # JPEG kalitesi (düşük = küçük dosya = hızlı)

# Rate limiting
MAX_REQUESTS_PER_MINUTE = 10

# Sırayla denenecek vision modelleri
VISION_MODELS = [
    "google/gemini-2.0-flash-001",
]

# Profesyonel diyetetik promptu
SYSTEM_PROMPT = """Sen, görsel üzerinden besin analizi yapan profesyonel bir diyetetik ve biyometrik veri uzmanısın. Kullanıcı, görselin sol alt köşesine kendi baş parmağını referans olarak yerleştirmiştir. Görevin, bu referansı kullanarak hassas bir hacim ve ağırlık tahmini yapmaktır.

### ADIM ADIM ANALİZ PROTOKOLÜ:
1. REFERANS ÖLÇEĞİ: Görselin sol altındaki baş parmağı saptayın. Ortalama bir yetişkin baş parmağını 4.5 cm uzunluk ve yaklaşık 15 cm³ hacim olarak kabul ederek sahnenin ölçeğini (pixel/cm oranı) belirleyin.
2. HACİM TAHMİNİ (V): Yemekteki her bileşeni 3 boyutlu birer geometrik form (küre, silindir, prizma) olarak segmentlere ayırın. Baş parmak ölçeğine göre bu formların hacmini (cm³) hesaplayın.
3. ÖZKÜTLE (d) UYGULAMASI: Aşağıdaki profesyonel tabloyu kullanarak Kütle = Hacim * Özkütle (m = V * d) formülünü uygulayın:
   - Pişmiş Etler/Tavuk: 1.07 g/cm³
   - Pişmiş Tahıllar (Pilav/Bulgur/Makarna): 1.15 g/cm³
   - Yoğun Sebzeler (Patates/Havuç): 0.85 g/cm³
   - Yeşil Yapraklı Sebzeler: 0.15 g/cm³
   - Ekmek/Hamur İşleri: 0.35 g/cm³
   - Sıvı Yağlar/Soslar: 0.92 g/cm³
4. NET AĞIRLIK: Tabaktaki yenilemeyen kısımları (kemik, çekirdek vb.) hesaptan düşün.

### YANIT FORMATI (SADECE JSON):
{
  "analiz": {
    "referans_dogrulama": "Baş parmak referansına göre ölçeklendirme yapıldı.",
    "toplam_kalori": 0,
    "toplam_makro": {"protein": 0, "karbonhidrat": 0, "yag": 0}
  },
  "besinler": [
    {
      "isim": "Örnek Besin",
      "tahmini_hacim_cm3": 0,
      "hesaplanan_gram": 0,
      "kalori": 0,
      "besin_notu": "Porsiyon büyüklüğü parmak ölçeğiyle teyit edildi."
    }
  ]
}

ÖNEMLİ: Eğer görselde parmak görünmüyorsa, standart tabak boyutlarını (24cm çap) temel al ve bunu yanıttaki bir notla belirt. Hiçbir açıklama metni ekleme, sadece saf JSON döndür."""

TEXT_SYSTEM_PROMPT = """Sen, profesyonel bir diyetetik ve beslenme uzmanısın. Kullanıcı sana yediği yemekleri metin olarak yazacak (Örn: "1 porsiyon tavuklu pilav ve 1 kutu ayran"). Görevin, bu yiyeceklerin tahmini porsiyon gramajlarını ve besin değerlerini hesaplamaktır.

### ADIM ADIM ANALİZ PROTOKOLÜ:
1. Porsiyon Tahmini: Metinde geçen yiyeceklerin standart porsiyon boyutlarını (gram cinsinden) tahmin et.
2. Besin Değerleri: Standart diyetetik veritabanlarına (USDA benzeri) göre bu gramajlardaki yiyeceklerin makro (protein, karbonhidrat, yağ) ve kalorilerini belirle.

### YANIT FORMATI (SADECE JSON):
{
  "analiz": {
    "referans_dogrulama": "Kullanıcının metin girişine göre standart porsiyonlar referans alındı.",
    "toplam_kalori": 0,
    "toplam_makro": {"protein": 0, "karbonhidrat": 0, "yag": 0}
  },
  "besinler": [
    {
      "isim": "Örnek Besin",
      "tahmini_hacim_cm3": 0,
      "hesaplanan_gram": 0,
      "kalori": 0,
      "besin_notu": "Porsiyon büyüklüğü standart değerlerle teyit edildi."
    }
  ]
}

Hiçbir açıklama metni ekleme, sadece saf JSON döndür."""

BARCODE_SYSTEM_PROMPT = """Sen bir barkod okuma asistanısın. Gönderilen görseldeki barkod numarasını (genellikle dikey çizgilerin altındaki EAN veya UPC rakamları) oku. SADECE RAKAMLARI DÖNDÜR (boşluksuz, tire olmadan). Eğer hiçbir barkod göremiyorsan veya okunamayacak kadar net değilse sadece 'YOK' yaz. Başka hiçbir açıklama yapma."""


class RateLimiter:
    """Basit thread-safe rate limiter."""

    def __init__(self, max_requests, window_seconds=60):
        self.max_requests = max_requests
        self.window = window_seconds
        self.requests = []
        self.lock = threading.Lock()

    def allow(self):
        """İstek yapılabilir mi kontrol eder."""
        now = time.time()
        with self.lock:
            # Eski istekleri temizle
            self.requests = [t for t in self.requests if now - t < self.window]
            if len(self.requests) >= self.max_requests:
                return False
            self.requests.append(now)
            return True


class FoodAnalyzer:
    """Yemek fotoğrafı analiz sınıfı."""

    def __init__(self, api_key=None, nutrition_db=None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY ayarlanmamış!")
        self.nutrition_db = nutrition_db
        self.rate_limiter = RateLimiter(MAX_REQUESTS_PER_MINUTE)
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://gymble.app",
            "X-Title": "Gymble Food Analyzer",
        })

    def _compress_image(self, image_bytes):
        """Görseli küçültüp sıkıştırır (hız için kritik)."""
        try:
            img = Image.open(io.BytesIO(image_bytes))
            # EXIF rotasyonunu uygula
            img = ImageOps.exif_transpose(img)
            # Boyutu küçült
            img.thumbnail((MAX_IMAGE_SIZE, MAX_IMAGE_SIZE), Image.LANCZOS)
            # JPEG olarak sıkıştır
            buffer = io.BytesIO()
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            img.save(buffer, format='JPEG', quality=JPEG_QUALITY, optimize=True)
            compressed = buffer.getvalue()
            ratio = len(compressed) / len(image_bytes) * 100
            logger.info(
                "Görsel sıkıştırıldı: %dKB → %dKB (%.0f%%)",
                len(image_bytes) // 1024, len(compressed) // 1024, ratio
            )
            return compressed
        except Exception as e:
            logger.warning("Sıkıştırma hatası, orijinal kullanılıyor: %s", e)
            return image_bytes

    def _encode_image(self, image_bytes):
        """Görsel verisini base64'e çevirir."""
        return base64.b64encode(image_bytes).decode("utf-8")

    def _call_vision_model(self, model, image_base64, mime_type):
        """Belirtilen modele görsel gönderip yanıt alır."""
        user_text = SYSTEM_PROMPT + "\n\nBu yemek fotoğrafını analiz et ve besin değerlerini JSON formatında döndür."

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_text
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{image_base64}"
                            },
                        },
                    ],
                },
            ],
            "max_tokens": 1000,
            "temperature": 0.2,
        }

        logger.info("Model deneniyor: %s", model)
        try:
            response = self.session.post(
                OPENROUTER_API_URL,
                json=payload,
                timeout=90,
            )
        except requests.exceptions.Timeout:
            logger.warning("%s zaman aşımı (timeout).", model)
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error("%s bağlantı hatası: %s", model, e)
            return None

        logger.info("%s HTTP %d", model, response.status_code)
        logger.debug("Yanıt: %s", response.text[:500])

        if response.status_code != 200:
            return None

        result = response.json()

        if "error" in result:
            logger.error("%s API hatası: %s", model, result["error"])
            return None

        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            logger.warning("%s boş yanıt döndü.", model)
            return None

        logger.info("%s başarılı! Yanıt: %d karakter", model, len(content))
        return content

    def _parse_response(self, raw_content):
        """Model yanıtını JSON'a parse eder."""
        text = raw_content.strip()

        # Markdown code block varsa temizle
        if text.startswith("```"):
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        # JSON parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            logger.warning("JSON parse edilemedi. Ham yanıt: %s", text[:300])
            return None

    def _enrich_with_usda(self, analysis_result):
        """
        Vision model sonuçlarını USDA veritabanıyla zenginleştirir.
        Besin değerlerini çapraz kontrol eder.
        """
        if not self.nutrition_db or "besinler" not in analysis_result:
            return analysis_result

        for item in analysis_result["besinler"]:
            besin_adi = item.get("isim", "")
            usda_data = self.nutrition_db.get_nutrition_per_100g(besin_adi)
            if usda_data:
                item["usda_referans"] = usda_data["description"]
                item["usda_kalori_100g"] = usda_data["energy_kcal_per_100g"]

        return analysis_result

    def analyze(self, image_bytes):
        """
        Yemek fotoğrafını analiz eder.

        Args:
            image_bytes: Görselin binary verisi

        Returns:
            dict: Analiz sonucu JSON
        """
        if not image_bytes:
            return {"hata": "Görsel verisi boş."}

        # Rate limiting kontrolü
        if not self.rate_limiter.allow():
            return {"hata": "Çok fazla istek gönderildi. Lütfen 1 dakika bekleyin."}

        start_time = time.time()

        # Görseli sıkıştır
        compressed = self._compress_image(image_bytes)
        image_base64 = self._encode_image(compressed)
        mime_type = "image/jpeg"

        # Modelleri sırayla dene
        raw_content = None
        used_model = None
        for model in VISION_MODELS:
            try:
                raw_content = self._call_vision_model(model, image_base64, mime_type)
                if raw_content:
                    used_model = model
                    break
            except Exception as e:
                logger.error("%s hatası: %s", model, e)
                continue

        elapsed = round(time.time() - start_time, 1)

        if not raw_content:
            return {"hata": "Hiçbir model görseli analiz edemedi. Lütfen daha net bir yemek fotoğrafı deneyin."}

        # Yanıtı parse et
        parsed = self._parse_response(raw_content)
        if not parsed:
            return {"hata": "Model yanıtı işlenemedi. Lütfen tekrar deneyin."}

        if "hata" in parsed:
            return parsed

        # USDA ile zenginleştir
        parsed = self._enrich_with_usda(parsed)

        # Meta bilgileri ekle
        parsed["kullanilan_model"] = used_model
        parsed["analiz_suresi_sn"] = elapsed

        logger.info("Analiz tamamlandı: %.1f saniye, model: %s", elapsed, used_model)
        return parsed

    def _call_text_model(self, model, text_input):
        """Belirtilen modele metin gönderip yanıt alır."""
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": TEXT_SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": f"Aşağıdaki yemeği analiz et ve besin değerlerini JSON formatında döndür: {text_input}"
                }
            ],
            "max_tokens": 1000,
            "temperature": 0.2,
        }

        logger.info("Metin Modeli deneniyor: %s", model)
        try:
            response = self.session.post(
                OPENROUTER_API_URL,
                json=payload,
                timeout=30,
            )
        except requests.exceptions.Timeout:
            logger.warning("%s zaman aşımı (timeout).", model)
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error("%s bağlantı hatası: %s", model, e)
            return None

        if response.status_code != 200:
            logger.error("%s HTTP %d: %s", model, response.status_code, response.text)
            return None

        result = response.json()
        if "error" in result:
            logger.error("%s API hatası: %s", model, result["error"])
            return None

        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            return None

        return content

    def analyze_text(self, text_input):
        """
        Metin bazlı yemekleri analiz eder.
        """
        if not text_input or not text_input.strip():
            return {"hata": "Metin verisi boş."}

        # Rate limiting kontrolü
        if not self.rate_limiter.allow():
            return {"hata": "Çok fazla istek gönderildi. Lütfen 1 dakika bekleyin."}

        start_time = time.time()
        
        raw_content = None
        used_model = None
        for model in VISION_MODELS:
            try:
                raw_content = self._call_text_model(model, text_input)
                if raw_content:
                    used_model = model
                    break
            except Exception as e:
                logger.error("%s hatası: %s", model, e)
                continue

        elapsed = round(time.time() - start_time, 1)

        if not raw_content:
            return {"hata": "Hiçbir model metni analiz edemedi."}

        # Yanıtı parse et
        parsed = self._parse_response(raw_content)
        if not parsed:
            return {"hata": "Model yanıtı işlenemedi. Lütfen formatı kontrol edin."}

        if "hata" in parsed:
            return parsed

        # USDA ile zenginleştir
        parsed = self._enrich_with_usda(parsed)

        parsed["kullanilan_model"] = used_model
        parsed["analiz_suresi_sn"] = elapsed

        logger.info("Metin analizi tamamlandı: %.1f saniye, model: %s", elapsed, used_model)
        return parsed

    def extract_barcode(self, image_bytes):
        """
        Bir görseldeki barkod numarasını yapay zekaya okutur.
        Sadece barkod numarasını (string) veya bulunamadıysa None döner.
        """
        if not image_bytes or len(image_bytes) == 0:
            return None

        # Rate limiting kontrolü
        if not self.rate_limiter.allow():
            return None

        start_time = time.time()
        compressed_image = self._compress_image(image_bytes)
        base64_image = self._encode_image(compressed_image)
        mime_type = "image/jpeg"

        model = VISION_MODELS[0]

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": BARCODE_SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Bu görseldeki barkod numarasını oku:"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 50,
            "temperature": 0.1,
        }

        logger.info("Yapay zeka barkod tespiti başlatıldı. Model: %s", model)
        try:
            response = self.session.post(
                OPENROUTER_API_URL,
                json=payload,
                timeout=20,
            )
        except requests.exceptions.RequestException as e:
            logger.error("Barkod extraction API hatası: %s", e)
            return None

        if response.status_code != 200:
            logger.error("Barkod extraction HTTP %d: %s", response.status_code, response.text)
            return None

        result = response.json()
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            return None

        content = content.strip().upper()
        elapsed = round(time.time() - start_time, 1)

        if content == "YOK" or "YOK" in content or len(content) < 3:
            logger.info("Yapay zeka barkod bulamadı. (Süre: %.1fs)", elapsed)
            return None

        # Sadece rakamları ayıkla
        numbers = re.sub(r'\D', '', content)
        if len(numbers) >= 8: # Geçerli bir EAN okuduysa
            logger.info("Yapay zeka barkodu başarıyla okudu: %s (Süre: %.1fs)", numbers, elapsed)
            return numbers
            
        logger.info("Okunan veri barkoda benzemiyor: %s (Süre: %.1fs)", content, elapsed)
        return None
