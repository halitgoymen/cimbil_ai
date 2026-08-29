"""
USDA FoodData Central SR Legacy veritabanı modülü.
JSON dosyasını yükler, cache'ler ve besin arama/çapraz doğrulama fonksiyonları sağlar.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

# Nutrient ID'leri (USDA standardı)
NUTRIENT_IDS = {
    "energy_kcal": 1008,   # Energy (kcal)
    "protein": 1003,       # Protein (g)
    "fat": 1004,           # Total lipid / fat (g)
    "carbs": 1005,         # Carbohydrate, by difference (g)
}

CACHE_FILENAME = "nutrition_cache.json"


class NutritionDB:
    """USDA FoodData Central SR Legacy veritabanı (cache destekli)."""

    def __init__(self, json_path=None):
        if json_path is None:
            json_path = os.path.join(
                os.path.dirname(__file__),
                "FoodData_Central_sr_legacy_food_json_2018-04.json"
            )
        self.json_path = json_path
        self.foods = []
        self._index = {}  # inverted index: kelime → [food index'leri]
        self._cache_path = os.path.join(os.path.dirname(json_path), CACHE_FILENAME)
        self._is_loaded = False

    def _ensure_loaded(self):
        """Veritabanını ilk istekte belleğe yükler (Lazy Load)."""
        if not self._is_loaded:
            logger.info("USDA Veritabanı belleğe alınıyor (Lazy Load)...")
            if not self._load_cache():
                self._load_raw(self.json_path)
                self._save_cache()
            self._build_index()
            self._is_loaded = True


    def _load_cache(self):
        """Cache dosyasından yüklemeyi dener."""
        if not os.path.exists(self._cache_path):
            return False

        try:
            logger.info("Cache'den yükleniyor: %s", self._cache_path)
            with open(self._cache_path, "r", encoding="utf-8") as f:
                self.foods = json.load(f)
            logger.info("Cache'den %d besin öğesi yüklendi.", len(self.foods))
            return True
        except Exception as e:
            logger.warning("Cache okunamadı: %s", e)
            return False

    def _save_cache(self):
        """İşlenmiş verileri cache dosyasına kaydeder."""
        try:
            with open(self._cache_path, "w", encoding="utf-8") as f:
                json.dump(self.foods, f, ensure_ascii=False)
            size_mb = os.path.getsize(self._cache_path) / (1024 * 1024)
            logger.info("Cache kaydedildi: %s (%.1f MB)", self._cache_path, size_mb)
        except Exception as e:
            logger.warning("Cache kaydedilemedi: %s", e)

    def _load_raw(self, path):
        """Orijinal USDA JSON dosyasını yükleyip hafif bir liste oluşturur."""
        logger.info("USDA veritabanı yükleniyor: %s", path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            raw_foods = data.get("SRLegacyFoods", [])
            for item in raw_foods:
                nutrients = {}
                for fn in item.get("foodNutrients", []):
                    nid = fn.get("nutrient", {}).get("id")
                    amount = fn.get("amount", 0)
                    if nid == NUTRIENT_IDS["energy_kcal"]:
                        nutrients["energy_kcal"] = amount
                    elif nid == NUTRIENT_IDS["protein"]:
                        nutrients["protein"] = amount
                    elif nid == NUTRIENT_IDS["fat"]:
                        nutrients["fat"] = amount
                    elif nid == NUTRIENT_IDS["carbs"]:
                        nutrients["carbs"] = amount

                # Porsiyon bilgisi
                portions = item.get("foodPortions", [])
                gram_weight = None
                portion_desc = None
                if portions:
                    gram_weight = portions[0].get("gramWeight")
                    portion_desc = portions[0].get("modifier", "serving")

                self.foods.append({
                    "description": item.get("description", "").lower(),
                    "category": item.get("foodCategory", {}).get("description", ""),
                    "energy_kcal": nutrients.get("energy_kcal", 0),
                    "protein": nutrients.get("protein", 0),
                    "fat": nutrients.get("fat", 0),
                    "carbs": nutrients.get("carbs", 0),
                    "portion_gram": gram_weight,
                    "portion_desc": portion_desc,
                })

            logger.info("USDA'dan %d besin öğesi yüklendi.", len(self.foods))
        except FileNotFoundError:
            logger.warning("Veritabanı dosyası bulunamadı: %s", path)
            self.foods = []
        except Exception as e:
            logger.error("Veritabanı yüklenemedi: %s", e)
            self.foods = []

    def _build_index(self):
        """Hızlı arama için inverted index oluşturur."""
        self._index = {}
        for i, food in enumerate(self.foods):
            words = food["description"].split()
            for word in words:
                if word not in self._index:
                    self._index[word] = []
                self._index[word].append(i)
        logger.info("Inverted index oluşturuldu: %d benzersiz kelime.", len(self._index))

    def search(self, query, limit=5):
        """
        Verilen sorguya en uygun besinleri döndürür.
        Inverted index ile hızlı arama yapar.
        """
        self._ensure_loaded()
        query_lower = query.lower().strip()
        query_words = query_lower.split()

        if not query_words:
            return []

        # İlk kelimenin indexinden aday setini al
        candidates = set()
        for word in query_words:
            if word in self._index:
                if not candidates:
                    candidates = set(self._index[word])
                else:
                    # Tüm kelimeleri içerenleri bul (intersection)
                    candidates &= set(self._index[word])

        if not candidates:
            # Intersection boşsa, union dene (en az 1 kelime eşleşen)
            for word in query_words:
                if word in self._index:
                    candidates.update(self._index[word])

        scored = []
        for idx in candidates:
            food = self.foods[idx]
            desc = food["description"]
            match_count = sum(1 for w in query_words if w in desc)
            exact_bonus = 10 if query_lower == desc else 0
            brevity_bonus = max(0, 5 - len(desc.split()) // 10)
            score = match_count * 10 + exact_bonus + brevity_bonus
            scored.append((score, food))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    def get_nutrition_per_100g(self, query):
        """
        Verilen besin adı için 100g başına besin değerlerini döndürür.
        USDA verileri zaten 100g başınadır.
        """
        results = self.search(query, limit=1)
        if results:
            r = results[0]
            return {
                "description": r["description"],
                "energy_kcal_per_100g": r["energy_kcal"],
                "protein_per_100g": r["protein"],
                "fat_per_100g": r["fat"],
                "carbs_per_100g": r["carbs"],
                "portion_gram": r["portion_gram"],
                "portion_desc": r["portion_desc"],
            }
        return None
