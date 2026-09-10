"""Backend FastAPI untuk dashboard & API imputasi hujan.

Menyajikan:
  - Dashboard dari hasil yang sudah dilatih sebelumnya (`train_export.py`),
    dibaca dari `DATA_DIR/cache/*` (lihat pipeline/results_cache.py).
  - Upload Excel baru -> imputasi Normal Ratio/IDW dihitung ulang, Random
    Forest memakai model tersimpan di `DATA_DIR/models.h5` untuk stasiun
    yang cocok namanya (tanpa retrain) -> hasil per-sesi bisa dilihat di
    dashboard yang sama dan diunduh sebagai Excel.

Jalankan (dari folder webapp/backend, dengan venv aktif):
    uvicorn app:app --host 0.0.0.0 --port 8000 --reload
"""

import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import model_store, results_cache
from pipeline.excel_export import export_excel
from pipeline.pipeline import run_pipeline_with_saved_models

BACKEND_DIR = Path(__file__).resolve().parent
DATA_DIR = BACKEND_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
MODELS_PATH = DATA_DIR / "models.h5"
SESSIONS_DIR = DATA_DIR / "sessions"
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
TEMPLATES_DIR = BACKEND_DIR.parent / "templates"

SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Rainfall Imputation API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_cache(base_dir):
    if not results_cache.cache_exists(base_dir):
        raise HTTPException(
            status_code=503,
            detail=(
                "Belum ada hasil yang tersimpan. Jalankan train_export.py terlebih "
                "dahulu, atau unggah file Excel lewat /api/upload."
            ),
        )


def _map_rows(summary, metadata):
    merged = metadata.merge(summary, on="NAMAPOS", how="left")
    total = merged["DATA_ASLI_VALID"] + merged["DATA_ASLI_KOSONG"]
    merged["completeness_pct"] = np.where(total > 0, merged["DATA_ASLI_VALID"] / total * 100, np.nan)
    merged = merged.replace({np.nan: None})
    return merged.to_dict(orient="records")


def _timeseries_response(base_dir, station, start=None, end=None):
    series = results_cache.load_station_timeseries(base_dir, station)
    if not series:
        raise HTTPException(status_code=404, detail=f"Stasiun '{station}' tidak ditemukan di cache.")

    merged = None
    for key, df in series.items():
        df = df.rename(columns={station: key})
        merged = df if merged is None else merged.merge(df, on="Tanggal", how="outer")

    merged["Tanggal"] = pd.to_datetime(merged["Tanggal"])
    merged = merged.sort_values("Tanggal")

    if start:
        merged = merged[merged["Tanggal"] >= pd.Timestamp(start)]
    if end:
        merged = merged[merged["Tanggal"] <= pd.Timestamp(end)]

    merged = merged.replace({np.nan: None})
    merged["Tanggal"] = merged["Tanggal"].dt.strftime("%Y-%m-%d")

    return {
        "station": station,
        "dates": merged["Tanggal"].tolist(),
        "series": {
            key: merged[key].tolist() for key in series.keys() if key in merged.columns
        },
    }


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "reference_cache_ready": results_cache.cache_exists(CACHE_DIR),
        "models_ready": MODELS_PATH.exists(),
    }


@app.get("/api/models")
def models_info():
    if not MODELS_PATH.exists():
        raise HTTPException(status_code=503, detail="File models.h5 belum ada. Jalankan train_export.py.")
    return model_store.read_model_bundle_info(MODELS_PATH)


# ---------------------------------------------------------------------------
# Dashboard dari hasil referensi (train_export.py)
# ---------------------------------------------------------------------------

@app.get("/api/dashboard/summary")
def dashboard_summary():
    _require_cache(CACHE_DIR)
    summary = results_cache.load_summary(CACHE_DIR)
    failure = results_cache.load_failure_percentage(CACHE_DIR)
    return {
        "stations": summary.replace({np.nan: None}).to_dict(orient="records"),
        "failure_percentage": failure.replace({np.nan: None}).to_dict(orient="records"),
    }


@app.get("/api/dashboard/map")
def dashboard_map():
    _require_cache(CACHE_DIR)
    metadata = results_cache.load_metadata(CACHE_DIR)
    summary = results_cache.load_summary(CACHE_DIR)
    return _map_rows(summary, metadata)


@app.get("/api/dashboard/top-missing")
def dashboard_top_missing(n: int = 20):
    _require_cache(CACHE_DIR)
    summary = results_cache.load_summary(CACHE_DIR)
    top = summary.sort_values("DATA_ASLI_KOSONG", ascending=False).head(n)
    return top.replace({np.nan: None}).to_dict(orient="records")


@app.get("/api/dashboard/stations")
def dashboard_stations():
    _require_cache(CACHE_DIR)
    return results_cache.list_available_stations(CACHE_DIR)


