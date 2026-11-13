"""stills_sheet.py <png folder> <out.jpg> [width] - hstack every PNG in a folder (look-tier stills) into one sheet."""
import subprocess, sys, glob
fs = sorted(glob.glob(sys.argv[1] + '/*.png')); w = sys.argv[3] if len(sys.argv) > 3 else '270'
args = [a for f in fs for a in ('-i', f)]
fc = (''.join(f'[{i}]scale={w}:-2[v{i}];' for i in range(len(fs))) + ''.join(f'[v{i}]' for i in range(len(fs))) + f'hstack={len(fs)}') if len(fs) > 1 else f'[0]scale={w}:-2'
subprocess.run(['ffmpeg', '-v', 'error', '-y', *args, '-filter_complex', fc, sys.argv[2]], check=True)
