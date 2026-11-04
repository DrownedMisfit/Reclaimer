"""
Búsqueda EXTERNA de imágenes (opcional, necesita internet).

Usa Openverse (https://openverse.org, de WordPress): un buscador abierto de imágenes con licencias
libres (Creative Commons y dominio público), sin claves ni registro, que indica la licencia y el
autor de cada imagen. Por defecto solo muestra imágenes que permiten USO COMERCIAL (tu canal está
monetizado).

Nada se descarga hasta que eliges «Usar» en una imagen; entonces se guarda en
Vídeos/Reclaimer/Imágenes de internet junto con un «créditos.txt» con su atribución.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request

API = "https://api.openverse.org/v1/images/"
UA = {"User-Agent": "Reclaimer/0.1 (editor de video local)"}

LICENSE_NAMES = {"cc0": "CC0 (dominio público)", "pdm": "Dominio público", "by": "CC BY", "by-sa": "CC BY-SA",
                 "by-nd": "CC BY-ND", "by-nc": "CC BY-NC", "by-nc-sa": "CC BY-NC-SA", "by-nc-nd": "CC BY-NC-ND"}


def folder() -> str:
    d = os.path.join(os.path.expanduser("~"), "Videos", "Reclaimer", "Imágenes de internet")
    os.makedirs(d, exist_ok=True)
    return d


def search(query: str, page_size: int = 20, commercial: bool = True, timeout: float = 20, page: int = 1) -> list[dict]:
    """[{title, url, thumbnail, license, license_text, creator, page, attribution, width, height}]
    (sin registrarse, Openverse permite como máximo 20 resultados por consulta; page = 1, 2, 3…)"""
    params = {"q": query, "page_size": str(page_size)}
    if page > 1:
        params["page"] = str(page)
    if commercial:
        params["license_type"] = "commercial,modification"   # uso comercial y se puede editar (sin ND)
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = []
    for it in data.get("results", []):
        lic = (it.get("license") or "").lower()
        out.append({
            "title": it.get("title") or "(sin título)",
            "url": it.get("url"),
            "thumbnail": it.get("thumbnail") or it.get("url"),
            "license": lic,
            "license_text": LICENSE_NAMES.get(lic, lic.upper()) + (f" {it.get('license_version')}"
                                                                  if it.get("license_version") and lic not in ("cc0", "pdm") else ""),
            "creator": it.get("creator") or "desconocido",
            "page": it.get("foreign_landing_url") or it.get("url"),
            "attribution": it.get("attribution") or "",
            "width": it.get("width") or 0,
            "height": it.get("height") or 0,
            "id": it.get("id") or "",
        })
    return [r for r in out if r["url"]]


COMMONS_API = "https://commons.wikimedia.org/w/api.php"
# Licencias de Wikimedia Commons que permiten uso comercial y modificarlas
_COMMONS_OK = re.compile(r"^(cc0|pd|public domain|cc-by(-sa)?(-\d(\.\d)?)?|cc by(-sa)?( \d(\.\d)?)?)", re.I)


def _strip_html(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t or "")).strip()


def search_commons(query: str, limit: int = 40, timeout: float = 20) -> list[dict]:
    """Wikimedia Commons (sin registrarse): imágenes con licencia libre de uso comercial, mismo formato que search."""
    params = {"action": "query", "generator": "search", "gsrnamespace": "6", "gsrsearch": f"{query} filetype:bitmap",
              "gsrlimit": str(limit), "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
              "iiurlwidth": "400", "format": "json"}
    req = urllib.request.Request(COMMONS_API + "?" + urllib.parse.urlencode(params), headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = []
    for pg in (data.get("query") or {}).get("pages", {}).values():
        ii = (pg.get("imageinfo") or [{}])[0]
        if ii.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        em = ii.get("extmetadata") or {}
        lic = (em.get("License", {}).get("value") or em.get("LicenseShortName", {}).get("value") or "").lower()
        short = em.get("LicenseShortName", {}).get("value") or lic.upper()
        if not _COMMONS_OK.match(lic) or "nc" in lic.split("-") or "nd" in lic.split("-"):
            continue
        title = re.sub(r"^File:|\.[A-Za-z0-9]+$", "", pg.get("title", "")).strip()
        artist = _strip_html(em.get("Artist", {}).get("value", "")) or "desconocido"
        out.append({
            "title": title or "(sin título)", "url": ii.get("url"), "thumbnail": ii.get("thumburl") or ii.get("url"),
            "license": lic, "license_text": short, "creator": artist[:80],
            "page": ii.get("descriptionurl") or ii.get("url"),
            "attribution": f"«{title}» de {artist[:80]}, {short}, vía Wikimedia Commons",
            "width": ii.get("width") or 0, "height": ii.get("height") or 0, "id": f"wm{pg.get('pageid', '')}",
            "source": "Wikimedia Commons",
        })
    return [r for r in out if r["url"]]


def smart_queries(q: str) -> list[str]:
    """Las imágenes libres están etiquetadas sobre todo en inglés: «elite de halo» → también «halo elite»;
    sin artículos («el jefe maestro» → «jefe maestro»)."""
    words = q.strip().split()
    out = [q.strip()]
    low = [w.lower() for w in words]
    if "de" in low[1:-1]:
        i = low.index("de", 1)
        swapped = " ".join(words[i + 1:] + words[:i])
        out.append(swapped)
    if low and low[0] in ("el", "la", "los", "las", "un", "una"):
        out.append(" ".join(words[1:]))
    seen, res = set(), []
    for x in out:
        if x and x.lower() not in seen:
            seen.add(x.lower())
            res.append(x)
    return res


def save_pasted(img, note: str = "") -> str:
    """Guarda una imagen pegada (copiada del navegador) en la carpeta de imágenes de internet y anota su
    origen en créditos.txt. img: QImage. Devuelve la ruta."""
    import time as _t
    base = "Imagen pegada " + _t.strftime("%Y-%m-%d %H.%M.%S")
    dest = os.path.join(folder(), base + ".png")
    k = 2
    while os.path.exists(dest):
        dest = os.path.join(folder(), f"{base} ({k}).png")
        k += 1
    if not img.save(dest, "PNG"):
        raise RuntimeError("No se pudo guardar la imagen pegada.")
    with open(os.path.join(folder(), "créditos.txt"), "a", encoding="utf-8") as f:
        f.write(f"{os.path.basename(dest)}: copiada de internet, con derechos de autor"
                f"{' — ' + note if note else ''} (uso bajo tu responsabilidad: crítica/comentario)\n")
    return dest


def search_many(queries: list[str], pages: int = 3, seen: set | None = None, cancelled=None,
                commons: bool = True, commercial: bool = True) -> list[dict]:
    """Varias búsquedas y páginas (Openverse y Wikimedia Commons), sin repetir imágenes. Si una página o una
    fuente falla (límites, sin conexión), se sigue con lo demás."""
    seen = set(seen or ())
    out = []
    if commons:
        for q in queries[:2]:
            if cancelled and cancelled():
                return out
            try:
                res = search_commons(q)
            except Exception:  # noqa: BLE001 - Commons no disponible: solo Openverse
                res = []
            for r in res:
                if (r["id"] or r["url"]) not in seen:
                    seen.add(r["id"] or r["url"])
                    r["query"] = q
                    out.append(r)
    for q in queries:
        for pg in range(1, pages + 1):
            if cancelled and cancelled():
                return out
            try:
                res = search(q, page=pg, commercial=commercial)
            except Exception:  # noqa: BLE001 - p. ej. sin más páginas
                break
            new = [r for r in res if (r["id"] or r["url"]) not in seen]
            for r in new:
                seen.add(r["id"] or r["url"])
                r["query"] = q
            out += new
            if len(res) < 20:
                break
    return out


def fetch(url: str, dest: str, timeout: float = 30, limit: int = 40_000_000) -> str:
    import time
    import urllib.error
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read(limit + 1)
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503):
                raise
            if attempt == 2:      # la web pide que esperes (demasiadas descargas seguidas)
                msg = "La web está limitando las descargas: prueba otra vez en unos segundos."
                raise RuntimeError(msg) from None
            try:
                wait = float(exc.headers.get("Retry-After", 0) or 0)
            except (TypeError, ValueError):
                wait = 0.0
            time.sleep(min(6.0, max(1.5 * (attempt + 1), wait)))
    if len(data) > limit:
        raise RuntimeError("La imagen es demasiado grande.")
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def thumb_path(item: dict, cache: str) -> str:
    return os.path.join(cache, f"web_{re.sub(r'[^A-Za-z0-9_-]', '', item['id'] or str(abs(hash(item['url']))))}.jpg")


def safe_name(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|]+', " ", text or "")).strip()[:60]


def next_numbered(dirpath: str, base: str, ext: str) -> str:
    """«base 1.ext», «base 2.ext»… el siguiente número libre (aunque hayas borrado alguno, nunca se repite)."""
    nums = [0]
    pat = re.compile(re.escape(base.lower()) + r" (\d+)\.[a-z0-9]+$")
    if os.path.isdir(dirpath):
        for f in os.listdir(dirpath):
            mt = pat.match(f.lower())
            if mt:
                nums.append(int(mt.group(1)))
    return os.path.join(dirpath, f"{base} {max(nums) + 1}{ext}")


def download(item: dict, name: str | None = None) -> str:
    """Descarga la imagen elegida y anota su crédito. Con name (lo que buscaste) se guarda en su carpeta y con
    número: «Imágenes de internet/master chief/master chief 1.jpg», «… 2.jpg»…"""
    ext = os.path.splitext(urllib.parse.urlparse(item["url"]).path)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        ext = ".jpg"
    if name and safe_name(name):
        sub_ = os.path.join(folder(), safe_name(name))
        os.makedirs(sub_, exist_ok=True)
        dest = next_numbered(sub_, safe_name(name), ext)
    else:
        base = safe_name(item["title"]) or "imagen"
        dest = os.path.join(folder(), base + ext)
        k = 2
        while os.path.exists(dest):
            dest = os.path.join(folder(), f"{base} ({k}){ext}")
            k += 1
    fetch(item["url"], dest)
    with open(os.path.join(folder(), "créditos.txt"), "a", encoding="utf-8") as f:
        f.write(f"{os.path.relpath(dest, folder())}: {item['attribution'] or item['title'] + ' — ' + item['creator']}"
                f" ({item['license_text']}) {item['page']}\n")
    return dest
