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

    # --- Pipeline v2 (afinables sin tocar lógica) ---
    # Extracción
    resize_max_side: int = 512        # lado largo máx para clustering
    kmeans_k_high: int = 60           # nº de grupos finos antes de fusionar
    merge_delta_e: float = 3.0        # resolución perceptual: ΔE bajo el que se fusionan colores
    min_cluster_weight: float = 0.005 # descarta clusters con menos peso (0.5%)
    max_colors: int = 50              # tope de seguridad de colores extraídos
    dominant_weight: float = 0.15     # weight >= esto => role 'dominant'
    alpha_threshold: int = 16         # alpha < esto => píxel transparente, descartar
    # Fondo
    bg_border_fraction: float = 0.5   # fracción de borde uniforme para considerarlo fondo
    bg_merge_delta_e: float = 4.0     # ΔE para borrar píxeles del color de fondo
    near_white_threshold: int = 250   # fallback: blanco si los 3 canales > esto
    # Matching
    candidates_n: int = 5             # nº de tintas candidatas por color
    quality_excellent: float = 2.0    # ΔE <= esto => 'excellent'
    quality_good: float = 5.0         # ΔE <= esto => 'good'
    quality_fair: float = 10.0        # ΔE <= esto => 'fair'; mayor => 'poor' + needs_mix


@lru_cache
def get_settings() -> Settings:
    return Settings()
