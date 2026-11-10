import os
import re
import ast
import json
import time
import base64
import shutil
import fnmatch
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from base.spider import Spider

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    import urllib.request
    import urllib.error


class Spider(Spider):
    SCAN_DIRS = [
        "/storage/emulated/0/tvbox/py",
        "/storage/emulated/0/tvbox/js",
        "/storage/emulated/0/tvbox/cat",
        "/storage/emulated/0/tvbox/xbpq",
        "/storage/emulated/0/tvbox/live",
    ]
    BASE_DIR = "/storage/emulated/0/tvbox"
    SAVE_PATH = f"{BASE_DIR}/自动加载.json"
    REPORT_PATH = f"{BASE_DIR}/检测报告.json"
    CACHE_FILE = f"{BASE_DIR}/.check_cache.json"
    DISABLED_FILE = f"{BASE_DIR}/禁用列表.json"
    PIN_FILE = f"{BASE_DIR}/置顶列表.json"
    LOG_FILE = f"{BASE_DIR}/spider.log"
    IGNORE_FILE = f"{BASE_DIR}/.ignore"
    BACKUP_DIR = f"{BASE_DIR}/backup"

    LOG_MAX_SIZE = 1024 * 1024
    MAX_BACKUPS = 10
    AUTO_DISABLE_THRESHOLD = 3
    INIT_MAX_RETRY = 3

    CATEGORY_PREFIX_ORDER = ["视", "播", "漫", "游", "短", "听", "瑟", "工"]

    JS_LOAD_MODE = "direct"
    JS_DRPY_API = "./lib/drpy2.min.js"
    XBPQ_API = "csp_XBPQ"

    SKIP_JS_CHECK = True
    ALWAYS_RETRY_FAILED = True

    STATIC_EXTS = (
        '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.bmp',
        '.css', '.woff', '.woff2', '.ttf', '.otf', '.eot',
        '.mp4', '.mp3', '.avi', '.mkv', '.ts', '.m3u8',
        '.js.map', '.css.map',
    )

    CLASS_COVER = {
        "PY": "file://tvbox/icon/py.png",
        "JS": "file://tvbox/icon/js.png",
        "CAT": "file://tvbox/icon/cat.png",
        "XBPQ": "file://tvbox/icon/xbpq.png"
    }

    EXCLUDE_FILES = {
        "JS": [
            "drpy2-fast.min.js", "drpy-core-lite.min.js",
            "drpy2.min.js", "drpy2-obj.min.js",
            "drpy2-template.js", "drpy2.js", "config.js",
        ],
        "PY": ["自动加载.py"],
    }

    TYPE_CLASSES = ["全部", "PY", "JS", "CAT", "XBPQ", "⚠无效"]
    TYPE_ORDER = {"PY": 0, "JS": 1, "CAT": 2, "XBPQ": 3, "LIVE": 4}

    PANEL_ACTIONS = {
        "🔄重扫":   "rescan",
        "📊状态":   "status",
        "💾备份":   "backup",
        "🗑️清缓存": "clear_cache",
        "🔓清禁用": "clear_disabled",
        "📍清置顶": "clear_pin",
        "🧹清理":   "cleanup",
    }
    PANEL_THROTTLE = 10

    ENABLE_DYNAMIC_CHECK = True
    DYNAMIC_TIMEOUT = 8
    DYNAMIC_MAX_URLS = 3
    DYNAMIC_RETRY = 1
    CHECK_LIVE = False
    MAX_WORKERS = 10
    PAGE_SIZE = 20
    DIR_CHECK_INTERVAL = 5

    def __init__(self):
        super().__init__()
        self.inited = False
        self._init_fail_count = 0
        self.self_path = None
        self._lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._file_lock = threading.Lock()   # 保护所有写文件操作
        self._dynamic_running = False
        self._last_dirs_sig = ""
        self._last_dir_check = 0
        self._panel_last_exec = {}
        self._scan_gen = 0
        self.cache = {
            "categories": [], "file_index": {}, "type_groups": {},
            "live_files": [], "invalid_files": []
        }
        self.check_cache = {}
        self.disabled_set = set()
        self.pin_set = set()
        self.ignore_patterns = []
        self.last_check_ts = 0

    def getName(self):
        return "本地爬虫自动聚合源（管理面板版）"

    # ==========================================================
    # 分类排序
    # ==========================================================
    def _extract_prefix(self, file_name):
        m = re.match(r'^\[(.+?)\]', file_name)
        if m:
            return m.group(1).strip()
        return ""

    def _get_category_rank(self, file_name):
        prefix = self._extract_prefix(file_name)
        if not prefix:
            return len(self.CATEGORY_PREFIX_ORDER) + 1
        if prefix in self.CATEGORY_PREFIX_ORDER:
            return self.CATEGORY_PREFIX_ORDER.index(prefix)
        return len(self.CATEGORY_PREFIX_ORDER)

    # ==========================================================
    # 工具 / 日志
    # ==========================================================
    def _log(self, msg):
        try:
            if os.path.exists(self.LOG_FILE) and \
                    os.path.getsize(self.LOG_FILE) > self.LOG_MAX_SIZE:
                try:
                    rot = self.LOG_FILE + ".1"
                    if os.path.exists(rot):
                        os.remove(rot)
                    os.replace(self.LOG_FILE, rot)
                except Exception:
                    pass
            with open(self.LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except Exception:
            pass

    def _human_time(self, ts):
        if not ts:
            return "-"
        delta = time.time() - ts
        if delta < 60:
            return "刚刚"
        if delta < 3600:
            return f"{int(delta / 60)}分钟前"
        if delta < 86400:
            return f"{int(delta / 3600)}小时前"
        if delta < 86400 * 30:
            return f"{int(delta / 86400)}天前"
        return time.strftime("%Y-%m-%d", time.localtime(ts))

    def _human_size(self, size):
        try:
            if size < 1024:
                return f"{size}B"
            if size < 1024 * 1024:
                return f"{size / 1024:.1f}KB"
            return f"{size / 1024 / 1024:.1f}MB"
        except Exception:
            return "?"

    def _read_text(self, f_path):
        with open(f_path, "r", encoding="utf-8-sig", errors="ignore") as fp:
            content = fp.read()
        if content and content[0] == '\ufeff':
            content = content[1:]
        return content

    def _detect_file_encoding_issue(self, f_path):
        try:
            with open(f_path, "rb") as f:
                raw = f.read(2048)
        except Exception as e:
            return f"无法读取: {e}"
        if raw.startswith(b"\xef\xbb\xbf"): return "UTF-8 BOM"
        if raw.startswith(b"\xff\xfe"): return "UTF-16 LE"
        if raw.startswith(b"\xfe\xff"): return "UTF-16 BE"
        if raw.startswith(b"PK\x03\x04"): return "ZIP 压缩包"
        if raw.startswith(b"{"): return "JSON 内容"
        if b"\x00" in raw: return "含 null byte"
        return None

    def _detect_type_tag(self, dir_name, file_ext):
        d, e = dir_name.lower(), file_ext.lower()
        if "live" in d: return "LIVE", 0
        if "cat" in d: return "CAT", 3
        if "xbpq" in d: return "XBPQ", 3
        if "js" in d and "py" not in d: return "JS", 3
        if "py" in d and "js" not in d: return "PY", 3
        if e == ".py": return "PY", 3
        if e == ".js": return "JS", 3
        if e == ".json": return "XBPQ", 3
        if e in [".txt", ".m3u"]: return "LIVE", 0
        return "PY", 3

    def _get_ext_list(self, dir_name):
        d = dir_name.lower()
        if "live" in d: return [".txt", ".m3u"]
        if d == "py": return [".py"]
        if d == "js": return [".js"]
        if d == "cat": return [".js"]
        if d == "xbpq": return [".json"]
        return [".py", ".js", ".json"]

    def _get_tag_prefix(self, type_tag):
        return {"PY": "[py]", "JS": "[js]", "XBPQ": "[xbpq]",
                "CAT": "[cat]", "LIVE": "[live]"}.get(type_tag, "⁽ᵘ⁾")

    def _is_excluded(self, file_name, type_tag):
        if type_tag in self.EXCLUDE_FILES:
            if file_name.lower() in [x.lower() for x in self.EXCLUDE_FILES[type_tag]]:
                return True
        return False

    def _is_ignored(self, file_name, rel_path):
        for pat in self.ignore_patterns:
            if pat.endswith("/"):
                if rel_path.startswith(pat) or \
                        rel_path.startswith(pat.rstrip("/") + "/"):
                    return True
                continue
            if fnmatch.fnmatch(file_name, pat):
                return True
            if fnmatch.fnmatch(rel_path, pat):
                return True
        return False

    def _load_ignore_patterns(self):
        if not os.path.exists(self.IGNORE_FILE):
            return []
        try:
            with open(self.IGNORE_FILE, "r", encoding="utf-8-sig") as f:
                return [l.strip() for l in f
                        if l.strip() and not l.strip().startswith("#")]
        except Exception as e:
            self._log(f"加载 .ignore 失败: {e}")
            return []

    def _load_json_list(self, path):
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [str(x) for x in data]
        except Exception as e:
            self._log(f"加载 {path} 失败: {e}")
        return []

    def _save_json_list(self, path, lst):
        # 原子写: 先写临时文件再 rename, 加锁避免并发
        try:
            with self._file_lock:
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(sorted(set(lst)), f,
                              ensure_ascii=False, indent=2)
                os.replace(tmp, path)
        except Exception as e:
            self._log(f"保存 {path} 失败: {e}")

    def _file_key(self, f_path):
        try:
            st = os.stat(f_path)
            return f"{f_path}|{int(st.st_mtime)}|{st.st_size}"
        except Exception:
            return None

    def _guess_live_group(self, file_name):
        n = file_name
        u = n.upper()
        if "央视" in n or "CCTV" in u or "中央" in n: return "央视"
        if "卫视" in n: return "卫视"
        if "地方" in n or "省级" in n: return "地方"
        if "港" in n or "澳" in n or "台" in n: return "港台"
        if "海外" in n or "国际" in n: return "海外"
        if "4K" in u or "8K" in u: return "4K"
        return "其他"

    # ==========================================================
    # 检测缓存
    # ==========================================================
    def _load_check_cache(self):
        if not os.path.exists(self.CACHE_FILE):
            return {}
        try:
            with open(self.CACHE_FILE, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception as e:
            self._log(f"加载检测缓存失败: {e}")
        return {}

    def _save_check_cache(self):
        try:
            with self._cache_lock:
                snapshot = dict(self.check_cache)
            # 原子写
            with self._file_lock:
                tmp = self.CACHE_FILE + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, ensure_ascii=False)
                os.replace(tmp, self.CACHE_FILE)
        except Exception as e:
            self._log(f"保存检测缓存失败: {e}")

    def _update_check_cache(self, f_path, ok, msg):
        fkey = self._file_key(f_path)
        if not fkey:
            return
        with self._cache_lock:
            old = self.check_cache.get(fkey, {})
            new_fail = 0 if ok else old.get("fail_count", 0) + 1
            new_ok = old.get("ok_count", 0) + (1 if ok else 0)
            self.check_cache[fkey] = {
                "ok": ok, "msg": msg, "ts": time.time(),
                "fail_count": new_fail, "ok_count": new_ok
            }

    def _get_score(self, fkey):
        with self._cache_lock:
            c = self.check_cache.get(fkey)
        if not c:
            return None
        ok = c.get("ok_count", 0)
        fail = c.get("fail_count", 0)
        total = ok + fail
        if total == 0:
            return None
        return int(ok / total * 100)

    def _get_cache_entry(self, fkey):
        with self._cache_lock:
            c = self.check_cache.get(fkey)
        if not c:
            return None
        if not c.get("ok", True) and self.ALWAYS_RETRY_FAILED:
            return None
        return c

    def _cleanup_check_cache(self):
        try:
            with self._lock:
                valid_paths = {info["path"]
                               for info in self.cache["file_index"].values()}
            with self._cache_lock:
                removed = 0
                for k in list(self.check_cache.keys()):
                    fpath = k.split("|")[0]
                    if fpath not in valid_paths:
                        del self.check_cache[k]
                        removed += 1
            if removed:
                self._log(f"🧹 清理僵尸缓存 {removed} 条")
            return removed
        except Exception as e:
            self._log(f"清理缓存失败: {e}")
            return 0

    def _clear_cache_file(self):
        with self._cache_lock:
            old = len(self.check_cache)
            self.check_cache = {}
        try:
            with self._file_lock:
                if os.path.exists(self.CACHE_FILE):
                    os.remove(self.CACHE_FILE)
        except Exception:
            pass
        return old

    # ==========================================================
    # 目录变化检查
    # ==========================================================
    def _get_dirs_signature(self):
        parts = []
        for d in self.SCAN_DIRS:
            if not os.path.isdir(d):
                parts.append("x")
                continue
            try:
                mt = int(os.path.getmtime(d))
                cnt = 0
                try:
                    for item in os.listdir(d):
                        p = os.path.join(d, item)
                        if os.path.isdir(p):
                            try:
                                mt = max(mt, int(os.path.getmtime(p)))
                            except Exception:
                                pass
                        else:
                            cnt += 1
                except Exception:
                    pass
                parts.append(f"{mt}:{cnt}")
            except Exception:
                parts.append("err")
        return "|".join(parts)

    def _check_dirs_changed(self):
        now = time.time()
        if now - self._last_dir_check < self.DIR_CHECK_INTERVAL:
            return False
        self._last_dir_check = now
        sig = self._get_dirs_signature()
        if sig != self._last_dirs_sig:
            self._last_dirs_sig = sig
            return True
        return False

    # ==========================================================
    # 静态检测
    # ==========================================================
    def _check_site_code(self, f_path, type_tag):
        try:
            if not os.path.isfile(f_path):
                return False, "文件不存在"
            if os.path.getsize(f_path) == 0:
                return False, "空文件"

            if type_tag in ("JS", "CAT") and self.SKIP_JS_CHECK:
                return True, "跳过检测"

            content = self._read_text(f_path)
            if not content.strip():
                return False, "内容为空"

            if type_tag == "PY":
                try:
                    tree = ast.parse(content)
                except SyntaxError as e:
                    extra = self._detect_file_encoding_issue(f_path)
                    if extra:
                        return False, f"语法错误 L{e.lineno} ({extra})"
                    return False, f"语法错误 L{e.lineno}"
                except ValueError as e:
                    return False, f"内容异常: {e}"

                classes = [n.name for n in ast.walk(tree)
                           if isinstance(n, ast.ClassDef)]
                funcs = [n.name for n in ast.walk(tree)
                         if isinstance(n, ast.FunctionDef)]
                if not any("Spider" in c for c in classes):
                    return False, "缺少 Spider 类"
                if "homeContent" not in funcs:
                    return False, "缺少 homeContent"
                return True, "OK"

            if type_tag in ("JS", "CAT"):
                stripped = content.strip()
                if len(stripped) < 3:
                    return False, "内容过短"
                low = stripped[:100].lower()
                if low.startswith(("<!doctype", "<html", "<head", "<body",
                                   "<meta", "<?xml")):
                    return False, "是 HTML 页面"
                head300 = stripped[:300].lower()
                if "404 not found" in head300 or \
                        "403 forbidden" in head300 or \
                        "502 bad gateway" in head300 or \
                        "503 service unavailable" in head300:
                    return False, "是错误页面"
                return True, "OK"

            if type_tag == "XBPQ":
                try:
                    data = json.loads(content)
                except Exception as e:
                    return False, f"JSON 错误: {e}"
                if not isinstance(data, (dict, list)):
                    return False, "JSON 结构异常"
                return True, "OK"

            return True, "OK"
        except Exception as e:
            return False, f"检测异常: {e}"

    # ==========================================================
    # 动态检测
    # ==========================================================
    def _http_probe(self, url, timeout=None, method="HEAD"):
        if timeout is None:
            timeout = self.DYNAMIC_TIMEOUT
        headers = {"User-Agent": "Mozilla/5.0"}
        if HAS_REQUESTS:
            try:
                if method == "HEAD":
                    r = requests.head(url, timeout=timeout, headers=headers,
                                      allow_redirects=True)
                else:
                    r = requests.get(url, timeout=timeout, headers=headers,
                                     stream=True)
                return r.status_code, r
            except requests.exceptions.Timeout:
                return None, "连接超时"
            except requests.exceptions.SSLError:
                return None, "SSL 证书错误"
            except requests.exceptions.ConnectionError:
                return None, "无法连接 (DNS/网络)"
            except Exception as e:
                return None, f"请求异常: {e}"
        else:
            try:
                req = urllib.request.Request(url, headers=headers, method=method)
                ctx = None
                if url.startswith("https"):
                    import ssl
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
                return resp.getcode(), resp
            except urllib.error.HTTPError as e:
                return e.code, None
            except urllib.error.URLError as e:
                return None, f"无法连接: {e.reason}"
            except Exception as e:
                return None, f"请求异常: {e}"

    def _check_remote_source(self, url, timeout=None, retry=None):
        if retry is None:
            retry = self.DYNAMIC_RETRY
        last_msg = ""
        for attempt in range(retry + 1):
            code, resp = self._http_probe(url, timeout, method="HEAD")
            if isinstance(code, str) or code is None:
                last_msg = resp if isinstance(resp, str) else "请求异常"
            else:
                if code == 404:
                    last_msg = "链接已失效 (404)"
                elif code == 410:
                    last_msg = "资源已删除 (410)"
                elif code >= 500:
                    last_msg = f"服务器错误 ({code})"
                elif code >= 400:
                    code2, _ = self._http_probe(url, timeout, method="GET")
                    if isinstance(code2, int) and code2 < 400:
                        return True, "OK"
                    last_msg = f"请求被拒绝 ({code})"
                else:
                    return True, "OK"
            if attempt < retry:
                time.sleep(1)
        return False, last_msg or "未知错误"

    def _check_live_url(self, url, timeout=None):
        if timeout is None:
            timeout = self.DYNAMIC_TIMEOUT
        code, resp = self._http_probe(url, timeout, method="GET")
        if not isinstance(code, int) or code != 200:
            return False, f"HTTP {code if code else resp}"
        if HAS_REQUESTS and resp is not None:
            try:
                chunk = next(resp.iter_content(chunk_size=1024), None)
                if chunk is None:
                    return False, "无数据返回"
            except Exception:
                pass
        return True, "OK"

    def _extract_urls(self, content, max_urls=3):
        urls = re.findall(r'https?://[^\s"\'<>)\]}]+', content)
        seen, uniq = set(), []
        for u in urls:
            u = u.rstrip(",;")
            low = u.lower().split('?')[0]
            if any(low.endswith(ext) for ext in self.STATIC_EXTS):
                continue
            if u in seen:
                continue
            seen.add(u)
            uniq.append(u)
            if len(uniq) >= max_urls:
                break
        return uniq

    def _dynamic_check_file(self, f_path):
        try:
            content = self._read_text(f_path)
            urls = self._extract_urls(content, self.DYNAMIC_MAX_URLS)
            if not urls:
                return True, "无外链, 跳过"
            for u in urls:
                ok, msg = self._check_remote_source(u)
                if not ok:
                    return False, f"{msg} -> {u[:60]}"
            return True, "OK"
        except Exception as e:
            return False, f"动态检测异常: {e}"

    def _dynamic_check_live_file(self, f_path):
        try:
            content = self._read_text(f_path)
            links = self._extract_urls(content, 1)
            if not links:
                return True, "无外链"
            return self._check_live_url(links[0])
        except Exception as e:
            return False, f"异常: {e}"

    # ==========================================================
    # 初始化
    # ==========================================================
    def init(self, extend):
        if self.inited:
            return
        success = False
        try:
            try:
                self.self_path = os.path.abspath(__file__)
            except Exception:
                self.self_path = ""

            self.disabled_set = set(self._load_json_list(self.DISABLED_FILE))
            self.pin_set = set(self._load_json_list(self.PIN_FILE))
            self.ignore_patterns = self._load_ignore_patterns()
            self.check_cache = self._load_check_cache()
            self._last_dirs_sig = self._get_dirs_signature()
            self._log("===== init 开始 =====")
            self._log(f"禁用: {len(self.disabled_set)}  置顶: {len(self.pin_set)}  "
                      f"缓存: {len(self.check_cache)}  ignore: {len(self.ignore_patterns)}  "
                      f"SKIP_JS_CHECK: {self.SKIP_JS_CHECK}  "
                      f"ALWAYS_RETRY_FAILED: {self.ALWAYS_RETRY_FAILED}")

            self._scan_all_dirs(use_cache=True)
            self._cleanup_check_cache()
            self._auto_backup_config()
            self._save_config_json()

            if self.ENABLE_DYNAMIC_CHECK:
                self._start_async_check()

            success = True
            self._log("init 完成")
        except Exception as e:
            self._init_fail_count += 1
            self._log(f"init 异常 (第 {self._init_fail_count} 次): {e}")
        finally:
            if success:
                self.inited = True
                self._init_fail_count = 0
            elif self._init_fail_count >= self.INIT_MAX_RETRY:
                self.inited = True
                self._log(f"init 连续失败 {self._init_fail_count} 次, 放弃重试")

    def _start_async_check(self):
        if self._dynamic_running:
            return
        self._dynamic_running = True
        t = threading.Thread(target=self._async_dynamic_worker, daemon=True)
        t.start()

    def _async_dynamic_worker(self):
        try:
            self._log("后台动态检测开始")
            t0 = time.time()
            with self._lock:
                my_gen = self._scan_gen
            self._dynamic_scan(my_gen)
            with self._lock:
                if my_gen != self._scan_gen:
                    self._log("扫描代已变, 丢弃后台检测结果, 不写缓存")
                    return
            self._save_check_cache()
            self._save_config_json()
            self.last_check_ts = time.time()
            self._log(f"后台动态检测完成, 耗时 {time.time() - t0:.1f}s")
        except Exception as e:
            self._log(f"后台检测异常: {e}")
        finally:
            self._dynamic_running = False

    def _auto_backup_config(self):
        if not os.path.exists(self.SAVE_PATH):
            return
        try:
            with self._file_lock:
                os.makedirs(self.BACKUP_DIR, exist_ok=True)
                ts = time.strftime("%Y%m%d_%H%M%S")
                dst = os.path.join(self.BACKUP_DIR, f"自动加载_{ts}.json")
                shutil.copy2(self.SAVE_PATH, dst)
                files = sorted([os.path.join(self.BACKUP_DIR, f)
                                for f in os.listdir(self.BACKUP_DIR)
                                if f.endswith(".json")])
                for old in files[:-self.MAX_BACKUPS]:
                    try:
                        os.remove(old)
                    except Exception:
                        pass
        except Exception as e:
            self._log(f"自动备份失败: {e}")

    # ==========================================================
    # 扫描
    # ==========================================================
    def _scan_all_dirs(self, use_cache=True):
        with self._lock:
            self._scan_gen += 1
            my_gen = self._scan_gen

        new_type_groups = {t: [] for t in self.TYPE_CLASSES if t != "⚠无效"}
        new_invalid = []
        new_file_index = {}
        new_live = []
        sites = []
        dynamic_pending = []
        key_seen = {}

        for dir_order, scan_dir in enumerate(self.SCAN_DIRS):
            if not os.path.isdir(scan_dir):
                continue
            dir_name = os.path.basename(scan_dir)
            ext_list = self._get_ext_list(dir_name)

            for root, _, files in os.walk(scan_dir):
                for f in sorted(files):
                    f_lower = f.lower()
                    matched_ext = None
                    for ext in ext_list:
                        if f_lower.endswith(ext):
                            matched_ext = ext
                            break
                    if not matched_ext:
                        continue

                    full_path = os.path.join(root, f)
                    if self.self_path and os.path.abspath(full_path) == self.self_path:
                        continue
                    if f in self.disabled_set or full_path in self.disabled_set:
                        continue

                    file_name = f[:-len(matched_ext)]
                    rel_path = os.path.relpath(full_path, scan_dir)
                    folder_part = os.path.dirname(rel_path)

                    if self._is_ignored(f, rel_path):
                        continue

                    type_tag, tvbox_type = self._detect_type_tag(dir_name, matched_ext)
                    if self._is_excluded(f, type_tag):
                        continue

                    if type_tag == "LIVE":
                        group = self._guess_live_group(file_name)
                        new_live.append({
                            "name": file_name, "type": 0,
                            "url": f"./{dir_name}/{rel_path}",
                            "full_path": full_path, "rel_path": rel_path,
                            "group": group
                        })
                        continue

                    ok, msg = self._check_site_code(full_path, type_tag)
                    if not ok:
                        new_invalid.append({
                            "file": full_path, "tag": type_tag,
                            "reason": msg
                        })
                        continue

                    fkey = self._file_key(full_path)
                    cached_ok = False
                    if use_cache and fkey:
                        cres = self._get_cache_entry(fkey)
                        if cres and cres.get("ok", True):
                            cached_ok = True

                    base_key = file_name
                    if folder_part:
                        base_key = f"{folder_part.replace('/', '_')}_{file_name}"
                    if base_key in key_seen:
                        key_seen[base_key] += 1
                        base_key = f"{base_key}_{key_seen[base_key]}"
                    else:
                        key_seen[base_key] = 0

                    is_pinned = file_name in self.pin_set
                    cat_rank = self._get_category_rank(file_name)
                    sort_key = (
                        0 if is_pinned else 1,
                        cat_rank,
                        dir_order,
                        self.TYPE_ORDER.get(type_tag, 9),
                        folder_part or "",
                        file_name
                    )
                    tag = f"{type_tag}|{full_path}"
                    tid = base64.b64encode(tag.encode()).decode()

                    item = {
                        "type_id": tid, "type_name": file_name,
                        "type_tag": type_tag, "tvbox_type": tvbox_type,
                        "scan_dir": scan_dir, "full_path": full_path,
                        "sk": sort_key, "pinned": is_pinned,
                        "unique_key": base_key,
                        "cat_rank": cat_rank
                    }

                    if cached_ok:
                        sites.append(item)
                    elif self.SKIP_JS_CHECK and type_tag in ("JS", "CAT"):
                        sites.append(item)
                    elif self.ENABLE_DYNAMIC_CHECK and \
                            type_tag in ("JS", "CAT", "XBPQ"):
                        dynamic_pending.append(item)
                    else:
                        sites.append(item)

        with self._lock:
            if my_gen != self._scan_gen:
                self._log(f"扫描代变更({my_gen}→{self._scan_gen}), 丢弃本次扫描结果")
                return

        self._apply_scan_result(sites, dynamic_pending, new_type_groups,
                                new_invalid, new_file_index, new_live)

    def _apply_scan_result(self, sites, dynamic_pending, new_type_groups,
                            new_invalid, new_file_index, new_live):
        for item in sites + dynamic_pending:
            tid = item["type_id"]
            new_file_index[tid] = {
                "path": item["full_path"], "scan_dir": item["scan_dir"],
                "type_tag": item["type_tag"], "tvbox_type": item["tvbox_type"],
                "file_name": item["type_name"], "ext": "",
                "unique_key": item.get("unique_key", item["type_name"])
            }
            new_type_groups[item["type_tag"]].append(item)

        all_sites = sites + dynamic_pending
        for t in ["PY", "JS", "XBPQ", "CAT"]:
            new_type_groups[t] = sorted(new_type_groups[t], key=lambda x: x["sk"])
        new_type_groups["全部"] = sorted(all_sites, key=lambda x: x["sk"])

        with self._lock:
            self.cache["type_groups"] = new_type_groups
            self.cache["file_index"] = new_file_index
            self.cache["invalid_files"] = new_invalid
            self.cache["live_files"] = new_live
            self.cache["categories"] = new_type_groups["全部"]

    # ==========================================================
    # 后台动态扫描
    # ==========================================================
    def _dynamic_scan(self, my_gen):
        with self._lock:
            if my_gen != self._scan_gen:
                self._log(f"_dynamic_scan 启动时代已过期({my_gen}→{self._scan_gen})")
                return
            all_sites = self.cache["categories"][:]
            invalid_files = self.cache["invalid_files"][:]

        pending = [s for s in all_sites if s["type_tag"] in ("JS", "CAT", "XBPQ")]
        if self.SKIP_JS_CHECK:
            pending = [s for s in pending if s["type_tag"] == "XBPQ"]

        pending_live = self.cache["live_files"][:] if self.CHECK_LIVE else []

        to_check, to_check_live = [], []
        for item in pending:
            fkey = self._file_key(item["full_path"])
            if fkey:
                cres = self._get_cache_entry(fkey)
                if cres and not cres.get("ok", True):
                    invalid_files.append({
                        "file": item["full_path"], "tag": item["type_tag"],
                        "reason": f"动态检测: {cres.get('msg', '')}"
                    })
                    self._remove_site(item["type_id"], my_gen)
                    continue
            to_check.append(item)

        for item in pending_live:
            fkey = self._file_key(item["full_path"])
            if fkey and self._get_cache_entry(fkey):
                continue
            to_check_live.append(item)

        with self._lock:
            if my_gen != self._scan_gen:
                self._log(f"动态检测准备阶段代已过期({my_gen}→{self._scan_gen})")
                return

        results = {}
        if to_check or to_check_live:
            with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as ex:
                fmap = {}
                for idx, item in enumerate(to_check):
                    fut = ex.submit(self._dynamic_check_file, item["full_path"])
                    fmap[fut] = ("site", idx)
                for idx, item in enumerate(to_check_live):
                    fut = ex.submit(self._dynamic_check_live_file, item["full_path"])
                    fmap[fut] = ("live", idx)
                for fut in as_completed(fmap):
                    kind, idx = fmap[fut]
                    try:
                        results[(kind, idx)] = fut.result()
                    except Exception as e:
                        results[(kind, idx)] = (False, f"线程异常: {e}")

        with self._lock:
            if my_gen != self._scan_gen:
                self._log(f"动态检测完成时代已过期({my_gen}→{self._scan_gen}), 丢弃结果")
                return

        for idx, item in enumerate(to_check):
            ok, msg = results.get(("site", idx), (True, "未检测"))
            self._update_check_cache(item["full_path"], ok, msg)
            if not ok:
                invalid_files.append({
                    "file": item["full_path"], "tag": item["type_tag"],
                    "reason": f"动态检测: {msg}"
                })
                self._remove_site(item["type_id"], my_gen)
                self._maybe_auto_disable(item["full_path"])

        for idx, item in enumerate(to_check_live):
            ok, msg = results.get(("live", idx), (True, "未检测"))
            self._update_check_cache(item["full_path"], ok, msg)
            if not ok:
                invalid_files.append({
                    "file": item["full_path"], "tag": "LIVE",
                    "reason": f"直播检测: {msg}"
                })
                self._remove_live(item["full_path"], my_gen)
                self._maybe_auto_disable(item["full_path"])

        with self._lock:
            if my_gen != self._scan_gen:
                return
            self.cache["invalid_files"] = invalid_files

    def _maybe_auto_disable(self, f_path):
        fkey = self._file_key(f_path)
        if not fkey:
            return
        with self._cache_lock:
            c = self.check_cache.get(fkey)
        if not c:
            return
        if c.get("fail_count", 0) >= self.AUTO_DISABLE_THRESHOLD:
            name = os.path.basename(f_path)
            if name not in self.disabled_set:
                self.disabled_set.add(name)
                self._save_json_list(self.DISABLED_FILE,
                                      list(self.disabled_set))
                self._log(f"⚠️ 自动禁用: {name} (连续失败 "
                          f"{c.get('fail_count')} 次)")

    def _remove_site(self, type_id, my_gen=None):
        with self._lock:
            if my_gen is not None and my_gen != self._scan_gen:
                return
            for t in self.TYPE_CLASSES:
                lst = self.cache["type_groups"].get(t, [])
                self.cache["type_groups"][t] = [x for x in lst
                                                 if x["type_id"] != type_id]
            self.cache["categories"] = self.cache["type_groups"].get("全部", [])
            self.cache["file_index"].pop(type_id, None)

    def _remove_live(self, full_path, my_gen=None):
        with self._lock:
            if my_gen is not None and my_gen != self._scan_gen:
                return
            self.cache["live_files"] = [x for x in self.cache["live_files"]
                                         if x["full_path"] != full_path]

    # ==========================================================
    # 生成配置 (整个写文件过程加锁)
    # ==========================================================
    def _build_api(self, f_path, scan_dir):
        dir_name = os.path.basename(scan_dir)
        rel = os.path.relpath(f_path, scan_dir)
        return f"./{dir_name}/{rel}"

    def _save_config_json(self):
        with self._lock:
            categories = self.cache["categories"][:]
            file_index = dict(self.cache["file_index"])
            live_files = self.cache["live_files"][:]
            invalid_files = self.cache["invalid_files"][:]

        config = {
            "spider": "./jar/xyqxbpq.jar",
            "logo": "./gif/logo.gif",
            "sites": [], "lives": [],
            "parses": [{"name": "虾米", "type": 0,
                        "url": "https://jx.xmflv.com/?url="}]
        }

        for cat in categories:
            info = file_index.get(cat["type_id"])
            if not info:
                continue
            f_path = info["path"]; scan_dir = info["scan_dir"]
            type_tag = info["type_tag"]; tvbox_type = info["tvbox_type"]
            file_name = info["file_name"]; prefix = self._get_tag_prefix(type_tag)
            unique_key = info.get("unique_key", file_name)
            api_path = self._build_api(f_path, scan_dir)

            if type_tag == "JS":
                if self.JS_LOAD_MODE == "drpy":
                    site = {
                        "key": unique_key, "name": f"{file_name}┃{prefix}",
                        "type": tvbox_type, "api": self.JS_DRPY_API,
                        "searchable": 1, "quickSearch": 1, "filterable": 1,
                        "ext": api_path
                    }
                else:
                    site = {
                        "key": unique_key, "name": f"{file_name}┃{prefix}",
                        "type": tvbox_type, "api": api_path,
                        "searchable": 1, "quickSearch": 1, "filterable": 1
                    }
                config["sites"].append(site)

            elif type_tag == "CAT":
                config["sites"].append({
                    "key": unique_key, "name": f"{file_name}┃{prefix}",
                    "type": tvbox_type, "api": api_path,
                    "searchable": 1, "quickSearch": 1, "filterable": 1
                })

            elif type_tag == "XBPQ":
                config["sites"].append({
                    "key": unique_key, "name": f"{file_name}┃{prefix}",
                    "type": tvbox_type, "api": self.XBPQ_API,
                    "searchable": 1, "quickSearch": 1, "filterable": 1,
                    "ext": api_path
                })

            else:
                config["sites"].append({
                    "key": unique_key, "name": f"{file_name}┃{prefix}",
                    "type": tvbox_type, "api": api_path,
                    "searchable": 1, "quickSearch": 1, "filterable": 1
                })

        for live_info in live_files:
            config["lives"].append({
                "name": live_info["name"], "type": live_info["type"],
                "url": live_info["url"],
                "group": live_info.get("group", "其他")
            })

        # ---- 加锁 + 原子写 ----
        try:
            with self._file_lock:
                os.makedirs(self.BASE_DIR, exist_ok=True)
                tmp = self.SAVE_PATH + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fp:
                    json.dump(config, fp, ensure_ascii=False, indent=2)
                os.replace(tmp, self.SAVE_PATH)
        except Exception as e:
            self._log(f"写配置失败: {e}")

        try:
            grouped = {}
            for item in invalid_files:
                grouped.setdefault(item["tag"], []).append(item)
            report = {
                "total_invalid": len(invalid_files),
                "by_type": {k: len(v) for k, v in grouped.items()},
                "invalid_files": invalid_files,
                "grouped": grouped
            }
            with self._file_lock:
                tmp = self.REPORT_PATH + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fp:
                    json.dump(report, fp, ensure_ascii=False, indent=2)
                os.replace(tmp, self.REPORT_PATH)
        except Exception:
            pass

    # ==========================================================
    # 面板动作
    # ==========================================================
    def _run_panel_action(self, tid):
        now = time.time()
        last = self._panel_last_exec.get(tid, 0)
        if now - last < self.PANEL_THROTTLE:
            remain = int(self.PANEL_THROTTLE - (now - last)) + 1
            v_id = base64.b64encode(b"NOOP").decode()
            return {"list": [{"vod_id": v_id, "vod_name": "⏱️ 冷却中",
                              "vod_remarks": f"{remain} 秒后可再次执行"}],
                    "page": 1, "pagecount": 1, "limit": 1, "total": 1}

        self._panel_last_exec[tid] = now
        action = self.PANEL_ACTIONS[tid]

        try:
            if action == "rescan":
                self.disabled_set = set(self._load_json_list(self.DISABLED_FILE))
                self.pin_set = set(self._load_json_list(self.PIN_FILE))
                self.ignore_patterns = self._load_ignore_patterns()
                self._scan_all_dirs(use_cache=True)
                self._cleanup_check_cache()
                self._save_config_json()
                if self.ENABLE_DYNAMIC_CHECK and not self._dynamic_running:
                    self._start_async_check()
                with self._lock:
                    cnt = len(self.cache["categories"])
                    live_cnt = len(self.cache["live_files"])
                title = "✅ 重扫完成"
                remark = f"站点 {cnt} / 直播 {live_cnt}"

            elif action == "status":
                with self._lock:
                    s = {
                        "站点数": len(self.cache["categories"]),
                        "无效数": len(self.cache["invalid_files"]),
                        "直播数": len(self.cache["live_files"]),
                        "缓存数": len(self.check_cache),
                        "禁用数": len(self.disabled_set),
                        "置顶数": len(self.pin_set),
                    }
                title = "📊 状态总览"
                remark = f"站点 {s['站点数']} / 无效 {s['无效数']}"

            elif action == "backup":
                if not os.path.exists(self.SAVE_PATH):
                    title, remark = "❌ 备份失败", "配置文件不存在"
                else:
                    with self._file_lock:
                        os.makedirs(self.BACKUP_DIR, exist_ok=True)
                        ts = time.strftime("%Y%m%d_%H%M%S")
                        dst = os.path.join(self.BACKUP_DIR,
                                           f"自动加载_{ts}.json")
                        shutil.copy2(self.SAVE_PATH, dst)
                        cnt = len([f for f in os.listdir(self.BACKUP_DIR)
                                   if f.endswith(".json")])
                    title = "✅ 已备份"
                    remark = f"共 {cnt} 份"

            elif action == "clear_cache":
                old = self._clear_cache_file()
                title = "✅ 缓存已清除"
                remark = f"删除 {old} 条"

            elif action == "clear_disabled":
                old = len(self.disabled_set)
                self.disabled_set = set()
                try:
                    with self._file_lock:
                        if os.path.exists(self.DISABLED_FILE):
                            os.remove(self.DISABLED_FILE)
                except Exception:
                    pass
                title = "✅ 禁用已清空"
                remark = f"解除 {old} 个"

            elif action == "clear_pin":
                old = len(self.pin_set)
                self.pin_set = set()
                try:
                    with self._file_lock:
                        if os.path.exists(self.PIN_FILE):
                            os.remove(self.PIN_FILE)
                except Exception:
                    pass
                title = "✅ 置顶已清空"
                remark = f"移除 {old} 个"

            elif action == "cleanup":
                cache_removed = self._cleanup_check_cache()
                log_size = 0
                if os.path.exists(self.LOG_FILE):
                    log_size = os.path.getsize(self.LOG_FILE)
                try:
                    with self._file_lock:
                        with open(self.LOG_FILE, "w",
                                  encoding="utf-8") as f:
                            f.write("")
                except Exception:
                    pass
                title = "🧹 清理完成"
                remark = f"缓存-{cache_removed} 日志{self._human_size(log_size)}"

            else:
                title, remark = "未知动作", action

        except Exception as e:
            title, remark = "❌ 执行失败", str(e)[:40]

        v_id = base64.b64encode(
            f"PANEL_DETAIL|{action}".encode()).decode()
        return {"list": [{"vod_id": v_id, "vod_name": title,
                          "vod_remarks": remark}],
                "page": 1, "pagecount": 1, "limit": 1, "total": 1}

    # ==========================================================
    # TVBox 接口
    # ==========================================================
    def homeContent(self, filter):
        if self.inited and self._check_dirs_changed():
            self._log("检测到目录变化, 触发重扫")
            try:
                self.disabled_set = set(self._load_json_list(self.DISABLED_FILE))
                self.pin_set = set(self._load_json_list(self.PIN_FILE))
                self.ignore_patterns = self._load_ignore_patterns()
                self._scan_all_dirs(use_cache=True)
                self._cleanup_check_cache()
                self._save_config_json()
                if self.ENABLE_DYNAMIC_CHECK and not self._dynamic_running:
                    self._start_async_check()
            except Exception as e:
                self._log(f"自动重扫失败: {e}")

        result = []
        with self._lock:
            type_groups = dict(self.cache["type_groups"])
            invalid_cnt = len(self.cache["invalid_files"])

        if self.last_check_ts:
            result.append({
                "type_id": "__time__",
                "type_name": f"🕐检测 {self._human_time(self.last_check_ts)}"
            })

        for t in self.TYPE_CLASSES:
            if t == "⚠无效":
                if invalid_cnt == 0:
                    continue
                result.append({"type_id": "⚠无效",
                               "type_name": f"⚠无效 {invalid_cnt}"})
                continue
            count = len(type_groups.get(t, []))
            if count == 0:
                continue
            display_name = f"全部 {count}" if t == "全部" else f"{t} {count}"
            item = {"type_id": t, "type_name": display_name}
            cover = self.CLASS_COVER.get(t, "")
            if cover:
                item["vod_pic"] = cover
            result.append(item)

        for name in self.PANEL_ACTIONS:
            result.append({"type_id": name, "type_name": name})

        return {"class": result}

    def categoryContent(self, tid, pg, filter, ext):
        try:
            pg = int(pg) if str(pg).isdigit() else 1
        except Exception:
            pg = 1

        if tid in self.PANEL_ACTIONS:
            return self._run_panel_action(tid)

        if tid == "__time__":
            info = f"上次动态检测: {self._human_time(self.last_check_ts)}"
            v_id = base64.b64encode(b"TIME_INFO").decode()
            return {"list": [{"vod_id": v_id, "vod_name": "🕐 检测时间",
                              "vod_remarks": info}],
                    "page": 1, "pagecount": 1, "limit": 1, "total": 1}

        if tid == "⚠无效":
            with self._lock:
                invalid = self.cache["invalid_files"][:]
            total = len(invalid)
            start = (pg - 1) * self.PAGE_SIZE
            page_items = invalid[start:start + self.PAGE_SIZE]
            result = []
            for item in page_items:
                fpath = item["file"]
                v_id = base64.b64encode(f"INVALID|{fpath}".encode()).decode()
                result.append({
                    "vod_id": v_id,
                    "vod_name": os.path.basename(fpath),
                    "vod_remarks": item["reason"]
                })
            return {"list": result, "page": pg,
                    "pagecount": (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE,
                    "limit": self.PAGE_SIZE, "total": total}

        with self._lock:
            if tid == "全部":
                files = self.cache["categories"][:]
            elif tid in self.TYPE_CLASSES:
                files = self.cache["type_groups"].get(tid, [])[:]
            else:
                files = []
            file_index = dict(self.cache["file_index"])

        if not files and tid in file_index:
            info = file_index.get(tid)
            if info:
                files = [{"type_id": tid, "type_name": info["file_name"],
                          "type_tag": info["type_tag"], "full_path": info["path"]}]

        total = len(files)
        start = (pg - 1) * self.PAGE_SIZE
        page_items = files[start:start + self.PAGE_SIZE]
        result = []
        for cat in page_items:
            info = file_index.get(cat["type_id"])
            if not info:
                continue
            v_id = base64.b64encode(
                f"{info['type_tag']}|{info['path']}".encode()).decode()
            fkey = self._file_key(info["path"])
            score = self._get_score(fkey) if fkey else None
            remark = info["type_tag"]
            if score is not None:
                remark = f"{remark} {score}分"
            vod_item = {"vod_id": v_id, "vod_name": info["file_name"],
                        "vod_remarks": remark}
            cover = self.CLASS_COVER.get(info["type_tag"], "")
            if cover:
                vod_item["vod_pic"] = cover
            result.append(vod_item)

        return {"list": result, "page": pg,
                "pagecount": max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE),
                "limit": self.PAGE_SIZE, "total": total}

    def detailContent(self, array):
        try:
            v_id_raw = str(array[0])
            v_id_raw += "=" * ((4 - len(v_id_raw) % 4) % 4)
            raw = base64.b64decode(v_id_raw).decode('utf-8', errors='ignore')

            if raw.startswith("PANEL_DETAIL|"):
                return self._panel_detail(raw.split("|", 1)[1])

            if raw == "NOOP":
                return {"list": [{"vod_name": "⏱️ 冷却中",
                                  "vod_content": "请稍后再试"}]}

            if raw == "TIME_INFO":
                with self._lock:
                    s = {
                        "站点数": len(self.cache["categories"]),
                        "无效数": len(self.cache["invalid_files"]),
                    }
                content = f"上次检测: {self._human_time(self.last_check_ts)}\n"
                content += "\n".join([f"{k}: {v}" for k, v in s.items()])
                return {"list": [{"vod_name": "🕐 检测状态",
                                  "vod_content": content}]}

            if raw.startswith("INVALID|"):
                fpath = raw.split("|", 1)[1]
                reason = ""
                with self._lock:
                    for it in self.cache["invalid_files"]:
                        if it["file"] == fpath:
                            reason = it["reason"]
                            break
                return {"list": [{
                    "vod_name": os.path.basename(fpath),
                    "vod_content": f"状态: ❌ 无效\n原因: {reason}\n路径: {fpath}"
                }]}

            if "|" in raw:
                type_tag, f_path = raw.split('|', 1)
            else:
                type_tag, f_path = "PY", raw

            if not os.path.exists(f_path):
                return {"list": [{"vod_name": "文件不存在",
                                  "vod_content": f"路径不存在: {f_path}"}]}

            file_name = os.path.basename(f_path).rsplit('.', 1)[0]
            ok, msg = self._check_site_code(f_path, type_tag)
            static_status = "✅ 正常" if ok else f"❌ {msg}"

            fkey = self._file_key(f_path)
            dyn_status = "未检测"
            last_check = "-"
            score = None
            fail_count = 0
            ok_count = 0
            if fkey:
                with self._cache_lock:
                    cres = self.check_cache.get(fkey)
                if cres:
                    dyn_status = "✅ 正常" if cres.get("ok") else \
                        f"❌ {cres.get('msg', '')}"
                    last_check = self._human_time(cres.get("ts", 0))
                    score = self._get_score(fkey)
                    fail_count = cres.get("fail_count", 0)
                    ok_count = cres.get("ok_count", 0)

            try:
                st = os.stat(f_path)
                fsize = self._human_size(st.st_size)
                fmtime = time.strftime("%Y-%m-%d %H:%M",
                                        time.localtime(st.st_mtime))
            except Exception:
                fsize, fmtime = "?", "?"

            pinned = "📌 是" if file_name in self.pin_set else "否"
            disabled = "🚫 是" if os.path.basename(f_path) in self.disabled_set else "否"

            preview = ""
            try:
                if type_tag in ("JS", "CAT", "XBPQ", "PY"):
                    with open(f_path, "r", encoding="utf-8-sig",
                              errors="ignore") as fp:
                        head = fp.read(200)
                    preview = head.replace("\n", " ⏎ ").replace("\r", "")
                    if len(preview) > 150:
                        preview = preview[:150] + "..."
            except Exception as e:
                preview = f"(读取失败: {e})"

            content = (f"类型: {type_tag}\n"
                       f"静态: {static_status}\n"
                       f"动态: {dyn_status}\n"
                       f"评分: {score if score is not None else '-'}\n"
                       f"成功/失败: {ok_count}/{fail_count}\n"
                       f"检测: {last_check}\n"
                       f"大小: {fsize}\n"
                       f"修改: {fmtime}\n"
                       f"置顶: {pinned}\n"
                       f"禁用: {disabled}\n"
                       f"路径: {f_path}\n\n"
                       f"【文件开头】\n{preview}")

            vod_item = {"vod_name": file_name, "vod_content": content}
            cover = self.CLASS_COVER.get(type_tag, "")
            if cover:
                vod_item["vod_pic"] = cover
            return {"list": [vod_item]}
        except Exception as e:
            return {"list": [{"vod_name": "解析错误",
                              "vod_content": f"错误详情: {str(e)}"}]}

    def _panel_detail(self, action):
        names = {"rescan": "🔄 重扫", "status": "📊 状态",
                 "backup": "💾 备份",
                 "clear_cache": "🗑️ 清缓存",
                 "clear_disabled": "🔓 清禁用",
                 "clear_pin": "📍 清置顶",
                 "cleanup": "🧹 清理"}
        name = names.get(action, action)

        with self._lock:
            s = {
                "站点数": len(self.cache["categories"]),
                "无效数": len(self.cache["invalid_files"]),
                "直播数": len(self.cache["live_files"]),
                "缓存数": len(self.check_cache),
                "禁用数": len(self.disabled_set),
                "置顶数": len(self.pin_set),
                "忽略规则": len(self.ignore_patterns),
                "扫描代": self._scan_gen,
                "init失败次数": self._init_fail_count,
            }
        content = f"动作: {name}\n\n" + "\n".join(
            [f"{k}: {v}" for k, v in s.items()])
        content += f"\n\n上次检测: {self._human_time(self.last_check_ts)}"
        content += f"\n\n日志: {self.LOG_FILE}"
        return {"list": [{"vod_name": name, "vod_content": content}]}

    def searchContent(self, key, quick):
        res = []
        kl = key.lower()
        with self._lock:
            file_index = dict(self.cache["file_index"])
        for tid, info in file_index.items():
            if not isinstance(info, dict):
                continue
            if kl in info["file_name"].lower():
                v_id = base64.b64encode(
                    f"{info['type_tag']}|{info['path']}".encode()).decode()
                item = {"vod_id": v_id, "vod_name": info["file_name"],
                        "vod_remarks": info["type_tag"]}
                cover = self.CLASS_COVER.get(info["type_tag"], "")
                if cover:
                    item["vod_pic"] = cover
                res.append(item)
        return {"list": res}

    def playerContent(self, flag, id, vipFlags):
        return {"url": id, "header": {}, "parse": 0}

    def destroy(self):
        self._log("===== destroy =====")
        return "destroy"