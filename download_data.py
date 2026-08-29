"""
Gymble Data Downloader
Container startup'ta Google Drive'dan veri dosyalarını indirir.
Dosyalar zaten varsa tekrar indirmez.
"""

import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [DOWNLOADER] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", "1BE1Z91MgrFXGpYg0V6BAbSzJayUsV72w")

# Hedef dizinler
GYMBLE_API_DIR = "/app/gymble_api"
CHATBOT_DATASETS_DIR = "/app/Chatbotv2/Datasets"

USDA_FILE = os.path.join(GYMBLE_API_DIR, "FoodData_Central_sr_legacy_food_json_2018-04.json")
MARKER_FILE = "/app/.data_downloaded"


def data_exists():
    """Veri dosyaları zaten indirilmiş mi kontrol eder."""
    if os.path.exists(MARKER_FILE):
        return True
    # USDA dosyası ve en az bir dataset dosyası varsa
    if os.path.exists(USDA_FILE) and os.path.isdir(CHATBOT_DATASETS_DIR):
        datasets_files = os.listdir(CHATBOT_DATASETS_DIR)
        if len(datasets_files) > 0:
            return True
    return False


def download_from_gdrive():
    """Google Drive klasöründen tüm dosyaları indirir."""
    try:
        import gdown
    except ImportError:
        logger.error("gdown yüklü değil! 'pip install gdown' çalıştırın.")
        return False

    logger.info("Google Drive'dan veri indiriliyor (Folder ID: %s)...", GDRIVE_FOLDER_ID)

    # Geçici dizine indir
    temp_dir = "/tmp/gdrive_data"
    os.makedirs(temp_dir, exist_ok=True)

    try:
        url = f"https://drive.google.com/drive/folders/{GDRIVE_FOLDER_ID}"
        gdown.download_folder(url, output=temp_dir, quiet=False)

        # İndirilen dosyaları doğru yerlere taşı
        _distribute_files(temp_dir)

        # Başarı marker'ı oluştur
        with open(MARKER_FILE, "w") as f:
            f.write("ok")

        logger.info("Veri indirme tamamlandı!")
        return True

    except Exception as e:
        logger.error("İndirme hatası: %s", e)
        return False


def _distribute_files(temp_dir):
    """İndirilen dosyaları doğru dizinlere dağıtır."""
    import shutil

    for root, dirs, files in os.walk(temp_dir):
        for fname in files:
            src = os.path.join(root, fname)

            # USDA JSON → gymble_api/
            if fname == "FoodData_Central_sr_legacy_food_json_2018-04.json" and "Datasets" not in root:
                dst = USDA_FILE
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                logger.info("  → %s", dst)
                shutil.move(src, dst)

            # Datasets/ altındaki her şey → Chatbotv2/Datasets/
            elif "Datasets" in root or fname.endswith(".json"):
                # Orijinal alt dizin yapısını koru
                rel = os.path.relpath(src, temp_dir)
                # "Datasets/" prefix'i varsa direkt kullan, yoksa Datasets/ altına koy
                if rel.startswith("Datasets"):
                    dst = os.path.join("/app/Chatbotv2", rel)
                else:
                    dst = os.path.join(CHATBOT_DATASETS_DIR, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                logger.info("  → %s", dst)
                shutil.move(src, dst)

    # Temp dizini temizle
    shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    if data_exists():
        logger.info("Veri dosyaları zaten mevcut, indirme atlanıyor.")
        sys.exit(0)

    success = download_from_gdrive()
    if not success:
        logger.warning("Veri indirilemedi! Servisler veri olmadan başlayacak.")
        sys.exit(1)
