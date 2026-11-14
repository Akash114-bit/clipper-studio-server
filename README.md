# Clipper Studio server

Paste a YouTube link (or upload a file), set start and end, add a title, caption, watermark, look and fades, and the finished MP4 downloads straight from your website.

## Run locally
1. Install Python 3.10+ and FFmpeg (with the drawtext filter and DejaVu fonts).
2. `pip install -r requirements.txt`
3. `uvicorn app:app --port 8000` then open http://localhost:8000

## Put it on your website
A static host (Netlify, GitHub Pages) cannot do this. You need a server that runs Python and FFmpeg:
- Easiest: push these files to GitHub and deploy with the included `Dockerfile` on Render, Railway or Fly.io. Then link to it from your site, or put it on a subdomain like clips.yoursite.com.
- Free tiers are slow and sleep when idle. A small paid server is more reliable.
- Keep `yt-dlp` updated (`pip install -U yt-dlp`); YouTube changes often.
- YouTube often blocks cloud server IPs. If downloads fail with a sign-in or bot error, export your own browser cookies and set `COOKIES=/path/cookies.txt`, or use uploads instead.

## Settings (environment variables)
`MAX_CLIP` max clip seconds (default 180), `FONT` path to a bold .ttf, `COOKIES` cookies file for yt-dlp.

## Rules
Only use videos you own, have permission to use, or that are licensed for reuse. Downloading other people's YouTube videos can break YouTube's terms. Before opening this to the public, add login and rate limits.
