#!/usr/bin/env python3
# ==============================================================
# RasPi MilliTome Reconstruction Software
# ==============================================================
#
# Integrated software package for serial-section image processing,
# volumetric reconstruction, and three-dimensional visualization
# developed for the RasPi MilliTome educational platform.
#
# --------------------------------------------------------------
# FEATURES
# --------------------------------------------------------------
#
# • Loading and visualization of sequential image stacks
# • Interactive navigation through serial slices
# • Optional ROI (Region of Interest) selection
# • HSV-based color segmentation
# • Real-time segmentation tuning using interactive sliders
# • Morphological filtering and mask cleanup
# • Binary mask generation and export
# • Blob filtering and connected-component analysis
# • Cavalieri volume estimation from serial sections
# • 3D volumetric reconstruction using marching cubes
# • Interactive 3D visualization using PyVista
# • STL export for 3D printing and mesh analysis
# • Saving/loading reconstruction parameters using JSON
#
# --------------------------------------------------------------
# EDUCATIONAL OBJECTIVES
# --------------------------------------------------------------
#
# The software was designed to introduce students and makers to:
#
# • Serial sectioning techniques
# • Stereology and volume estimation
# • Digital image segmentation
# • Computational image analysis
# • Volumetric reconstruction
# • Scientific visualization
# • Open-source scientific programming
#
# The workflow is intended for low-cost educational experiments
# involving heterogeneous materials such as kinetic sand,
# marble cake models, biological specimens, and other layered
# reconstruction datasets.
#
# --------------------------------------------------------------
# MAIN DEPENDENCIES
# --------------------------------------------------------------
#
# Python >= 3.10
#
# Required libraries:
#
#   opencv-python
#   numpy
#   pillow
#   scipy
#   scikit-image
#   pyvista
#
# Optional:
#
#   vtk
#
# --------------------------------------------------------------
# INSTALLATION EXAMPLE
# --------------------------------------------------------------
#
# pip install opencv-python numpy pillow scipy
# pip install scikit-image pyvista vtk
#
# --------------------------------------------------------------
# AUTHOR
# --------------------------------------------------------------
#
# Danilo Roccatano
#
# RasPi MilliTome Project
#
# Instructables:
# https://www.instructables.com/
#
# --------------------------------------------------------------
# LICENSE
# --------------------------------------------------------------
#
# Educational and research use.
#
# --------------------------------------------------------------
# CITATION
# --------------------------------------------------------------
#
# If this software contributes to published work, please cite:
#
# Roccatano D.
# The RasPi MilliTome: A Low-Cost Platform for Teaching
# Three-Dimensional Reconstruction from Serial Sections
#
# ==============================================================

import os
import cv2
import numpy as np
import glob
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
from skimage import measure
import multiprocessing
from scipy import ndimage
import json
import csv
import re
import sys
import tempfile

# =========================
# GLOBAL STATE
# =========================
files = []
current_idx = 0
roi = None
volume = []
last_mesh = None

slice_areas = []
estimated_volume = 0

SOFTWARE_VERSION = "settings-fix-2"
restoring_settings = False
morphology_entries = {}
image_shape = None
processed_calibration = None
MORPHOLOGY = {"kernel_size": 5, "close_iterations": 2, "open_iterations": 1}


def invalidate_results():
    global volume, slice_areas, estimated_volume, last_mesh, processed_calibration
    volume, slice_areas = [], []
    estimated_volume, last_mesh, processed_calibration = 0, None, None
    if "volume_label" in globals():
        volume_label.config(text="Estimated Volume: --- mm³ (reprocess required)")


def positive_number(value, name):
    number = float(value)
    if not np.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and positive.")
    return number


def crop_image(img, selected_roi=None):
    if img is None or img.ndim != 3:
        raise ValueError("Cannot read a colour image.")
    if selected_roi is None:
        return img
    if len(selected_roi) != 4 or any(type(v) is not int for v in selected_roi):
        raise ValueError("ROI must contain four integer pixel coordinates.")
    x, y, w, h = selected_roi
    if min(x, y) < 0 or min(w, h) <= 0 or x+w > img.shape[1] or y+h > img.shape[0]:
        raise ValueError("ROI lies outside the original image.")
    return img[y:y+h, x:x+w]


