import json
import os
import logging

logger = logging.getLogger(__name__)

# Base path for datasets (Adjust based on Docker vs Local)
DATASETS_DIR = "/app/Datasets" if os.path.exists("/app/Datasets") else os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "Datasets")

def load_volume_conversions() -> list[dict]:
    filepath = os.path.join(DATASETS_DIR, "ingredient_volume_to_gram_conversions.json")
    if not os.path.exists(filepath):
        logger.warning(f"File not found: {filepath}")
        return []

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("ingredients", [])
    chunks = []
    conversion_labels = {
        "turkish_glass_gram": "1 su bardağı",
        "turkish_tea_glass_gram": "1 çay bardağı",
        "tablespoon_gram": "1 yemek kaşığı",
        "dessert_spoon_gram": "1 tatlı kaşığı",
        "teaspoon_gram": "1 çay kaşığı",
        "cup_gram": "1 cup (US)",
    }

    for item in items:
        name_en = item.get("name", "")
        name_tr = item.get("name_tr", "")
        conversions = item.get("conversions", {})
        conv_lines = [f"- {label}: {conversions.get(key)} g" for key, label in conversion_labels.items() if conversions.get(key) is not None]
        text = f"Ölçü Dönüşümü - Malzeme: {name_tr} ({name_en})\n"
        text += f"Bir su bardağı {name_tr} kaç gram? Ölçü birim dönüşümleri:\n" + "\n".join(conv_lines)
        chunks.append({"id": f"conv_{name_en}".replace(" ", "_").lower(), "text": text, "metadata": {"source": "volume_conversions", "name_tr": name_tr, "name_en": name_en}})
    return chunks

def load_knowledge_base(filename: str, source_name: str) -> list[dict]:
    filepath = os.path.join(DATASETS_DIR, "Nutritions", filename)
    if not os.path.exists(filepath):
        logger.warning(f"File not found: {filepath}")
        return []

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    chunks = []
    for i, item in enumerate(data):
        topic = item.get("topic", "")
        category = item.get("category", "")
        content = item.get("content", "")
        # Improved formatting for semantic search
        text = f"Konu/Tarif: {topic}\nKategori: {category}\n\nDetaylar:\n{content}"
        chunks.append({
            "id": f"{source_name}_{filename.split('.')[0]}_{i}", 
            "text": text, 
            "metadata": {"source": source_name, "topic": topic, "category": category}
        })
    return chunks

def load_dietitian_recipes(max_recipes: int = 2000) -> list[dict]: # Reduced further for speed
    filepath = os.path.join(DATASETS_DIR, "Recipes", "dietitian_recipes_clean.json")
    if not os.path.exists(filepath):
        return []

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    chunks = []
    for i, recipe in enumerate(data[:max_recipes]):
        name = recipe.get("name", "Unknown")
        ing = ", ".join(recipe.get("ingredients", []))[:300]
        steps = " ".join(recipe.get("steps", []))[:500]
        nut = recipe.get("nutrition", {})
        text = f"Tarif Adı: {name}\nMalzemeler: {ing}\nYapılışı: {steps}\nBesin Değerleri: {nut.get('calories_kcal')} kcal"
        chunks.append({"id": f"recipe_{i}", "text": text, "metadata": {"source": "recipes", "name": name}})
    return chunks

def load_all_datasets() -> list[dict]:
    all_chunks = []
    all_chunks.extend(load_volume_conversions())
    all_chunks.extend(load_knowledge_base("knowledge_base.json", "kb"))
    all_chunks.extend(load_knowledge_base("sivrihisar_recipes_kb.json", "kb"))
    all_chunks.extend(load_knowledge_base("turkish_recipes_kb.json", "kb"))
    all_chunks.extend(load_knowledge_base("tuber_knowledge_base.json", "kb"))
    all_chunks.extend(load_dietitian_recipes(2000))
    logger.info(f"Loaded {len(all_chunks)} chunks for indexing")
    return all_chunks
