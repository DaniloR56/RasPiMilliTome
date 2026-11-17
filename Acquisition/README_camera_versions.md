# Camera acquisition versions

## Camera Module 3

The three quantitative kinetic-sand datasets were acquired with Raspberry Pi Camera Module 3. The current acquisition script uses Picamera2:

```bash
python3 Acquisition/RasPiMilliTome_Picamera2_Focus_v2_GPIO27_Zero2W_Compact.py
```

Run this command from the repository root on the Raspberry Pi. The script requires Python with Tk support, Picamera2/libcamera, OpenCV and Pillow. The repository's reconstruction requirements file does not install the complete Raspberry Pi camera environment.

The interface provides a live preview, autofocus followed by a fixed lens position, manual focus adjustments, **SAVE FOCUS** and **CAPTURE IMAGE**. Keep camera geometry and focus fixed throughout a sequence. Wait for the saved-image confirmation before advancing or cutting again.

- Photographs are saved in `~/MilliTomeDemos/photos/`.
- Files are named `photo_001.jpg`, `photo_002.jpg`, and so on, continuing after the highest existing number. Use an empty output folder or archive the previous sequence before starting another specimen.
- The configured capture size is 2304 × 1296 pixels; preview guides are not saved over the photograph.
- The saved focus file is `~/MilliTomeDemos/millitome_camera_focus.json`.
- Optional camera settings are read from `~/MilliTomeDemos/camera_settings.json`.
- The optional physical capture switch connects BCM GPIO27 (header pin 13) to GND. The GUI capture button remains available without the switch. GPIO support requires `RPi.GPIO` or a compatible implementation.

Record the actual specimen advancement separately; the acquisition script does not measure slice spacing.

## Legacy Camera V1.3

`RasPiMilliTome_Acquisition.py` is retained for the original Camera V1.3 configuration. It uses the legacy `picamera` library and requires a compatible legacy Raspberry Pi camera stack and the peripherals expected by that script.

The scripts use different camera APIs and interfaces. Choose the program appropriate to the installed hardware and camera software.

See the [acquisition and reconstruction manual](../docs/Manual.pdf) for illustrated instructions.
