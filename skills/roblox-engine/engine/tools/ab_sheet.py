"""ab_sheet.py before.mp4 after.mp4 out.jpg [n=8] [w=300] - the SAME n frames of two cuts of one story, before on the top row,
after below (evidence sheets for acting/camera changes). Frames are spread evenly over the shorter video."""
import subprocess, sys

a, b, out = sys.argv[1:4]; n = int(sys.argv[4]) if len(sys.argv) > 4 else 8; w = int(sys.argv[5]) if len(sys.argv) > 5 else 300
def count(p):
    return int(subprocess.run(['ffprobe', '-v', 'error', '-count_packets', '-select_streams', 'v:0', '-show_entries', 'stream=nb_read_packets',
                               '-of', 'csv=p=0', p], capture_output=True, text=True).stdout.strip())
m = min(count(a), count(b)); fr = [round((i + 0.5) * m / n) for i in range(n)]
sel = '+'.join(f'eq(n\\,{f})' for f in fr)
fc = f"[0]select='{sel}',scale={w}:-2,tile={n}x1[x];[1]select='{sel}',scale={w}:-2,tile={n}x1[y];[x][y]vstack"
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', a, '-i', b, '-filter_complex', fc, '-frames:v', '1', '-q:v', '3', out], check=True)
print('AB_SHEET', out, 'frames', fr)
