#!/usr/bin/env python3
"""Image-based sensitivity checks; never changes source images or saved settings.

Uses the actual crop_image, segment and measurement functions extracted from
RasPiMilliTome_Reconstruction.py without starting its graphical interface.
"""
import argparse, ast, csv, hashlib, json, math
from pathlib import Path
import cv2
import numpy as np


def write_csv(path, rows):
    if not rows:
        return
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--script', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--axial-displacements', type=float, nargs='+',
                        help='At least two measured travel distances in mm, each over 10 half-turns')
    parser.add_argument('--caliper-resolution', type=float,
                        help='Displayed caliper increment in mm; not an accuracy specification')
    args = parser.parse_args()
    if args.caliper_resolution is not None and (not math.isfinite(args.caliper_resolution) or args.caliper_resolution <= 0):
        raise ValueError('Caliper resolution must be finite and positive.')
    folder = args.dataset.resolve(); output = args.output.resolve()
    if output == folder or folder in output.parents:
        raise ValueError('Use an output folder outside the source dataset.')
    output.mkdir(parents=True, exist_ok=True)
    settings_path = folder / 'segmentation_params.json'
    d = json.loads(settings_path.read_text())
    original_settings = settings_path.read_bytes()
    fnames = d['ordered_source_files']
    if len(fnames) != len(set(fnames)):
        raise ValueError('Duplicate source filenames.')
    base_params = {k: d[k] for k in ['Hmin','Hmax','Smin','Smax','Vmin','Vmax']}
    scope = {'np': np, 'cv2': cv2, 'params': dict(base_params),
             'MORPHOLOGY': dict(d['morphology'])}
    names = {'positive_number','crop_image','segment','measurement'}
    tree = ast.parse(args.script.read_text())
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if {n.name for n in functions} != names:
        raise ValueError('The expected reconstruction functions are missing.')
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(args.script), 'exec'), scope)
    images = [cv2.imread(str(folder / name)) for name in fnames]
    for name, im in zip(fnames, images):
        if im is None or list(im.shape[:2]) != d['original_image_shape_hw']:
            raise ValueError(f'Unreadable image or shape mismatch: {name}')
    roi = tuple(d['roi']); width = float(d['square_size']); dz = float(d['slice_thickness'])
    if width <= 0 or dz <= 0 or roi[2] != roi[3]:
        raise ValueError('Positive calibration and a square ROI are required.')

    def process(selected_roi=roi, change=None, check_saved=False):
        scope['params'].update(base_params)
        scope['params'].update(change or {})
        counts=[]; areas=[]; matching=0
        for i, im in enumerate(images):
            mask = scope['segment'](scope['crop_image'](im, selected_roi))
            counts.append(int(np.count_nonzero(mask)))
            areas.append(scope['measurement'](mask, width))
            if check_saved:
                saved = cv2.imread(str(folder / 'saved_masks' / f'mask_{i:04d}.png'), 0)
                if saved is None or not np.array_equal(mask, saved):
                    raise AssertionError(f'Baseline mask mismatch: {fnames[i]}')
                matching += 1
        return float(sum(areas)*dz), areas, sum(counts), matching

    baseline, areas, base_count, matching = process(check_saved=True)
    archived = list(csv.DictReader((folder/'slice_areas.csv').open()))
    if len(archived) != len(areas): raise AssertionError('CSV row count mismatch.')
    max_area_error = max(abs(a-float(r['Area_mm2'])) for a,r in zip(areas,archived))
    if max_area_error > 1e-8: raise AssertionError('Baseline CSV mismatch.')
    relative = lambda v: 100*(v/baseline-1)

    hsv=[]
    for key, values in [('Hmin',[20,30]),('Hmax',[90,100]),('Smin',[40,60]),('Vmin',[20,60])]:
        for value in values:
            v, _, _, _ = process(change={key:value})
            hsv.append({'bound':key,'value':value,'volume_mm3':v,'change_percent':relative(v)})
    write_csv(output/'hsv_sensitivity.csv',hsv)

    width_rows=[]
    for delta in [-10,-5,-2,0,2,5,10]:
        n=roi[2]+delta
        new_roi=(roi[0]+math.floor(-delta/2),roi[1]+math.floor(-delta/2),n,n)
        v, _, count, _ = process(new_roi)
        predicted=baseline*(roi[2]/n)**2
        width_rows.append({'width_change_pixels':delta,'roi_width_pixels':n,
            'volume_mm3':v,'change_percent':relative(v),
            'foreground_pixel_change':count-base_count,
            'scale_only_prediction_mm3':predicted,'prediction_residual_mm3':v-predicted})
    write_csv(output/'roi_width_sensitivity.csv',width_rows)

    shifts=[]
    for dx,dy in [(-5,0),(5,0),(0,-5),(0,5)]:
        new_roi=(roi[0]+dx,roi[1]+dy,roi[2],roi[3])
        v, _, count, _ = process(new_roi)
        shifts.append({'dx_pixels':dx,'dy_pixels':dy,'volume_mm3':v,
                       'change_percent':relative(v),'foreground_pixel_change':count-base_count})
    write_csv(output/'roi_position_sensitivity.csv',shifts)

    sampling=[]
    for phase in [0,1]:
        selected=areas[phase::2];v=float(sum(selected)*2*dz)
        sampling.append({'phase':phase,'first_source_file':fnames[phase],
                         'image_count':len(selected),'spacing_mm':2*dz,
                         'volume_mm3':v,'change_percent':relative(v)})
    write_csv(output/'axial_sampling.csv',sampling)
    assert abs(np.mean([x['volume_mm3'] for x in sampling])-baseline)<1e-8

    thickness=[]
    for error in [-5,-3,-2,-1,0,1,2,3,5]:
        spacing=dz*(1+error/100);v=float(sum(areas)*spacing)
        thickness.append({'spacing_error_percent':error,'spacing_mm':spacing,
                          'half_turn_angle_error_degrees':180*error/100,
                          'volume_mm3':v,'change_percent':relative(v)})
    for spacing in [0.58,0.59,0.60,0.61,0.62]:
        v=float(sum(areas)*spacing)
        thickness.append({'spacing_error_percent':100*(spacing/dz-1),'spacing_mm':spacing,
                          'half_turn_angle_error_degrees':180*(spacing/dz-1),
                          'volume_mm3':v,'change_percent':relative(v)})
    write_csv(output/'spacing_sensitivity.csv',thickness)

    summary={'source_script_sha256':hashlib.sha256(args.script.read_bytes()).hexdigest(),
        'source_settings_sha256':hashlib.sha256(original_settings).hexdigest(),
        'opencv_version':cv2.__version__,'numpy_version':np.__version__,
        'baseline':{'images':len(images),'volume_mm3':baseline,'physical_width_mm':width,
                    'spacing_mm':dz,'roi_width_pixels':roi[2],
                    'matching_saved_masks':matching,'max_csv_area_error_mm2':max_area_error},
        'hsv_max_abs_change_percent':max(abs(x['change_percent']) for x in hsv),
        'roi_width':width_rows,'roi_position':shifts,'sampling':sampling,'spacing':thickness}
    if args.axial_displacements:
        travel=np.asarray(args.axial_displacements,dtype=float)
        if len(travel)<2 or not np.all(np.isfinite(travel)) or np.any(travel<=0):
            raise ValueError('Measured travel distances must be finite and positive.')
        h=travel/10
        summary['axial_measurement']={'half_turns_per_run':10,'travel_mm':travel.tolist(),
            'mean_advance_per_half_turn_mm':float(h.mean()),
            'sample_sd_of_ten_step_mean_advances_mm':float(h.std(ddof=1)),
            'se_of_mean_advance_mm_assuming_independent_runs':float(h.std(ddof=1)/math.sqrt(len(travel))),
            'mean_lead_per_full_turn_mm':float(2*h.mean()),
            'adjusted_baseline_volume_mm3':float(baseline*h.mean()/dz),
            'difference_from_recorded_spacing_percent':float(100*(h.mean()/dz-1)),
            'caliper_display_resolution_mm':args.caliper_resolution}
    else:
        summary['axial_measurement']={'status':'not supplied; no axial measurement result inferred'}
    (output/'validation_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    assert settings_path.read_bytes()==original_settings
    print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
