# coding=utf-8
try:
    from base.spider import Spider as BaseSpider
except:
    class BaseSpider:
        def getName(self): return ""
        def init(self, extend=""): pass
        def homeContent(self, filter=None): return {}
        def homeVideoContent(self): return {}
        def categoryContent(self, tid, pg, filter=None, extend=None): return {}
        def detailContent(self, ids): return {}
        def searchContent(self, key, quick=False, pg="1"): return {}
        def playerContent(self, flag, id, vipFlags=None): return {}
        def localProxy(self, param): return [404, "text/plain", ""]
        def getDependence(self): return ""
        def isVideoFormat(self, url): return False
        def manualVideoCheck(self): return False

import re, time, json, urllib.request
from urllib.parse import quote, urljoin, urlparse, unquote

class Spider(BaseSpider):
    def getName(self):
        return "后妈的诱惑"

    def init(self, extend=""):
        self.host = "https://houma51.lol"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.host + "/",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        self._data = None
        self._page_size = 24

    def getDependence(self):
        return ""

    def _load(self):
        if self._data is not None:
            return self._data
        for i in range(3):
            try:
                req = urllib.request.Request(self.host + "/js/data.js", headers=self.headers)
                with urllib.request.urlopen(req, timeout=20) as resp:
                    raw = resp.read().decode("utf-8", "ignore")
                m = re.search(r"const\s+pageData\s*=\s*(\[[\s\S]*\])\s*;?\s*$", raw)
                if not m:
                    m = re.search(r"const\s+pageData\s*=\s*(\[[\s\S]*)", raw)
                text = (m.group(1) if m else "").rstrip().rstrip(";")
                data = json.loads(text)
                # normalize
                out = []
                for idx, it in enumerate(data):
                    title = (it.get("title") or "").strip()
                    video = (it.get("video") or "").strip()
                    img = (it.get("img") or "").strip()
                    if not title or not video:
                        continue
                    out.append({
                        "vod_id": str(idx),
                        "vod_name": title,
                        "vod_pic": img,
                        "vod_remarks": "",
                        "_url": video,
                    })
                self._data = out
                return out
            except Exception:
                if i == 2:
                    self._data = []
                    return []
                time.sleep(0.5)
        self._data = []
        return []

    def homeContent(self, filter=None):
        return {
            "class": [
                {"type_id": "all", "type_name": "全部"},
            ],
            "filters": {},
        }

    def homeVideoContent(self):
        return self.categoryContent("all", "1")

    def categoryContent(self, tid, pg, filter=None, extend=None):
        data = self._load()
        pg = int(pg or 1)
        ps = self._page_size
        total = len(data)
        pages = max(1, (total + ps - 1) // ps)
        start = (pg - 1) * ps
        chunk = data[start:start + ps]
        videos = [{"vod_id": v["vod_id"], "vod_name": v["vod_name"], "vod_pic": v["vod_pic"], "vod_remarks": ""} for v in chunk]
        return {
            "page": pg,
            "pagecount": pages,
            "limit": ps,
            "total": total,
            "list": videos,
        }

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vod_id = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        data = self._load()
        item = None
        for v in data:
            if v["vod_id"] == vod_id:
                item = v
                break
        if not item:
            # maybe id is m3u8 url encoded
            url = unquote(vod_id)
            if url.startswith("http"):
                return {
                    "list": [{
                        "vod_id": vod_id,
                        "vod_name": "视频",
                        "vod_pic": "",
                        "vod_content": "",
                        "vod_play_from": "线路1",
                        "vod_play_url": f"正片${url}",
                    }]
                }
            return {"list": []}
        return {
            "list": [{
                "vod_id": item["vod_id"],
                "vod_name": item["vod_name"],
                "vod_pic": item["vod_pic"],
                "vod_content": item["vod_name"],
                "vod_play_from": "线路1",
                "vod_play_url": f"正片${item['_url']}",
            }]
        }

    def searchContent(self, key, quick=False, pg="1"):
        data = self._load()
        key = (key or "").strip().lower()
        matched = [v for v in data if key in v["vod_name"].lower()]
        pg = int(pg or 1)
        ps = self._page_size
        start = (pg - 1) * ps
        chunk = matched[start:start + ps]
        videos = [{"vod_id": v["vod_id"], "vod_name": v["vod_name"], "vod_pic": v["vod_pic"], "vod_remarks": ""} for v in chunk]
        pages = max(1, (len(matched) + ps - 1) // ps) if matched else 1
        return {
            "list": videos,
            "page": pg,
            "pagecount": pages,
            "limit": ps,
            "total": len(matched),
        }

    def _fetch_media(self, url):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": self.headers["User-Agent"],
                "Referer": self.host + "/",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception:
            return ""

    def _resolve_m3u8(self, url):
        if not url or ".m3u8" not in url:
            return url
        body = self._fetch_media(url)
        if not body:
            return url
        if "#EXTINF" in body and "#EXT-X-STREAM-INF" not in body:
            return url
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and ".m3u8" in line:
                return line if line.startswith("http") else urljoin(url, line)
        return url

    def playerContent(self, flag, id, vipFlags=None):
        raw = id or ""
        if not raw.startswith("http"):
            data = self._load()
            for v in data:
                if v["vod_id"] == str(raw):
                    raw = v["_url"]
                    break
        url = self._resolve_m3u8(raw) if raw.startswith("http") else ""
        header = {
            "User-Agent": self.headers["User-Agent"],
            "Referer": self.host + "/",
        }
        if not url:
            return {"parse": 0, "jx": 0, "url": "", "header": header}
        if ".m3u8" in url and hasattr(self, "getProxyUrl") and self.getProxyUrl():
            base = self.getProxyUrl()
            proxy = base + ("&" if "?" in base else "?") + "url=" + quote(url) + "&type=m3u8"
            return {"parse": 0, "jx": 0, "url": proxy, "header": header}
        return {"parse": 0, "jx": 0, "url": url, "header": header}

    def localProxy(self, param):
        try:
            url = param.get("url") if isinstance(param, dict) else str(param or "")
            if not url:
                return [404, "text/plain", ""]
            body = self._fetch_media(url)
            if not body:
                return [502, "text/plain", "fetch failed"]
            if "#EXT-X-STREAM-INF" in body and "#EXTINF" not in body:
                for line in body.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and ".m3u8" in line:
                        sub = line if line.startswith("http") else urljoin(url, line)
                        body = self._fetch_media(sub)
                        url = sub
                        break
            cleaned = self._clean_m3u8(body or "", url)
            return [200, "application/vnd.apple.mpegurl", cleaned]
        except Exception as e:
            return [500, "text/plain", str(e)[:200]]

    def _clean_m3u8(self, content, base_url=""):
        if not content or "#EXTM3U" not in content:
            return content
        parsed = urlparse(base_url)
        base_origin = f"{parsed.scheme}://{parsed.netloc}"
        base_dir = base_url.rsplit("/", 1)[0] + "/"
        base_date = None
        m = re.search(r"/(20\d{6})/", base_url)
        if m:
            base_date = m.group(1)
        lines = [l.strip() for l in content.splitlines()]
        real_start = 0
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-DISCONTINUITY"):
                real_start = i + 1
                break
        header = []
        for line in lines:
            if line.startswith("#EXTM3U") or line.startswith("#EXT-X-VERSION") or \
               line.startswith("#EXT-X-TARGETDURATION") or line.startswith("#EXT-X-PLAYLIST-TYPE") or \
               line.startswith("#EXT-X-MEDIA-SEQUENCE") or line.startswith("#EXT-X-INDEPENDENT"):
                header.append(line)
            elif line.startswith("#EXTINF") or line.startswith("#EXT-X-KEY") or \
                 line.startswith("#EXT-X-DISCONTINUITY") or (line and not line.startswith("#")):
                break
        body_lines = lines[real_start:] if real_start > 0 else lines
        out = list(header)
        if not any(x.startswith("#EXT-X-MEDIA-SEQUENCE") for x in out):
            out.append("#EXT-X-MEDIA-SEQUENCE:0")
        i = 0
        while i < len(body_lines):
            line = body_lines[i]
            if line.startswith("#EXT-X-KEY"):
                if "METHOD=NONE" in line:
                    i += 1
                    continue
                mk = re.search(r'URI="([^"]+)"', line)
                if mk:
                    key_uri = mk.group(1)
                    if key_uri.startswith("/"):
                        line = line.replace(f'URI="{key_uri}"', f'URI="{base_origin + key_uri}"')
                    elif not key_uri.startswith("http"):
                        line = line.replace(f'URI="{key_uri}"', f'URI="{urljoin(base_dir, key_uri)}"')
                out.append(line)
                i += 1
                continue
            if line.startswith("#EXTINF:"):
                j = i + 1
                while j < len(body_lines) and body_lines[j].startswith("#") and not body_lines[j].startswith("#EXTINF"):
                    if body_lines[j].startswith("#EXT-X-DISCONTINUITY"):
                        j += 1
                        continue
                    break
                next_line = body_lines[j] if j < len(body_lines) else ""
                if next_line.startswith("#"):
                    i += 1
                    continue
                abs_next = next_line
                if next_line.startswith("/") and not next_line.startswith("//"):
                    abs_next = base_origin + next_line
                elif next_line and not next_line.startswith("http"):
                    abs_next = urljoin(base_dir, next_line)
                is_ad = False
                if base_date and abs_next:
                    md = re.search(r"/(20\d{6})/", abs_next)
                    if md and md.group(1) != base_date:
                        is_ad = True
                if is_ad:
                    i = j + 1
                    continue
                out.append(line)
                if abs_next:
                    out.append(abs_next)
                    i = j + 1
                    continue
                i += 1
                continue
            if line.startswith("#EXT-X-DISCONTINUITY"):
                i += 1
                continue
            if line.startswith("#EXT-X-ENDLIST"):
                out.append(line)
                i += 1
                continue
            if line and not line.startswith("#"):
                abs_l = line
                if line.startswith("/") and not line.startswith("//"):
                    abs_l = base_origin + line
                elif not line.startswith("http"):
                    abs_l = urljoin(base_dir, line)
                if base_date:
                    md = re.search(r"/(20\d{6})/", abs_l)
                    if md and md.group(1) != base_date:
                        i += 1
                        continue
                out.append(abs_l)
            elif line.startswith("#"):
                out.append(line)
            i += 1
        return "\n".join(out)

    def isVideoFormat(self, url):
        return bool(re.search(r"\.(m3u8|mp4|flv|mkv)(\?|$)", url or "", re.I))

    def manualVideoCheck(self):
        return False
