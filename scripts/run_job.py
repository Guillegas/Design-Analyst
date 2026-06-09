"""CLI: procesa un job_id real contra el Supabase configurado en .env.
Uso: python scripts/run_job.py <job_id>"""
import logging
import sys

from app.config import get_settings
from app.pipeline.runner import process_job


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) != 2:
        print("uso: python scripts/run_job.py <job_id>")
        raise SystemExit(2)
    job_id = sys.argv[1]
    process_job(job_id, get_settings())
    print(f"hecho. revisa analysis_jobs.status del job {job_id}")


if __name__ == "__main__":
    main()
