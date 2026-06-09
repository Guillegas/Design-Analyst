from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


# Perfiles de piel: heurísticos, NO validados por profesional (ver brief §6).
# hex representativo + s (cuánto influye la piel, 0..1).
SKIN_PROFILES: dict[str, dict] = {
    "very_light": {"hex": "#F5D9C4", "s": 0.05},
    "light":      {"hex": "#E8B89B", "s": 0.10},
    "medium":     {"hex": "#C68642", "s": 0.18},
    "tan":        {"hex": "#8D5524", "s": 0.26},
    "dark":       {"hex": "#5A3825", "s": 0.35},
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str
    supabase_service_role_key: str
    supabase_storage_bucket: str = "designs"
    worker_secret: str

    # Parámetros del pipeline de paleta (afinables sin tocar lógica).
    kmeans_k: int = 6
    near_white_threshold: int = 240
    alpha_threshold: int = 16
    min_cluster_weight: float = 0.03
    merge_delta_e: float = 5.0
    dominant_weight: float = 0.20
    resize_max_side: int = 200


@lru_cache
def get_settings() -> Settings:
    return Settings()
