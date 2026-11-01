import os, sys, glob, time
#Replace FILE_PATH string value with the PATH TO YOUR GAME MUSIC eg C:\game\romfs\Sound\stream
FILE_PATH = r'FILE_PATH'
#Replace OUTPUT_PATH string value with the PATH TO WHERE YOU WANT TO DUMP TO eg C:\game\output
OUTPUT_PATH = r'OUTPUT_PATH'
sys.path.insert(0, FILE_PATH)
import nop2ogg

#Replace FILE_PATH with the PATH TO YOUR GAME eg C:\game\romfs\Sound\stream
STREAM = FILE_PATH
OUT = OUTPUT_PATH
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(OUT, 'convert_log.txt')

# Only top-level .opus files in `stream`; V_EN / V_JP are subfolders and are naturally excluded.
files = sorted(glob.glob(os.path.join(STREAM, '*.opus')))
print(f"total files: {len(files)}")

log = open(LOG, 'a', encoding='utf-8')
ok = skip = fail = 0
t0 = time.time()
for idx, src in enumerate(files, 1):
    base = os.path.splitext(os.path.basename(src))[0]
    dst = os.path.join(OUT, base + '.ogg')
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        skip += 1
        continue
    try:
        n, ch, sr, ps = nop2ogg.convert(src, dst)
        dur = (n * 960 - ps) / 48000.0
        ok += 1
        line = f"OK   {base:32s} {n:6d} pkts {ch}ch ~{dur:7.2f}s -> {os.path.getsize(dst)} bytes"
    except Exception as e:
        fail += 1
        line = f"FAIL {base:32s} {type(e).__name__}: {e}"
    if line.startswith("FAIL"):
        log.write(line + "\n"); log.flush()
    if idx % 25 == 0 or idx == len(files):
        el = time.time() - t0
        print(f"[{idx}/{len(files)}] ok={ok} skip={skip} fail={fail} elapsed={el:.0f}s")

el = time.time() - t0
summary = (f"\n=== DONE in {el:.0f}s === ok={ok} skip(existing)={skip} fail={fail} total={len(files)}\n")
log.write(summary); log.close()
print(summary)
print(f"log: {LOG}")
