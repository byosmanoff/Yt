from flask import Flask, request, jsonify, send_file, render_template
import yt_dlp
import os
import re
import uuid
import threading
import time

app = Flask(__name__)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# How long a finished file is kept on disk before being auto-deleted (seconds)
FILE_TTL_SECONDS = 30 * 60

# Domains we accept — everything else is rejected before it ever reaches yt-dlp
ALLOWED_DOMAINS = [
    "youtube.com", "youtu.be", "m.youtube.com",
    "instagram.com", "www.instagram.com",
    "tiktok.com", "www.tiktok.com", "vm.tiktok.com",
    "vimeo.com", "www.vimeo.com",
    "twitter.com", "x.com", "www.twitter.com", "www.x.com",
    "facebook.com", "www.facebook.com", "fb.watch", "m.facebook.com",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_allowed_url(url: str) -> bool:
    match = re.match(r"^https?://([^/]+)/?", url.strip())
    if not match:
        return False
    host = match.group(1).lower()
    host = re.sub(r"^www\.", "", host)
    return any(host == re.sub(r"^www\.", "", d) for d in ALLOWED_DOMAINS)


def human_label(fmt: dict) -> str:
    """Build a short human-readable label like '1080p · 12.4MB' for a yt-dlp format dict."""
    height = fmt.get("height")
    label = f"{height}p" if height else fmt.get("format_note", fmt.get("format_id", "format"))
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    if size:
        mb = size / (1024 * 1024)
        label += f" · {mb:.1f}MB"
    ext = fmt.get("ext")
    if ext and ext != "mp4":
        label += f" · {ext.upper()}"
    return label


def schedule_cleanup(path: str, delay: int = FILE_TTL_SECONDS):
    def _cleanup():
        time.sleep(delay)
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
    threading.Thread(target=_cleanup, daemon=True).start()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/info", methods=["POST"])
def api_info():
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()

    if not url:
        return jsonify({"error": "Missing URL"}), 400
    if not is_allowed_url(url):
        return jsonify({"error": "Unsupported link. Use YouTube, Instagram, TikTok, Vimeo, X/Twitter or Facebook."}), 400

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError:
        return jsonify({"error": "Could not read this link. It may be private, deleted, or unsupported."}), 422
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    raw_formats = info.get("formats") or []

    # Keep only formats that actually carry video, dedupe by height, sort best-first
    seen_heights = set()
    video_formats = []
    for f in sorted(raw_formats, key=lambda x: (x.get("height") or 0), reverse=True):
        if f.get("vcodec") in (None, "none"):
            continue
        height = f.get("height")
        if height in seen_heights:
            continue
        seen_heights.add(height)
        video_formats.append({
            "format_id": f.get("format_id"),
            "label": human_label(f),
            "hasVideo": True,
            "height": height or 0,
        })

    video_formats.sort(key=lambda x: x["height"], reverse=True)

    return jsonify({
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or info.get("channel"),
        "formats": video_formats[:6],
    })


@app.route("/api/download", methods=["GET"])
def api_download():
    url = (request.args.get("url") or "").strip()
    format_id = (request.args.get("format_id") or "").strip()
    audio_only = (request.args.get("audioOnly") or "").lower() == "true"

    if not url:
        return jsonify({"error": "Missing URL"}), 400
    if not is_allowed_url(url):
        return jsonify({"error": "Unsupported link."}), 400

    file_id = uuid.uuid4().hex
    outtmpl = os.path.join(DOWNLOAD_DIR, f"{file_id}.%(ext)s")

    if audio_only:
        ydl_opts = {
            "outtmpl": outtmpl,
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }
    else:
        fmt = f"{format_id}+bestaudio/best" if format_id else "bestvideo+bestaudio/best"
        ydl_opts = {
            "outtmpl": outtmpl,
            "format": fmt,
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            final_path = ydl.prepare_filename(info)
            if audio_only:
                final_path = os.path.splitext(final_path)[0] + ".mp3"
            elif not final_path.endswith(".mp4") and os.path.exists(os.path.splitext(final_path)[0] + ".mp4"):
                final_path = os.path.splitext(final_path)[0] + ".mp4"
    except yt_dlp.utils.DownloadError:
        return jsonify({"error": "Download failed. The video may be private or region-locked."}), 422
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not os.path.exists(final_path):
        return jsonify({"error": "File was not created."}), 500

    safe_title = re.sub(r"[^\w\-. ]", "_", info.get("title") or "video")[:80]
    ext = os.path.splitext(final_path)[1]
    download_name = f"{safe_title}{ext}"

    schedule_cleanup(final_path)

    return send_file(final_path, as_attachment=True, download_name=download_name)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