def quantitative_slice(img):
    if image_shape is not None and list(img.shape[:2]) != image_shape:
        raise ValueError("Image dimensions differ from the saved/loaded dataset.")
    cropped = crop_image(img, roi)
    if cropped.shape[0] != cropped.shape[1]:
        raise ValueError("Select a square ROI: calibration assumes square pixels and a square specimen region.")
    return cropped, segment(cropped)


def measurement(mask, width_mm):
    scale = positive_number(width_mm, "ROI physical width") / mask.shape[1]
    return float(np.count_nonzero(mask)) * scale**2


params = {
    "Hmin": 25, "Hmax": 95,
    "Smin": 50, "Smax": 255,
    "Vmin": 40, "Vmax": 255
}

# =========================
# 3D VIEW PROCESS
# =========================
def show_3d_process(vol, square_size, thickness):
    import pyvista as pv
    from skimage import measure
    import numpy as np

    pixel_size = square_size / vol.shape[2]

    vol_small = vol[::2, ::2, ::2]
    spacing = (thickness*2, pixel_size*2, pixel_size*2)

    verts, faces, _, _ = measure.marching_cubes(vol_small, level=0.5)
    verts *= spacing
    verts = verts[:, [2, 1, 0]]  # marching cubes uses z,y,x; mesh axes are x,y,z

    faces_pv = np.hstack([[3, f[0], f[1], f[2]] for f in faces])
    mesh = pv.PolyData(verts, faces_pv)

    xmin, xmax, ymin, ymax, zmin, zmax = mesh.bounds
    mesh.translate([-xmin, -ymin, -zmin])

    plotter = pv.Plotter()
    plotter.add_mesh(mesh, color="green", opacity=0.6)
    plotter.add_mesh_slice_orthogonal(mesh)

    plotter.set_scale(1,1,1)

    plotter.show_bounds(
        xtitle="X (mm)",
        ytitle="Y (mm)",
        ztitle="Z (mm)"
    )

    plotter.view_isometric()
    plotter.show()

# =========================
# BLOB FILTER
# =========================
def filter_blobs(vol, min_volume_voxels=1000, keep_largest=True):
    labeled, num = ndimage.label(vol)

    if num == 0:
        return vol

    sizes = ndimage.sum(vol, labeled, range(1, num+1))

    mask = np.zeros_like(vol)

    if keep_largest:
        largest = np.argmax(sizes) + 1
        mask[labeled == largest] = 1
    else:
        for i, size in enumerate(sizes):
            if size > min_volume_voxels:
                mask[labeled == (i+1)] = 1

    return mask

# =========================
# BUILD MESH
# =========================
def build_mesh(vol, square_size, thickness):
    import pyvista as pv

    pixel_size = square_size / vol.shape[2]

    vol_small = vol[::2, ::2, ::2]
    spacing = (thickness*2, pixel_size*2, pixel_size*2)

    verts, faces, _, _ = measure.marching_cubes(vol_small, level=0.5)
    verts *= spacing
    verts = verts[:, [2, 1, 0]]  # marching cubes uses z,y,x; mesh axes are x,y,z

    faces_pv = np.hstack([[3, f[0], f[1], f[2]] for f in faces])
    mesh = pv.PolyData(verts, faces_pv)

    xmin, xmax, ymin, ymax, zmin, zmax = mesh.bounds
    mesh.translate([-xmin, -ymin, -zmin])

    return mesh

