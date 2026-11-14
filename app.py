"""Clipper Studio server: YouTube link or uploaded file -> trimmed, edited MP4 downloaded straight from your site."""
import os, shutil, subprocess, textwrap, uuid
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from yt_dlp import YoutubeDL
from yt_dlp.utils import download_range_func

FONT = os.getenv("FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
MAX_CLIP = int(os.getenv("MAX_CLIP", "180"))  # seconds per clip
WORK = Path("work"); WORK.mkdir(exist_ok=True)
app = FastAPI()
SIZE = {"916": (1080, 1920), "11": (1080, 1080)}
LOOK = {"none": "", "vivid": "eq=saturation=1.5:contrast=1.1", "warm": "colorbalance=rs=0.15:bs=-0.15",
        "cool": "colorbalance=rs=-0.12:bs=0.15", "bw": "hue=s=0,eq=contrast=1.1",
        "fade": "eq=contrast=0.85:brightness=0.06:saturation=0.8"}
COLORS = {"white": "white", "yellow": "0xffd23f", "mint": "0x7dffb2", "pink": "0xff7a90"}

def secs(v):
    try: return sum(float(p) * 60 ** i for i, p in enumerate(reversed(v.strip().split(":"))))
    except ValueError: raise HTTPException(400, f"Bad time: {v!r}. Use 1:23 or 83.")

def probe_h(src):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=height",
                        "-of", "csv=p=0", str(src)], capture_output=True, text=True)
    return int(r.stdout.strip() or 720)

def vf_chain(job, h, fmt, look, title, tmode, cap, wm, color, fade, length):
    f = []
    if fmt in SIZE:
        w, h = SIZE[fmt]; f.append(f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}")
    else:
        h = min(1080, h); f.append(f"scale=-2:{h}")
    if LOOK.get(look): f.append(LOOK[look])
    base = f"fontfile={FONT}:borderw=4:bordercolor=black"
    wrap = 18 if fmt == "916" else 30
    def put(name, txt): (job / name).write_text(textwrap.fill(txt, wrap), encoding="utf-8")
    col = COLORS.get(color, "white")
    if title:
        put("title.txt", title); en = "" if tmode == "all" else ":enable='lt(t,3)'"
        f.append(f"drawtext={base}:fontcolor={col}:textfile=title.txt:fontsize={h//26}:x=(w-text_w)/2:y=h*0.08{en}")
    if cap:
        put("cap.txt", cap)
        f.append(f"drawtext={base}:fontcolor={col}:textfile=cap.txt:fontsize={h//32}:x=(w-text_w)/2:y=h*0.78:box=1:boxcolor=black@0.55:boxborderw=24")
    if wm:
        (job / "wm.txt").write_text(wm, encoding="utf-8")
        f.append(f"drawtext={base}:fontcolor=white@0.75:textfile=wm.txt:fontsize={h//55}:x=w-text_w-30:y=h-text_h-30")
    if fade > 0 and length > 2 * fade:
        f.append(f"fade=t=in:st=0:d={fade},fade=t=out:st={length - fade}:d={fade}")
    return ",".join(f)

def fetch(url, job, s, e):
    opts = {"format": "bv*[height<=1080]+ba/b[height<=1080]", "outtmpl": str(job / "src.%(ext)s"),
            "merge_output_format": "mp4", "noplaylist": True, "quiet": True,
            "download_ranges": download_range_func(None, [(s, e)]), "force_keyframes_at_cuts": True}
    if os.getenv("COOKIES"): opts["cookiefile"] = os.getenv("COOKIES")
    with YoutubeDL(opts) as y: y.download([url])
    return next(p for p in job.glob("src.*") if p.suffix != ".part")

