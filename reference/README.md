# Data referensi wilayah

`wilayah_indonesia.csv`: 38 provinsi + 514 kabupaten/kota (kode Kemendagri, nama, ibu kota,
koordinat ibu kota, luas, penduduk). Dipakai untuk geotagging berita (Fase 4) dan agregasi GIS (Fase 5).

Sumber: [cahyadsn/wilayah](https://github.com/cahyadsn/wilayah) (MIT License, © 2017-2025 Cahya DSN),
tabel `wilayah_level_1_2` (kolom `path`/poligon tidak disertakan di CSV ini).

Koreksi: nama 3 kabupaten di tabel `wilayah_level_1_2` terpotong/berspasi ganda (15.02, 15.05, 16.02 "Ogan Komering" → "Ogan Komering Ilir") dan diselaraskan dengan tabel `wilayah` (sumber yang sama).

`batas_provinsi.geojson` (38) dan `batas_kabkota.geojson` (514): poligon batas dari kolom `path` sumber yang sama, disederhanakan (toleransi 0,01° provinsi / 0,004° kab/kota) dan dibulatkan 4 desimal. Poligon Kota Banjar (32.79) dan Kabupaten Sorong (96.01) di sumber tidak valid secara format dan direkonstruksi dari pasangan koordinatnya. Cukup untuk agregasi & peta tematik, bukan untuk keperluan batas administratif resmi.

**Kontrol kualitas poligon (aturan 1, luas):** 20 dari 514 poligon kab/kota di sumber luasnya menyimpang lebih dari 3× dari luas resmi
(mis. poligon "Kota Kendari" ±11.800 km² vs luas resmi 266 km², tampaknya tertukar dengan kabupaten tetangga; "Kota Semarang"
dan "Kota Langsa" luasnya nol). `scripts/risk.py::validate_geom` menggantinya dengan lingkaran seluas luas resmi di koordinat
ibu kota dan menandainya (`batas_valid=false` / `approx=1`). File referensi mentah tidak diubah.

**Aturan 2, posisi:** poligon dianggap tidak valid juga bila ibu kota wilayahnya berjarak >40 km dari poligon. Menangkap 4 kabupaten kepulauan yang poligonnya tergeser (Kepulauan Meranti, Kepulauan Sangihe, Kepulauan Talaud, Kepulauan Mentawai). Total batas perkiraan: 24.

**Koreksi koordinat:** Kabupaten Wakatobi (74.07) di sumber memiliki bujur 23.5389 (salah ketik); dikoreksi menjadi 123.5389.

**Keterbatasan diketahui:** poligon Kota Palangkaraya tidak mencakup pusat kotanya (±3 km), sehingga titik di pusat kota bisa terhitung ke Kabupaten Pulang Pisau.
