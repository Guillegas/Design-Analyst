# Spec: de-duplicación de tintas en el resultado del análisis

**Fecha:** 2026-06-20
**Estado:** aprobado para implementar

## Problema

El matching es **por color, independiente**: cada color extraído del diseño busca su
tinta más cercana (rank 1) sin saber qué tintas se han asignado a los demás colores.
Resultado: la lista final puede repetir tintas. Se observan dos casos:

1. **Misma tinta exacta** — dos colores parecidos del diseño (p. ej. dos negros) resuelven
   al mismo `ink_id`, que aparece dos veces.
2. **Tintas equivalentes de marcas distintas** — al elegir 2 marcas, sale el negro de la
   marca A y el negro de la marca B (`ink_id` distinto, ΔE casi 0) para lo que es el mismo
   color.

Requisito: la lista final **no puede repetir tinta** con ningún color. Cuando dos tintas
son muy parecidas o iguales (negros, blancos, etc.) se omite una y se conserva la del
color **más fuerte** (mayor peso).

## Solución: paso de consolidación post-matching

La de-duplicación es transversal: solo puede hacerse cuando todos los colores ya están
matcheados. Se añade un paso puro tras el matching, antes de insertar resultados.

### Función nueva — `app/pipeline/matching.py`

```
consolidate_by_ink(
    pairs: list[tuple[dict, ColorMatch]],
    inks: list[Ink],
    s: Settings,
) -> list[tuple[dict, ColorMatch]]
```

`pairs` es la lista `[(color, match), ...]` de todos los colores extraídos ya matcheados.
Devuelve la lista consolidada (≤ entradas), sin tintas repetidas ni equivalentes.

### Algoritmo

Mismo patrón perceptual que la fusión de paleta (`_merge_perceptual`):

1. Ordenar `pairs` por `color["weight"]` descendente.
2. Recorrerlos formando **grupos**. Un color se une a un grupo existente si la tinta rank-1
   de ese grupo y la tinta rank-1 del color tienen `ΔE CIEDE2000 < ink_merge_delta_e`.
   Como `ΔE = 0` cubre el mismo `ink_id`, un único umbral resuelve los dos casos del problema.
   Si no encaja en ningún grupo, abre uno nuevo.
3. El **primer** color de cada grupo (el de mayor peso, por el orden del paso 1) es el
   **dominante** y gana: aporta el color mostrado y su `ColorMatch` (tinta rank-1 + candidatos).
4. Fusión del grupo:
   - `weight` = suma de los pesos del grupo (no se pierde la superficie del color absorbido).
   - `role` se recalcula con `dominant_weight` sobre el peso sumado.
   - `hex` / `rgb` / `lab` = los del dominante.
   - `best_delta_e` / `match_quality` / `needs_mix` / `candidates` = los del `ColorMatch`
     del dominante.

La distancia tinta-a-tinta usa `ink.lab` (ya disponible en `inks`) localizando cada
`Candidate.ink_id` en `inks`.

### Wiring — `app/pipeline/runner.py`

Tras el bucle de matching, en vez de insertar dentro del bucle:

1. Acumular `pairs = [(color, match), ...]`.
2. `pairs = consolidate_by_ink(pairs, inks, settings)`.
3. Insertar `extracted_colors` + `match_results` recorriendo los `pairs` consolidados.

El log de "N colores" pasa a reflejar el número consolidado.

### Config — `app/config.py`

Nuevo parámetro afinable (sección Matching):

```
ink_merge_delta_e: float = 2.0   # ΔE bajo el que dos tintas se consideran la misma
```

Alineado con `quality_excellent = 2.0` ("dos tintas más cercanas que 'excellent' son la
misma tinta").

## Sin cambios de esquema

Solo se insertan menos filas en `extracted_colors` (y sus `match_results`). No hay
migración.

## Tests — `tests/test_matching.py`

1. **Misma tinta exacta:** dos colores cuyo rank-1 es el mismo `ink_id` → una sola entrada,
   pesos sumados.
2. **Equivalentes de marcas distintas:** dos colores con tintas rank-1 distintas pero
   ΔE < umbral → fusión; gana el dominante (mayor peso), su tinta es la conservada.
3. **No fusionar:** dos colores con tintas rank-1 a ΔE > umbral → se mantienen separados.
4. **Pesos y role:** peso sumado correcto y `role` recalculado a `dominant` si el peso
   sumado supera `dominant_weight`.
