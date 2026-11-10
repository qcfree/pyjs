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
from urllib.parse import quote, urljoin, urlparse

class Spider(BaseSpider):
    def getName(self):
        return "青青草视频"

    def init(self, extend=""):
        self.host = "https://www.qqcav10.top"
        self.prefix = "/aa"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.host + self.prefix + "/",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "identity",
        }

    def getDependence(self):
        return ""

    def _get(self, path, retry=2):
        if path.startswith("http"):
            url = path
        else:
            url = self.host + self.prefix + path
        for i in range(retry + 1):
            try:
                req = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return resp.read().decode("utf-8", "ignore")
            except Exception:
                if i == retry:
                    return ""
                time.sleep(0.4)
        return ""

    def _unescape(self, s):
        try:
            import html as H
            return H.unescape(s or "")
        except Exception:
            return s or ""

    def homeContent(self, filter=None):
        classes = [
            {"type_id": "2", "type_name": "精品推荐"},
            {"type_id": "3", "type_name": "国产精品"},
            {"type_id": "4", "type_name": "主播秀色"},
            {"type_id": "5", "type_name": "日本无码"},
            {"type_id": "6", "type_name": "欧美情色"},
            {"type_id": "7", "type_name": "自拍偷拍"},
            {"type_id": "8", "type_name": "日本片商"},
            {"type_id": "10", "type_name": "网曝系列"},
            {"type_id": "12", "type_name": "探花嫖娼"},
            {"type_id": "13", "type_name": "国产人妻"},
            {"type_id": "16", "type_name": "麻豆传媒"},
            {"type_id": "17", "type_name": "国产乱伦"},
            {"type_id": "62", "type_name": "国产主播"},
            {"type_id": "63", "type_name": "欧美劲爆"},
            {"type_id": "15", "type_name": "国产丝袜"},
            {"type_id": "14", "type_name": "国产SM"},
        ]
        return {"class": classes, "filters": {}}

    def homeVideoContent(self):
        return self.categoryContent("2", "1")

    def categoryContent(self, tid, pg, filter=None, extend=None):
        pg = str(pg or "1")
        if pg == "1":
            path = f"/index.php/vod/type/id/{tid}.html"
        else:
            path = f"/index.php/vod/type/id/{tid}/page/{pg}.html"
        html = self._get(path)
        if not html:
            return {"page": int(pg), "pagecount": 1, "limit": 0, "total": 0, "list": []}
        videos = self._parse_list(html)
        pagecount = int(pg)
        pages = re.findall(r"type/id/%s/page/(\d+)" % re.escape(str(tid)), html)
        if pages:
            pagecount = max(int(x) for x in pages if x.isdigit())
        return {"page": int(pg), "pagecount": pagecount, "limit": 24, "total": pagecount * 24, "list": videos}

    def _parse_list(self, html):
        videos = []
        # each li has play link + img + h3 title
        for m in re.finditer(
            r'href="%s/index\.php/vod/play/id/(\d+)/sid/\d+/nid/\d+\.html"[^>]*>' % re.escape(self.prefix),
            html,
        ):
            vid = m.group(1)
            chunk = html[m.start():m.start() + 800]
            pic = ""
            pm = re.search(r'data-original="(https?://[^"]+)"', chunk)
            if pm:
                pic = pm.group(1)
            name = ""
            # <text>title or h3 content
            tm = re.search(r"<text>([^<]+)</text>", chunk)
            if tm:
                name = self._unescape(tm.group(1)).strip()
            if not name:
                tm = re.search(r'class="video-title"[^>]*>[\s\S]*?</a>\s*<a><text>([^<]+)</text>', chunk)
                if tm:
                    name = self._unescape(tm.group(1)).strip()
            if not name:
                # strip tags from h3
                hm = re.search(r'class="video-title"[^>]*>([\s\S]*?)</h3>', chunk)
                if hm:
                    name = self._unescape(re.sub(r"<[^>]+>", "", hm.group(1))).strip()
            if len(name) < 2:
                continue
            videos.append({"vod_id": vid, "vod_name": name, "vod_pic": pic, "vod_remarks": ""})
        seen = set()
        uniq = []
        for v in videos:
            if v["vod_id"] in seen:
                continue
            seen.add(v["vod_id"])
            uniq.append(v)
        return uniq

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vod_id = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        html = self._get(f"/index.php/vod/play/id/{vod_id}/sid/1/nid/1.html")
        if not html:
            return {"list": []}
        name = ""
        m = re.search(r"<title>([^<]+)</title>", html)
        if m:
            name = self._unescape(m.group(1))
            for sep in ["在线播放", "-", "_"]:
                if sep in name:
                    name = name.split(sep)[0].strip()
        pic = ""
        m = re.search(r'data-original="(https?://[^"]+)"', html)
        if m:
            pic = m.group(1)
        return {
            "list": [{
                "vod_id": vod_id,
                "vod_name": name or f"视频{vod_id}",
                "vod_pic": pic,
                "vod_content": name,
                "vod_play_from": "线路1",
                "vod_play_url": f"正片${vod_id}",
            }]
        }

    def searchContent(self, key, quick=False, pg="1"):
        pg = str(pg or "1")
        q = quote(key)
        if pg == "1":
            path = f"/index.php/vod/search.html?wd={q}"
        else:
            path = f"/index.php/vod/search/wd/{q}/page/{pg}.html"
        html = self._get(path)
        videos = self._parse_list(html or "")
        return {"list": videos, "page": int(pg), "pagecount": 1, "limit": 24, "total": len(videos)}

    def _extract_player_url(self, html):
        m = re.search(r"player_aaaa\s*=\s*(\{.+?\})\s*</script>", html or "", re.S)
        if not m:
            return ""
        try:
            data = json.loads(m.group(1))
            return (data.get("url") or "").strip()
        except Exception:
            u = re.search(r'"url"\s*:\s*"([^"]+)"', m.group(1))
            if u:
                return u.group(1).replace("\\/", "/")
        return ""

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
        if raw.startswith("http"):
            url = self._resolve_m3u8(raw)
        else:
            html = self._get(f"/index.php/vod/play/id/{raw}/sid/1/nid/1.html")
            url = self._extract_player_url(html)
            if url:
                url = self._resolve_m3u8(url)
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
