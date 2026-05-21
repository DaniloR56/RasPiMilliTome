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

OUTPUT_SIZE = 256

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

    pixel_size = square_size / OUTPUT_SIZE

    vol_small = vol[::2, ::2, ::2]
    spacing = (thickness*2, pixel_size*2, pixel_size*2)

    verts, faces, _, _ = measure.marching_cubes(vol_small, level=0.5)
    verts *= spacing

    faces_pv = np.hstack([[3, f[0], f[1], f[2]] for f in faces])
    mesh = pv.PolyData(verts, faces_pv)

    xmin, xmax, ymin, ymax, zmin, zmax = mesh.bounds
    mesh.translate([-xmin, -ymin, -zmin])

    return mesh

# =========================
# LOAD IMAGES
# =========================
def load_images():

    global files, current_idx, volume

    folder = filedialog.askdirectory(
        initialdir="."
    )

    if not folder:
        return

    # Supported image formats
    extensions = [
        "*.jpg",
        "*.jpeg",
        "*.png",
        "*.tif",
        "*.tiff"
    ]

    files = []

    for ext in extensions:
        files.extend(
            glob.glob(os.path.join(folder, ext))
        )

    files = sorted(files)

    print("Loaded files:", len(files))

    if len(files) == 0:
        messagebox.showerror(
            "Error",
            "No image files found!"
        )
        return

    current_idx = 0
    volume = []

    update_display()


# =========================
# ROI
# =========================
def select_roi():
    global roi
    img = cv2.imread(files[current_idx])
    r = cv2.selectROI("Select ROI", img)
    cv2.destroyAllWindows()

    x, y, w, h = r
    size = min(w, h)
    roi = (x, y, size, size)

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

    kernel = np.ones((5,5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, 2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, 1)

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

    # Crop ROI if selected
    if roi is not None:
        x, y, w, h = roi
        img = img[y:y+h, x:x+w]

    # ---------- FULL RESOLUTION PROCESSING ----------

    # Grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # HSV
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # Threshold values
    lower = np.array([
        params["Hmin"],
        params["Smin"],
        params["Vmin"]
    ])

    upper = np.array([
        params["Hmax"],
        params["Smax"],
        params["Vmax"]
    ])

    # Mask
    mask = cv2.inRange(hsv, lower, upper)

    # Morphological cleanup
    kernel = np.ones((3,3), np.uint8)

    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    # Overlay
    overlay = img.copy()
    overlay[mask > 0] = [0,255,0]

    # Save full-resolution publication figures
    #save_stage_images(img, gray, mask, overlay)

    # ---------- SMALL DISPLAY COPIES ----------

    display_size = (400, 400)

    img_disp = cv2.resize(img, display_size)
    mask_disp = cv2.resize(mask, display_size)
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
    # Physical calibration
    square_size = float(square_entry.get())
    thickness = float(thickness_entry.get())
    pixel_size = square_size / OUTPUT_SIZE
    pixel_area = pixel_size * pixel_size
    # Create output folder
    os.makedirs("saved_masks", exist_ok=True)
    for idx, f in enumerate(files):
        img = cv2.imread(f)
        if img is None:
            continue
        # Crop only if ROI exists
        if roi is not None:
            x, y, w, h = roi
            img = img[y:y+h, x:x+w]
        # Resize
        img = cv2.resize(img, (OUTPUT_SIZE, OUTPUT_SIZE))
        # Segment
        mask = segment(img)
        # Boolean slice
        binary_slice = mask > 0
        volume.append(binary_slice)
        # Save mask
        cv2.imwrite(
            f"saved_masks/mask_{idx:04d}.png",
            mask
        )
        # =========================
        # AREA CALCULATION
        # =========================
        area_pixels = np.sum(binary_slice)
        area_mm2 = area_pixels * pixel_area
        slice_areas.append(area_mm2)
        # Cavalieri contribution
        estimated_volume += area_mm2 * thickness
        print(
            f"Slice {idx+1}: "
            f"Area = {area_mm2:.2f} mm²"
        )
    # =========================
    # SAVE CSV REPORT
    # =========================
    csv_path = os.path.join( os.path.dirname(files[0]), "slice_areas.csv")

    with open(csv_path, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            "Slice",
            "Area_mm2"
        ])
        for i, area in enumerate(slice_areas):
            writer.writerow([
                i+1,
                area
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
    show_3d()


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

    square_size = float(square_entry.get())
    thickness = float(thickness_entry.get())

    last_mesh = build_mesh(
        vol,
        square_size,
        thickness
    )

    p = multiprocessing.Process(
        target=show_3d_process,
        args=(vol, square_size, thickness)
    )

    p.start()


def update_hsv():

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
def save_parameters():

    params_to_save = {

        "Hmin": params["Hmin"],
        "Hmax": params["Hmax"],

        "Smin": params["Smin"],
        "Smax": params["Smax"],

        "Vmin": params["Vmin"],
        "Vmax": params["Vmax"],

        "square_size": square_entry.get(),
        "slice_thickness": thickness_entry.get(),

        "min_blob_size": min_blob_entry.get(),

        "keep_largest":
            keep_largest_var.get()
    }

    with open("segmentation_params.json", "w") as f:
        json.dump(params_to_save, f, indent=4)

    print("Parameters saved!")

# =========================
# LOAD PARAMETERS
# =========================
def load_parameters():

    global params

    if not os.path.exists(
        "segmentation_params.json"
    ):
        print("No saved parameter file.")
        return

    with open(
        "segmentation_params.json", "r"
    ) as f:

        data = json.load(f)

    # HSV
    for key in params:
        if key in data:
            params[key] = data[key]

    # GUI fields
    square_entry.delete(0, tk.END)
    square_entry.insert(
        0,
        data.get("square_size", "25")
    )

    thickness_entry.delete(0, tk.END)
    thickness_entry.insert(
        0,
        data.get("slice_thickness", "0.5")
    )

    min_blob_entry.delete(0, tk.END)
    min_blob_entry.insert(
        0,
        data.get("min_blob_size", "1000")
    )

    keep_largest_var.set(
        data.get("keep_largest", True)
    )

    # Update sliders if present
    if "slider_vars" in globals():

        for key in slider_vars:

            slider_vars[key].set(
                params[key]
            )

    print("Parameters loaded!")

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
        to=255,
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
        to=255,
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

if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    root.mainloop()
