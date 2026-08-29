"""
OpenFoodFacts API üzerinden barkod ile ürün analizi modülü.
"""

import logging
import requests

logger = logging.getLogger(__name__)

OPENFOODFACTS_API_URL = "https://world.openfoodfacts.org/api/v2/product/{}"

class BarcodeAnalyzer:
    """Yemek barkodu analiz sınıfı."""

    def __init__(self):
        # İstekler için varsayılan bir User-Agent belirtmek iyi bir pratiktir
        self.headers = {
            "User-Agent": "GymbleApp/1.0 (info@gymble.app)",
            "Accept": "application/json"
        }

    def analyze(self, barcode: str):
        """
        Barkod numarasını OpenFoodFacts üzerinden analiz eder.

        Args:
            barcode: Ürünün barkod numarası (EAN-13, vs.)

        Returns:
            dict: Analiz sonucu JSON (Gemini çıktısına benzer formatta)
        """
        if not barcode:
            return {"hata": "Barkod numarası boş olamaz."}

        url = OPENFOODFACTS_API_URL.format(barcode)

        try:
            logger.info("Barkod sorgulanıyor: %s", barcode)
            response = requests.get(url, headers=self.headers, timeout=10)
            
            # OpenFoodFacts v2 returns 404 when product not found
            if response.status_code == 404:
                return {"hata": "Ürün bulunamadı veya barkod geçersiz."}
                
            response.raise_for_status()
            data = response.json()
            
            # v0 check backup
            if data.get('status') == 0:
                return {"hata": "Ürün bulunamadı veya barkod geçersiz."}
                
            product = data.get('product', {})
            nutriments = product.get('nutriments', {})
            
            # Ürün bilgileri
            product_name = product.get('product_name', 'Bilinmeyen Ürün')
            ingredients = product.get('ingredients_text', 'İçerik bilgisi bulunamadı.')
            
            # Besin değerleri (100g üzerinden)
            # Energy genelde kcal, protein/fat/carbohydrates gram cinsindendir
            kcal = nutriments.get('energy-kcal_100g', 0)
            if not kcal and nutriments.get('energy_100g'):
                # Sadece kJ varsa yaklaşık çevir
                kcal = round(nutriments.get('energy_100g') / 4.184)
                
            protein = nutriments.get('proteins_100g', 0)
            carbs = nutriments.get('carbohydrates_100g', 0)
            fat = nutriments.get('fat_100g', 0)

            # Gemini çıktı formatına uyarlama
            result = {
                "analiz": {
                    "referans_dogrulama": "Barkod taraması (OpenFoodFacts), 100g değerleri.",
                    "toplam_kalori": round(float(kcal)) if kcal else 0,
                    "toplam_makro": {
                        "protein": round(float(protein), 1) if protein else 0,
                        "karbonhidrat": round(float(carbs), 1) if carbs else 0,
                        "yag": round(float(fat), 1) if fat else 0
                    }
                },
                "besinler": [
                    {
                        "isim": product_name,
                        "icerik": ingredients,
                        "tahmini_hacim_cm3": 0,  # Barkodda hacim bilinemez
                        "hesaplanan_gram": 100,  # API standart olarak 100g döndürüyor
                        "kalori": round(float(kcal)) if kcal else 0,
                        "besin_notu": f"100g için değerler. Barkod: {barcode}"
                    }
                ]
            }
            
            logger.info("Barkod analizi başarılı: %s", product_name)
            return result

        except requests.exceptions.Timeout:
            logger.warning("Barkod sorgusu zaman aşımına uğradı: %s", barcode)
            return {"hata": "Barkod servisi zaman aşımına uğradı."}
        except requests.exceptions.RequestException as e:
            logger.error("Barkod sorgu hatası (%s): %s", barcode, e)
            return {"hata": "Barkod servisine ulaşılamadı."}
        except Exception as e:
            logger.exception("Beklenmeyen barkod hatası (%s): %s", barcode, e)
            return {"hata": "Sunucu hatası oluştu. Lütfen tekrar deneyin."}
