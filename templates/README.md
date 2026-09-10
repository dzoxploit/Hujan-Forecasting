# Template Excel Data Hujan

Format wajib (dibaca oleh `pipeline/data_io.py`, sama seperti sumber data notebook asli):

| Baris | Isi |
|---|---|
| 1 | Nama PCH (satu kolom per stasiun, mulai kolom B) |
| 2 | Longitude tiap PCH |
| 3 | Latitude tiap PCH |
| 4 | Header kolom (bebas, tidak diproses - hanya label) |
| 5+ | Data harian: kolom A = tanggal, kolom B dst = curah hujan (mm) |

Aturan nilai:
- **Kosongkan sel** untuk tanggal yang datanya tidak tersedia.
- **Jangan isi 0** untuk data yang tidak diketahui - `0` berarti "hari tanpa hujan" (data sah), beda makna dengan sel kosong ("tidak diketahui"). Mencampur keduanya akan membuat imputasi dan Normal Ratio jadi bias.
- Nilai boleh pakai koma atau titik sebagai desimal (mis. `12,5` atau `12.5`), keduanya otomatis dibaca dengan benar.

## Isi folder ini

- `TEMPLATE_KOSONG_HUJAN.xlsx` - kerangka kosong dengan 5 nama PCH contoh, koordinat contoh, dan baris tanggal kosong siap diisi. Ganti nama/koordinat PCH sesuai stasiun sungguhan, lalu isi data hariannya.
- `TEMPLATE_CONTOH_TERISI.xlsx` - contoh terisi (120 hari, 5 PCH sintetis) dengan sekitar 12% sel sengaja dikosongkan, supaya bisa langsung dicoba diunggah ke dashboard (`/api/upload`) untuk melihat bagaimana Normal Ratio/IDW/Random Forest mengisi data kosong tanpa perlu menyiapkan data sungguhan dulu.

Dibuat lewat `webapp/backend/generate_templates.py` - jalankan ulang skrip itu (dengan venv aktif) kalau perlu menambah jumlah PCH contoh atau mengubah rentang tanggal.
