# -*- coding: utf-8 -*-
"""
TVBox Python Spider Plugin (Standard Library Only)
Site: 7月视频 (qiyue)
API: https://webinit.ali.bdkayc.com/api
Encryption: MD5 sign header + AES-128-CBC response decrypt (PKCS7)

Limitation: video_info endpoint requires login token (returns code=3 for guest).
Guest users can browse categories, search, and view video details (metadata only).
Play URL (m3u8) is only available with a logged-in user token.

Environment: No requests, no pycryptodome. Uses urllib.request + ssl + json + base64 + re only.
"""

import json
import time
import hashlib
import base64
import ssl
import urllib.request
import urllib.parse

# ========== base.spider 兼容桩 ==========
try:
    from base.spider import Spider as BaseSpider
except ImportError:
    try:
        from base.spider import BaseSpider
    except ImportError:
        try:
            from spider import Spider as BaseSpider
        except ImportError:
            class BaseSpider(object):
                """本地调试桩，装进壳后不生效"""
                def fetch(self, url, headers={}, cookies=""):
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                        return type('Resp', (), {
                            'text': resp.read().decode('utf-8', errors='replace'),
                            'status_code': resp.status
                        })()
                def post(self, url, data, headers={}, cookies={}):
                    return self.fetch(url, headers)
                def postJson(self, url, json, headers={}, cookies={}):
                    return self.fetch(url, headers)
                def html(self, content):
                    return content
                def cleanText(self, src):
                    return src
                def loadModule(self, name, fileName):
                    return None
                def getDependence(self):
                    return []


# ===================== Config =====================
INIT_HOSTS = [
    "https://webinit.ali.bdkayc.com",
    "https://init.web.qiyueads.com",
    "https://aliinit.webnew.cqjlzh.com",
    "https://h5init.new.uj926.com",
]
SIGN_KEY = "a2ef62227536ab01"
AES_KEY = b"ec5279154d05ac2c"
AES_IV = b"515cd1587d7cfbdd"
TIMEOUT = 15
UA = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
ORIGIN = "https://e4af6jgl.bjakkgg.cn"
REFERER = "https://e4af6jgl.bjakkgg.cn/"

