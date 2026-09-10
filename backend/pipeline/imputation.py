"""Tiga metode imputasi: Normal Ratio, IDW, Random Forest + fallback.

Diadaptasi dari sel 6-16 notebook. Perbedaan utama dari versi notebook:
`fit_predict_rf_station` di sini juga mengembalikan model Pipeline yang
sudah dilatih (bukan dibuang), supaya bisa disimpan ke file .h5 lewat
`model_store.py` dan dipakai ulang nanti tanpa melatih ulang.
"""

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

from . import config
from .features import (
    calendar_features,
    donor_order_for_station,
    haversine_distance_km,
    metadata_lookup,
    select_rf_donors,
)


def calculate_annual_normals(reference_matrix):

    normals = {}
    years = sorted(reference_matrix.index.year.unique())

    for station in reference_matrix.columns:
        series = reference_matrix[station]
        annual_totals = []

        for year in years:
            year_data = series[series.index.year == year]
            if len(year_data) == 0:
                continue

            expected_days = 366 if pd.Timestamp(year, 12, 31).dayofyear == 366 else 365
            completeness = year_data.notna().sum() / expected_days

            if completeness >= 0.80:
                annual_totals.append(year_data.sum(skipna=True))

        if len(annual_totals) >= 3:
            normal = float(np.mean(annual_totals))
        else:
            valid = series.dropna()
            normal = float(valid.mean() * 365.25) if len(valid) > 0 else np.nan

        normals[station] = normal

    return pd.Series(normals, dtype=float)


def impute_normal_ratio(original, normals, active_ranges, metadata):

    result = original.copy()
    stations = list(original.columns)
    metadata_dict = metadata_lookup(metadata)

    donor_orders = {
        station: donor_order_for_station(station, stations, metadata_dict)
        for station in stations
    }

    for station in stations:
        target_normal = normals.get(station, np.nan)
        if pd.isna(target_normal) or target_normal <= 0:
            continue

        start_date, end_date = active_ranges.get(station, (pd.NaT, pd.NaT))
        if pd.isna(start_date):
            continue

        missing_dates = original.index[
            (original.index >= start_date)
            & (original.index <= end_date)
            & original[station].isna()
        ]

        for date in missing_dates:
            ratios = []

            for donor in donor_orders[station][:config.N_NEIGHBORS]:
                donor_normal = normals.get(donor, np.nan)
                if pd.isna(donor_normal) or donor_normal <= 0:
                    continue

                donor_value = original.at[date, donor]
                if pd.isna(donor_value):
                    continue

                ratio = donor_value / donor_normal
                if np.isfinite(ratio):
                    ratios.append(ratio)

            if len(ratios) == 0:
                continue

            estimated = target_normal * np.mean(ratios)

            if np.isfinite(estimated) and estimated >= 0:
                result.at[date, station] = estimated

    return result


def impute_idw(original, active_ranges, metadata, donor_orders=None, max_neighbors=None):

    result = original.copy()
    stations = list(original.columns)
    metadata_dict = metadata_lookup(metadata)
    max_neighbors = config.N_NEIGHBORS if max_neighbors is None else max_neighbors

    if donor_orders is None:
        donor_orders = {
            station: donor_order_for_station(station, stations, metadata_dict)
            for station in stations
        }

    for station in stations:
        if station not in metadata_dict:
            continue

        target_lat = metadata_dict[station]["lat"]
        target_lon = metadata_dict[station]["lon"]
        if pd.isna(target_lat) or pd.isna(target_lon):
            continue

        start_date, end_date = active_ranges.get(station, (pd.NaT, pd.NaT))
        if pd.isna(start_date):
            continue

        missing_dates = original.index[
            (original.index >= start_date)
            & (original.index <= end_date)
            & original[station].isna()
        ]

        neighbor_list = donor_orders[station]
        if max_neighbors is not None:
            neighbor_list = neighbor_list[:max_neighbors]

        for date in missing_dates:
            values = []
            weights = []

            for donor in neighbor_list:
                donor_lat = metadata_dict[donor]["lat"]
                donor_lon = metadata_dict[donor]["lon"]

                donor_value = original.at[date, donor]
                if pd.isna(donor_value):
                    continue

                distance = haversine_distance_km(target_lat, target_lon, donor_lat, donor_lon)
                if not np.isfinite(distance):
                    continue

                if distance == 0:
                    values = [donor_value]
                    weights = [1.0]
                    break

                weight = 1 / (distance ** config.IDW_POWER)
                values.append(donor_value)
                weights.append(weight)

            if len(values) == 0:
                continue

            estimated = np.sum(np.array(values) * np.array(weights)) / np.sum(weights)

            if np.isfinite(estimated) and estimated >= 0:
                result.at[date, station] = estimated

    return result


def impute_fallback_wide_idw(original, active_ranges, metadata, still_missing_mask):
    stations = list(original.columns)
    metadata_dict = metadata_lookup(metadata)
    donor_orders_full = {
        station: donor_order_for_station(station, stations, metadata_dict)
        for station in stations
    }
    return impute_idw(
        original, active_ranges, metadata,
        donor_orders=donor_orders_full, max_neighbors=None,
    ).where(still_missing_mask, other=np.nan)


