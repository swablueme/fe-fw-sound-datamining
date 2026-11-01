import nop2ogg
import os
import sys
import glob
import time
# Replace FILE_PATH string value with the PATH TO YOUR GAME MUSIC eg C:\game\romfs\Sound\stream
FILE_PATH = r'FILE_PATH'
# Replace OUTPUT_PATH string value with the PATH TO WHERE YOU WANT TO DUMP TO eg C:\game\output
OUTPUT_PATH = r'OUTPUT_PATH'
sys.path.insert(0, FILE_PATH)

# Replace FILE_PATH with the PATH TO YOUR GAME eg C:\game\romfs\Sound\stream
STREAM = FILE_PATH
OUT = OUTPUT_PATH
os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(OUT, 'convert_log.txt')

# Opus decodes at a fixed 48 kHz, so durations use a 48000 Hz sample rate
OPUS_SAMPLE_RATE = 48000.0
OPUS_PACKET_FRAME_SIZE = 960  # 20 ms of audio per opus packet, in 48 kHz samples

# Only top-level .opus files in `stream`; V_EN / V_JP are subfolders and are naturally excluded.
opus_files = sorted(glob.glob(os.path.join(STREAM, '*.opus')))
print(f"total files: {len(opus_files)}")

log = open(LOG, 'a', encoding='utf-8')
ok = skip = fail = 0
t0 = time.time()
for file_index, opus_path in enumerate(opus_files, 1):
    base = os.path.splitext(os.path.basename(opus_path))[0]
    ogg_path = os.path.join(OUT, base + '.ogg')
    if os.path.exists(ogg_path) and os.path.getsize(ogg_path) > 0:
        skip += 1
        continue
    try:
        packet_count, channel_count, sample_rate, pre_skip = nop2ogg.convert(opus_path, ogg_path)
        duration_seconds = (packet_count * OPUS_PACKET_FRAME_SIZE - pre_skip) / OPUS_SAMPLE_RATE
        ok += 1
        line = f"OK   {base:32s} {packet_count:6d} pkts {channel_count}ch ~{duration_seconds:7.2f}s -> {os.path.getsize(ogg_path)} bytes"
    except Exception as error:
        fail += 1
        line = f"FAIL {base:32s} {type(error).__name__}: {error}"
    if line.startswith("FAIL"):
        log.write(line + "\n")
        log.flush()
    if file_index % 25 == 0 or file_index == len(opus_files):
        el = time.time() - t0
        print(
            f"[{file_index}/{len(opus_files)}] ok={ok} skip={skip} fail={fail} elapsed={el:.0f}s")

el = time.time() - t0
summary = (
    f"\n=== DONE in {el:.0f}s === ok={ok} skip(existing)={skip} fail={fail} total={len(files)}\n")
log.write(summary)
log.close()
print(summary)
print(f"log: {LOG}")
