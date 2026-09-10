"""Konfigurasi pipeline imputasi hujan.

Dipindah dari sel 2 notebook `rekap_hujan_imputasi.ipynb`, tanpa perubahan
nilai default, supaya hasil backend web tetap konsisten dengan notebook.
"""

import os

# Periode analisis
START_DATE = "2016-01-01"
END_DATE = "2025-12-31"

# Nilai data yang masih kosong
MISSING_EXPORT_VALUE = -99.0

# Parameter IDW
N_NEIGHBORS = 5
IDW_POWER = 2.0

# Parameter Random Forest
RF_MAX_DONORS = 12
RF_N_ESTIMATORS = 300
RF_MIN_TRAIN_SAMPLES = 180
RF_MIN_OVERLAP_FOR_DONOR = 60
RF_MIN_SAMPLES_LEAF = 2
RANDOM_STATE = 42

# Core
NUM_CORES = max(1, (os.cpu_count() or 4) - 1)
