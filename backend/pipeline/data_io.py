"""Membaca Excel sumber dan membangun matriks harian (sel 4-6 notebook)."""

import numpy as np
import pandas as pd

from . import config
from .parsing import fix_digit_typos, parse_flexible_decimal, parse_coordinate_value


def load_all_rainfall(excel_path, sheet_name=0):

    import openpyxl

    workbook = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)

    worksheet = (
        workbook.worksheets[sheet_name]
        if isinstance(sheet_name, int)
        else workbook[sheet_name]
    )

    row_iterator = worksheet.iter_rows(values_only=True)

    header_row = next(row_iterator)     # Baris 1: nama PCH
    longitude_row = next(row_iterator)  # Baris 2: longitude
    latitude_row = next(row_iterator)   # Baris 3: latitude
    next(row_iterator)                  # Baris 4: header kolom (tidak dipakai)

    station_columns = []
    for col in range(1, len(header_row)):
        value = header_row[col]
        if value is None:
            continue
        name = str(value).strip()
        if name == "":
            continue
        station_columns.append(col)

    if len(station_columns) == 0:
        raise ValueError("Tidak ditemukan nama PCH pada baris 1.")

    station_names = [str(header_row[col]).strip() for col in station_columns]

    longitude = [
        parse_coordinate_value(longitude_row[col] if col < len(longitude_row) else None)
        for col in station_columns
    ]
    latitude = [
        parse_coordinate_value(latitude_row[col] if col < len(latitude_row) else None)
        for col in station_columns
    ]

    records = []

    for row in row_iterator:
        date_value = row[0] if row else None
        if date_value is None:
            continue

        date_parsed = pd.to_datetime(date_value, errors="coerce", dayfirst=True)
        if pd.isna(date_parsed):
            continue

        date_normalized = pd.Timestamp(date_parsed).normalize()

        for station_index, col in enumerate(station_columns):
            station = station_names[station_index]
            rainfall_value = row[col] if col < len(row) else None

            if rainfall_value is None:
                rainfall = np.nan
            else:
                text = fix_digit_typos(str(rainfall_value).strip())
                if text == "" or text.lower() in ["nan", "na", "n/a", "-", "--"]:
                    rainfall = np.nan
                else:
                    rainfall = parse_flexible_decimal(text)

            if pd.notna(rainfall) and rainfall < 0:
                rainfall = np.nan

            records.append({
                "date": date_normalized,
                "NAMAPOS": station,
                "value": rainfall,
            })

    workbook.close()

    rainfall = pd.DataFrame(records)
    rainfall = (
        rainfall
        .groupby(["date", "NAMAPOS"], as_index=False)["value"]
        .first()
    )

    metadata = pd.DataFrame({
        "NAMAPOS": station_names,
        "Longitude": longitude,
        "Latitude": latitude,
    })

    return rainfall, metadata


def make_daily_matrix(rainfall, start_date=None, end_date=None):

    start = pd.Timestamp(start_date or config.START_DATE)
    end = pd.Timestamp(end_date or config.END_DATE)

    rainfall_period = rainfall[
        rainfall["date"].between(start, end, inclusive="both")
    ].copy()

    if rainfall_period.empty:
        raise ValueError(f"Tidak ada data pada periode {start} sampai {end}.")

    full_dates = pd.date_range(start, end, freq="D", name="Tanggal")

    matrix = (
        rainfall_period
        .pivot(index="date", columns="NAMAPOS", values="value")
        .reindex(full_dates)
        .sort_index()
        .sort_index(axis=1)
    )

    matrix.columns.name = None
    matrix = matrix.astype(float)

    active_ranges = {}
    for station in matrix.columns:
        valid_count = int(matrix[station].notna().sum())
        if valid_count > 0:
            active_ranges[station] = (start, end)
        else:
            active_ranges[station] = (pd.NaT, pd.NaT)

    return matrix, active_ranges