@app.post("/api/process")
async def process(url: str = Form(""), file: UploadFile | None = File(None), start: str = Form("0"),
                  end: str = Form(""), fmt: str = Form("916"), look: str = Form("none"),
                  title: str = Form(""), tmode: str = Form("3"), cap: str = Form(""), wm: str = Form(""),
                  color: str = Form("white"), fade: float = Form(0.5), mute: bool = Form(False),
                  own: bool = Form(False)):
    if not own: raise HTTPException(400, "Confirm you own this video or have permission to use it.")
    s, e = secs(start), secs(end)
    length = e - s
    if not (0 < length <= MAX_CLIP): raise HTTPException(400, f"Clip must be between 0 and {MAX_CLIP} seconds.")
    job = WORK / uuid.uuid4().hex; job.mkdir()
    try:
        if file and file.filename:
            src = job / ("src" + Path(file.filename).suffix)
            with open(src, "wb") as o: shutil.copyfileobj(file.file, o)
            ss = s
        elif url.startswith("http"):
            src = await run_in_threadpool(fetch, url, job, s, e); ss = 0
        else: raise HTTPException(400, "Paste a video link or choose a file.")
        h = await run_in_threadpool(probe_h, src)
        vf = vf_chain(job, h, fmt, look, title.strip(), tmode, cap.strip(), wm.strip(), color, fade, length)
        audio = ["-an"] if mute else ["-af", f"afade=t=in:d={fade},afade=t=out:st={max(0, length - fade)}:d={fade}" if fade else "anull", "-c:a", "aac"]
        cmd = ["ffmpeg", "-y", "-ss", str(ss), "-i", str(src), "-t", str(length), "-vf", vf, *audio,
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "out.mp4"]
        r = await run_in_threadpool(lambda: subprocess.run(cmd, cwd=job, capture_output=True, text=True))
        if r.returncode: raise HTTPException(500, "Video processing failed: " + r.stderr[-300:])
    except HTTPException: shutil.rmtree(job, True); raise
    except Exception as ex:
        shutil.rmtree(job, True); m = str(ex)
        if any(k in m for k in ("player response", "Sign in", "bot", "403", "429")):
            m = "YouTube blocked this server from fetching the video. Download the video to your phone, then use Choose file instead."
        raise HTTPException(400, f"Could not get the video: {m[:200]}")
    return FileResponse(job / "out.mp4", filename="edited-clip.mp4", media_type="video/mp4",
                        background=BackgroundTask(shutil.rmtree, job, True))

PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Clipper Studio</title>
<style>body{font:16px/1.5 system-ui;max-width:640px;margin:24px auto;padding:0 16px}input,select,button{font:inherit;padding:8px;margin:2px 0;width:100%;box-sizing:border-box}
.g{display:grid;grid-template-columns:1fr 1fr;gap:8px}button{background:#2f5bff;color:#fff;border:0;border-radius:8px;padding:12px;font-weight:700}#s{min-height:1.5em}</style>
<h1>Clipper Studio</h1><form id=f>
<input name=url placeholder="YouTube link (or choose a file below)"><input type=file name=file accept="video/*">
<div class=g><input name=start placeholder="Start 0:30" required><input name=end placeholder="End 1:15" required></div>
<div class=g><select name=fmt><option value=916>Vertical 9:16<option value=11>Square<option value=orig>Original</select>
<select name=look><option value=none>Normal<option value=vivid>Vivid<option value=warm>Warm<option value=cool>Cool<option value=bw>Black &amp; white<option value=fade>Faded</select>
<input name=title placeholder="Title (top)"><input name=cap placeholder="Caption (bottom)">
<input name=wm placeholder="Watermark"><select name=color><option value=white>White text<option value=yellow>Yellow<option value=mint>Mint<option value=pink>Pink</select>
<select name=tmode><option value=3>Title: first 3 s<option value=all>Title: whole clip</select><select name=fade><option value=0>No fade<option value=0.5 selected>Short fade<option value=1.2>Long fade</select></div>
<label><input type=checkbox name=mute value=true style="width:auto"> Mute original sound</label><br>
<label><input type=checkbox name=own value=true style="width:auto" required> I own this video or have permission to use it</label>
<p><button>Make and download</button><p id=s></form>
<script>f.onsubmit=async e=>{e.preventDefault();s.textContent='Working… this can take a minute or two.';
const r=await fetch('/api/process',{method:'POST',body:new FormData(f)});
if(!r.ok){let m='Failed';try{m=(await r.json()).detail}catch(_){}s.textContent=m;return}
const a=document.createElement('a');a.href=URL.createObjectURL(await r.blob());a.download='edited-clip.mp4';a.click();s.textContent='Done. Your video was downloaded.'}</script>"""

@app.get("/", response_class=HTMLResponse)
def home(): return PAGE
