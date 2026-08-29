"""
Gymble API - Görsel Besin Analiz Servisi
Flask tabanlı REST API. Yemek fotoğraflarını analiz ederek
kalori ve makro besin değerlerini döndürür.
"""

import logging
import os
import time
from datetime import date
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# .env dosyasını yükle
load_dotenv()

# Logging konfigürasyonu
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gymble")

try:
    from nutrition_db import NutritionDB
    from food_analyzer import FoodAnalyzer
    from barcode_analyzer import BarcodeAnalyzer
except ImportError:
    from gymble_api.nutrition_db import NutritionDB
    from gymble_api.food_analyzer import FoodAnalyzer
    from gymble_api.barcode_analyzer import BarcodeAnalyzer

# Flask uygulaması
app = Flask(__name__)
# Nginx kaldırıldığı için CORS direkt uygulamada geniş yetkilerle yapılandırıldı
CORS(app, resources={r"/*": {"origins": "*"}})

# Veritabanı ve analizör başlat
logger.info("Başlatılıyor (Veritabanı yükleniyor)...")
nutrition_db = NutritionDB()
nutrition_db._ensure_loaded()  # Belleğe hemen al (Eager load)
analyzer = FoodAnalyzer(nutrition_db=nutrition_db)
barcode_analyzer = BarcodeAnalyzer()
logger.info("Hazır! Veritabanı yüklendi.")

# Maksimum dosya boyutu: 10 MB
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

# İzin verilen uzantılar
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}


