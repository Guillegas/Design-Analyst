"""Orquesta un job (brief §4): estados pending->processing->completed/failed,
idempotencia (borra resultados previos), manejo de errores."""
import io
import logging
import traceback
from datetime import datetime, timezone

from PIL import Image

from app.config import SKIN_PROFILES, Settings
from app.pipeline.color import hex_to_rgb, rgb_to_lab
from app.pipeline.matching import best_match
from app.pipeline.palette import extract_palette
from app.pipeline.skin import precompensate
from app import supabase_client as sb

log = logging.getLogger("runner")


def process_job(job_id: str, settings: Settings) -> None:
    client = None
    try:
        client = sb.make_client(settings)
        job = sb.fetch_job(client, job_id)

        # evita doble ejecución (brief §4.1)
        if job["status"] != "pending":
            log.info("job %s ya está en estado %s; no se reprocesa", job_id, job["status"])
            return

        sb.set_status(client, job_id, "processing")

        storage_path = sb.fetch_storage_path(client, job["design_upload_id"])
        skin_name = sb.fetch_skin_profile_name(client, job["project_id"])
        inks = sb.fetch_eligible_inks(client, job)
        if not inks:
            raise ValueError("conjunto de tintas elegibles vacío")

        img_bytes = sb.download_image_bytes(client, settings.supabase_storage_bucket, storage_path)
        img = Image.open(io.BytesIO(img_bytes))

        colors = extract_palette(img, settings)
        if not colors:
            raise ValueError("no se extrajo ningún color del diseño")

        # parámetros de piel
        if skin_name and skin_name in SKIN_PROFILES:
            prof = SKIN_PROFILES[skin_name]
            skin_rgb = hex_to_rgb(prof["hex"])
            s = float(prof["s"])
        else:
            skin_rgb, s = (0, 0, 0), 0.0

        # idempotencia
        sb.clear_previous_results(client, job_id)

        for color in colors:
            ec_id = sb.insert_extracted_color(client, job_id, color)
            target_rgb = (color["rgb"]["r"], color["rgb"]["g"], color["rgb"]["b"])
            comp_rgb = precompensate(target_rgb, skin_rgb, s)
            comp_lab = rgb_to_lab(*comp_rgb)
            match = best_match(comp_lab, inks)
            sb.insert_match_result(client, job_id, ec_id, match.ink_id, match.delta_e)

        sb.set_status(
            client, job_id, "completed",
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        log.info("job %s completado (%d colores)", job_id, len(colors))

    except Exception as e:  # noqa: BLE001
        log.error("job %s falló: %s\n%s", job_id, e, traceback.format_exc())
        try:
            sb.set_status(client, job_id, "failed", error_message=str(e))
        except Exception:  # noqa: BLE001
            log.error("no se pudo marcar el job %s como failed", job_id)
