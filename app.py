import io
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

import instaloader
from flask import Flask, jsonify, render_template, request, send_file
from flask_cors import CORS

app = Flask(__name__)

ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:5005,http://127.0.0.1:5005,https://instagram-downloader-687.pages.dev",
).split(",")
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})

SHORTCODE_RE = re.compile(r"instagram\.com/(?:[^/]+/)?(p|reel|reels|tv)/([A-Za-z0-9_-]+)")


def extract_shortcode(url: str) -> str | None:
    if not url:
        return None
    match = SHORTCODE_RE.search(url)
    if not match:
        return None
    return match.group(2)


def build_loader(target_dir: str) -> instaloader.Instaloader:
    loader = instaloader.Instaloader(
        dirname_pattern=target_dir,
        filename_pattern="{shortcode}_{date_utc}_{mediaid}",
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=True,
        compress_json=False,
        post_metadata_txt_pattern="{caption}",
        quiet=True,
    )
    session_user = os.environ.get("IG_USERNAME")
    session_pass = os.environ.get("IG_PASSWORD")
    session_file = os.environ.get("IG_SESSION_FILE")
    if session_file and Path(session_file).exists() and session_user:
        try:
            loader.load_session_from_file(session_user, session_file)
        except Exception:
            pass
    elif session_user and session_pass:
        try:
            loader.login(session_user, session_pass)
        except Exception:
            pass
    return loader


MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".heic"}


def renumber_slides(post_dir: str) -> None:
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

    used = set()
    for slot, (_, original, ext) in enumerate(entries, start=1):
        new_name = f"{str(slot).zfill(width)}{ext}"
        if new_name in used:
            continue
        src = os.path.join(post_dir, original)
        dst = os.path.join(post_dir, new_name)
        if src != dst:
            os.replace(src, dst)
        used.add(new_name)


def zip_directory(source_dir: str) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(source_dir):
            for name in files:
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
        loader = build_loader(workdir)
        try:
            post = instaloader.Post.from_shortcode(loader.context, shortcode)
        except instaloader.exceptions.LoginRequiredException:
            return jsonify({"error": "Instagram exige login para esta publicación. Define IG_USERNAME e IG_PASSWORD."}), 401
        except instaloader.exceptions.QueryReturnedNotFoundException:
            return jsonify({"error": "Publicación no encontrada o privada."}), 404
        except Exception as e:
            return jsonify({"error": f"No se pudo obtener la publicación: {e}"}), 500

        try:
            loader.download_post(post, target=shortcode)
        except Exception as e:
            return jsonify({"error": f"Error descargando: {e}"}), 500

        post_dir = os.path.join(workdir, shortcode)
        if not os.path.isdir(post_dir) or not os.listdir(post_dir):
            return jsonify({"error": "La descarga no produjo archivos."}), 500

        renumber_slides(post_dir)
        zip_buffer = zip_directory(post_dir)
        filename = f"instagram_{shortcode}.zip"
        return send_file(
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=filename,
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
