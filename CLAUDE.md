  # CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Spanish-language data-science repo (`github.com/Quantium/Zeus-Notebooks`) of Jupyter
notebooks analyzing warehouse operations for a pharmaceutical distributor (Libra Fármacos /
Plataforma Galileo / módulo SGA "Zeus"). Domains: entradas (recepción), surtido (picking),
embarques, recibo, ubicaciones. The flagship deliverables are an hourly workload dashboard
and a man-hours (`horas hombre`) time-series forecast. Notebooks and comments are written in
Spanish — match that when editing.

There is no test suite, no build, and no application. The "code" is notebooks plus one
client module.

## Environment & commands

Python 3.12 in a local venv (`.venv/`). There is no Makefile or task runner.

```bash
source .venv/bin/activate          # or call .venv/bin/python directly
pip install -r requirements.txt

.venv/bin/python lisa_client.py    # smoke-test the SGA API client (runs main())

# Run a notebook headless (this is how notebooks are "tested"):
.venv/bin/jupyter nbconvert --to notebook --execute --inplace <notebook>.ipynb
```

Secrets live in `.env` (gitignored), read via `python-dotenv`:
- `LISA_TOKEN` — bearer token for the LISA/SGA API.
- `ZEUS_DATABASE_URL` — `postgresql://…` URL for the Zeus DB (Neon/Supabase). No longer needed
  for entradas (now API-only); kept for the legacy per-domain notebooks that still read the DB.

## The single-source-of-truth principle (read before touching `entradas`)

The **canonical source for entradas data is the SGA API**, not the DB and not Google Sheets.
Everything is supposed to be rebuilt on top of that API import. This is the architectural
intent of the repo.

**Resolved — migration done (see `README.md`):** the *hourly* analyses used to read directly
from the Zeus DB table `ds_entradas` because the SGA API returned `fecha_gen` / `fecha_inicio` /
`fecha_fin` **without time** (everything at 00:00). The API now returns real `HH:MM:SS`, so §6
of `fuente_unica_entradas.ipynb` reuses the API `df_limpio` and `prediccion_horas_hombre.ipynb`
queries the API directly (`fecha_gen` acts as a **lower bound** — an early date pulls full
history in one call). The `ZEUS_DATABASE_URL` dependency was dropped from both notebooks; the
API is again the single source for entradas.

## Three data sources (know which a notebook uses)

1. **SGA API** via `lisa_client.py` — the canonical path. `LisaClient.entradas_almacen(fecha_gen="dd/mm/aaaa", almacen="5460D")` → `POST /galileo/lisa/geninf/isp/sga_entradas`. Used by `entradas_almacen.ipynb` and §1–3 of `fuente_unica_entradas.ipynb`.
2. **Zeus DB** (Postgres) via SQLAlchemy `create_engine(ZEUS_DATABASE_URL)` + `pd.read_sql`. The entradas hourly analyses **no longer use it** (migrated to the API); only legacy per-domain notebooks (`recibo.ipynb`, etc.) may still read the DB. Note: the `fecha_inicio` feature-engineering block (SYS_USERS filter, `hora`/`fecha`/`dia_sem`/`dur_min`) is still duplicated between `fuente_unica_entradas.ipynb` §6 and `prediccion_horas_hombre.ipynb` — keep those in sync.
3. **Google Sheets** via `gspread` — the legacy Colab pipeline (`ZeusPipeline.ipynb`), which pulls every domain (OC líneas/pedidos, citas, entradas, ubicaciones, surtido, embarque) from worksheets. The older per-domain EDA notebooks descend from this.

## `lisa_client.py` (the only hand-written module)

SGA-only REST client mirroring `swagger.json` (the final EDISA contract, 9 SGA endpoints).
Constraints encoded in the file:
- **Only SGA-module endpoints belong here.** `entradas_almacen` (sga_entradas) is the
  canonical one for the repo's analyses (`fecha_gen` required); the client also wraps
  `colocacion(_2)`, `preparacion(_2)`, `embalaje` and `actividad_maquina(_2/_historico)`,
  all with optional filters. Note: `preparacion_2` filters by `p_fecha_tarea`, not
  `p_fecha_gen`. Legacy non-SGA wrappers (pedidos, albaranes, etc.) are meant to live in
  `lisa_old_client.py` (referenced but not yet present) — do not add them to `lisa_client.py`.
- "Bring all records" is `l$regs=-1`, **not** `l$pag=-1` — confusing them silently drops to a
  default page size.
- `_post()` is the shared transport; `session` is injectable for mocking. Errors raise
  `LisaAPIError(status_code, message)`.
- API response shape: records are at `registros.reg` (a dict when there's a single record,
  a list otherwise), count at `registros.rowstat.numero_registros`.

## Notebook map

| Notebook | Source | Purpose |
|----------|--------|---------|
| `fuente_unica_entradas.ipynb` | API | **Canonical entradas notebook.** API import → date cleaning → categorical ordering → EDA → hourly handheld workload dashboard (§6 reuses `df_limpio`). |
| `entradas_almacen.ipynb` | API | Minimal API → DataFrame → CSV extraction. |
| `prediccion_horas_hombre.ipynb` | API | Hourly man-hours forecast. SARIMA (s=24, weekly seasonality via Fourier exog, period 168) + Prophet. |
| `Timeseries.ipynb` | — | Generic monthly SARIMA + Prophet reference notebook. |
| `ZeusPipeline.ipynb` | Google Sheets (Colab) | Legacy ingestion pipeline for all warehouse domains. |
| `recibo.ipynb`, `surtido.ipynb`, `embarques.ipynb`, `UBICACIONES.ipynb` | DB / Sheets | Older per-domain EDA (sklearn feature selection, regressors). |

CSV outputs follow the pattern `<source>_<fecha>_<almacen>.csv` (e.g.
`fuente_unica_entradas_01-06-2026_5460D.csv`).

## Conventions

- Date parsing for API data uses `pd.to_datetime(..., format="mixed", dayfirst=True)`
  (Mexican `dd/mm/aaaa HH:MM:SS`); `format="mixed"` preserves the time the API now sends and
  still tolerates the date-only fields (`fecha`, `fecha_doc_externo`).
- Hourly analyses window to the observed shift `HORAS = range(6, 21)` (06h–20h) and cap
  heatmaps/rankings to `TOP_N` for legibility.
- `fecha_inicio` = task start on the handheld; it is the time basis for hourly work.
