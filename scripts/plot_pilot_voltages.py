"""Plot accepted raw LabOS pilot voltage samples; no instrument access.

Run with an isolated plotting environment, for example:
uv run --no-project --isolated --with matplotlib python scripts/plot_pilot_voltages.py \
  --artifact <private-raw-artifact.json> --output <private-output-directory>
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo


def plot(artifact_path, output, refresh=False):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    artifact = json.loads(Path(artifact_path).read_text(encoding='utf-8'))
    canonical = json.dumps(artifact, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=False, allow_nan=False).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    report = artifact['report']
    samples = report['samples']
    if not samples or any(s.get('simulated') is not False for s in samples):
        raise ValueError('Requires accepted real samples; no simulated or placeholder points')
    phases = list(dict.fromkeys(s['phase'] for s in samples))
    roles = sorted({r for s in samples for r, c in s['channels'].items()
                    if 'x_v' in c and 'y_v' in c})
    if not roles:
        raise ValueError('No raw voltage channels in this artifact')
    rows = []
    for s in samples:
        for role in roles:
            c = s['channels'].get(role)
            if c is None:
                continue
            values = [c['x_v'], c['y_v'], s['elapsed_s']]
            if not all(type(v) in (int, float) and math.isfinite(v) for v in values):
                raise ValueError('Nonfinite raw data')
            rows.append({'phase': s['phase'], 'sample_index': s['sample_index'],
                         'elapsed_s': s['elapsed_s'], 'captured_at_utc': s['captured_at_utc'],
                         'role': role, 'x_v': c['x_v'], 'y_v': c['y_v'],
                         'harmonic': c.get('harmonic'),
                         'detection_frequency_hz': c.get('detection_frequency_hz'),
                         'lia_status_raw': c.get('lia_status_raw'),
                         'error_status_raw': c.get('error_status_raw')})
    output = Path(output)
    if output.exists():
        previous = json.loads((output/'plot_provenance.json').read_text())
        if not refresh or previous['artifact_sha256'] != digest:
            raise ValueError('Refresh requires an existing plot of this exact source artifact')
    output.mkdir(parents=True, exist_ok=True)
    with (output/'raw_voltage_samples.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':11,
                         'axes.labelcolor':'#263343', 'text.color':'#263343',
                         'axes.spines.top':False, 'axes.spines.right':False,
                         'pdf.fonttype':42, 'svg.fonttype':'none'})
    fig, axes = plt.subplots(len(roles), len(phases), squeeze=False,
                             figsize=(6.1*len(phases), 3.5*len(roles)+3.2))
    fig.subplots_adjust(left=0.09, right=0.97, bottom=0.34, top=0.72,
                        wspace=0.22, hspace=0.4)
    dark = report['mode']=='dark_a'
    title = 'LabOS | Dark a-axis voltage readbacks' if dark else 'LabOS | Raw voltage readbacks'
    fig.text(0.06, 0.95, title, fontsize=21, weight='bold', va='top')
    plan = report['plan']
    fig.text(0.06, 0.88,
             f"{report['sample_id']}  |  SR830 terminal drive: {plan['excitation_v_rms']*1e3:g} mV RMS, "
             f"{plan['reference_hz']:g} Hz  |  {len(samples)} accepted samples", fontsize=11)
    local = [datetime.fromisoformat(s['captured_at_utc']).astimezone(ZoneInfo('Europe/Helsinki')) for s in samples]
    fig.text(0.06, 0.825,
             f"{local[0]:%Y-%m-%d %H:%M:%S} – {local[-1]:%H:%M:%S %Z}  |  "
             f"Acquisition: {report['status']}  |  Protection verified: {report['protection_verified']}", fontsize=10)
    legend = [Line2D([],[], color='#2461a6', marker='o', linestyle='None', markersize=6, label='X'),
              Line2D([],[], color='#ad7418', marker='s', markerfacecolor='none',
                     linestyle='None', markersize=10, label='Y')]
    fig.legend(handles=legend, loc='upper right', bbox_to_anchor=(0.97,0.80),
               frameon=False, ncol=2)
    all_zero = all(r['x_v']==0 and r['y_v']==0 for r in rows)
    for i, role in enumerate(roles):
        role_rows = [r for r in rows if r['role']==role]
        bound = max(abs(r[k])*1e6 for r in role_rows for k in ('x_v','y_v'))
        bound = 1.0 if bound==0 else 1.15*bound
        for j, phase in enumerate(phases):
            ax = axes[i,j]
            rr = [r for r in role_rows if r['phase']==phase]
            tt = [r['elapsed_s'] for r in rr]
            if not rr:
                ax.set_visible(False)
                continue
            ax.axhline(0,color='#88919a',linewidth=0.8,zorder=0)
            ax.scatter(tt,[r['x_v']*1e6 for r in rr],c='#2461a6',s=40,zorder=3)
            ax.scatter(tt,[r['y_v']*1e6 for r in rr],edgecolors='#ad7418',facecolors='none',
                       marker='s',s=110,linewidths=1.4,zorder=4)
            ax.set_ylim(-bound,bound)
            pad = max((max(tt)-min(tt))*0.18, 0.04)
            ax.set_xlim(min(tt)-pad,max(tt)+pad)
            ax.set_xticks(tt, [f'{t:.3f}' for t in tt])
            ax.set_xlabel('Elapsed time since run start (s)', labelpad=10)
            ax.set_ylabel(f'{role.upper()} voltage input (µV)')
            harmonic = rr[0]['harmonic']
            ax.set_title(f"{harmonic}f detection ({rr[0]['detection_frequency_hz']:g} Hz) · n={len(rr)}",
                         loc='left',fontsize=13,pad=15)
            ax.grid(axis='y', color='#e1e5e9', linewidth=0.7)
            if all_zero:
                ax.text(0.5,0.76,'X and Y overlap at 0 V',transform=ax.transAxes,
                        ha='center',fontsize=11)
    notes = [
        'Instrument-returned points only; no interpolation, noise estimate or fitted response.',
        ('All plotted X/Y replies are 0 V. The ±1 µV display span is not an instrument sensitivity.'
         if all_zero else 'Input sensitivity and resolution are not recorded in this artifact.'),
        'Input sensitivity/resolution unrecorded; sample current and contact polarity uncalibrated.',
        'Raw LIAS/ERRS flags are retained in CSV. Instantaneous overload qualification remains unverified.',
        'Cleanup verified: laser emission OFF, zero current setpoint, 4 mV RMS and XX restored to 1f.'
        if report['protection_verified'] and dark else
        f"Independent output protection verified: {report['protection_verified']}.",
    ]
    for i, note in enumerate(notes):
        fig.text(0.06,0.17-i*0.031,note,fontsize=9)
    fig.savefig(output/'voltage_readbacks.png',dpi=180,facecolor='white')
    fig.savefig(output/'voltage_readbacks.pdf',facecolor='white')
    plt.close(fig)
    metadata = {'artifact_sha256':digest,'source_task_id':report['task_id'],
                'accepted_samples':len(samples),'voltage_rows':len(rows),
                'plot_uses_raw_values':True,'x_y_all_zero':all_zero,
                'units':'raw CSV inV, displayed chart inµV','timezone':'Europe/Helsinki',
                'uncertainty':'not estimated; no independent noise samples or sensitivity metadata'}
    (output/'plot_provenance.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--refresh', action='store_true')
    args=parser.parse_args()
    print(plot(args.artifact,args.output,args.refresh))
