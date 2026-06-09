-- Pipeline v2: resumen del match por color + candidatas rankeadas
alter table public.extracted_colors
  add column if not exists best_delta_e numeric,
  add column if not exists match_quality text,
  add column if not exists needs_mix boolean default false;

alter table public.match_results
  add column if not exists rank integer;