@app.get("/api/dashboard/timeseries/{station}")
def dashboard_timeseries(station: str, start: str | None = None, end: str | None = None):
    _require_cache(CACHE_DIR)
    return _timeseries_response(CACHE_DIR, station, start, end)


# ---------------------------------------------------------------------------
# Upload data baru -> jalankan Normal Ratio/IDW + Random Forest (model
# tersimpan) -> hasil per-sesi
# ---------------------------------------------------------------------------

@app.post("/api/upload")
async def upload_excel(file: UploadFile = File(...)):
    if not MODELS_PATH.exists():
        raise HTTPException(status_code=503, detail="File models.h5 belum ada. Jalankan train_export.py.")

    session_id = uuid.uuid4().hex[:12]
    session_dir = SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    upload_path = session_dir / file.filename
    with open(upload_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        import openpyxl  # noqa: F401 - validasi format lebih awal
        rainfall_preview = pd.ExcelFile(upload_path)
        del rainfall_preview

        # Muat metadata dulu (murah) untuk tahu stasiun mana yang ada di file
        # ini, supaya hanya model yang relevan yang di-unpickle dari models.h5.
        from pipeline.data_io import load_all_rainfall
        _, metadata_preview = load_all_rainfall(upload_path)
        wanted_stations = metadata_preview["NAMAPOS"].tolist()

        saved_models = model_store.load_models_h5(MODELS_PATH, stations=wanted_stations)

        results = run_pipeline_with_saved_models(upload_path, saved_models)
    except Exception as exc:
        shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Gagal memproses file: {exc}") from exc

    results_cache.save_results_cache(results, session_dir / "cache")

    n_stations = len(results["metadata"])
    n_with_model = len(results.get("stations_with_model", []))

    return {
        "session_id": session_id,
        "station_count": n_stations,
        "stations_with_rf_model": n_with_model,
        "message": (
            f"{n_with_model}/{n_stations} stasiun memakai model Random Forest "
            "tersimpan (nama PCH cocok dengan yang dilatih). Sisanya diisi lewat "
            "Normal Ratio/IDW/fallback."
        ),
    }


@app.get("/api/sessions/{session_id}/summary")
def session_summary(session_id: str):
    base_dir = SESSIONS_DIR / session_id / "cache"
    _require_cache(base_dir)
    summary = results_cache.load_summary(base_dir)
    failure = results_cache.load_failure_percentage(base_dir)
    return {
        "stations": summary.replace({np.nan: None}).to_dict(orient="records"),
        "failure_percentage": failure.replace({np.nan: None}).to_dict(orient="records"),
    }


@app.get("/api/sessions/{session_id}/map")
def session_map(session_id: str):
    base_dir = SESSIONS_DIR / session_id / "cache"
    _require_cache(base_dir)
    metadata = results_cache.load_metadata(base_dir)
    summary = results_cache.load_summary(base_dir)
    return _map_rows(summary, metadata)


@app.get("/api/sessions/{session_id}/stations")
def session_stations(session_id: str):
    base_dir = SESSIONS_DIR / session_id / "cache"
    _require_cache(base_dir)
    return results_cache.list_available_stations(base_dir)


@app.get("/api/sessions/{session_id}/timeseries/{station}")
def session_timeseries(session_id: str, station: str, start: str | None = None, end: str | None = None):
    base_dir = SESSIONS_DIR / session_id / "cache"
    _require_cache(base_dir)
    return _timeseries_response(base_dir, station, start, end)


@app.get("/api/sessions/{session_id}/download")
def session_download(session_id: str):
    base_dir = SESSIONS_DIR / session_id / "cache"
    _require_cache(base_dir)

    metadata = results_cache.load_metadata(base_dir)
    summary = results_cache.load_summary(base_dir)
    failure_percentage = results_cache.load_failure_percentage(base_dir)

    def _load(name):
        return pd.read_parquet(base_dir / f"series_{name}.parquet").set_index("Tanggal")

    original = _load("original")
    normal_ratio = _load("normal_ratio")
    idw = _load("idw")
    random_forest = _load("random_forest")
    best_result = _load("best_result") if (base_dir / "series_best_result.parquet").exists() else None

    out_path = Path(tempfile.gettempdir()) / f"hasil_imputasi_{session_id}.xlsx"
    export_excel(
        out_path, original, normal_ratio, idw, random_forest, summary, metadata,
        failure_percentage=failure_percentage, best_result=best_result,
    )

    return FileResponse(
        out_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"hasil_imputasi_{session_id}.xlsx",
    )


# Template Excel (blank + contoh terisi) yang bisa diunduh dari dashboard
if TEMPLATES_DIR.exists():
    app.mount("/templates", StaticFiles(directory=TEMPLATES_DIR), name="templates")

# Frontend statis (dashboard) - dipasang terakhir supaya tidak menutupi /api/*
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
