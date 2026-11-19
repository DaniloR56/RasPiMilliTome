# Kinetic-sand examples at 0.6 mm spacing

These three datasets accompany the RasPi MilliTome manuscript's quantitative examples. Dataset 3 is illustrated in the main text; the Supporting Information compares all three.

| Dataset | Background | Photographs | Assigned physical ROI width (mm) | Nominal interval (mm) | Reconstructed volume (mm³) |
|---|---|---:|---:|---:|---:|
| [Dataset 1](Dataset1) | Orange | 32 | 23.65 | 0.6 | 2021.41 |
| [Dataset 2](Dataset2) | Magenta | 40 | 23.65 | 0.6 | 2334.46 |
| [Dataset 3](Dataset3) | Magenta | 40 | 23.65 | 0.6 | 2226.55 |

Each folder contains the original photographs, `segmentation_params.json`, `saved_masks/` and `slice_areas.csv`. Source filenames and processing order are recorded explicitly.

All three use H = 25–95, S = 50–255 and V = 40–255 in OpenCV's 8-bit HSV convention (H = 0–179; S and V = 0–255). Morphology uses a 5 × 5 all-ones kernel, closing twice and opening once. Quantitative areas and volumes use the native-resolution masks before the optional 3D blob filtering.

## Reproducing an archived result

1. Work on a copy of the individual dataset folder.
2. Open it with **Load** in the reconstruction application. Its valid JSON settings are restored automatically.
3. Retain the saved ROI, physical width, spacing, image order, HSV thresholds and morphology settings.
4. Inspect representative sections, then press **Accept ALL** to reproduce the masks and area CSV.
5. Compare the result with the archived CSV. Volume is the sum of sectional areas multiplied by 0.6 mm.

Reprocessing overwrites generated outputs. Changing the ROI while retaining its assigned physical width changes the lateral scale and can change the volume even if the selected foreground pixels do not change. Shared HSV settings do not make ROI coordinates or calibration interchangeable between datasets.

All three use a common effective physical ROI width of 23.65 mm. The Supporting Information reports the mean, sample standard deviation and relative standard deviation across these independent acquisitions as a preliminary assessment of the complete workflow. The earlier 1.2 mm acquisition is not included in these three quantitative examples.

See the [software manual](../../docs/Manual.pdf) for operation and calibration guidance.

Across the three independent acquisitions, the mean volume is 2194.14 mm³, the sample standard deviation is 159.02 mm³, and the relative standard deviation is 7.25% (n = 3). At nominal spacing, the best observed difference from the 2074.27 mm³ spherical reference is 2.55%, approximately 3%.

## Axial calibration check

The volumes above use the archived nominal spacing of 0.6 mm. Five subsequent caliper measurements over ten half-turns gave travels of 6.20, 6.25, 6.24, 6.20 and 6.20 mm. Mean advancement was 0.6218 mm per half-turn, with sample SD 0.0025 mm between ten-step averages. Applying that mean to the same areas increases volumes by 3.63%: Dataset 1 = 2094.85 mm³; Dataset 2 = 2419.28 mm³; Dataset 3 = 2307.45 mm³. This assumes the later travel check represents the earlier acquisitions. It does not change the archived nominal-spacing JSON or CSV files. See the SI calibration table and sensitivity tests.
