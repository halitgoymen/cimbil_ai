"""
Gymble User Profile Service
API Gateway'den kullanıcı profil bilgilerini çeker.

API Gateway User Schema:
{
  "username": "ahmetyilmaz",
  "age": 28, "height": 178, "weight": 75,
  "targetWeight": 70, "gender": "male",
  "goal": "lose_weight", "activityLevel": "moderate",
  "dietaryPreference": "omnivore",
  "allergies": ["gluten"], "healthConditions": []
}
"""

import os
import logging
import httpx

logger = logging.getLogger(__name__)

API_GATEWAY_URL = os.getenv("API_GATEWAY_URL", "http://api-gateway-production-fd99.up.railway.app")

# Profil cache (aynı user_id için tekrar istek atmamak için)
_profile_cache: dict[str, dict] = {}

GOAL_MAP = {
    "lose_weight": "Kilo Vermek",
    "gain_weight": "Kilo Almak",
    "maintain": "Kiloyu Korumak",
    "build_muscle": "Kas Yapmak",
}

ACTIVITY_MAP = {
    "sedentary": "Hareketsiz",
    "light": "Hafif Aktif",
    "moderate": "Orta Aktif",
    "active": "Aktif",
    "very_active": "Çok Aktif",
}

DIET_MAP = {
    "omnivore": "Her şey",
    "vegetarian": "Vejetaryen",
    "vegan": "Vegan",
    "pescatarian": "Pesketaryen",
    "keto": "Ketojenik",
    "paleo": "Paleo",
}


async def fetch_user_profile(user_id: str, token: str | None = None) -> dict | None:
    """
    API Gateway'den kullanıcı profil bilgilerini çeker.

    Args:
        user_id: Kullanıcı UUID
        token: JWT veya auth token (varsa)

    Returns:
        dict: Kullanıcı profil bilgileri veya None
    """
    if not user_id:
        return None

    # Cache kontrol
    if user_id in _profile_cache:
        logger.debug("Profil cache'den alındı: %s", user_id)
        return _profile_cache[user_id]

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{API_GATEWAY_URL}/api/users/{user_id}",
                headers=headers,
            )

            if response.status_code != 200:
                logger.warning(
                    "Profil alınamadı (user_id=%s, status=%d)",
                    user_id, response.status_code
                )
                return None

            data = response.json()
            profile = _extract_profile(data)

            # Cache'e kaydet
            _profile_cache[user_id] = profile
            logger.info("Profil alındı: user_id=%s", user_id)
            return profile

    except Exception as e:
        logger.error("Profil çekme hatası (user_id=%s): %s", user_id, e)
        return None


def _extract_profile(data: dict) -> dict:
    """API yanıtından chatbot için kullanılacak profil bilgilerini çıkarır."""
    profile = {}

    if data.get("username"):
        profile["Kullanıcı"] = data["username"]
    if data.get("age"):
        profile["Yaş"] = data["age"]
    if data.get("gender"):
        profile["Cinsiyet"] = "Erkek" if data["gender"] == "male" else "Kadın"
    if data.get("height"):
        profile["Boy"] = f"{data['height']} cm"
    if data.get("weight"):
        profile["Kilo"] = f"{data['weight']} kg"
    if data.get("targetWeight"):
        profile["Hedef_Kilo"] = f"{data['targetWeight']} kg"
    if data.get("goal"):
        profile["Hedef"] = GOAL_MAP.get(data["goal"], data["goal"])
    if data.get("activityLevel"):
        profile["Aktivite"] = ACTIVITY_MAP.get(data["activityLevel"], data["activityLevel"])
    if data.get("dietaryPreference"):
        profile["Beslenme_Tercihi"] = DIET_MAP.get(data["dietaryPreference"], data["dietaryPreference"])

    # Alerjiler
    allergies = data.get("allergies") or []
    if isinstance(allergies, list) and allergies:
        profile["Alerji"] = ", ".join(str(a) for a in allergies)

    # Sağlık durumları
    conditions = data.get("healthConditions") or []
    if isinstance(conditions, list) and conditions:
        profile["Sağlık_Durumları"] = ", ".join(str(c) for c in conditions)

    return profile


def clear_cache(user_id: str | None = None):
    """Profil cache'ini temizler."""
    if user_id:
        _profile_cache.pop(user_id, None)
    else:
        _profile_cache.clear()