# =========================
# LOAD IMAGES
# =========================
def load_images(folder=None):
    """Load a folder and its exact segmentation_params.json, if present."""
    global files, current_idx, roi, image_shape
    if folder is None:
        folder = filedialog.askdirectory(initialdir=".")
    if not folder:
        return False
    old = files, current_idx, roi, image_shape
    try:
        candidates = [os.path.join(folder, name) for name in os.listdir(folder)
                      if os.path.splitext(name)[1].lower() in
                      (".jpg", ".jpeg", ".png", ".tif", ".tiff")
                      and os.path.isfile(os.path.join(folder, name))]
        candidates.sort(key=lambda p: [int(t) if t.isdigit() else t.lower()
                                      for t in re.split(r"(\d+)", os.path.basename(p))])
        if not candidates:
            raise ValueError("No image files found in the selected folder.")
        first = cv2.imread(candidates[0])
        if first is None:
            raise ValueError("Cannot read the first image.")
        files, current_idx, roi, image_shape = candidates, 0, None, list(first.shape[:2])
        settings_path = os.path.join(folder, "segmentation_params.json")
        if os.path.isfile(settings_path):
            with open(settings_path, encoding="utf-8") as stream:
                restore_parameters(json.load(stream))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        files, current_idx, roi, image_shape = old
        messagebox.showerror("Load folder", f"Folder was not loaded: {exc}")
        return False
    invalidate_results()
    update_display()
    return True


# =========================
# ROI
# =========================
def select_roi():
    global roi
    if not files:
        messagebox.showwarning("ROI", "Load images first.")
        return
    img = cv2.imread(files[current_idx])
    r = cv2.selectROI("Select ROI", img)
    cv2.destroyAllWindows()

    x, y, w, h = r
    size = min(w, h)
    if size <= 0:
        return
    roi = (int(x), int(y), int(size), int(size))
    invalidate_results()

    print("ROI:", roi)
    update_display()

# =========================
# SEGMENT
# =========================
def segment(img):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    lower = np.array([params["Hmin"], params["Smin"], params["Vmin"]])
    upper = np.array([params["Hmax"], params["Smax"], params["Vmax"]])

    mask = cv2.inRange(hsv, lower, upper)

    kernel = np.ones((MORPHOLOGY["kernel_size"],)*2, np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel,
                            iterations=MORPHOLOGY["close_iterations"])
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel,
                            iterations=MORPHOLOGY["open_iterations"])

    return mask

# =========================
# DISPLAY
# =========================
def save_stage_images(img, gray, mask, overlay):

    cv2.imwrite("stage1_original.png", img)
    cv2.imwrite("stage2_grayscale.png", gray)
    cv2.imwrite("stage3_mask.png", mask)
    cv2.imwrite("stage4_overlay.png", overlay)

    print("Stage images saved!")


def update_display(*args):

    global current_idx, files, roi

    if len(files) == 0:
        return

    # Load original full-resolution image
    img = cv2.imread(files[current_idx])

    if img is None:
        return

    try:
        img, mask = quantitative_slice(img)
    except ValueError as exc:
        messagebox.showerror("Segmentation", str(exc))
        return

    # Overlay
    overlay = img.copy()
    overlay[mask > 0] = [0,255,0]

    # Save full-resolution publication figures
    #save_stage_images(img, gray, mask, overlay)

    # ---------- SMALL DISPLAY COPIES ----------

    display_size = (400, 400)

    img_disp = cv2.resize(img, display_size)
    mask_disp = cv2.resize(mask, display_size, interpolation=cv2.INTER_NEAREST)
    overlay_disp = cv2.resize(overlay, display_size)

    # Display in GUI
    show(panel_original, img_disp)
    show(panel_mask, mask_disp)
    show(panel_overlay, overlay_disp)


def show(panel, img):
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    else:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    img = Image.fromarray(img)
    img = ImageTk.PhotoImage(img)

    panel.configure(image=img)
    panel.image = img

# =========================
# NAVIGATION
# =========================
def next_image():
    global current_idx
    if current_idx < len(files)-1:
        current_idx += 1
    update_display()

def prev_image():
    global current_idx
    if current_idx > 0:
        current_idx -= 1
    update_display()

# =========================
# ACCEPT ALL
# =========================

