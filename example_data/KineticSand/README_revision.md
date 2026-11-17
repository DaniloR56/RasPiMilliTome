# Kinetic-sand examples at 0.6 mm spacing

These three datasets accompany the RasPi MilliTome manuscript's quantitative examples. Dataset 3 is illustrated in the main text; the Supporting Information compares all three.

| Dataset | Background | Photographs | Assigned physical ROI width (mm) | Recorded interval (mm) | Reconstructed volume (mm³) |
|---|---|---:|---:|---:|---:|
| [Dataset 1](Dataset1) | Orange | 32 | 23.50 | 0.6 | 1995.85 |
| [Dataset 2](Dataset2) | Magenta | 40 | 23.50 | 0.6 | 2304.94 |
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

The physical-width assignments and specimen-preparation differences are discussed in the Supporting Information. These examples illustrate variation between preparations; they are not a controlled repeatability experiment. The earlier 1.2 mm acquisition is not included in these three quantitative examples.

See the [software manual](../../docs/Manual.pdf) for operation and calibration guidance.
