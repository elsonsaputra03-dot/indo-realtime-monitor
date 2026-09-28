# Data referensi wilayah

`wilayah_indonesia.csv`: 38 provinsi + 514 kabupaten/kota (kode Kemendagri, nama, ibu kota,
koordinat ibu kota, luas, penduduk). Dipakai untuk geotagging berita (Fase 4) dan agregasi GIS (Fase 5).

Sumber: [cahyadsn/wilayah](https://github.com/cahyadsn/wilayah) (MIT License, © 2017-2025 Cahya DSN),
tabel `wilayah_level_1_2` (kolom `path`/poligon tidak disertakan di CSV ini).

Koreksi: nama 3 kabupaten di tabel `wilayah_level_1_2` terpotong/berspasi ganda (15.02, 15.05, 16.02 "Ogan Komering" → "Ogan Komering Ilir") dan diselaraskan dengan tabel `wilayah` (sumber yang sama).

`batas_provinsi.geojson` (38) dan `batas_kabkota.geojson` (514): poligon batas dari kolom `path` sumber yang sama, disederhanakan (toleransi 0,01° provinsi / 0,004° kab/kota) dan dibulatkan 4 desimal. Poligon Kota Banjar (32.79) dan Kabupaten Sorong (96.01) di sumber tidak valid secara format dan direkonstruksi dari pasangan koordinatnya. Cukup untuk agregasi & peta tematik, bukan untuk keperluan batas administratif resmi.
