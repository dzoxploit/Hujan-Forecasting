"""Cache hasil pipeline ke disk (Parquet + CSV) supaya backend web tidak
perlu menjalankan ulang pipeline setiap kali dashboard dibuka.

Terpisah sengaja dari `model_store.py`: file di sini berisi HASIL angka
(matriks harian), bukan model - jadi dipakai format kolumnar (Parquet)
yang lebih hemat untuk dibaca sebagian kolom saja (satu stasiun), bukan
HDF5 seperti file model.
"""

from pathlib import Path

import pandas as pd

_SERIES_FILES = {
    "original": "series_original.parquet",
    "normal_ratio": "series_normal_ratio.parquet",
    "idw": "series_idw.parquet",
    "random_forest": "series_random_forest.parquet",
    "best_result": "series_best_result.parquet",
}


def _matrix_to_parquet(matrix, path):
    out = matrix.reset_index().rename(columns={matrix.index.name or "index": "Tanggal"})
    out.to_parquet(path, index=False)


def save_results_cache(results, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for key, filename in _SERIES_FILES.items():
        if key in results and results[key] is not None:
            _matrix_to_parquet(results[key], out_dir / filename)

    results["metadata"].to_csv(out_dir / "metadata.csv", index=False)
    results["summary"].to_csv(out_dir / "summary.csv", index=False)

    if results.get("failure_percentage") is not None and not results["failure_percentage"].empty:
        results["failure_percentage"].to_csv(out_dir / "failure_percentage.csv", index=False)


def cache_exists(out_dir):
    out_dir = Path(out_dir)
    return (out_dir / "summary.csv").exists() and (out_dir / _SERIES_FILES["original"]).exists()


def load_metadata(out_dir):
    return pd.read_csv(Path(out_dir) / "metadata.csv")


def load_summary(out_dir):
    return pd.read_csv(Path(out_dir) / "summary.csv")


def load_failure_percentage(out_dir):
    path = Path(out_dir) / "failure_percentage.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def load_station_timeseries(out_dir, station):
    """Baca hanya kolom [Tanggal, station] dari tiap file Parquet - jauh
    lebih murah daripada memuat seluruh matriks 163 stasiun."""

    out_dir = Path(out_dir)
    series = {}

    for key, filename in _SERIES_FILES.items():
        path = out_dir / filename
        if not path.exists():
            continue
        df = pd.read_parquet(path, columns=["Tanggal", station])
        series[key] = df

    return series


def list_available_stations(out_dir):
    metadata = load_metadata(out_dir)
    return sorted(metadata["NAMAPOS"].tolist())