def accept_all_slices():
    global volume
    global slice_areas
    global estimated_volume
    if not files:
        messagebox.showwarning(
            "Warning",
            "Please load images first."
        )
        return
    volume = []
    slice_areas = []
    estimated_volume = 0
    global processed_calibration
    try:
        parameter_snapshot()  # Reject invalid settings before writing any output.
        square_size = positive_number(square_entry.get(), "ROI physical width")
        thickness = positive_number(thickness_entry.get(), "Axial spacing")
        masks = []
        areas = []
        # Validate the complete stack before writing or committing any result.
        for f in files:
            img = cv2.imread(f)
            if img is None:
                raise ValueError(f"Cannot read image: {f}; no slices may be skipped.")
            _, mask = quantitative_slice(img)
            masks.append(mask)
            areas.append(measurement(mask, square_size))
        if len({m.shape for m in masks}) != 1:
            raise ValueError("All quantitative masks must have identical dimensions.")
    except (ValueError, TypeError) as exc:
        invalidate_results()
        messagebox.showerror("Processing", str(exc))
        return
    mask_folder = os.path.join(os.path.dirname(files[0]), "saved_masks")
    os.makedirs(mask_folder, exist_ok=True)
    for idx, mask in enumerate(masks):
        if not cv2.imwrite(os.path.join(mask_folder, f"mask_{idx:04d}.png"), mask):
            raise OSError("Could not save quantitative mask.")
    volume = [mask > 0 for mask in masks]
    slice_areas = areas
    estimated_volume = sum(areas) * thickness
    processed_calibration = (square_size, thickness)
    save_parameters(os.path.join(os.path.dirname(files[0]), "segmentation_params.json"))
    # =========================
    # SAVE CSV REPORT
    # =========================
    csv_path = os.path.join( os.path.dirname(files[0]), "slice_areas.csv")

    with open(csv_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            "Slice",
            "Area_mm2", "Source_file", "Mask_file", "Axial_spacing_mm", "Index_convention"
        ])
        for i, area in enumerate(slice_areas):
            writer.writerow([
                i+1,
                area, os.path.basename(files[i]), f"saved_masks/mask_{i:04d}.png",
                thickness, "Slice is 1-based; mask filename index is 0-based"
            ])
    print("All slices processed!")
    print(
        f"Estimated Volume = "
        f"{estimated_volume:.2f} mm³"
    )
    messagebox.showinfo(
        "Cavalieri Volume Estimate",
        f"Estimated volume:\n"
        f"{estimated_volume:.2f} mm³"
    )
    volume_label.config(
        text=f"Estimated Volume: {estimated_volume:.2f} mm³"
    )


# =========================
# 3D + EXPORT
# =========================
def show_3d():

    global last_mesh

    if len(volume) == 0:
        messagebox.showerror(
            "Error",
            "No processed slices available.\nPress 'Accept ALL' first."
        )
        return

    vol = np.stack(volume, axis=0).astype(np.uint8)

    # Filter blobs
    vol = filter_blobs(
        vol,
        min_volume_voxels=int(min_blob_entry.get()),
        keep_largest=keep_largest_var.get()
    )

    square_size, thickness = processed_calibration

    sampled = vol[::2, ::2, ::2]
    if min(sampled.shape) < 2 or sampled.min() == sampled.max():
        last_mesh = None
        messagebox.showwarning("3D view", "The display volume is too small, empty, or uniform for surface extraction. Quantitative areas remain available.")
        return
    try:
        last_mesh = build_mesh(vol, square_size, thickness)
    except (ImportError, ValueError, RuntimeError) as exc:
        last_mesh = None
        messagebox.showerror("3D view", str(exc))
        return

    p = multiprocessing.Process(
        target=show_3d_process,
        args=(vol, square_size, thickness)
    )

    p.start()


def update_hsv():

    if restoring_settings:
        return
    invalidate_results()

    for key in params:
        params[key] = slider_vars[key].get()

    update_display()

def toggle_hsv_panel():

    if hsv_frame.winfo_ismapped():
        hsv_frame.pack_forget()
    else:
        hsv_frame.pack()

