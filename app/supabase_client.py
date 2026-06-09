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
    source = job["analysis_source"]
    q = client.table("inks").select("id,lab_reference")
    if source == "brands":
        ids = job.get("selected_brand_ids") or []
        if not ids:
            return []
        q = q.in_("brand_id", ids)
    elif source == "my_inks":
        ids = job.get("selected_ink_ids") or []
        if not ids:
            return []
        q = q.in_("id", ids)
    else:
        raise ValueError(f"analysis_source desconocido: {source}")
    rows = q.execute().data
    inks = []
    for r in rows:
        lab = r["lab_reference"]
        inks.append(Ink(id=r["id"], lab=(lab["l"], lab["a"], lab["b"])))
    return inks


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
    rows = [{
        "analysis_job_id": job_id,
        "extracted_color_id": extracted_color_id,
        "match_type": "direct_ink",
        "ink_id": cand.ink_id,
        "ink_mix_id": None,
        "delta_e": cand.delta_e,
        "rank": cand.rank,
    } for cand in candidates]
    client.table("match_results").insert(rows).execute()
