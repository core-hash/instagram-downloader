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
    "http://localhost:5005,http://127.0.0.1:5005,https://muse-co.pages.dev,https://instagram-downloader-687.pages.dev",
).split(",")
CORS(
    app,
    resources={r"/api/*": {"origins": ALLOWED_ORIGINS}},
    expose_headers=["Content-Disposition"],
)

MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".heic", ".m4a", ".gif"}
NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n# Auto-generated.\n\n"

PLATFORM_RULES = [
    ("instagram", r"instagram\.com|cdninstagram\.com",                    "gallery-dl"),
    ("tiktok",    r"tiktok\.com|vm\.tiktok\.com",                         "yt-dlp"),
    ("youtube",   r"youtube\.com|youtu\.be|youtube-nocookie\.com",        "yt-dlp"),
    ("twitter",   r"twitter\.com|x\.com",                                 "gallery-dl"),
    ("reddit",    r"reddit\.com|redd\.it",                                "gallery-dl"),
    ("pinterest", r"pinterest\.|pin\.it",                                 "gallery-dl"),
    ("facebook",  r"facebook\.com|fb\.watch|fb\.com",                     "yt-dlp"),
    ("vimeo",     r"vimeo\.com",                                          "yt-dlp"),
    ("twitch",    r"twitch\.tv|clips\.twitch\.tv",                        "yt-dlp"),
    ("threads",   r"threads\.net",                                        "gallery-dl"),
]


def detect_platform(url: str) -> tuple[str | None, str]:
    if not url:
        return (None, "gallery-dl")
    for name, pattern, tool in PLATFORM_RULES:
        if re.search(pattern, url, re.IGNORECASE):
            return (name, tool)
    return (None, "gallery-dl")


def extract_short_id(url: str) -> str:
    """Best-effort identifier extraction for filename fallback."""
    m = re.search(r"/(?:p|reel|reels|tv|status|video|watch|posts|pin)/([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"v=([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"youtu\.be/([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"/(\d+)/?$", url.rstrip("/"))
    if m:
        return m.group(1)
    return "media"


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


YT_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.5 Mobile/15E148 Safari/604.1"
)


def write_yt_cookies_file(path: str) -> bool:
    raw = os.environ.get("YT_COOKIES", "").strip()
    if not raw:
        return False
    if not raw.startswith("# Netscape"):
        raw = NETSCAPE_HEADER + raw
    with open(path, "w") as f:
        f.write(raw)
        if not raw.endswith("\n"):
            f.write("\n")
    return True


def download_via_ytdlp(url: str, target_dir: str) -> tuple[int, str]:
    out_template = os.path.join(target_dir, "%(autonumber)02d.%(ext)s")
    cookies_path = os.path.join(target_dir, "_yt_cookies.txt")
    has_yt_cookies = write_yt_cookies_file(cookies_path)

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-o", out_template,
        "--autonumber-start", "1",
        "--no-warnings",
        "--no-progress",
        "-f", "bestvideo*+bestaudio/best",
        "--merge-output-format", "mp4",
        "--write-info-json",
        "--no-write-thumbnail",
        "--no-playlist",
        "--restrict-filenames",
        "--extractor-args", "youtube:player_client=ios,mweb,web",
        "--user-agent", YT_USER_AGENT,
        "--add-header", "Accept-Language:es-ES,es;q=0.9,en;q=0.8",
    ]
    if has_yt_cookies:
        cmd.extend(["--cookies", cookies_path])
    cmd.append(url)

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
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
        if "info" in name.lower():
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


def derive_basename(meta: dict, fallback_id: str) -> str:
    username = ""
    for key in ("uploader_id", "uploader", "channel", "username", "creator"):
        v = meta.get(key)
        if isinstance(v, str) and v:
            username = v.lstrip("@")
            break
    if not username:
        for key in ("owner", "user", "author", "channel_id"):
            owner = meta.get(key)
            if isinstance(owner, dict):
                username = owner.get("username") or owner.get("name") or owner.get("id") or ""
                if username:
                    break

    date_raw = meta.get("date") or meta.get("post_date") or meta.get("upload_date") or ""
    if isinstance(date_raw, str) and len(date_raw) == 8 and date_raw.isdigit():
        date_str = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
    elif isinstance(date_raw, str):
        date_str = date_raw[:10]
    else:
        date_str = ""

    caption = (meta.get("description") or meta.get("caption")
               or meta.get("title") or meta.get("fulltitle") or "")
    caption_slug = slugify_caption(caption) or fallback_id

    parts = [safe_chunk(p) for p in (username, date_str, caption_slug) if p]
    return "_".join(parts) if parts else f"muse_{fallback_id}"


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


def map_error_response(output: str, platform: str | None) -> tuple[dict, int]:
    low = output.lower()
    if "login" in low or "private" in low or "401" in output or "logged" in low:
        return {"error": f"Login requerido o contenido privado en {platform or 'esta plataforma'}."}, 401
    if "429" in output or "rate" in low or "throttl" in low or "wait" in low:
        return {"error": "La plataforma aplicó rate-limit. Espera unos minutos."}, 429
    if "404" in output or "not found" in low or "does not exist" in low or "no such" in low:
        return {"error": "Publicación no encontrada o eliminada."}, 404
    if "no video formats" in low or "unable to extract" in low:
        return {"error": "No se pudo extraer media de este link. Verifica que sea público y soportado."}, 422
    if "sign in" in low or "confirm you" in low or "not a bot" in low:
        return {"error": "YouTube exige autenticación para esta IP. Considera configurar YT_COOKIES en el servidor con cookies de YouTube."}, 401
    return {"error": f"Error al descargar: {output[:400]}"}, 500


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/download", methods=["POST"])
def download():
    data = request.get_json(silent=True) or request.form
    url = (data.get("url") or "").strip()
    if not url or not re.match(r"^https?://", url):
        return jsonify({"error": "URL no válida. Pega un link completo (con https://)."}), 400

    platform, primary_tool = detect_platform(url)
    fallback_id = extract_short_id(url)

    workdir = tempfile.mkdtemp(prefix="muse_")
    try:
        try:
            if primary_tool == "yt-dlp":
                rc, output = download_via_ytdlp(url, workdir)
                if rc != 0 or not collect_media(workdir):
                    rc2, out2 = download_via_gallery_dl(url, workdir)
                    if rc2 == 0 and collect_media(workdir):
                        rc, output = rc2, out2
            else:
                rc, output = download_via_gallery_dl(url, workdir)
                if rc != 0 or not collect_media(workdir):
                    rc2, out2 = download_via_ytdlp(url, workdir)
                    if rc2 == 0 and collect_media(workdir):
                        rc, output = rc2, out2
        except subprocess.TimeoutExpired:
            return jsonify({"error": "Timeout: la descarga tardó demasiado."}), 504
        except Exception as e:
            return jsonify({"error": f"Error inesperado: {str(e)[:300]}"}), 500

        media = collect_media(workdir)
        if not media:
            err, code = map_error_response(output, platform)
            return jsonify(err), code

        meta = find_metadata(workdir)
        basename = derive_basename(meta, fallback_id)

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
    return {"ok": True, "platforms": [name for name, _, _ in PLATFORM_RULES]}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5005"))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=False)
