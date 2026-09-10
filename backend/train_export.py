"""CLI: jalankan pipeline penuh sekali, lalu simpan:

  - models.h5           model Random Forest per stasiun (lihat pipeline/model_store.py)
  - cache/*.parquet,csv  hasil imputasi (dipakai backend web untuk dashboard)
  - HASIL_....xlsx       (opsional, --excel-out) file Excel lengkap seperti notebook

Contoh:
    python train_export.py --excel "../PENGISIAN DATA HUJAN HILANG (2).xlsx" \
        --out-dir data --sample --sample-stations 5 \
        --sample-start 2023-01-01 --sample-end 2023-12-31

    python train_export.py --excel "../PENGISIAN DATA HUJAN HILANG (2).xlsx" \
        --out-dir data --excel-out "../HASIL_PENGISIAN_DATA_HUJAN_2016_2025_v2.xlsx"
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import model_store, results_cache
from pipeline.excel_export import export_excel
from pipeline.pipeline import run_full_pipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--excel", required=True, help="Path ke Excel sumber (format PCH/lon/lat/header/data).")
    parser.add_argument("--sheet", default=0, help="Nama atau index sheet sumber (default: 0).")
    parser.add_argument("--out-dir", default="data", help="Folder output untuk models.h5 + cache/.")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--sample", action="store_true", help="Mode contoh: subset PCH + rentang tanggal pendek.")
    parser.add_argument("--sample-stations", type=int, default=5)
    parser.add_argument("--sample-start", default="2023-01-01")
    parser.add_argument("--sample-end", default="2023-12-31")
    parser.add_argument("--num-cores", type=int, default=None)
    parser.add_argument("--excel-out", default=None, help="Kalau diisi, juga tulis file Excel hasil lengkap.")
    args = parser.parse_args()

    sheet = int(args.sheet) if str(args.sheet).lstrip("-").isdigit() else args.sheet
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Membaca dan memproses: {args.excel}")
    t0 = time.time()

    results = run_full_pipeline(
        args.excel,
        sheet_name=sheet,
        start_date=args.start_date,
        end_date=args.end_date,
        num_cores=args.num_cores,
        sample_station_count=args.sample_stations if args.sample else None,
        sample_start=args.sample_start,
        sample_end=args.sample_end,
    )

    print(f"Pipeline selesai dalam {time.time() - t0:.1f} detik.")
    print(f"Jumlah stasiun         : {len(results['metadata'])}")
    print(f"Model RF berhasil latih: {len(results['rf_models'])}")

    models_path = out_dir / "models.h5"
    model_store.save_models_h5(results["rf_models"], models_path)
    print(f"Model tersimpan di     : {models_path}")

    cache_dir = out_dir / "cache"
    results_cache.save_results_cache(results, cache_dir)
    print(f"Cache hasil tersimpan  : {cache_dir}")

    if args.excel_out:
        export_excel(
            args.excel_out,
            results["original"],
            results["normal_ratio"],
            results["idw"],
            results["random_forest"],
            results["summary"],
            results["metadata"],
            fallback_mask=results["fallback_mask"],
            failure_percentage=results["failure_percentage"],
            best_result=results["best_result"],
            best_source=results["best_source"],
        )
        print(f"Excel hasil tersimpan  : {args.excel_out}")

    print("SELESAI.")


if __name__ == "__main__":
    main()
