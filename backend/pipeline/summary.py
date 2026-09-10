"""Ringkasan, validasi, dan penggabungan hasil terbaik (sel 12, 15-17 notebook)."""

import numpy as np
import pandas as pd

from . import config


def validate_imputation(original, imputed):
    if not original.index.equals(imputed.index):
        raise ValueError("Index berbeda.")
    if not original.columns.equals(imputed.columns):
        raise ValueError("Kolom berbeda.")

    original_valid = original.notna()
    changed = original_valid & (original != imputed)
    changed_count = int(changed.sum().sum())
    if changed_count > 0:
        raise ValueError(f"Ada {changed_count} data asli yang berubah.")


def build_summary(original, normal_ratio, idw, random_forest, normals):

    rows = []

    for station in original.columns:
        original_series = original[station]

        first_valid = original_series.first_valid_index()
        last_valid = original_series.last_valid_index()
        original_valid = int(original_series.notna().sum())
        original_missing = int(original_series.isna().sum())

        nr_fill = int((original_series.isna() & normal_ratio[station].notna()).sum())
        idw_fill = int((original_series.isna() & idw[station].notna()).sum())
        rf_fill = int((original_series.isna() & random_forest[station].notna()).sum())

        rows.append({
            "NAMAPOS": station,
            "FIRST_VALID_ASLI": first_valid,
            "LAST_VALID_ASLI": last_valid,
            "DATA_ASLI_VALID": original_valid,
            "DATA_ASLI_KOSONG": original_missing,
            "ISI_NORMAL_RATIO": nr_fill,
            "ISI_IDW": idw_fill,
            "ISI_RANDOM_FOREST": rf_fill,
            "RF_MEMENUHI_SYARAT_LATIH": original_valid >= config.RF_MIN_TRAIN_SAMPLES,
            "NORMAL_HUJAN": normals.get(station, np.nan),
        })

    return pd.DataFrame(rows)


def build_best_result(original, normal_ratio, idw, random_forest, fallback_result=None):

    best = original.copy()
    source = pd.DataFrame("", index=original.index, columns=original.columns)

    missing = original.isna()

    methods = [
        ("RANDOM_FOREST", random_forest),
        ("NORMAL_RATIO", normal_ratio),
        ("IDW", idw),
    ]
    if fallback_result is not None:
        methods.append(("FALLBACK", fallback_result))

    for name, result in methods:
        fill_here = missing & best.isna() & result.notna()
        best = best.mask(fill_here, result)
        source = source.mask(fill_here, name)

    return best, source


def failure_percentage_table(original, normal_ratio, idw, random_forest, fallback_mask=None):

    original_missing = original.isna()
    total_missing = int(original_missing.sum().sum())

    if total_missing == 0:
        return pd.DataFrame()

    rows = []

    def _add_row(name, filled):
        failed = total_missing - filled
        rows.append({
            "METODE": name,
            "BERHASIL": filled,
            "GAGAL": failed,
            "PERSEN_BERHASIL": round(filled / total_missing * 100, 2),
            "PERSEN_GAGAL": round(failed / total_missing * 100, 2),
        })

    methods = {
        "Normal Ratio": normal_ratio,
        "IDW": idw,
        "Random Forest": random_forest,
    }
    for name, result in methods.items():
        filled = int((original_missing & result.notna()).sum().sum())
        _add_row(name, filled)

    combined_filled_mask = original_missing & (
        normal_ratio.notna() | idw.notna() | random_forest.notna()
    )
    combined_filled = int(combined_filled_mask.sum().sum())
    _add_row("Gabungan 3 metode (OR)", combined_filled)

    if fallback_mask is not None:
        fallback_filled = int(fallback_mask.sum().sum())
        _add_row("+ Fallback radius luas", combined_filled + fallback_filled)

    return pd.DataFrame(rows)
