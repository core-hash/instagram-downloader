import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from urllib.parse import unquote

from flask import Flask, jsonify, render_template, request, send_file
from flask_cors import CORS

app = Flask(__name__)

# Public API — allow any origin.
# (No auth, no cookies, no secrets — CORS restriction adds no security here.)
CORS(
    app,
    resources={r"/api/*": {"origins": "*"}},
    expose_headers=["Content-Disposition"],
    supports_credentials=False,
)

MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".heic", ".m4a", ".mp3", ".gif"}
NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n# Auto-generated.\n\n"

PLATFORM_RULES = [
    ("instagram", r"instagram\.com|cdninstagram\.com",   "gallery-dl"),
    ("tiktok",    r"tiktok\.com|vm\.tiktok\.com",        "yt-dlp"),
    ("twitter",   r"twitter\.com|x\.com",                "gallery-dl"),
    ("reddit",    r"reddit\.com|redd\.it",               "gallery-dl"),
    ("pinterest", r"pinterest\.|pin\.it",                "gallery-dl"),
]

UNSUPPORTED_PATTERNS = [
    (r"youtube\.com|youtu\.be",                          "YouTube no está disponible en este momento (bloqueo de IP del servidor)."),
    (r"facebook\.com|fb\.watch|fb\.com",                 "Facebook no está soportado actualmente."),
    (r"vimeo\.com",                                      "Vimeo no está soportado actualmente."),
    (r"twitch\.tv",                                      "Twitch no está soportado actualmente."),
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
    """Write Instagram cookies to a Netscape cookies file.

    Priority:
    1. IG_COOKIES  — full Netscape cookies.txt content (set this from browser export)
    2. IG_SESSIONID — just the session ID (fallback, decoded automatically)
    """
    import base64

    # Option 1: full cookies file (base64-encoded or plain text)
    raw_cookies = os.environ.get("IG_COOKIES", "")
    if raw_cookies:
        # Try base64 decode first, fall back to raw text
        try:
            content = base64.b64decode(raw_cookies).decode("utf-8")
        except Exception:
            content = raw_cookies
        with open(path, "w") as f:
            f.write(content)
        return True

    # Option 2: individual env vars
    sessionid = os.environ.get("IG_SESSIONID")
    if not sessionid:
        return False

    # Always store the URL-decoded value in the cookie file
    decoded_session = unquote(sessionid)
    csrftoken = os.environ.get("IG_CSRFTOKEN", "")
    ds_user_id = os.environ.get("IG_DS_USER_ID") or decoded_session.split(":")[0]
    mid = os.environ.get("IG_MID", "")
    ig_did = os.environ.get("IG_DID", "")

    expiry = "2147483647"
    rows = []
    for name, value in (
        ("sessionid", decoded_session),
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
TIKTOK_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; SM-S928U) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.6478.71 Mobile Safari/537.36"
)


def _is_tiktok(url: str) -> bool:
    return bool(re.search(r"tiktok\.com|vm\.tiktok\.com", url, re.IGNORECASE))

try:
    import imageio_ffmpeg
    FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_PATH = None


