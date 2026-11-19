# Dataset 3 calibration and sensitivity checks

These checks use the original images and saved native masks. They quantify the effects of HSV, ROI selection, axial sampling and assigned spacing. The five caliper travels over ten half-turns are recorded in results/axial_caliper_measurements.csv. No individual-step scatter or complete instrument uncertainty is inferred.

Run from the repository root:

```bash
python3 validation/validate_millitome_sensitivity.py --dataset example_data/KineticSand/Dataset3 --script Reconstruction/RasPiMilliTome_Reconstruction.py --output validation_recheck --axial-displacements 6.20 6.25 6.24 6.20 6.20
```

Requires Python 3, NumPy and OpenCV. The output folder must be outside the dataset. The script verifies archived masks and areas before perturbations, uses the actual program functions without opening its GUI, and preserves source images and parameter JSON. The SD reported for advancement is the SD between ten-step averages. Methods and interpretation are described in the paper’s Supporting Information.
