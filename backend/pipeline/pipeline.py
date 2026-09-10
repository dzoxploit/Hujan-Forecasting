"""Orkestrasi pipeline lengkap - dipakai oleh CLI training dan API web."""

import numpy as np
import pandas as pd

from . import config
from .data_io import load_all_rainfall, make_daily_matrix
from .imputation import (
    calculate_annual_normals,
    impute_fallback_wide_idw,
    impute_idw,
    impute_normal_ratio,
    impute_random_forest,
    predict_with_saved_model,
)
from .summary import build_best_result, build_summary, failure_percentage_table, validate_imputation


def apply_sample_subset(matrix, active_ranges, metadata, station_count, sample_start, sample_end):
    """Ambil subset PCH paling lengkap datanya + rentang tanggal lebih pendek,
    supaya pipeline bisa dicoba cepat sebelum dijalankan penuh (mirip sel 5b
    notebook, versi generik dipakai dari CLI training)."""

    completeness = matrix.notna().sum().sort_values(ascending=False)
    selected_stations = list(completeness.head(station_count).index)

    start = max(pd.Timestamp(sample_start), matrix.index.min())
    end = min(pd.Timestamp(sample_end), matrix.index.max())

    sample_matrix = matrix.loc[start:end, selected_stations].copy()
    sample_active_ranges = {
        station: (start, end)
        for station in selected_stations
        if pd.notna(active_ranges.get(station, (pd.NaT, pd.NaT))[0])
    }
    sample_metadata = metadata[metadata["NAMAPOS"].isin(selected_stations)].reset_index(drop=True)

    return sample_matrix, sample_active_ranges, sample_metadata


def run_full_pipeline(
    excel_path, sheet_name=0, start_date=None, end_date=None, num_cores=None,
    sample_station_count=None, sample_start=None, sample_end=None,
):
    """Pipeline lengkap sesuai notebook: load -> matriks -> normal -> 3 metode
    -> fallback -> ringkasan -> hasil terbaik. Mengembalikan dict berisi semua
    DataFrame perantara + model Random Forest per stasiun (untuk disimpan
    lewat `model_store.save_models_h5`).
    """

    rainfall, metadata = load_all_rainfall(excel_path, sheet_name=sheet_name)
    matrix, active_ranges = make_daily_matrix(rainfall, start_date=start_date, end_date=end_date)

    if sample_station_count:
        matrix, active_ranges, metadata = apply_sample_subset(
            matrix, active_ranges, metadata, sample_station_count, sample_start, sample_end,
        )

    normals = calculate_annual_normals(matrix)

    normal_ratio_result = impute_normal_ratio(matrix, normals, active_ranges, metadata)
    idw_result = impute_idw(matrix, active_ranges, metadata)
    random_forest_result, rf_models = impute_random_forest(matrix, active_ranges, metadata, num_cores=num_cores)

    validate_imputation(matrix, normal_ratio_result)
    validate_imputation(matrix, idw_result)
    validate_imputation(matrix, random_forest_result)

    summary = build_summary(matrix, normal_ratio_result, idw_result, random_forest_result, normals)

    still_missing_mask = (
        matrix.isna() & normal_ratio_result.isna() & idw_result.isna() & random_forest_result.isna()
    )
    fallback_result = impute_fallback_wide_idw(matrix, active_ranges, metadata, still_missing_mask)
    fallback_mask = still_missing_mask & fallback_result.notna()
    summary["ISI_FALLBACK_RADIUS_LUAS"] = summary["NAMAPOS"].map(fallback_mask.sum())

    failure_percentage = failure_percentage_table(
        matrix, normal_ratio_result, idw_result, random_forest_result, fallback_mask,
    )

    best_result, best_source = build_best_result(
        matrix, normal_ratio_result, idw_result, random_forest_result, fallback_result,
    )

    normal_ratio_result = normal_ratio_result.mask(fallback_mask, fallback_result)
    idw_result = idw_result.mask(fallback_mask, fallback_result)
    random_forest_result = random_forest_result.mask(fallback_mask, fallback_result)

    validate_imputation(matrix, normal_ratio_result)
    validate_imputation(matrix, idw_result)
    validate_imputation(matrix, random_forest_result)

    return {
        "metadata": metadata,
        "original": matrix,
        "normal_ratio": normal_ratio_result,
        "idw": idw_result,
        "random_forest": random_forest_result,
        "best_result": best_result,
        "best_source": best_source,
        "summary": summary,
        "failure_percentage": failure_percentage,
        "fallback_mask": fallback_mask,
        "rf_models": rf_models,
        "normals": normals,
    }


def run_pipeline_with_saved_models(excel_path, saved_models, sheet_name=0, start_date=None, end_date=None):
    """Untuk data BARU yang diunggah lewat web: Normal Ratio & IDW dihitung
    ulang (murah), sedangkan Random Forest memakai model yang sudah dilatih
    (dari file .h5) untuk stasiun yang cocok namanya - tanpa melatih ulang.
    Stasiun yang tidak ada modelnya dilewati untuk Random Forest (hasilnya
    tetap ada lewat Normal Ratio/IDW/fallback).
    """

    rainfall, metadata = load_all_rainfall(excel_path, sheet_name=sheet_name)
    matrix, active_ranges = make_daily_matrix(rainfall, start_date=start_date, end_date=end_date)

    normals = calculate_annual_normals(matrix)

    normal_ratio_result = impute_normal_ratio(matrix, normals, active_ranges, metadata)
    idw_result = impute_idw(matrix, active_ranges, metadata)

    random_forest_result = matrix.copy()
    stations_with_model = []
    for station in matrix.columns:
        if station not in saved_models:
            continue
        prediction = predict_with_saved_model(station, saved_models[station], matrix, active_ranges, metadata)
        mask = matrix[station].isna() & prediction.notna()
        random_forest_result.loc[mask, station] = prediction.loc[mask]
        stations_with_model.append(station)

    summary = build_summary(matrix, normal_ratio_result, idw_result, random_forest_result, normals)
    summary["RF_MODEL_TERSEDIA"] = summary["NAMAPOS"].isin(stations_with_model)

    still_missing_mask = (
        matrix.isna() & normal_ratio_result.isna() & idw_result.isna() & random_forest_result.isna()
    )
    fallback_result = impute_fallback_wide_idw(matrix, active_ranges, metadata, still_missing_mask)
    fallback_mask = still_missing_mask & fallback_result.notna()

    best_result, best_source = build_best_result(
        matrix, normal_ratio_result, idw_result, random_forest_result, fallback_result,
    )

    normal_ratio_result = normal_ratio_result.mask(fallback_mask, fallback_result)
    idw_result = idw_result.mask(fallback_mask, fallback_result)
    random_forest_result = random_forest_result.mask(fallback_mask, fallback_result)

    failure_percentage = failure_percentage_table(
        matrix, normal_ratio_result, idw_result, random_forest_result, fallback_mask,
    )

    return {
        "metadata": metadata,
        "original": matrix,
        "normal_ratio": normal_ratio_result,
        "idw": idw_result,
        "random_forest": random_forest_result,
        "best_result": best_result,
        "best_source": best_source,
        "summary": summary,
        "failure_percentage": failure_percentage,
        "fallback_mask": fallback_mask,
        "stations_with_model": stations_with_model,
        "normals": normals,
    }