def download_via_ytdlp(url: str, target_dir: str, audio_only: bool = False, max_height: int | None = None) -> tuple[int, str]:
    """yt-dlp downloader. Used primarily for TikTok (with multi-attempt fallbacks)."""
    out_template = os.path.join(target_dir, "%(autonumber)02d.%(ext)s")
    is_tt = _is_tiktok(url)
    ua = TIKTOK_USER_AGENT if is_tt else YT_USER_AGENT

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-o", out_template,
        "--autonumber-start", "1",
        "--no-warnings",
        "--no-progress",
        "--write-info-json",
        "--no-write-thumbnail",
        "--no-playlist",
        "--restrict-filenames",
        "--user-agent", ua,
        "--add-header", "Accept-Language:es-ES,es;q=0.9,en;q=0.8",
        "--retries", "3",
        "--fragment-retries", "3",
    ]
    if is_tt:
        cmd.extend([
            "--extractor-args",
            "tiktok:app_name=trill;tiktok:app_version=34.1.2;tiktok:manifest_app_version=2023408050",
        ])
    if FFMPEG_PATH:
        cmd.extend(["--ffmpeg-location", FFMPEG_PATH])

    if audio_only:
        cmd.extend([
            "-f", "bestaudio/best",
            "-x",
            "--audio-format", "mp3",
            "--audio-quality", "0",
        ])
    elif max_height:
        cmd.extend([
            "-f", "bv*+ba/b",
            "-S", f"res:{max_height},vcodec:h264,acodec:m4a",
            "--merge-output-format", "mp4",
        ])
    else:
        cmd.extend([
            "-f", "bv*+ba/b",
            "-S", "res,vcodec:h264,acodec:m4a",
            "--merge-output-format", "mp4",
        ])

    cmd.append(url)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    # TikTok-specific retry with alt API host if the first attempt fails
    if is_tt and proc.returncode != 0 and ("status code 0" in proc.stderr.lower() or "not available" in proc.stderr.lower()):
        cmd_retry = list(cmd)
        for i, a in enumerate(cmd_retry):
            if a == "--extractor-args":
                cmd_retry[i + 1] = "tiktok:api_hostname=api22-normal-c-useast2a.tiktokv.com"
                break
        try:
            proc = subprocess.run(cmd_retry, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
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


def _clean_media_only(workdir: str) -> None:
    """Remove media files (keep metadata JSON, cookies, etc.)."""
    for f in list(os.listdir(workdir)):
        if f.startswith("_") or f.endswith(".json"):
            continue
        try:
            os.remove(os.path.join(workdir, f))
        except OSError:
            pass


def _convert_videos_to_mp3(workdir: str) -> bool:
    """Convert any video files in workdir to MP3 using ffmpeg. Returns True on success."""
    if not FFMPEG_PATH:
        return False
    converted = False
    for f in list(os.listdir(workdir)):
        if f.startswith("_") or f.endswith(".json"):
            continue
        ext = os.path.splitext(f)[1].lower()
        if ext in (".mp4", ".mov", ".webm", ".mkv", ".m4a"):
            vpath = os.path.join(workdir, f)
            mpath = os.path.splitext(vpath)[0] + ".mp3"
            try:
                subprocess.run(
                    [FFMPEG_PATH, "-i", vpath, "-vn",
                     "-acodec", "libmp3lame", "-q:a", "2",
                     "-y", "-loglevel", "error", mpath],
                    capture_output=True, timeout=60, check=True,
                )
                if os.path.exists(mpath) and os.path.getsize(mpath) > 0:
                    try:
                        os.remove(vpath)
                    except OSError:
                        pass
                    converted = True
            except Exception:
                pass
    return converted


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


def _is_reel(url: str) -> bool:
    return bool(re.search(r'/reel[s]?/', url, re.IGNORECASE))


def _is_story(url: str) -> bool:
    return bool(re.search(r'/stories/', url, re.IGNORECASE))


def _extract_ig_shortcode(url: str) -> str | None:
    m = re.search(r'/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)', url)
    return m.group(1) if m else None


def _extract_ig_story_ids(url: str) -> tuple[str | None, str | None]:
    """Returns (username, story_id) from a stories URL."""
    m = re.search(r'/stories/([^/?]+)/?(\d+)?', url)
    if m:
        return m.group(1), m.group(2)
    return None, None


def download_via_cobalt(url: str, target_dir: str) -> tuple[int, str]:
    """cobalt.tools public API — free, no credentials needed, supports IG posts & reels."""
    COBALT_API = "https://api.cobalt.tools/"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = json.dumps({"url": url, "videoQuality": "max"}).encode()
    try:
        req = urllib.request.Request(COBALT_API, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return 1, f"cobalt: {str(e)[:120]}"

    status = data.get("status", "")
    if status == "error":
        return 1, f"cobalt error: {data.get('error', {}).get('code', 'unknown')}"

    def _fetch(media_url: str, fname: str) -> bool:
        try:
            r = urllib.request.Request(media_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(r, timeout=60) as resp:
                content = resp.read()
            if content:
                with open(os.path.join(target_dir, fname), "wb") as f:
                    f.write(content)
                return True
        except Exception:
            pass
        return False

    downloaded = 0
    if status in ("redirect", "tunnel") and data.get("url"):
        ext = ".mp4" if "video" in data.get("type", "") else ".jpg"
        if _fetch(data["url"], f"01{ext}"):
            downloaded += 1
    elif status == "picker" and data.get("picker"):
        for i, item in enumerate(data["picker"], start=1):
            item_url = item.get("url", "")
            item_type = item.get("type", "")
            ext = ".mp4" if item_type == "video" else ".jpg"
            if item_url and _fetch(item_url, f"{i:02d}{ext}"):
                downloaded += 1

    if downloaded == 0:
        return 1, f"cobalt: sin media (status={status})"
    return 0, f"cobalt: {downloaded} archivo(s)"


def download_via_instaloader(url: str, target_dir: str) -> tuple[int, str]:
    """Instaloader fallback for Instagram. Requires IG_SESSIONID or IG_COOKIES env var.
    Uses context.update_cookies() (instaloader 4.11+) for correct cookie injection."""
    try:
        import instaloader
    except ImportError:
        return 1, "instaloader not installed"

    # Extract sessionid from env
    sessionid = os.environ.get("IG_SESSIONID", "")
    if not sessionid:
        raw = os.environ.get("IG_COOKIES", "")
        if raw:
            import base64
            try:
                content = base64.b64decode(raw).decode("utf-8")
            except Exception:
                content = raw
            for line in content.splitlines():
                parts = line.split("\t")
                if len(parts) >= 7 and parts[5] == "sessionid":
                    sessionid = parts[6].strip()
                    break

    if not sessionid:
        return 1, "instaloader: IG_SESSIONID no configurado"

    # Use a separate temp dir so instaloader's subdir structure doesn't affect target_dir
    il_tmp = tempfile.mkdtemp(prefix="il_")
    try:
        L = instaloader.Instaloader(
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            post_metadata_txt_pattern="",
            quiet=True,
        )
        # Inject session cookie via the correct method (4.11+)
        L.context.update_cookies({"sessionid": sessionid})

        downloaded = 0
        if _is_story(url):
            username, story_id = _extract_ig_story_ids(url)
            if username:
                profile = instaloader.Profile.from_username(L.context, username)
                for story in L.get_stories(userids=[profile.userid]):
                    for item in story.get_items():
                        if story_id and str(item.mediaid) != story_id:
                            continue
                        L.download_storyitem(item, il_tmp)
                        downloaded += 1
                        if story_id:
                            break
        else:
            shortcode = _extract_ig_shortcode(url)
            if shortcode:
                post = instaloader.Post.from_shortcode(L.context, shortcode)
                L.download_post(post, target=il_tmp)
                downloaded += 1

        if downloaded == 0:
            return 1, "instaloader: no media descargada"

        # Move all media files from nested dirs to flat target_dir
        slot = 1
        for root, _dirs, files in os.walk(il_tmp):
            for fname in sorted(files):
                ext = os.path.splitext(fname)[1].lower()
                if ext not in MEDIA_EXTS:
                    continue
                src = os.path.join(root, fname)
                dst = os.path.join(target_dir, f"{slot:02d}{ext}")
                os.replace(src, dst)
                slot += 1

        if slot == 1:
            return 1, "instaloader: no media encontrada en directorio"
        return 0, f"instaloader: {slot - 1} archivo(s)"

    except Exception as e:
        return 1, f"instaloader: {str(e)[:200]}"
    finally:
        shutil.rmtree(il_tmp, ignore_errors=True)


def download_via_apify(url: str, target_dir: str) -> tuple[int, str]:
    """Two-actor Apify strategy for Instagram.

    1. data-slayer/instagram-post-details  (LjQn99w1uTJa26p3T)
       → No login required, returns full Instagram API data (photos + videos).
       Extracts video_versions / image_versions / carousel children.

    2. apify/instagram-scraper  (shu8hvrXbJbY3Eb9W)
       → Fallback for carousels/posts; proven to work for image posts.
    """
    token = os.environ.get("APIFY_API_TOKEN", "")
    if not token:
        return 1, "No APIFY_API_TOKEN"

    def _fetch(media_url: str, fname: str) -> bool:
        try:
            r = urllib.request.Request(media_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(r, timeout=60) as resp:
                data = resp.read()
            if data:
                with open(os.path.join(target_dir, fname), "wb") as f:
                    f.write(data)
                return True
        except Exception:
            pass
        return False

    def _run_actor(actor_id: str, payload: dict, timeout: int = 120, memory: int = 512):
        api_url = (
            f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"
            f"?token={token}&timeout={timeout}&memory={memory}"
        )
        req = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout + 15) as resp:
            return json.loads(resp.read().decode())

    downloaded = 0

    # ── Strategy 1: data-slayer (no login, full IG API data) ──────────────
    try:
        items = _run_actor("LjQn99w1uTJa26p3T", {"urls": [url]}, timeout=90, memory=512)
        if items and not items[0].get("error"):
            post = items[0]
            is_video = post.get("is_video") or post.get("media_type") == 2

            if is_video:
                # Video reel: get best quality from video_versions
                versions = post.get("video_versions") or []
                best = sorted(versions, key=lambda v: v.get("width", 0), reverse=True)
                if best and _fetch(best[0]["url"], "01.mp4"):
                    downloaded += 1

            if not downloaded:
                # Photo or carousel children
                children = post.get("carousel_media") or []
                if children:
                    for i, child in enumerate(children, start=1):
                        if child.get("is_video"):
                            vers = sorted(child.get("video_versions") or [],
                                          key=lambda v: v.get("width", 0), reverse=True)
                            if vers and _fetch(vers[0]["url"], f"{i:02d}.mp4"):
                                downloaded += 1
                        else:
                            cands = (child.get("image_versions") or {}).get("candidates") or []
                            best_img = sorted(cands, key=lambda v: v.get("width", 0), reverse=True)
                            if best_img and _fetch(best_img[0]["url"], f"{i:02d}.jpg"):
                                downloaded += 1

            if not downloaded:
                # Single photo
                thumb = post.get("thumbnail_url")
                if thumb and _fetch(thumb, "01.jpg"):
                    downloaded += 1

    except Exception:
        pass

    # ── Strategy 2: apify/instagram-scraper (carousels fallback) ──────────
    if not downloaded:
        try:
            items = _run_actor(
                "shu8hvrXbJbY3Eb9W",
                {"directUrls": [url], "resultsType": "posts", "resultsLimit": 1,
                 "searchType": "hashtag", "addParentData": False},
                timeout=120, memory=1024,
            )
            if items and not items[0].get("error"):
                post = items[0]
                if post.get("videoUrl") and _fetch(post["videoUrl"], "01.mp4"):
                    downloaded += 1
                if not downloaded:
                    for i, child in enumerate(post.get("childPosts") or [], start=1):
                        v = child.get("videoUrl")
                        img = child.get("displayUrl") or child.get("thumbnailUrl")
                        if v and _fetch(v, f"{i:02d}.mp4"):
                            downloaded += 1
                        elif img and _fetch(img, f"{i:02d}.jpg"):
                            downloaded += 1
                if not downloaded:
                    img = post.get("displayUrl") or post.get("thumbnailUrl")
                    if img and _fetch(img, "01.jpg"):
                        downloaded += 1
        except Exception:
            pass

    if downloaded == 0:
        return 1, "Apify: no se encontró media descargable"
    return 0, f"Apify: {downloaded} archivo(s)"


def map_error_response(output: str, platform: str | None) -> tuple[dict, int]:
    low = output.lower()
    if "login" in low or "private" in low or "401" in output or "logged" in low or "restricted_page" in low:
        if platform == "instagram":
            return {"error": "Instagram requiere sesión. Agrega IG_SESSIONID en Render Environment con el valor de tu cookie sessionid de instagram.com."}, 401
        return {"error": f"Login requerido o contenido privado en {platform or 'esta plataforma'}."}, 401
    if "429" in output or "rate" in low or "throttl" in low or "wait" in low:
        return {"error": "La plataforma aplicó rate-limit. Espera unos minutos."}, 429
    if "404" in output or "not found" in low or "does not exist" in low or "no such" in low:
        return {"error": "Publicación no encontrada o eliminada."}, 404
    if "no video formats" in low or "unable to extract" in low:
        if platform == "youtube":
            return {"error": "YouTube bloqueó este video desde la IP del servidor. Para descargar de YouTube necesitas configurar YT_COOKIES en Render con cookies de tu sesión (cuenta secundaria)."}, 401
        return {"error": "No se pudo extraer media de este link. Verifica que sea público y soportado."}, 422
    if "sign in" in low or "confirm you" in low or "not a bot" in low:
        return {"error": "YouTube exige autenticación. Configura YT_COOKIES en Render con cookies de YouTube (instala 'Get cookies.txt LOCALLY' → exporta youtube.com → pégalo en Render → Environment → YT_COOKIES)."}, 401
    if "status code 0" in low or "video not available" in low:
        return {"error": "Video no disponible (puede estar removido, ser privado o tener restricciones de región)."}, 404
    return {"error": f"Error al descargar: {output[:400]}"}, 500


@app.route("/")
def index():
    return render_template("index.html")


def _process_one(url: str, workdir: str, audio_only: bool = False, max_height: int | None = None) -> tuple[bool, str, str | None]:
    """Download one URL into workdir. Returns (success, message, basename_used)."""
    if not url or not re.match(r"^https?://", url):
        return False, "URL inválida", None
    for pattern, msg in UNSUPPORTED_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return False, msg, None

    platform, primary_tool = detect_platform(url)
    fallback_id = extract_short_id(url)

    try:
        if audio_only:
            # MP3 path: try yt-dlp -x first (efficient, audio-only).
            # If that fails, download a video by ANY means and extract audio with ffmpeg.
            rc, output = download_via_ytdlp(url, workdir, audio_only=True)
            has_audio = any(f.lower().endswith(".mp3") or f.lower().endswith(".m4a")
                            for f in collect_media(workdir))
            if rc != 0 or not has_audio:
                _clean_media_only(workdir)
                # Fallback A: gallery-dl video → ffmpeg → MP3
                rc2, out2 = download_via_gallery_dl(url, workdir)
                if rc2 == 0 and collect_media(workdir) and _convert_videos_to_mp3(workdir):
                    rc, output = 0, "ok"
                else:
                    _clean_media_only(workdir)
                    # Fallback B: yt-dlp video → ffmpeg → MP3
                    rc3, out3 = download_via_ytdlp(url, workdir, audio_only=False)
                    if rc3 == 0 and collect_media(workdir) and _convert_videos_to_mp3(workdir):
                        rc, output = 0, "ok"
                    else:
                        rc = rc3 if rc3 else (rc2 if rc2 else rc)
                        output = out3 or out2 or output
        elif primary_tool == "yt-dlp":
            rc, output = download_via_ytdlp(url, workdir, max_height=max_height)
            if rc != 0 or not collect_media(workdir):
                rc2, out2 = download_via_gallery_dl(url, workdir)
                if rc2 == 0 and collect_media(workdir):
                    rc, output = rc2, out2
            # Apify fallback for Instagram/TikTok when local tools fail
            if not collect_media(workdir) and platform in ("instagram", "tiktok"):
                rc3, out3 = download_via_apify(url, workdir)
                if rc3 == 0 and collect_media(workdir):
                    rc, output = rc3, out3
        else:
            rc, output = download_via_gallery_dl(url, workdir)
            if rc != 0 or not collect_media(workdir):
                rc2, out2 = download_via_ytdlp(url, workdir, max_height=max_height)
                if rc2 == 0 and collect_media(workdir):
                    rc, output = rc2, out2
            # cobalt.tools: free public API, no credentials, works for IG posts & reels
            if not collect_media(workdir) and platform == "instagram":
                rc3, out3 = download_via_cobalt(url, workdir)
                if rc3 == 0 and collect_media(workdir):
                    rc, output = rc3, out3
            # instaloader: requires IG_SESSIONID, handles new IG auth requirements
            if not collect_media(workdir) and platform == "instagram":
                rc4, out4 = download_via_instaloader(url, workdir)
                if rc4 == 0 and collect_media(workdir):
                    rc, output = rc4, out4
            # Apify: reliable residential-proxy fallback, requires APIFY_API_TOKEN
            if not collect_media(workdir) and platform == "instagram":
                rc5, out5 = download_via_apify(url, workdir)
                if rc5 == 0 and collect_media(workdir):
                    rc, output = rc5, out5
    except subprocess.TimeoutExpired:
        return False, "Timeout", None
    except Exception as e:
        return False, f"Error: {str(e)[:200]}", None

    media = collect_media(workdir)
    if not media:
        return False, output[:200] if output else "Sin archivos", None

    meta = find_metadata(workdir)
    basename = derive_basename(meta, fallback_id)
    return True, "ok", basename


@app.route("/api/download", methods=["POST"])
def download():
    data = request.get_json(silent=True) or request.form

    urls = data.get("urls")
    if isinstance(urls, list) and urls:
        urls = [u.strip() for u in urls if isinstance(u, str) and u.strip()]
    elif data.get("url"):
        urls = [data["url"].strip()]
    else:
        urls = []

    fmt = str(data.get("format") or "").lower()
    audio_only = fmt in ("mp3", "audio")
    max_height = None
    if fmt == "4k":
        max_height = 2160
    elif fmt == "1440p":
        max_height = 1440
    elif fmt == "1080p":
        max_height = 1080
    elif fmt == "720p":
        max_height = 720

    if not urls:
        return jsonify({"error": "URL no válida. Pega un link completo (con https://)."}), 400

    if len(urls) > 20:
        return jsonify({"error": "Máximo 20 links por descarga."}), 413

    if len(urls) == 1:
        return _single_download(urls[0], audio_only=audio_only, max_height=max_height)
    return _bulk_download(urls, audio_only=audio_only, max_height=max_height)


def _single_download(url: str, audio_only: bool = False, max_height: int | None = None):
    if not re.match(r"^https?://", url):
        return jsonify({"error": "URL no válida. Pega un link completo (con https://)."}), 400

    for pattern, msg in UNSUPPORTED_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return jsonify({"error": f"{msg} Plataformas activas: Instagram, TikTok, X, Reddit, Pinterest."}), 422

    workdir = tempfile.mkdtemp(prefix="muse_")
    try:
        ok, msg, basename = _process_one(url, workdir, audio_only=audio_only, max_height=max_height)
        if not ok:
            platform, _ = detect_platform(url)
            err, code = map_error_response(msg, platform)
            return jsonify(err), code

        media = collect_media(workdir)
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


def _bulk_download(urls: list[str], audio_only: bool = False, max_height: int | None = None):
    bulkdir = tempfile.mkdtemp(prefix="muse_bulk_")
    failures = []
    successes = 0
    try:
        for idx, url in enumerate(urls, start=1):
            sub = os.path.join(bulkdir, f"item_{idx:02d}")
            os.makedirs(sub, exist_ok=True)
            ok, msg, basename = _process_one(url, sub, audio_only=audio_only, max_height=max_height)
            if not ok:
                failures.append({"url": url, "error": msg})
                shutil.rmtree(sub, ignore_errors=True)
                continue
            renumber_slides(sub)
            target_name = basename or f"item_{idx:02d}"
            new_dir = os.path.join(bulkdir, target_name)
            counter = 2
            while os.path.exists(new_dir):
                new_dir = os.path.join(bulkdir, f"{target_name}_{counter}")
                counter += 1
            os.rename(sub, new_dir)
            successes += 1

        if successes == 0:
            return jsonify({
                "error": "Ninguna descarga tuvo éxito.",
                "details": failures[:5],
            }), 422

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(bulkdir):
                for name in files:
                    if name.startswith("_") or name.endswith(".json"):
                        continue
                    full = os.path.join(root, name)
                    arcname = os.path.relpath(full, bulkdir)
                    zf.write(full, arcname)
        buffer.seek(0)

        filename = f"muse_bulk_{successes}_de_{len(urls)}.zip"
        return send_file(
            buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=filename,
        )
    finally:
        shutil.rmtree(bulkdir, ignore_errors=True)


@app.route("/healthz")
def healthz():
    return {"ok": True, "platforms": [name for name, _, _ in PLATFORM_RULES]}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5005"))
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=False)
