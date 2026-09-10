"""Fitur jarak (haversine) dan fitur kalender (sel 8, 11 notebook)."""

import numpy as np
import pandas as pd

from . import config


def haversine_distance_km(lat1, lon1, lat2, lon2):

    if any(pd.isna(v) for v in [lat1, lon1, lat2, lon2]):
        return np.inf

    R = 6371.0
    lat1_rad = np.radians(lat1)
    lat2_rad = np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)

    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2) ** 2
    c = 2 * np.arcsin(np.sqrt(a))

    return float(R * c)


def metadata_lookup(metadata):
    return {
        row["NAMAPOS"]: {"lat": row["Latitude"], "lon": row["Longitude"]}
        for _, row in metadata.iterrows()
    }


def donor_order_for_station(station, stations, metadata_dict):

    if station not in metadata_dict:
        return []

    target_lat = metadata_dict[station]["lat"]
    target_lon = metadata_dict[station]["lon"]

    candidates = []
    for donor in stations:
        if donor == station:
            continue
        donor_lat = metadata_dict[donor]["lat"]
        donor_lon = metadata_dict[donor]["lon"]
        distance = haversine_distance_km(target_lat, target_lon, donor_lat, donor_lon)
        candidates.append((donor, distance))

    finite = [x for x in candidates if np.isfinite(x[1])]
    finite.sort(key=lambda x: x[1])

    return [x[0] for x in finite]


def calendar_features(dates, start_date=None):
    start = pd.Timestamp(start_date or config.START_DATE)
    df = pd.DataFrame(index=dates)
    df["hari_epoch"] = (dates - start).days
    df["month"] = dates.month
    df["dayofyear"] = dates.dayofyear
    df["sin_month"] = np.sin(2 * np.pi * dates.month / 12)
    df["cos_month"] = np.cos(2 * np.pi * dates.month / 12)
    df["sin_dayofyear"] = np.sin(2 * np.pi * dates.dayofyear / 365.25)
    df["cos_dayofyear"] = np.cos(2 * np.pi * dates.dayofyear / 365.25)
    return df


def select_rf_donors(station, original, metadata):

    stations = list(original.columns)
    target = original[station]
    metadata_dict = metadata_lookup(metadata)

    candidates = []
    for donor in stations:
        if donor == station:
            continue

        pair = pd.concat([target, original[donor]], axis=1).dropna()
        if len(pair) < config.RF_MIN_OVERLAP_FOR_DONOR:
            continue

        correlation = pair.iloc[:, 0].corr(pair.iloc[:, 1])
        if pd.isna(correlation):
            continue

        distance = np.inf
        if station in metadata_dict and donor in metadata_dict:
            distance = haversine_distance_km(
                metadata_dict[station]["lat"], metadata_dict[station]["lon"],
                metadata_dict[donor]["lat"], metadata_dict[donor]["lon"],
            )

        candidates.append((donor, correlation, distance, len(pair)))

    if not candidates:
        return []

    candidates.sort(key=lambda x: (-abs(x[1]), x[2]))

    return [x[0] for x in candidates[:config.RF_MAX_DONORS]]
