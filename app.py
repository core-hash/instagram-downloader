import io
import os
import re
import shutil
import tempfile
import zipfile
from urllib.parse import unquote

import yt_dlp
from flask import Flask, jsonify, render_template, request, send_file
from flask_cors import CORS

app = Flask(__name__)

ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:5005,http://127.0.0.1:5005,https://instagram-downloader-687.pages.dev",
).split(",")
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})

SHORTCODE_RE = re.compile(r"instagram\.com/(?:[^/]+/)?(p|reel|reels|tv)/([A-Za-z0-9_-]+)")
MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".heic", ".m4a"}
NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n# Auto-generated.\n\n"


def extract_shortcode(url: str) -> str | None:
    if not url:
        return None
    match = SHORTCODE_RE.search(url)
    return match.group(2) if match else None


def write_cookies_file(path: str) -> bool:
    sessionid = os.environ.get("IG_SESSIONID")
    if not sessionid:
        return False
    decoded = unquote(sessionid)
    csrftoken = os.environ.get("IG_CSRFTOKEN", "")
    ds_user_id = os.environ.get("IG_DS_USER_ID") or decoded.split(":")[0]
    mid = os.environ.get("IG_MID", "")
    ig_did = os.environ.get("IG_DID", "")

    expiry = "2147483647"
    rows = []
    for name, value in (
        ("sessionid", sessionid),
        ("csrftoken", csrftoken),
        ("ds_user_id", ds_user_id),
        ("mid", mid),
        ("ig_did", ig_did),
    ):
        if value:
            rows.append(f".instagram.com\tTRUE\t/\tTRUE\t{expiry}\t{name}\t{value}")

    with open(path, "w") as f:
        f.write(NETSCAPE_HEADER)
        f.write("\n".join(rows) + "\n")
    return True


def download_via_ytdlp(url: str, target_dir: str, shortcode: str) -> None:
    cookies_path = os.path.join(target_dir, "_cookies.txt")
    has_cookies = write_cookies_file(cookies_path)

    out_template = os.path.join(target_dir, f"{shortcode}_%(autonumber)02d.%(ext)s")

    ydl_opts = {
        "outtmpl": out_template,
        "autonumber_start": 1,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "format": "best",
        "noplaylist": False,
        "writeinfojson": False,
        "writedescription": True,
        "writethumbnail": False,
        "ignoreerrors": False,
        "user_agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1 "
            "Instagram 327.0.0.39.93 (iPhone15,3; iOS 17_4; en_US; en; scale=3.00; 1290x2796; 615279337)"
        ),
    }
    if has_cookies:
        ydl_opts["cookiefile"] = cookies_path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
    finally:
        if os.path.exists(cookies_path):
            try:
                os.remove(cookies_path)
            except OSError:
                pass


def renumber_slides(post_dir: str, shortcode: str) -> None:
    entries = []
    for name in os.listdir(post_dir):
        path = os.path.join(post_dir, name)
        if not os.path.isfile(path):
            continue
        stem, ext = os.path.splitext(name)
        if ext.lower() not in MEDIA_EXTS:
            continue
        m = re.search(r"_(\d+)$", stem)
        idx = int(m.group(1)) if m else 0
        entries.append((idx, name, ext.lower()))

    if not entries:
        return

    entries.sort(key=lambda e: e[0])
    width = max(2, len(str(len(entries))))

    for slot, (_, original, ext) in enumerate(entries, start=1):
        new_name = f"{str(slot).zfill(width)}{ext}"
        src = os.path.join(post_dir, original)
        dst = os.path.join(post_dir, new_name)
        if src != dst and not os.path.exists(dst):
            os.replace(src, dst)


def zip_directory(source_dir: str) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(source_dir):
            for name in files:
                if name.startswith("_"):
                    continue
                full = os.path.join(root, name)
                arcname = os.path.relpath(full, source_dir)
                zf.write(full, arcname)
    buffer.seek(0)
    return buffer


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/download", methods=["POST"])
def download():
    data = request.get_json(silent=True) or request.form
    url = (data.get("url") or "").strip()
    shortcode = extract_shortcode(url)
    if not shortcode:
        return jsonify({"error": "URL no válida. Usa una URL de post, reel o IGTV de Instagram."}), 400

    workdir = tempfile.mkdtemp(prefix="ig_")
    try:
        try:
            download_via_ytdlp(url, workdir, shortcode)
        except yt_dlp.utils.DownloadError as e:
            msg = str(e)
            low = msg.lower()
            if "login" in low or "private" in low or "logged" in low:
                return jsonify({"error": "Esta publicación requiere login o es privada. Verifica que IG_SESSIONID esté actualizado en Render."}), 401
            if "rate" in low or "wait" in low or "429" in msg:
                return jsonify({"error": "Instagram aplicó rate-limit. Espera unos minutos y reintenta."}), 429
            if "404" in msg or "not found" in low:
                return jsonify({"error": "Publicación no encontrada o eliminada."}), 404
            return jsonify({"error": f"Error de yt-dlp: {msg[:300]}"}), 500
        except Exception as e:
            return jsonify({"error": f"Error al descargar: {str(e)[:300]}"}), 500

        media_files = [
            f for f in os.listdir(workdir)
            if not f.startswith("_") and os.path.splitext(f)[1].lower() in MEDIA_EXTS
        ]
        if not media_files:
            return jsonify({"error": "yt-dlp no devolvió archivos descargables."}), 500

        renumber_slides(workdir, shortcode)
        zip_buffer = zip_directory(workdir)
        return send_file(
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"instagram_{shortcode}.zip",
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@app.route("/healthz")
def healthz():
    return {"ok": True}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5005"))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=False)