# ===================== Pure-Python AES-128-CBC =====================
_SBOX = [
    0x63,0x7C,0x77,0x7B,0xF2,0x6B,0x6F,0xC5,0x30,0x01,0x67,0x2B,0xFE,0xD7,0xAB,0x76,
    0xCA,0x82,0xC9,0x7D,0xFA,0x59,0x47,0xF0,0xAD,0xD4,0xA2,0xAF,0x9C,0xA4,0x72,0xC0,
    0xB7,0xFD,0x93,0x26,0x36,0x3F,0xF7,0xCC,0x34,0xA5,0xE5,0xF1,0x71,0xD8,0x31,0x15,
    0x04,0xC7,0x23,0xC3,0x18,0x96,0x05,0x9A,0x07,0x12,0x80,0xE2,0xEB,0x27,0xB2,0x75,
    0x09,0x83,0x2C,0x1A,0x1B,0x6E,0x5A,0xA0,0x52,0x3B,0xD6,0xB3,0x29,0xE3,0x2F,0x84,
    0x53,0xD1,0x00,0xED,0x20,0xFC,0xB1,0x5B,0x6A,0xCB,0xBE,0x39,0x4A,0x4C,0x58,0xCF,
    0xD0,0xEF,0xAA,0xFB,0x43,0x4D,0x33,0x85,0x45,0xF9,0x02,0x7F,0x50,0x3C,0x9F,0xA8,
    0x51,0xA3,0x40,0x8F,0x92,0x9D,0x38,0xF5,0xBC,0xB6,0xDA,0x21,0x10,0xFF,0xF3,0xD2,
    0xCD,0x0C,0x13,0xEC,0x5F,0x97,0x44,0x17,0xC4,0xA7,0x7E,0x3D,0x64,0x5D,0x19,0x73,
    0x60,0x81,0x4F,0xDC,0x22,0x2A,0x90,0x88,0x46,0xEE,0xB8,0x14,0xDE,0x5E,0x0B,0xDB,
    0xE0,0x32,0x3A,0x0A,0x49,0x06,0x24,0x5C,0xC2,0xD3,0xAC,0x62,0x91,0x95,0xE4,0x79,
    0xE7,0xC8,0x37,0x6D,0x8D,0xD5,0x4E,0xA9,0x6C,0x56,0xF4,0xEA,0x65,0x7A,0xAE,0x08,
    0xBA,0x78,0x25,0x2E,0x1C,0xA6,0xB4,0xC6,0xE8,0xDD,0x74,0x1F,0x4B,0xBD,0x8B,0x8A,
    0x70,0x3E,0xB5,0x66,0x48,0x03,0xF6,0x0E,0x61,0x35,0x57,0xB9,0x86,0xC1,0x1D,0x9E,
    0xE1,0xF8,0x98,0x11,0x69,0xD9,0x8E,0x94,0x9B,0x1E,0x87,0xE9,0xCE,0x55,0x28,0xDF,
    0x8C,0xA1,0x89,0x0D,0xBF,0xE6,0x42,0x68,0x41,0x99,0x2D,0x0F,0xB0,0x54,0xBB,0x16,
]
_INV_SBOX = [0] * 256
for _i in range(256):
    _INV_SBOX[_SBOX[_i]] = _i
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _key_expansion(key):
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    for i in range(4, 44):
        temp = w[i - 1][:]
        if i % 4 == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[b] for b in temp]
            temp[0] ^= _RCON[(i // 4) - 1]
        w.append([w[i - 4][j] ^ temp[j] for j in range(4)])
    return w


def _gf_mul(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = ((a << 1) & 0xFF)
        if hi:
            a ^= 0x1B
        b >>= 1
    return p


def _aes_decrypt_block(block, w):
    state = [[block[c * 4 + r] for c in range(4)] for r in range(4)]
    for c in range(4):
        for r in range(4):
            state[r][c] ^= w[40 + c][r]
    for rnd in range(9, 0, -1):
        state[1] = state[1][3:] + state[1][:3]
        state[2] = state[2][2:] + state[2][:2]
        state[3] = state[3][1:] + state[3][:1]
        for r in range(4):
            for c in range(4):
                state[r][c] = _INV_SBOX[state[r][c]]
        for c in range(4):
            for r in range(4):
                state[r][c] ^= w[rnd * 4 + c][r]
        for c in range(4):
            a = [state[r][c] for r in range(4)]
            state[0][c] = _gf_mul(0x0e, a[0]) ^ _gf_mul(0x0b, a[1]) ^ _gf_mul(0x0d, a[2]) ^ _gf_mul(0x09, a[3])
            state[1][c] = _gf_mul(0x09, a[0]) ^ _gf_mul(0x0e, a[1]) ^ _gf_mul(0x0b, a[2]) ^ _gf_mul(0x0d, a[3])
            state[2][c] = _gf_mul(0x0d, a[0]) ^ _gf_mul(0x09, a[1]) ^ _gf_mul(0x0e, a[2]) ^ _gf_mul(0x0b, a[3])
            state[3][c] = _gf_mul(0x0b, a[0]) ^ _gf_mul(0x0d, a[1]) ^ _gf_mul(0x09, a[2]) ^ _gf_mul(0x0e, a[3])
    state[1] = state[1][3:] + state[1][:3]
    state[2] = state[2][2:] + state[2][:2]
    state[3] = state[3][1:] + state[3][:1]
    for r in range(4):
        for c in range(4):
            state[r][c] = _INV_SBOX[state[r][c]]
    for c in range(4):
        for r in range(4):
            state[r][c] ^= w[c][r]
    out = bytearray(16)
    for c in range(4):
        for r in range(4):
            out[c * 4 + r] = state[r][c]
    return bytes(out)


def _aes_cbc_decrypt(ciphertext, key, iv):
    w = _key_expansion(key)
    plaintext = bytearray()
    prev = iv
    for i in range(0, len(ciphertext), 16):
        block = ciphertext[i:i + 16]
        dec = _aes_decrypt_block(block, w)
        for j in range(16):
            plaintext.append(dec[j] ^ prev[j])
        prev = block
    pad_len = plaintext[-1]
    if 1 <= pad_len <= 16:
        plaintext = plaintext[:-pad_len]
    return bytes(plaintext)


# ===================== Crypto =====================
def _gen_sign(pathname, ts=None):
    if ts is None:
        ts = int(time.time())
    sign_str = "%s?time=%s&%s" % (pathname, ts, SIGN_KEY)
    return ts, hashlib.md5(sign_str.encode()).hexdigest().lower()


def _aes_decrypt(data_b64):
    ct = base64.b64decode(data_b64)
    pt = _aes_cbc_decrypt(ct, AES_KEY, AES_IV)
    return json.loads(pt.decode("utf-8"))


def _decrypt_response(rj):
    if not isinstance(rj, dict):
        return None
    data = rj.get("data")
    if isinstance(data, str) and len(data) > 0:
        try:
            rj["data"] = _aes_decrypt(data)
        except Exception:
            pass
    return rj


# ===================== HTTP =====================
def _http_post(host, path, data=None, ct="application/x-www-form-urlencoded",
                token=None, uid=None):
    if data is None:
        data = {}
    sign_path = "/api%s" % path
    ts, sign = _gen_sign(sign_path)
    url = "%s/api%s" % (host, path)
    post_data = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=post_data, method="POST")
    req.add_header("User-Agent", UA)
    req.add_header("X-App-Version", "7")
    req.add_header("time", str(ts))
    req.add_header("sign", sign)
    req.add_header("Content-Type", ct)
    req.add_header("Origin", ORIGIN)
    req.add_header("Referer", REFERER)
    if token:
        req.add_header("Access-Token", token)
        req.add_header("token", token)
    if uid:
        req.add_header("uid", str(uid))
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            body = resp.read()
            try:
                # Encrypted base64 response
                ct_bytes = base64.b64decode(body)
                pt = _aes_cbc_decrypt(ct_bytes, AES_KEY, AES_IV)
                rj = json.loads(pt.decode("utf-8"))
            except Exception:
                # Plain JSON fallback
                rj = json.loads(body.decode("utf-8"))
            return _decrypt_response(rj)
    except Exception:
        return None


# ===================== API =====================
class QiyueAPI:
    def __init__(self):
        self.host = INIT_HOSTS[0]
        self.host_idx = 0
        self.api_host = None
        self.token = None
        self.uid = None
        self.last_switch = 0
        self._cate2_cache = {}
        self._vod_cache = {}

    def _switch_host(self):
        now = time.time()
        if now - self.last_switch < 5:
            return False
        self.last_switch = now
        self.host_idx = (self.host_idx + 1) % len(INIT_HOSTS)
        self.host = INIT_HOSTS[self.host_idx]
        return True

    def init(self):
        r = _http_post(self.host, "/player/do_init_h5", {
            "system": "3", "channel": "1051", "new_live": "1"
        })
        if r and r.get("code") == 1 and isinstance(r.get("data"), dict):
            pi = r["data"].get("player_info", {})
            self.token = pi.get("token", "")
            self.uid = pi.get("uid", "")
            api_url = r["data"].get("api_url", "")
            if api_url:
                self.api_host = api_url.rstrip("/")
            return True
        return False

    def _ensure_init(self):
        if self.token is None:
            self.init()

    def get_index(self):
        self._ensure_init()
        return _http_post(self.host, "/video/index", {}, token=self.token, uid=self.uid)

    def get_cate_list(self, cate_id, page=1):
        self._ensure_init()
        return _http_post(self.host, "/video/cate_list", {
            "cate_id": cate_id, "page": page
        }, token=self.token, uid=self.uid)

    def get_cate2_list(self, cate2_id, page=1):
        self._ensure_init()
        return _http_post(self.host, "/video/cate2_list", {
            "cate2_id": cate2_id, "page": page
        }, token=self.token, uid=self.uid)

    def search(self, keyword, page=1):
        self._ensure_init()
        return _http_post(self.host, "/video/search_list", {
            "keyword": keyword, "page": page
        }, token=self.token, uid=self.uid)

    def search_video_library(self, keyword, page=1, video_id=None):
        self._ensure_init()
        params = {"keyword": keyword, "page": page}
        if video_id:
            params["video_id"] = video_id
        return _http_post(self.host, "/video/search_video_library", params,
                           token=self.token, uid=self.uid)

    def get_new_updates(self, page=1):
        self._ensure_init()
        return _http_post(self.host, "/video/new_update_list", {
            "page": page
        }, token=self.token, uid=self.uid)

    def get_video_info(self, video_id):
        self._ensure_init()
        host = self.api_host or self.host
        sign_path = "/api/video/video_info"
        ts, sign = _gen_sign(sign_path)
        url = "%s/api/video/video_info" % host
        post_data = urllib.parse.urlencode({"video_id": video_id, "is_h5": "1"}).encode("utf-8")
        req = urllib.request.Request(url, data=post_data, method="POST")
        req.add_header("User-Agent", UA)
        req.add_header("X-App-Version", "7")
        req.add_header("time", str(ts))
        req.add_header("sign", sign)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("Origin", ORIGIN)
        req.add_header("Referer", REFERER)
        if self.token:
            req.add_header("Access-Token", self.token)
            req.add_header("token", self.token)
        if self.uid:
            req.add_header("uid", str(self.uid))
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
                body = resp.read()
                try:
                    ct_bytes = base64.b64decode(body)
                    pt = _aes_cbc_decrypt(ct_bytes, AES_KEY, AES_IV)
                    rj = json.loads(pt.decode("utf-8"))
                except Exception:
                    rj = json.loads(body.decode("utf-8"))
                return _decrypt_response(rj)
        except Exception:
            return None

    def cache_vod(self, v):
        if not isinstance(v, dict):
            return
        vid = v.get("video_id") or v.get("id")
        if not vid:
            return
        self._vod_cache[str(vid)] = {
            "vod_id": str(vid),
            "title": v.get("title", v.get("video_title", "")),
            "img": v.get("img", v.get("video_img", "")),
            "tags": v.get("tags", ""),
            "cate2": v.get("cate2", ""),
            "video_time": v.get("video_time", ""),
            "is_vip": v.get("is_vip", v.get("video_is_vip", 0)),
            "play_num": v.get("play_num", ""),
        }

    def get_cached_vod(self, vid):
        return self._vod_cache.get(str(vid))

    def get_cate2_ids(self, tid):
        tid_str = str(tid)
        if tid_str in self._cate2_cache:
            return self._cate2_cache[tid_str]
        data = self.get_cate_list(tid, 1)
        ids = []
        if data and data.get("code") == 1 and isinstance(data.get("data"), dict):
            for c2 in data["data"].get("cate2_list", []):
                cid = c2.get("id")
                if cid:
                    ids.append(cid)
        if ids:
            self._cate2_cache[tid_str] = ids
        return ids


# ===================== Global instance =====================
_api = None


def _get_api():
    global _api
    if _api is None:
        _api = QiyueAPI()
        _api.init()
    return _api


# ===================== TVBox Interfaces =====================
def homeContent(filter):
    api = _get_api()
    classes = []
    videos = []

    data = api.get_index()
    if data and data.get("code") == 1 and isinstance(data.get("data"), dict):
        d = data["data"]

        for cat in d.get("cate_list", []):
            classes.append({
                "type_id": str(cat.get("cate_id", "")),
                "type_name": cat.get("name", ""),
            })

        for section in d.get("recommend_list", []):
            if not isinstance(section, dict):
                continue
            for v in section.get("list", []):
                if not isinstance(v, dict):
                    continue
                videos.append(_build_vod(v))
                if len(videos) >= 20:
                    break
            if len(videos) >= 20:
                break

    return {"class": classes, "list": videos}


def homeVideoContent():
    api = _get_api()
    videos = []
    data = api.get_index()
    if data and data.get("code") == 1 and isinstance(data.get("data"), dict):
        for section in data["data"].get("recommend_list", []):
            if not isinstance(section, dict):
                continue
            for v in section.get("list", []):
                if not isinstance(v, dict):
                    continue
                videos.append(_build_vod(v))
                if len(videos) >= 20:
                    break
            if len(videos) >= 20:
                break
    return {"list": videos}


def categoryContent(tid, pg, filter, ext):
    api = _get_api()
    page = int(pg) if pg else 1

    cate2_id = None
    if ext and isinstance(ext, dict):
        cate2_id = ext.get("cate2_id")

    if page == 1 and not cate2_id:
        data = api.get_cate_list(tid, 1)
        if not data or data.get("code") != 1 or not isinstance(data.get("data"), dict):
            return {"list": [], "page": str(page), "pagecount": "1", "limit": "20", "total": "0"}

        d = data["data"]

        # Cache cate2_ids from this response to avoid extra API call on page 2+
        cate2_ids = []
        for c2 in d.get("cate2_list", []):
            cid = c2.get("id")
            if cid:
                cate2_ids.append(cid)
        if cate2_ids:
            api._cate2_cache[str(tid)] = cate2_ids

        videos = []

        for item in d.get("list", []):
            if isinstance(item, dict) and "list" in item:
                for v in item.get("list", []):
                    if isinstance(v, dict):
                        videos.append(_build_vod(v))
            elif isinstance(item, dict) and item.get("video_id"):
                videos.append(_build_vod(item))

        # If no preview videos, load from first subcategory
        pagecount = 1 if not cate2_ids else 200
        if not videos and cate2_ids:
            sub_data = api.get_cate2_list(cate2_ids[0], 1)
            if sub_data and sub_data.get("code") == 1 and isinstance(sub_data.get("data"), dict):
                sd = sub_data["data"]
                for v in sd.get("list", []):
                    if isinstance(v, dict):
                        videos.append(_build_vod(v))
                # Use cate2_info.count for accurate pagecount
                info = sd.get("cate2_info", {})
                count = info.get("count", 0) if isinstance(info, dict) else 0
                if count > 0:
                    pagecount = max(1, (count + 19) // 20)
                else:
                    pagecount = 1

        return {
            "list": videos[:20],
            "page": str(page),
            "pagecount": str(pagecount),
            "limit": "20",
            "total": str(len(videos)),
        }

    else:
        if not cate2_id:
            cate2_ids = api.get_cate2_ids(tid)
            if not cate2_ids:
                return {"list": [], "page": str(page), "pagecount": "1", "limit": "20", "total": "0"}
            cate2_id = cate2_ids[0]

        data = api.get_cate2_list(cate2_id, page)
        if not data or data.get("code") != 1 or not isinstance(data.get("data"), dict):
            return {"list": [], "page": str(page), "pagecount": "1", "limit": "20", "total": "0"}

        d = data["data"]
        videos = []
        for v in d.get("list", []):
            if isinstance(v, dict):
                videos.append(_build_vod(v))

        # Calculate pagecount from cate2_info.count (provided by API)
        info = d.get("cate2_info", {})
        count = info.get("count", 0) if isinstance(info, dict) else 0
        pagecount = max(1, (count + 19) // 20) if count > 0 else 1

        return {
            "list": videos,
            "page": str(page),
            "pagecount": str(pagecount),
            "limit": "20",
            "total": str(count if count > 0 else len(videos)),
        }


def detailContent(ids):
    api = _get_api()
    vid = ids[0]
    try:
        vid_int = int(vid)
    except (ValueError, TypeError):
        return {"list": []}

    info = api.get_video_info(vid_int)
    if info and info.get("code") == 1 and isinstance(info.get("data"), dict):
        d = info["data"]
        vi = d.get("video_info") if isinstance(d.get("video_info"), dict) else d
        title = vi.get("title", "")
        img = vi.get("img", vi.get("cover", ""))
        desc = vi.get("desc", vi.get("content", ""))
        cate2 = vi.get("cate2", "")
        if isinstance(cate2, dict):
            cate2 = cate2.get("name", "")
        tags = vi.get("tags", "") or cate2
        duration = vi.get("video_time", vi.get("duration", ""))

        # 多线路：video_line = [{"name": "线路1", "url": "..."}, ...]
        lines = vi.get("video_line") or []
        play_from_list = []
        play_url_list = []
        if isinstance(lines, list) and lines:
            for line in lines:
                if not isinstance(line, dict):
                    continue
                line_url = line.get("url", "")
                if not line_url:
                    continue
                line_name = line.get("name", "") or "线路%s" % (len(play_from_list) + 1)
                play_from_list.append(line_name)
                play_url_list.append("%s$%s" % (line_name, line_url))
        else:
            play_url = vi.get("play_url", vi.get("url", vi.get("play_url_1", "")))
            if play_url:
                play_from_list.append("7\u6708\u89c6\u9891")
                play_url_list.append("%s$%s" % ("播放", play_url))

        return {
            "list": [{
                "vod_id": str(vid),
                "vod_name": title,
                "vod_pic": _proxy_url(img),
                "vod_content": desc,
                "vod_play_from": "$$$".join(play_from_list),
                "vod_play_url": "$$$".join(play_url_list),
                "type_name": str(tags) if tags else "",
                "vod_remarks": str(duration) if duration else "",
            }]
        }

    cached = api.get_cached_vod(vid)
    if cached:
        return {
            "list": [{
                "vod_id": str(vid),
                "vod_name": cached.get("title", ""),
                "vod_pic": _proxy_url(cached.get("img", "")),
                "vod_content": cached.get("tags", ""),
                "vod_play_from": "7\u6708\u89c6\u9891",
                "vod_play_url": "",
                "type_name": cached.get("cate2", ""),
                "vod_remarks": cached.get("video_time", ""),
            }]
        }

    lib_result = api.search_video_library("", 1, video_id=vid_int)
    if lib_result and lib_result.get("code") == 1 and isinstance(lib_result.get("data"), list):
        for v in lib_result["data"]:
            if str(v.get("video_id")) == str(vid):
                return {
                    "list": [{
                        "vod_id": str(vid),
                        "vod_name": v.get("title", ""),
                        "vod_pic": _proxy_url(v.get("img", "")),
                        "vod_content": v.get("tags", ""),
                        "vod_play_from": "7\u6708\u89c6\u9891",
                        "vod_play_url": "",
                        "type_name": v.get("cate2", ""),
                        "vod_remarks": v.get("video_time", ""),
                    }]
                }

    search_result = api.search(str(vid), 1)
    if search_result and search_result.get("code") == 1 and isinstance(search_result.get("data"), list):
        for v in search_result["data"]:
            if str(v.get("video_id")) == str(vid):
                return {
                    "list": [{
                        "vod_id": str(vid),
                        "vod_name": v.get("title", ""),
                        "vod_pic": _proxy_url(v.get("img", "")),
                        "vod_content": v.get("tags", ""),
                        "vod_play_from": "7\u6708\u89c6\u9891",
                        "vod_play_url": "",
                        "type_name": v.get("cate2", ""),
                        "vod_remarks": v.get("video_time", ""),
                    }]
                }

    return {
        "list": [{
            "vod_id": str(vid),
            "vod_name": "\u89c6\u9891 %s" % vid,
            "vod_pic": "",
            "vod_content": "\u9700\u8981\u767b\u5f55\u540e\u624d\u80fd\u83b7\u53d6\u64ad\u653e\u5730\u5740",
            "vod_play_from": "",
            "vod_play_url": "",
        }]
    }


def searchContent(key, quick, pg=1):
    api = _get_api()
    page = int(pg) if pg else 1
    data = api.search(key, page)
    if not data or data.get("code") != 1 or not isinstance(data.get("data"), list):
        return {"list": [], "page": str(page), "pagecount": "1", "limit": "20", "total": "0"}

    videos = []
    for v in data["data"]:
        if not isinstance(v, dict):
            continue
        videos.append(_build_vod(v))

    return {
        "list": videos,
        "page": str(page),
        "pagecount": "100",
        "limit": "20",
        "total": str(len(videos)),
    }


def playerContent(flags, id, vipFlags):
    return {
        "parse": 0,
        "playUrl": "",
        "url": id,
        "header": {"User-Agent": UA},
    }


# ===================== Helpers =====================
def _build_vod(v):
    api = _get_api()
    api.cache_vod(v)
    raw_pic = v.get("img", v.get("video_img", ""))
    return {
        "vod_id": str(v.get("video_id", v.get("id", ""))),
        "vod_name": v.get("title", v.get("video_title", "")),
        "vod_pic": _proxy_url(raw_pic),
        "vod_remarks": v.get("video_time", "") or ("VIP" if v.get("is_vip", v.get("video_is_vip")) else ""),
    }


def _proxy_url(u):
    """站点图片走 localProxy: 经 jk 解密后 TVBox 才能正常显示"""
    if not u:
        return ""
    return "http://127.0.0.1:9978/proxy?url=" + urllib.parse.quote(str(u), safe="")


def _img_mime(data):
    if not data or len(data) < 12:
        return "application/octet-stream"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"GIF8":
        return "image/gif"
    return "application/octet-stream"


def _decrypt_img(raw_b64):
    """前端 jk(t) 解密实现: base64 -> 偏移字节 -> (byte-n)^Ga[i%32]"""
    ga = hashlib.sha256(b"sdkvgl2hj92h23h923h").digest()
    try:
        data = base64.b64decode(raw_b64)
    except Exception:
        return b""
    if len(data) < 1:
        return b""
    n = data[0]
    rest = data[1:]
    r = bytearray(len(rest))
    for i in range(len(rest)):
        r[i] = ((rest[i] - n) & 0xFF) ^ ga[i % 32]
    return bytes(r)


def _proxy_fetch(url):
    """拉取并解密封面图, 返回 [status, mime, data]"""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": REFERER})
        data = urllib.request.urlopen(req, context=ctx, timeout=15).read()
        dec = _decrypt_img(data)
        mime = _img_mime(dec)
        return [200, mime, dec]
    except Exception:
        return [500, "text/plain", b"proxy error"]


# ===================== TVBox Standard Class Wrapper =====================
class Spider(BaseSpider):
    def __init__(self):
        pass

    def getName(self):
        return "\u4e03\u6708\u89c6\u9891"

    def init(self, extend):
        return

    def homeContent(self, filter):
        return homeContent(filter)

    def homeVideoContent(self):
        return homeVideoContent()

    def categoryContent(self, tid, pg, filter, ext):
        return categoryContent(tid, pg, filter, ext)

    def detailContent(self, ids):
        return detailContent(ids)

    def searchContent(self, key, quick, pg=1):
        return searchContent(key, quick, pg)

    def playerContent(self, flags, id, vipFlags):
        return playerContent(flags, id, vipFlags)

    def searchContentPage(self, key, quick, pg):
        return searchContent(key, quick, pg)

    def localProxy(self, param):
        url = ""
        if isinstance(param, dict):
            url = param.get("url", "")
        elif isinstance(param, str):
            url = param
        if not url:
            return [400, "text/plain", b"missing url"]
        url = urllib.parse.unquote(url)
        return _proxy_fetch(url)

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False


# ===================== Main (for testing) =====================
if __name__ == "__main__":
    print("=== Initializing API ===")
    api = QiyueAPI()
    ok = api.init()
    print("Init: %s" % ("OK" if ok else "FAIL"))
    if ok and api.token:
        print("Token: %s..." % api.token[:40])
        print("UID: %s" % api.uid)
        print("API Host: %s" % api.api_host)

    print("\n=== video/index ===")
    r = api.get_index()
    if r and r.get("code") == 1:
        d = r["data"]
        print("Categories: %s" % len(d.get("cate_list", [])))
        print("Recommend sections: %s" % len(d.get("recommend_list", [])))
        for c in d.get("cate_list", [])[:5]:
            print("  %s: %s" % (c.get("cate_id"), c.get("name")))

    print("\n=== TVBox homeContent ===")
    h = homeContent(False)
    print("Classes: %s" % len(h.get("class", [])))
    print("Videos: %s" % len(h.get("list", [])))

    print("\n=== TVBox categoryContent (page 1, cate=607) ===")
    c = categoryContent("607", "1", 0, {})
    print("Videos: %s" % len(c.get("list", [])))
    print("Pagecount: %s" % c.get("pagecount"))
    if c.get("list"):
        print("First: %s" % c["list"][0].get("vod_name", "")[:40])

    print("\n=== TVBox searchContent ===")
    s = searchContent("\u5973\u795e", False, 1)
    print("Videos: %s" % len(s.get("list", [])))
    if s.get("list"):
        print("First: %s" % s["list"][0].get("vod_name", "")[:40])