# =========================
# SAVE PARAMETERS
# =========================
def parameter_snapshot():
    if not files or image_shape is None:
        raise ValueError("Load an image dataset before saving parameters.")
    data = dict(params, schema_version=2, software_version=SOFTWARE_VERSION,
                roi=list(roi) if roi is not None else None,
                original_image_shape_hw=image_shape,
                ordered_source_files=[os.path.basename(f) for f in files],
                square_size=positive_number(square_entry.get(), "ROI width"),
                slice_thickness=positive_number(thickness_entry.get(), "Axial spacing"),
                min_blob_size=int(min_blob_entry.get()),
                keep_largest=bool(keep_largest_var.get()),
                morphology=dict(MORPHOLOGY), quantitative_resolution="native ROI pixels",
                resize_before_segmentation=False,
                volume_mask="unfiltered segmentation; 3D blob filtering is visualization-only",
                sampling_convention="sum of sectional areas times uniform axial spacing; terminal coverage must be verified experimentally")

    validate_parameters(data)
    return data


def validate_parameters(data):
    """Validate a complete snapshot without changing processing or GUI state."""
    if not isinstance(data, dict):
        raise ValueError("Settings must be a JSON object.")
    if data.get("schema_version") != 2:
        raise ValueError("Legacy settings omit reproducibility metadata. Select the original ROI and save a new settings file.")
    required = set(params) | {"roi", "square_size", "slice_thickness", "min_blob_size", "keep_largest"}
    if required - data.keys():
        raise ValueError("Missing settings: " + ", ".join(sorted(required - data.keys())))
    if (data.get("resize_before_segmentation") is not False or
            data.get("quantitative_resolution") != "native ROI pixels"):
        raise ValueError("Settings use an unsupported processing resolution.")
    morph = data.get("morphology")
    if not isinstance(morph, dict) or set(morph) != set(MORPHOLOGY):
        raise ValueError("Invalid morphology settings.")
    for key, value in morph.items():
        if type(value) is not int or value < (1 if key == "kernel_size" else 0):
            raise ValueError("Morphology requires a positive kernel and nonnegative integer iterations.")
    if morph["kernel_size"] % 2 != 1:
        raise ValueError("Morphology kernel size must be odd.")
    shape = data.get("original_image_shape_hw")
    if not isinstance(shape, list) or len(shape) != 2 or any(type(v) is not int or v <= 0 for v in shape):
        raise ValueError("Invalid original image dimensions.")
    if not files:
        raise ValueError("Load the matching dataset before restoring settings.")
    names = data.get("ordered_source_files")
    available = {os.path.basename(f): f for f in files}
    if (not isinstance(names, list) or any(not isinstance(n, str) for n in names)
            or len(names) != len(set(names)) or set(names) != set(available)
            or len(files) != len(names)):
        raise ValueError("Saved source filenames do not match this dataset (missing, extra or duplicate names).")
    ordered = [available[n] for n in names]
    if image_shape != shape:
        raise ValueError("Saved image dimensions do not match this dataset.")
    selected = data["roi"]
    if selected is not None:
        if (not isinstance(selected, (list, tuple)) or len(selected) != 4
                or any(type(v) is not int for v in selected)):
            raise ValueError("ROI must contain four integer pixel coordinates.")
        x, y, w, h = selected
        if min(x, y) < 0 or min(w, h) <= 0 or x+w > shape[1] or y+h > shape[0] or w != h:
            raise ValueError("ROI must be square and inside the original image.")
    elif shape[0] != shape[1]:
        raise ValueError("A square ROI is required for rectangular images.")
    for path in ordered:
        img = cv2.imread(path)
        if img is None or list(img.shape[:2]) != shape:
            raise ValueError(f"Unreadable image or inconsistent dimensions: {path}")
    for ch in ("H", "S", "V"):
        lo, hi = data[ch+"min"], data[ch+"max"]
        if type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi <= (179 if ch == "H" else 255):
            raise ValueError("Invalid HSV thresholds (H: 0–179; S and V: 0–255; min <= max).")
    positive_number(data["square_size"], "ROI width")
    positive_number(data["slice_thickness"], "Axial spacing")
    if type(data["min_blob_size"]) is not int or data["min_blob_size"] < 0 or type(data["keep_largest"]) is not bool:
        raise ValueError("Invalid blob filter settings.")
    return ordered


