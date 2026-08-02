"""Capa de I/O contra Supabase: leer job + joins, descargar imagen, escribir
resultados. Usa la service_role key (salta RLS). Sin lógica de pipeline."""
from __future__ import annotations

from supabase import Client, create_client

from app.config import Settings
from app.pipeline.matching import Ink


def make_client(s: Settings) -> Client:
    return create_client(s.supabase_url, s.supabase_service_role_key)


def fetch_job(client: Client, job_id: str) -> dict:
    rows = client.table("analysis_jobs").select("*").eq("id", job_id).execute().data
    if not rows:
        raise ValueError(f"job {job_id} no existe")
    return rows[0]


def fetch_storage_path(client: Client, design_upload_id: str) -> str:
    rows = (
        client.table("design_uploads")
        .select("storage_path,format")
        .eq("id", design_upload_id)
        .execute()
        .data
    )
    if not rows:
        raise ValueError(f"design_upload {design_upload_id} no existe")
    return rows[0]["storage_path"]


def fetch_skin_profile_name(client: Client, project_id: str) -> str | None:
    proj = (
        client.table("projects")
        .select("skin_tone_profile_id")
        .eq("id", project_id)
        .execute()
        .data
    )
    if not proj or not proj[0].get("skin_tone_profile_id"):
        return None
    stp_id = proj[0]["skin_tone_profile_id"]
    stp = (
        client.table("skin_tone_profiles")
        .select("name")
        .eq("id", stp_id)
        .execute()
        .data
    )
    return stp[0]["name"] if stp else None


def fetch_eligible_inks(client: Client, job: dict) -> list[Ink]:
    """Candidatas del job: botes del catálogo y, en modo `my_inks`, también las
    mezclas propias del tatuador. Las dos van en la misma lista y compiten en la
    misma comparación de ΔE."""
    source = job["analysis_source"]
    if source == "brands":
        ids = job.get("selected_brand_ids") or []
        if not ids:
            return []
        return _fetch_inks(client, "brand_id", ids)
    if source == "my_inks":
        ink_ids = job.get("selected_ink_ids") or []
        mix_ids = job.get("selected_mix_ids") or []
        if not ink_ids and not mix_ids:
            return []
        inks = _fetch_inks(client, "id", ink_ids) if ink_ids else []
        return inks + (_fetch_user_mixes(client, mix_ids) if mix_ids else [])
    raise ValueError(f"analysis_source desconocido: {source}")


def _fetch_inks(client: Client, column: str, ids: list[str]) -> list[Ink]:
    rows = (
        client.table("inks")
        .select("id,lab_reference")
        .in_(column, ids)
        .execute()
        .data
    )
    inks = []
    for r in rows:
        lab = r["lab_reference"]
        inks.append(Ink(id=r["id"], lab=(lab["l"], lab["a"], lab["b"])))
    return inks


def _fetch_user_mixes(client: Client, mix_ids: list[str]) -> list[Ink]:
    """Mezclas propias como candidatas. `result_lab` viene ya calculado por la
    app con la conversión canónica: se lee tal cual, igual que `lab_reference`,
    sin recalcular nada ni predecir mezclas aquí."""
    rows = (
        client.table("user_ink_mixes")
        .select("id,result_lab")
        .in_("id", mix_ids)
        .execute()
        .data
    )
    mixes = []
    for r in rows:
        lab = r["result_lab"]
        mixes.append(
            Ink(id=r["id"], lab=(lab["l"], lab["a"], lab["b"]), is_user_mix=True)
        )
    return mixes


def download_image_bytes(client: Client, bucket: str, storage_path: str) -> bytes:
    return client.storage.from_(bucket).download(storage_path)


def set_status(client: Client, job_id: str, status: str, **extra) -> None:
    client.table("analysis_jobs").update({"status": status, **extra}).eq(
        "id", job_id
    ).execute()


def clear_previous_results(client: Client, job_id: str) -> None:
    # match_results primero (FK -> extracted_colors), luego extracted_colors
    client.table("match_results").delete().eq("analysis_job_id", job_id).execute()
    client.table("extracted_colors").delete().eq("analysis_job_id", job_id).execute()


def insert_extracted_color(client: Client, job_id: str, color: dict, match) -> str:
    row = {
        "analysis_job_id": job_id,
        "hex": color["hex"],
        "rgb": color["rgb"],
        "lab": color["lab"],
        "weight": color["weight"],
        "role": color["role"],
        "best_delta_e": match.best_delta_e,
        "match_quality": match.match_quality,
        "needs_mix": match.needs_mix,
    }
    res = client.table("extracted_colors").insert(row).execute().data
    return res[0]["id"]


def insert_match_candidates(
    client: Client, job_id: str, extracted_color_id: str, candidates
) -> None:
    # `match_results_type_coherence` es estricto: exactamente una de las tres
    # columnas de referencia va rellena, coherente con `match_type`. `ink_mix_id`
    # (mezclas curadas del catálogo) sigue sin usarse.
    rows = [{
        "analysis_job_id": job_id,
        "extracted_color_id": extracted_color_id,
        "match_type": "user_mix" if cand.is_user_mix else "direct_ink",
        "ink_id": None if cand.is_user_mix else cand.ink_id,
        "ink_mix_id": None,
        "user_ink_mix_id": cand.ink_id if cand.is_user_mix else None,
        "delta_e": cand.delta_e,
        "rank": cand.rank,
    } for cand in candidates]
    client.table("match_results").insert(rows).execute()