def build_rf_training_frame(station, original, active_ranges, metadata):
    """Menyiapkan X_train/y_train/X_predict untuk satu stasiun.

    Dipakai baik saat melatih model baru maupun saat menyiapkan fitur yang
    sama persis untuk prediksi dengan model yang sudah tersimpan.
    """

    target = original[station]
    train_dates = target[target.notna()].index

    if len(train_dates) < config.RF_MIN_TRAIN_SAMPLES:
        return None

    start_date, end_date = active_ranges.get(station, (pd.NaT, pd.NaT))
    if pd.isna(start_date):
        return None

    prediction_dates = original.index[
        (original.index >= start_date)
        & (original.index <= end_date)
        & target.isna()
    ]

    donors = select_rf_donors(station, original, metadata)

    X_calendar_train = calendar_features(train_dates)
    X_calendar_predict = calendar_features(prediction_dates)

    available_donors = [d for d in donors if d in original.columns]

    if available_donors:
        X_donor_train = original.loc[train_dates, available_donors]
        X_donor_predict = original.loc[prediction_dates, available_donors]
        X_train = pd.concat([X_calendar_train, X_donor_train], axis=1)
        X_predict = pd.concat([X_calendar_predict, X_donor_predict], axis=1)
    else:
        X_train = X_calendar_train
        X_predict = X_calendar_predict

    y_train = target.loc[train_dates]

    return {
        "X_train": X_train,
        "y_train": y_train,
        "X_predict": X_predict,
        "prediction_dates": prediction_dates,
        "donors": donors,
        "feature_columns": list(X_train.columns),
    }


def fit_predict_rf_station(station, original, active_ranges, metadata):

    result = pd.Series(np.nan, index=original.index, name=station, dtype=float)

    frame = build_rf_training_frame(station, original, active_ranges, metadata)
    if frame is None or len(frame["prediction_dates"]) == 0:
        return result, None

    model = Pipeline(steps=[
        ("imputer", SimpleImputer(strategy="median")),
        ("rf", RandomForestRegressor(
            n_estimators=config.RF_N_ESTIMATORS,
            min_samples_leaf=config.RF_MIN_SAMPLES_LEAF,
            random_state=config.RANDOM_STATE,
            n_jobs=1,
        )),
    ])

    try:
        model.fit(frame["X_train"], frame["y_train"])
        predictions = model.predict(frame["X_predict"])

        for date, value in zip(frame["prediction_dates"], predictions):
            if np.isfinite(value) and value >= 0:
                result.loc[date] = float(value)
    except Exception:
        return result, None

    model_info = {
        "model": model,
        "donors": frame["donors"],
        "feature_columns": frame["feature_columns"],
        "n_train_samples": int(len(frame["X_train"])),
    }

    return result, model_info


def impute_random_forest(original, active_ranges, metadata, num_cores=None):
    """Melatih & memprediksi Random Forest untuk setiap stasiun.

    Mengembalikan (result_matrix, models) di mana `models` adalah dict
    {nama_stasiun: model_info} untuk semua stasiun yang berhasil dilatih -
    siap dipakai oleh `model_store.save_models_h5`.
    """

    stations = list(original.columns)
    num_cores = num_cores or config.NUM_CORES

    outputs = Parallel(n_jobs=num_cores, verbose=0)(
        delayed(fit_predict_rf_station)(station, original, active_ranges, metadata)
        for station in stations
    )

    result = original.copy()
    models = {}

    for station, (prediction, model_info) in zip(stations, outputs):
        mask = original[station].isna() & prediction.notna()
        result.loc[mask, station] = prediction.loc[mask]
        if model_info is not None:
            models[station] = model_info

    return result, models


def predict_with_saved_model(station, model_info, original, active_ranges, metadata):
    """Memakai model RF yang sudah dilatih (dari file .h5) untuk stasiun
    yang sama pada data (baru) yang punya kolom donor yang sama.

    Kalau stasiun target tidak lengkap kolom donornya di data baru, fitur
    donor yang hilang diisi NaN dan diteruskan ke SimpleImputer di dalam
    Pipeline (median dari data latih asli), sama seperti perilaku sklearn
    saat data prediksi punya nilai kosong.
    """

    result = pd.Series(np.nan, index=original.index, name=station, dtype=float)

    if station not in original.columns:
        return result

    target = original[station]
    start_date, end_date = active_ranges.get(station, (pd.NaT, pd.NaT))
    if pd.isna(start_date):
        return result

    prediction_dates = original.index[
        (original.index >= start_date)
        & (original.index <= end_date)
        & target.isna()
    ]
    if len(prediction_dates) == 0:
        return result

    X_calendar = calendar_features(prediction_dates)
    donors = model_info["donors"]

    donor_frame = pd.DataFrame(index=prediction_dates)
    for donor in donors:
        donor_frame[donor] = (
            original.loc[prediction_dates, donor]
            if donor in original.columns
            else np.nan
        )

    X_predict = pd.concat([X_calendar, donor_frame], axis=1)
    X_predict = X_predict.reindex(columns=model_info["feature_columns"])

    try:
        predictions = model_info["model"].predict(X_predict)
    except Exception:
        return result

    for date, value in zip(prediction_dates, predictions):
        if np.isfinite(value) and value >= 0:
            result.loc[date] = float(value)

    return result
