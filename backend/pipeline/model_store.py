"""Menyimpan/memuat model Random Forest per-stasiun ke/dari satu file .h5.

Catatan penting soal format: `RandomForestRegressor` scikit-learn BUKAN
model Keras/TensorFlow, jadi tidak punya representasi .h5 native seperti
`model.save("model.h5")` di Keras. Yang dilakukan di sini adalah membungkus
setiap model (lewat `pickle`) sebagai blob byte di dalam satu container
HDF5 asli (dibuat dengan `h5py`, bisa dibuka dengan HDFView/h5dump apa pun),
supaya ekstensi file tetap `.h5` dan semua model + metadata donor/fitur
per stasiun tersimpan dalam SATU file yang portable.

Struktur file:
    /                                   (attrs: created_at, format_version,
                                         rf_n_estimators, rf_random_state,
                                         start_date, stations = json list)
    /models/<nama_stasiun>/pickle       dataset uint8 (pickled Pipeline)
    /models/<nama_stasiun>              attrs: donors (json), feature_columns
                                         (json), n_train_samples (int)
"""

import json
import pickle
from datetime import datetime, timezone

import h5py
import numpy as np

from . import config

FORMAT_VERSION = 1


def save_models_h5(models, path, extra_attrs=None):
    """models: dict {nama_stasiun: {"model", "donors", "feature_columns",
    "n_train_samples"}}, hasil dari `imputation.impute_random_forest`.
    """

    with h5py.File(path, "w") as f:
        f.attrs["format_version"] = FORMAT_VERSION
        f.attrs["created_at"] = datetime.now(timezone.utc).isoformat()
        f.attrs["rf_n_estimators"] = config.RF_N_ESTIMATORS
        f.attrs["rf_min_samples_leaf"] = config.RF_MIN_SAMPLES_LEAF
        f.attrs["rf_random_state"] = config.RANDOM_STATE
        f.attrs["start_date"] = config.START_DATE
        f.attrs["end_date"] = config.END_DATE
        f.attrs["stations"] = json.dumps(sorted(models.keys()))

        if extra_attrs:
            for key, value in extra_attrs.items():
                f.attrs[key] = value

        group = f.create_group("models")

        for station, info in models.items():
            station_group = group.create_group(station)

            blob = pickle.dumps(info["model"], protocol=pickle.HIGHEST_PROTOCOL)
            station_group.create_dataset(
                "pickle",
                data=np.frombuffer(blob, dtype=np.uint8),
                compression="gzip",
                compression_opts=4,
            )

            station_group.attrs["donors"] = json.dumps(info["donors"])
            station_group.attrs["feature_columns"] = json.dumps(info["feature_columns"])
            station_group.attrs["n_train_samples"] = int(info["n_train_samples"])


def load_models_h5(path, stations=None):
    """Memuat model dari file .h5. `stations=None` memuat semua stasiun."""

    models = {}

    with h5py.File(path, "r") as f:
        available = json.loads(f.attrs["stations"])
        wanted = available if stations is None else [s for s in stations if s in available]

        for station in wanted:
            station_group = f["models"][station]
            blob = station_group["pickle"][()].tobytes()
            model = pickle.loads(blob)

            models[station] = {
                "model": model,
                "donors": json.loads(station_group.attrs["donors"]),
                "feature_columns": json.loads(station_group.attrs["feature_columns"]),
                "n_train_samples": int(station_group.attrs["n_train_samples"]),
            }

    return models


def read_model_bundle_info(path):
    """Metadata ringan (tanpa unpickle model) - dipakai untuk endpoint
    `/api/models` supaya cepat walau file .h5 besar."""

    with h5py.File(path, "r") as f:
        stations = json.loads(f.attrs["stations"])
        info = {
            "format_version": int(f.attrs["format_version"]),
            "created_at": f.attrs["created_at"],
            "rf_n_estimators": int(f.attrs["rf_n_estimators"]),
            "rf_random_state": int(f.attrs["rf_random_state"]),
            "start_date": f.attrs["start_date"],
            "end_date": f.attrs["end_date"],
            "station_count": len(stations),
            "stations": [],
        }
        for station in stations:
            station_group = f["models"][station]
            info["stations"].append({
                "NAMAPOS": station,
                "n_train_samples": int(station_group.attrs["n_train_samples"]),
                "n_donors": len(json.loads(station_group.attrs["donors"])),
            })

    return info