def restore_parameters(data):
    global roi, files, current_idx, restoring_settings
    ordered = validate_parameters(data)
    restoring_settings = True
    try:
        files, current_idx = ordered, 0
        roi = tuple(data["roi"]) if data["roi"] is not None else None
        params.update({key: data[key] for key in params})
        MORPHOLOGY.update(data["morphology"])
        controls = [(square_entry, data["square_size"]), (thickness_entry, data["slice_thickness"]),
                    (min_blob_entry, data["min_blob_size"])]
        controls += [(entry, MORPHOLOGY[key]) for key, entry in morphology_entries.items()]
        for entry, value in controls:
            entry.delete(0, tk.END)
            entry.insert(0, str(value))
        keep_largest_var.set(data["keep_largest"])
        for key, var in slider_vars.items():
            var.set(params[key])
    finally:
        restoring_settings = False
    invalidate_results()


def apply_morphology():
    previous = dict(MORPHOLOGY)
    try:
        candidate = {key: int(entry.get()) for key, entry in morphology_entries.items()}
        MORPHOLOGY.update(candidate)
        parameter_snapshot()
    except (ValueError, TypeError) as exc:
        MORPHOLOGY.update(previous)
        messagebox.showerror("Morphology", str(exc))
        return
    invalidate_results()
    update_display()


def save_parameters(path=None):
    try:
        data = parameter_snapshot()
        if path is None:
            path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="segmentation_params.json")
        if path:
            path = os.path.abspath(path)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(path),
                                                 suffix=".tmp", delete=False) as stream:
                    temporary = stream.name
                    json.dump(data, stream, indent=4, allow_nan=False)
                os.replace(temporary, path)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
        return bool(path)
    except (ValueError, OSError) as exc:
        messagebox.showerror("Save settings", str(exc))


def load_parameters(path=None):
    if path is None:
        path = filedialog.askopenfilename(filetypes=[("JSON settings", "*.json")],
                                          initialdir=os.path.dirname(files[0]) if files else ".")
    if not path:
        return
    try:
        with open(path) as f:
            restore_parameters(json.load(f))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        messagebox.showerror("Load settings", str(exc))
        return
    update_display()

def export_stl():
    global last_mesh

    if last_mesh is None:
        print("No mesh available!")
        return

    filename = filedialog.asksaveasfilename(defaultextension=".stl")
    if filename:
        last_mesh.save(filename)
        print("Saved STL:", filename)