def allowed_file(filename):
    """Dosya uzantısının geçerli olup olmadığını kontrol eder."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def format_response(result, meal_type="other", source="manual"):
    """
    Analizör çıktısını standart formata dönüştürür.
    Dönen format: {foodName, calories, protein, carbs, fat, fiber, mealType, date, source}
    """
    if "hata" in result:
        return result

    # Besin adını al
    food_name = "Bilinmeyen"
    if "besinler" in result and result["besinler"]:
        names = [b.get("isim", "") for b in result["besinler"] if b.get("isim")]
        food_name = ", ".join(names) if names else "Bilinmeyen"

    # Makro değerler
    analiz = result.get("analiz", {})
    makro = analiz.get("toplam_makro", {})

    return {
        "foodName": food_name,
        "calories": analiz.get("toplam_kalori", 0),
        "protein": makro.get("protein", 0),
        "carbs": makro.get("karbonhidrat", 0),
        "fat": makro.get("yag", 0),
        "fiber": makro.get("lif", 0),
        "mealType": meal_type,
        "date": date.today().isoformat(),
        "source": source,
        "details": result.get("besinler", []),
    }



@app.route("/analyze", methods=["POST"])
def analyze():
    """
    Yemek fotoğrafını analiz eder.

    Request:
        POST /analyze
        Content-Type: multipart/form-data
        Body: image=<dosya>

    Response:
        JSON formatında besin analizi
    """
    req_start = time.time()
    client_ip = request.remote_addr

    # Dosya kontrolü
    if "image" not in request.files:
        return jsonify({
            "hata": "İstekte 'image' alanı bulunamadı. Lütfen bir yemek fotoğrafı yükleyin."
        }), 400

    file = request.files["image"]

    if file.filename == "":
        return jsonify({
            "hata": "Dosya seçilmedi. Lütfen bir yemek fotoğrafı seçin."
        }), 400

    if not allowed_file(file.filename):
        return jsonify({
            "hata": f"Desteklenmeyen dosya formatı. İzin verilen formatlar: {', '.join(ALLOWED_EXTENSIONS)}"
        }), 400

    meal_type = request.form.get("mealType", "other")

    try:
        image_bytes = file.read()
        file_size_kb = len(image_bytes) // 1024

        if len(image_bytes) == 0:
            return jsonify({
                "hata": "Yüklenen dosya boş."
            }), 400

        logger.info(
            "Analiz isteği: IP=%s, dosya=%s, boyut=%dKB",
            client_ip, file.filename, file_size_kb
        )

        # Analiz et
        result = analyzer.analyze(image_bytes)

        elapsed = round(time.time() - req_start, 1)
        logger.info("İstek tamamlandı: %s saniye (IP: %s)", elapsed, client_ip)

        # Hata varsa 422 döndür
        if "hata" in result:
            return jsonify(result), 422

        return jsonify(format_response(result, meal_type, "image")), 200

    except Exception as e:
        logger.exception("Analiz hatası: %s", e)
        return jsonify({
            "hata": "Sunucu hatası oluştu. Lütfen tekrar deneyin."
        }), 500


@app.route("/analyze/barcode", methods=["POST"])
def analyze_barcode():
    """
    Barkod numarasını OpenFoodFacts üzerinden analiz eder.

    Request:
        POST /analyze/barcode
        Content-Type: application/json
        Body: {"barcode": "1234567890123"}

    Response:
        JSON formatında besin analizi
    """
    req_start = time.time()
    client_ip = request.remote_addr

    # JSON kontrolü
    if not request.is_json:
        return jsonify({
            "hata": "İstek JSON formatında olmalıdır. 'Content-Type: application/json' başlığını kullanın."
        }), 400

    data = request.get_json()
    barcode = data.get("barcode")
    meal_type = data.get("mealType", "other")

    if not barcode:
        return jsonify({
            "hata": "İstekte 'barcode' alanı bulunamadı."
        }), 400

    barcode = str(barcode).strip()

    try:
        logger.info("Barkod analiz isteği: IP=%s, barcode=%s", client_ip, barcode)

        # Analiz et
        result = barcode_analyzer.analyze(barcode)

        elapsed = round(time.time() - req_start, 1)
        logger.info("Barkod isteği tamamlandı: %s saniye (IP: %s)", elapsed, client_ip)

        # Hata varsa 422 döndür
        if "hata" in result:
            return jsonify(result), 422

        return jsonify(format_response(result, meal_type, "barcode")), 200

    except Exception as e:
        logger.exception("Barkod analiz hatası: %s", e)
        return jsonify({
            "hata": "Sunucu hatası oluştu. Lütfen tekrar deneyin."
        }), 500


@app.route("/analyze/barcode_image", methods=["POST"])
def analyze_barcode_image():
    """
    Kullanıcının yüklediği barkod fotoğrafından yapay zeka ile barkodu okur
    ve okunan numarayı OpenFoodFacts ile analiz eder (Fallback).
    """
    req_start = time.time()
    client_ip = request.remote_addr

    # Dosya kontrolü
    if "image" not in request.files:
        return jsonify({
            "hata": "İstekte 'image' alanı bulunamadı. Lütfen bir barkod fotoğrafı yükleyin."
        }), 400

    file = request.files["image"]

    if file.filename == "":
        return jsonify({
            "hata": "Dosya seçilmedi. Lütfen bir barkod fotoğrafı seçin."
        }), 400

    if not allowed_file(file.filename):
        return jsonify({
            "hata": f"Desteklenmeyen dosya formatı. İzin verilen formatlar: {', '.join(ALLOWED_EXTENSIONS)}"
        }), 400

    meal_type = request.form.get("mealType", "other")

    try:
        image_bytes = file.read()
        if len(image_bytes) == 0:
            return jsonify({
                "hata": "Yüklenen dosya boş."
            }), 400

        logger.info(
            "Barkod Görseli İsteği: IP=%s, dosya=%s",
            client_ip, file.filename
        )

        # 1. Yapay zeka ile barkodu oku
        barcode = analyzer.extract_barcode(image_bytes)
        
        if not barcode:
            return jsonify({
                "hata": "Yapay zeka görselde herhangi bir barkod tespit edemedi. Lütfen daha net bir fotoğraf çekin."
            }), 422

        logger.info("Yapay Zeka Barkod Buldu: %s. OFF API çağrılıyor...", barcode)

        # 2. Barkod numarası ile besin analizi yap
        result = barcode_analyzer.analyze(barcode)

        elapsed = round(time.time() - req_start, 1)
        logger.info("Barkod Görsel İsteği tamamlandı: %s saniye", elapsed)

        # Hata varsa 422 döndür
        if "hata" in result:
            result["hata"] = f"Arama '{barcode}' için yapıldı: " + result["hata"]
            return jsonify(result), 422

        return jsonify(format_response(result, meal_type, "barcode_image")), 200

    except Exception as e:
        logger.exception("Barkod görsel analiz hatası: %s", e)
        return jsonify({
            "hata": "Sunucu hatası oluştu. Lütfen tekrar deneyin."
        }), 500


@app.route("/analyze/text", methods=["POST"])
def analyze_text():
    """
    Kullanıcının yazdığı metin üzerinden yemek veya porsiyonu analiz eder.

    Request:
        POST /analyze/text
        Content-Type: application/json
        Body: {"text": "1 porsiyon pilav ve ayran"}

    Response:
        JSON formatında besin analizi
    """
    req_start = time.time()
    client_ip = request.remote_addr

    # JSON kontrolü
    if not request.is_json:
        return jsonify({
            "hata": "İstek JSON formatında olmalıdır. 'Content-Type: application/json' başlığını kullanın."
        }), 400

    data = request.get_json()
    text_input = data.get("text")
    meal_type = data.get("mealType", "other")

    if not text_input:
        return jsonify({
            "hata": "İstekte 'text' alanı bulunamadı."
        }), 400

    text_input = str(text_input).strip()

    try:
        logger.info("Metin analiz isteği: IP=%s, text=%s", client_ip, text_input[:50])

        # Analiz et
        result = analyzer.analyze_text(text_input)

        elapsed = round(time.time() - req_start, 1)
        logger.info("Metin isteği tamamlandı: %s saniye (IP: %s)", elapsed, client_ip)

        # Hata varsa 422 döndür
        if "hata" in result:
            return jsonify(result), 422

        return jsonify(format_response(result, meal_type, "text")), 200

    except Exception as e:
        logger.exception("Metin analiz hatası: %s", e)
        return jsonify({
            "hata": "Sunucu hatası oluştu. Lütfen tekrar deneyin."
        }), 500


@app.route("/health", methods=["GET"])
def health():
    """Sağlık kontrolü endpoint'i."""
    is_loaded = getattr(nutrition_db, "_is_loaded", False)
    return jsonify({
        "status": "ok",
        "veritabani_yuklendi": is_loaded,
        "besin_sayisi": len(nutrition_db.foods) if is_loaded else 0,
    })


@app.errorhandler(413)
def too_large(e):
    """Dosya boyutu aşıldığında."""
    return jsonify({
        "hata": "Dosya boyutu çok büyük. Maksimum 10 MB yüklenebilir."
    }), 413


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    logger.info("http://localhost:%d adresinde çalışıyor...", port)
    app.run(host="0.0.0.0", port=port, debug=debug)
