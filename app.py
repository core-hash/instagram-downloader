import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from urllib.parse import unquote

from flask import Flask, jsonify, render_template, request, send_file
from flask_cors import CORS

app = Flask(__name__)

ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:5005,http://127.0.0.1:5005,https://instagram-downloader-687.pages.dev",
).split(",")
CORS(
    app,
    resources={r"/api/*": {"origins": ALLOWED_ORIGINS}},
    expose_headers=["Content-Disposition"],
)

MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".heic", ".m4a"}
NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n# Auto-generated.\n\n"


def extract_shortcode(url: str) -> str | None:
    if not url:
        return None
    m = re.search(r"instagram\.com/(?:[^/]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"instagram\.com/stories/(?:highlights/)?[^/]+/(\d+)", url)
    if m:
        return m.group(1)
    return None


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


def download_via_gallery_dl(url: str, target_dir: str) -> tuple[int, str]:
    cookies_path = os.path.join(target_dir, "_cookies.txt")
    has_cookies = write_cookies_file(cookies_path)

    cmd = [
        sys.executable, "-m", "gallery_dl",
        "-D", target_dir,
        "--filename", "{num:>02}.{extension}",
        "--write-metadata",
        "--write-info-json",
        "--no-mtime",
    ]
    if has_cookies:
        cmd.extend(["--cookies", cookies_path])
    cmd.append(url)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    finally:
        if os.path.exists(cookies_path):
            try:
                os.remove(cookies_path)
            except OSError:
                pass

    return proc.returncode, (proc.stderr.strip() or proc.stdout.strip())


def safe_chunk(s: str, max_len: int = 60) -> str:
    s = re.sub(r"[^\w\-.]", "_", s).strip("._")
    return s[:max_len] or "x"


def slugify_caption(caption: str, max_words: int = 6, max_chars: int = 50) -> str:
    if not caption:
        return ""
    text = re.sub(r"[^\w\s\-]", " ", caption, flags=re.UNICODE)
    words = [w for w in text.split() if w]
    slug = "-".join(w.lower() for w in words[:max_words])
    return slug[:max_chars].strip("-_")


def find_metadata(target_dir: str) -> dict:
    candidates = []
    for name in os.listdir(target_dir):
        if name.startswith("_") or not name.endswith(".json"):
            continue
        path = os.path.join(target_dir, name)
        if name == "info.json":
            candidates.insert(0, path)
        else:
            candidates.append(path)

    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def derive_basename(meta: dict, shortcode: str) -> str:
    username = meta.get("username") if isinstance(meta.get("username"), str) else ""
    if not username:
        for key in ("owner", "user", "author"):
            owner = meta.get(key)
            if isinstance(owner, dict):
                username = owner.get("username") or owner.get("name") or ""
                if username:
                    break
            elif isinstance(owner, str):
                username = owner
                break

    date_raw = meta.get("date") or meta.get("post_date") or meta.get("created_at") or ""
    date_str = date_raw[:10] if isinstance(date_raw, str) else ""

    caption = meta.get("description") or meta.get("caption") or meta.get("title") or ""
    caption_slug = slugify_caption(caption) or shortcode

    parts = [safe_chunk(p) for p in (username, date_str, caption_slug) if p]
    return "_".join(parts) if parts else f"instagram_{shortcode}"


def collect_media(target_dir: str) -> list[str]:
    return sorted(
        f for f in os.listdir(target_dir)
        if not f.startswith("_") and os.path.splitext(f)[1].lower() in MEDIA_EXTS
    )


def renumber_slides(target_dir: str) -> None:
    files = collect_media(target_dir)
    if not files:
        return
    width = max(2, len(str(len(files))))
    for slot, name in enumerate(files, start=1):
        ext = os.path.splitext(name)[1].lower()
        new_name = f"{str(slot).zfill(width)}{ext}"
        if new_name == name:
            continue
        src = os.path.join(target_dir, name)
        dst = os.path.join(target_dir, new_name)
        if not os.path.exists(dst):
            os.replace(src, dst)


def zip_directory(source_dir: str) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(source_dir):
            for name in files:
                if name.startswith("_") or name.endswith(".json"):
                    continue
                full = os.path.join(root, name)
                arcname = os.path.relpath(full, source_dir)
                zf.write(full, arcname)
    buffer.seek(0)
    return buffer


def file_to_buffer(path: str) -> io.BytesIO:
    with open(path, "rb") as f:
        buf = io.BytesIO(f.read())
    buf.seek(0)
    return buf


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/download", methods=["POST"])
def download():
    data = request.get_json(silent=True) or request.form
    url = (data.get("url") or "").strip()
    shortcode = extract_shortcode(url)
    if not shortcode:
        return jsonify({"error": "URL no válida. Usa una URL de post, reel, IGTV o story de Instagram."}), 400

    workdir = tempfile.mkdtemp(prefix="ig_")
    try:
        try:
            rc, output = download_via_gallery_dl(url, workdir)
        except subprocess.TimeoutExpired:
            return jsonify({"error": "Timeout: la descarga tardó más de 120s."}), 504
        except Exception as e:
            return jsonify({"error": f"Error inesperado: {str(e)[:300]}"}), 500

        if rc != 0:
            low = output.lower()
            if "login" in low or "private" in low or "401" in output:
                return jsonify({"error": "Login requerido o post privado. Verifica que IG_SESSIONID esté actualizado en Render."}), 401
            if "429" in output or "rate" in low or "throttl" in low:
                return jsonify({"error": "Instagram aplicó rate-limit. Espera unos minutos."}), 429
            if "404" in output or "not found" in low or "does not exist" in low:
                return jsonify({"error": "Publicación no encontrada o eliminada."}), 404
            return jsonify({"error": f"gallery-dl falló: {output[:400]}"}), 500

        media = collect_media(workdir)
        if not media:
            return jsonify({"error": "No se descargó ningún archivo."}), 500

        meta = find_metadata(workdir)
        basename = derive_basename(meta, shortcode)

        if len(media) == 1:
            single = media[0]
            ext = os.path.splitext(single)[1].lower()
            mime, _ = mimetypes.guess_type(single)
            buf = file_to_buffer(os.path.join(workdir, single))
            return send_file(
                buf,
                mimetype=mime or "application/octet-stream",
                as_attachment=True,
                download_name=f"{basename}{ext}",
            )

        renumber_slides(workdir)
        zip_buffer = zip_directory(workdir)
        return send_file(
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{basename}.zip",
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
