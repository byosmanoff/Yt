from flask import Flask, request, jsonify, render_template, send_file, send_from_directory
import yt_dlp
import imageio_ffmpeg
import os
import tempfile
import shutil
import re

app = Flask(__name__)
FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
COOKIES_PATH = "/etc/secrets/cookies.txt"


def get_common_opts():
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
            }
        },
    }
    if os.path.exists(COOKIES_PATH):
        opts["cookiefile"] = COOKIES_PATH
    return opts


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/sitemap.xml")
def sitemap():
    return send_from_directory(app.root_path, "sitemap.xml", mimetype="application/xml")


@app.route("/robots.txt")
def robots():
    return send_from_directory(app.root_path, "robots.txt", mimetype="text/plain")


@app.route("/api/info", methods=["POST"])
def info():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()

    if not url:
        return jsonify({"error": "Zəhmət olmasa bir YouTube linki daxil edin."}), 400

    ydl_opts = {
        **get_common_opts(),
        "skip_download": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=False)
    except Exception:
        return jsonify({"error": "Video tapılmadı. Linki yoxlayıb yenidən cəhd edin."}), 400

    duration = result.get("duration") or 0
    mins = int(duration) // 60
    secs = int(duration) % 60

    return jsonify({
        "title": result.get("title"),
        "thumbnail": result.get("thumbnail"),
        "channel": result.get("uploader") or result.get("channel") or "",
        "duration": f"{mins}:{secs:02d}",
    })


@app.route("/api/download")
def download():
    url = (request.args.get("url") or "").strip()
    mode = request.args.get("mode", "video")
    quality = request.args.get("quality", "720")

    if not url:
        return jsonify({"error": "URL boşdur."}), 400

    if not re.match(r"^[0-9]{2,4}$", quality):
        quality = "720"

    tmp_dir = tempfile.mkdtemp(prefix="ytdl_")
    out_template = os.path.join(tmp_dir, "%(title).80s.%(ext)s")

    try:
        if mode == "audio":
            ydl_opts = {
                **get_common_opts(),
                "format": "bestaudio/best",
                "outtmpl": out_template,
                "ffmpeg_location": FFMPEG_PATH,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": quality,
                }],
            }
        else:
            fmt = (
                f"bestvideo[height<={quality}][ext=mp4]+bestaudio[ext=m4a]/"
                f"best[height<={quality}][ext=mp4]/best[height<={quality}]/best"
            )
            ydl_opts = {
                **get_common_opts(),
                "format": fmt,
                "outtmpl": out_template,
                "ffmpeg_location": FFMPEG_PATH,
                "merge_output_format": "mp4",
            }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        files = [f for f in os.listdir(tmp_dir) if not f.endswith(".part")]
        if not files:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return jsonify({"error": "Fayl hazırlana bilmədi."}), 500

        filepath = os.path.join(tmp_dir, files[0])
        filename = files[0]

        response = send_file(filepath, as_attachment=True, download_name=filename)

        @response.call_on_close
        def cleanup():
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return response

    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({"error": "Endirmə zamanı xəta baş verdi. Yenidən cəhd edin."}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