# =========================
# GUI
# =========================
def main(startup_folder=None):
    global root, panel_original, panel_mask, panel_overlay, volume_label
    global square_entry, thickness_entry, min_blob_entry, keep_largest_var
    global hsv_frame, slider_vars
    root = tk.Tk()
    root.title("Sand Volume Tool PRO")
    
    frame = tk.Frame(root)
    frame.pack()
    
    panel_original = tk.Label(frame)
    panel_original.grid(row=0, column=0)
    panel_mask = tk.Label(frame)
    panel_mask.grid(row=0, column=1)
    panel_overlay = tk.Label(frame)
    panel_overlay.grid(row=0, column=2)
    
    btn_frame = tk.Frame(root)
    btn_frame.pack()
    
    tk.Button(btn_frame, text="Load", command=load_images).pack(side="left")
    tk.Button( btn_frame, text="Save Params", command=save_parameters).pack(side="left")
    tk.Button( btn_frame, text="Load Params", command=load_parameters).pack(side="left")
    tk.Button(btn_frame, text="HSV Tune", command=toggle_hsv_panel).pack(side="left")
    tk.Button(btn_frame, text="ROI", command=select_roi).pack(side="left")
    tk.Button(btn_frame, text="Prev", command=prev_image).pack(side="left")
    tk.Button(btn_frame, text="Next", command=next_image).pack(side="left")
    tk.Button(btn_frame, text="Accept ALL", command=accept_all_slices).pack(side="left")
    tk.Button(btn_frame, text="3D View", command=show_3d).pack(side="left")
    tk.Button(btn_frame, text="Export STL", command=export_stl).pack(side="left")
    
    # Blob filter controls
    filter_frame = tk.Frame(root)
    filter_frame.pack()
    
    keep_largest_var = tk.BooleanVar(value=True)
    tk.Checkbutton(filter_frame, text="Keep largest blob only",
                   variable=keep_largest_var).pack()
    
    tk.Label(filter_frame, text="Min blob size (voxels)").pack()
    min_blob_entry = tk.Entry(filter_frame)
    min_blob_entry.insert(0, "1000")
    min_blob_entry.pack()
    
    # Physical inputs
    phys_frame = tk.Frame(root)
    phys_frame.pack()
    
    volume_label = tk.Label(
        root,
        text="Estimated Volume: --- mm³",
        font=("Arial", 12, "bold")
    )
    volume_label.pack(pady=5)
    
    
    # =========================
    # HSV PANEL
    # =========================
    hsv_frame = tk.Frame(root)
    
    slider_vars = {}
    
    channels = ["H", "S", "V"]
    
    for row, ch in enumerate(channels):
    
        # Label
        tk.Label(
            hsv_frame,
            text=ch,
            font=("Arial", 10, "bold")
        ).grid(row=row, column=0, padx=5)
    
        # MIN slider
        min_key = f"{ch}min"
    
        min_var = tk.IntVar(value=params[min_key])
    
        tk.Label(hsv_frame, text="Min").grid(row=row, column=1)
    
        min_slider = tk.Scale(
            hsv_frame,
            from_=0,
            to=179 if ch == "H" else 255,
            orient="horizontal",
            variable=min_var,
            command=lambda x: update_hsv(),
            length=150
        )
    
        min_slider.grid(row=row, column=2)
    
        slider_vars[min_key] = min_var
    
        # MAX slider
        max_key = f"{ch}max"
    
        max_var = tk.IntVar(value=params[max_key])
    
        tk.Label(hsv_frame, text="Max").grid(row=row, column=3)
    
        max_slider = tk.Scale(
            hsv_frame,
            from_=0,
            to=179 if ch == "H" else 255,
            orient="horizontal",
            variable=max_var,
            command=lambda x: update_hsv(),
            length=150
        )
    
        max_slider.grid(row=row, column=4)
    
        slider_vars[max_key] = max_var
    
    #tk.Label(phys_frame, text="Square size (mm)").grid(row=0, column=0)
    tk.Label( phys_frame, text="ROI physical width (mm)").grid(row=0, column=0)
    
    square_entry = tk.Entry(phys_frame)
    square_entry.insert(0, "25")
    square_entry.grid(row=0, column=1)
    
    tk.Label(phys_frame, text="Slice thickness (mm)").grid(row=1, column=0)
    thickness_entry = tk.Entry(phys_frame)
    thickness_entry.insert(0, "0.5")
    thickness_entry.grid(row=1, column=1)
    
    for entry in (square_entry, thickness_entry):
        entry.bind("<KeyRelease>", lambda event: invalidate_results())
    morph_frame = tk.Frame(root)
    morph_frame.pack()
    for column, (key, value) in enumerate(MORPHOLOGY.items()):
        tk.Label(morph_frame, text=key.replace("_", " ")).grid(row=0, column=column)
        entry = tk.Entry(morph_frame, width=8)
        entry.insert(0, str(value))
        entry.grid(row=1, column=column)
        morphology_entries[key] = entry
    tk.Button(morph_frame, text="Apply morphology", command=apply_morphology).grid(row=1, column=3)
    if startup_folder:
        root.after_idle(lambda: load_images(startup_folder))
    elif os.path.isfile("segmentation_params.json"):
        root.after_idle(lambda: load_images(os.getcwd()))
    root.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    multiprocessing.set_start_method("spawn", force=True)
    main(sys.argv[1] if len(sys.argv) > 1 else None)
