# -*- coding: utf-8 -*-
"""
TVBox / CatVod Python 源 - 樱花视频 (yinghua)

逆向要点:
  - AES-CBC(Pkcs7) 加密请求 body 和响应 body
  - KEY = "NHboMHZerxFQ401E" (固定 16 字节)
  - IV  = "i7JeCEIMVrj2W9xN" (固定 16 字节)
  - 请求体: AES 加密 JSON -> base64 -> 再用 JSON.stringify() 包裹引号
  - 响应体: 同样是 AES 加密 -> base64 -> JSON 字符串包裹
  - 播放: playDomain + playUrl -> m3u8 直链，需要移动端 UA
"""

import json
import time
import base64
import uuid as _uuid
import re
import os
import sys
from urllib.parse import quote, unquote

# ================================================================================
# 可选依赖探测
# ================================================================================
try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

# ================================================================================
# 基类导入兼容
# ================================================================================
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(_THIS_DIR)
sys.path.append(os.path.join(_THIS_DIR, '..'))

try:
    from base.spider import Spider
    _BASE_INFO = 'base.spider.Spider'
except ImportError:
    try:
        from base.spider import BaseSpider as Spider
        _BASE_INFO = 'base.spider.BaseSpider'
    except ImportError:
        try:
            from spider import Spider
            _BASE_INFO = 'spider.Spider'
        except ImportError:
            class _LocalStubSpider(object):
                def fetch(self, url, headers={}, cookies=""):
                    return requests.get(url, headers=headers, timeout=15, verify=False)
                def post(self, url, data, headers={}, cookies={}):
                    return requests.post(url, data=data, headers=headers, timeout=15, verify=False)
                def postJson(self, url, json, headers={}, cookies={}):
                    return requests.post(url, json=json, headers=headers, timeout=15, verify=False)
                def html(self, content):
                    return content
                def cleanText(self, src):
                    return src
                def loadModule(self, name, fileName):
                    return None
                def getDependence(self):
                    return []
            Spider = _LocalStubSpider
            _BASE_INFO = 'LocalStub'

class Spider(Spider):
    NAME = '樱花视频'
    HOST = 'https://yinghua-t1474.cc'
    PLATFORM = '4'
    PAGE_SIZE = 24
    TIMEOUT = 15
    RETRY = 2
    SLEEP_BASE = 1.5

    AES_KEY = b'NHboMHZerxFQ401E'
    AES_IV  = b'i7JeCEIMVrj2W9xN'

    API_LOGIN  = '/app/users/loginByDevice'
    API_LIST   = '/app/movie/getListV2'
    API_DETAIL = '/app/movie/getDetail'

    CATES = [
        ('国产-乱伦','76_乱伦'),('国产-偷情','76_偷情'),('国产-剧情','76_剧情'),
        ('国产-偷拍','76_偷拍'),('国产-自拍','76_自拍'),('国产-直播','76_直播'),
        ('国产-探花','76_探花'),('日韩-中字','76_中字'),('日韩-无码','76_无码'),
        ('日韩-乱伦','76_乱伦'),('日韩-人妻','76_人妻'),('日韩-群交','76_群交'),
        ('日韩-OL','76_OL'),('欧美-黑白配','76_黑白配'),('欧美-剧情','76_剧情'),
        ('欧美-中字','76_中字'),('欧美-SM','76_SM'),('欧美-自拍','76_自拍'),
        ('欧美-女同','76_女同'),('吃瓜','93'),('传媒','60'),('AI视频','137'),
        ('动漫','83'),('综艺','71'),('短视频','125'),
    ]

    # 播放器请求头
    PLAY_UA = 'Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'

    # 备用 UA 列表(按顺序尝试,解决某些 CDN 对特定 UA 限速/拦截)
    PLAY_UA_LIST = [
        'Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ]

    # 视频 CDN(2026-09 实测):详情接口 imgDomain=goeusig.kwvqaj.cn 上 m3u8/key/ts 全部可达;
    # 旧域 vdo-yinghua.ozuesa.cn 已 403 失效,vdo./vdoy.yinghua-t1474.cc 只回 SPA 壳(假 200)。
    # 播放 URL 一律做"内容级"探测(#EXTM3U 开头才算真 m3u8),失败按 PLAY_CDN_BACKUP 顺序换域。
    PLAY_CDN = 'https://goeusig.kwvqaj.cn'
    # 备用 CDN 列表(按优先级尝试)
    PLAY_CDN_BACKUP = [
        'https://goeusig.kwvqaj.cn',
        'https://vdo.yinghua-t1474.cc',
        'https://vdoy.yinghua-t1474.cc',
        'https://vdo-yinghua.ozuesa.cn',
    ]

    # Referer 候选(部分 CDN 强制校验)
    PLAY_REFERER_LIST = [
        '',  # 不带 Referer
        'https://yinghua-t1474.cc/',
        'https://www.yinghua-t1474.cc/',
    ]

    # 备用 host 候选(主站挂了就换)
    PLAY_HOST_BACKUP = [
        'https://yinghua-t1474.cc',
        'https://www.yinghua-t1474.cc',
        'https://m.yinghua-t1474.cc',
        'https://yinghua-t1474.com',
    ]

    # H5 播放页路径候选(嗅探用)
    PLAY_PAGE_PATHS = [
        '/movie?viewKey={vk}',     # 主
        '/play?viewKey={vk}',      # 备用 1
        '/h5/play?viewKey={vk}',   # 备用 2
        '/detail/play?vk={vk}',    # 备用 3
        '/?viewKey={vk}&play=1',   # 备用 4
    ]

    # 图片代理类型(给 TVBox 用的,挂载到 localProxy)
    PROXY_TYPE = 'yinghua_img'
    # 播放代理类型(m3u8 / ts 切片反代,所有 CDN 校验都从我这里过)
    PROXY_TYPE_PLAY = 'yinghua_play'

    # 是否启用图片代理(默认开,解决部分 CDN 防盗链)
    USE_IMAGE_PROXY = True
    # 是否启用播放反代(auto 模式默认开,等于在 TVBox 内置 CDN 中转,最稳)
    USE_PLAY_PROXY = True

    def __init__(self):
        self.host = self.HOST
        self._token = ''
        self._token_time = 0
        # 已实测可用的视频 CDN 域名(不带协议),首次探测命中后缓存,后续直接用
        self._verified_cdn = ''
        self.headers = {
            'User-Agent': self.PLAY_UA,
            'Accept': 'application/json, text/plain, */*',
        }
        if _HAS_REQUESTS:
            self.session = requests.Session()
            self.session.verify = False
            self.session.headers.update(self.headers)
            self.session.headers['platform'] = self.PLATFORM
        else:
            self.session = None

    def init(self, extend=''):
        if extend and extend.startswith('http'):
            self.host = extend.rstrip('/')

    def getName(self):
        return self.NAME

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def getDependence(self):
        return []

    def destroy(self):
        pass

    # ===================== Crypto =====================
    def _aes_encrypt(self, text):
        if not _HAS_CRYPTO:
            return ''
        cipher = AES.new(self.AES_KEY, AES.MODE_CBC, self.AES_IV)
        padded = pad(text.encode('utf-8'), AES.block_size, style='pkcs7')
        return base64.b64encode(cipher.encrypt(padded)).decode('utf-8')

    def _aes_decrypt(self, b64_text):
        if not _HAS_CRYPTO:
            return ''
        cipher = AES.new(self.AES_KEY, AES.MODE_CBC, self.AES_IV)
        raw = base64.b64decode(b64_text)
        return unpad(cipher.decrypt(raw), AES.block_size, style='pkcs7').decode('utf-8')

    def _decrypt_response(self, text):
        if not text:
            return {}
        text = text.strip()
        try:
            j = json.loads(text)
            if isinstance(j, dict):
                return j
            if isinstance(j, str):
                dec = self._aes_decrypt(j)
                if dec:
                    try:
                        return json.loads(dec)
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            dec = self._aes_decrypt(text)
            if dec:
                try:
                    return json.loads(dec)
                except Exception:
                    pass
        except Exception:
            pass
        return {}

    # ===================== API =====================
    def _login(self):
        if self._token and (time.time() - self._token_time < 3600):
            return self._token

        client_id = _uuid.uuid4().hex
        body = json.dumps({
            'clientId': client_id,
            'browser': 'Chrome 120.0.0.0',
            'deviceInfo': 'Windows 10',
            'network': '4g/10/100',
        }, ensure_ascii=False, separators=(',', ':'))
        enc_body = self._aes_encrypt(body)
        if not enc_body:
            return ''

        payload = enc_body  # 裸 base64,不 json.dumps 套引号

        try:
            url = self.host + self.API_LOGIN
            for i in range(self.RETRY + 1):
                if _HAS_REQUESTS and self.session is not None:
                    r = self.session.post(
                        url,
                        data=payload,
                        headers={
                            'Content-Type': 'application/json',
                            'platform': self.PLATFORM,
                            'token': '',
                        },
                        timeout=self.TIMEOUT)
                    if r.status_code == 200:
                        resp = self._decrypt_response(r.text)
                        if resp:
                            token = ''
                            if resp.get('errCode', -1) == 0:
                                data = resp.get('data', {})
                                if isinstance(data, dict):
                                    token = data.get('token', '')
                            if not token and 'data' in resp:
                                data = resp.get('data', {})
                                if isinstance(data, dict):
                                    token = data.get('token', '')
                            if not token:
                                token = resp.get('token', '')
                            if not token:
                                for k, v in resp.items():
                                    if 'token' in k.lower() and isinstance(v, str) and len(v) > 20:
                                        token = v
                                        break
                            if token:
                                self._token = token
                                self._token_time = time.time()
                                self.session.headers['token'] = self._token
                                return self._token
                    time.sleep(self.SLEEP_BASE * (i + 1))
        except Exception:
            pass

        return ''

    def _post_api(self, path, data):
        token = self._login()
        if not token:
            return {}
        enc_body = self._aes_encrypt(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
        if not enc_body:
            return {}
        payload = enc_body  # 裸 base64
        try:
            if _HAS_REQUESTS and self.session is not None:
                r = self.session.post(
                    self.host + path,
                    data=payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=self.TIMEOUT)
                if r.status_code == 200:
                    return self._decrypt_response(r.text)
        except Exception:
            pass
        return {}

    def _get_api(self, path, params=None):
        token = self._login()
        if not token:
            return {}
        try:
            url = self.host + path
            if params:
                url += '?' + '&'.join(['%s=%s' % (k, v) for k, v in params.items()])
            if _HAS_REQUESTS and self.session is not None:
                r = self.session.get(url, timeout=self.TIMEOUT)
                if r.status_code == 200:
                    return self._decrypt_response(r.text)
        except Exception:
            pass
        return {}

    # ===================== Helpers =====================
    def fixUrl(self, url):
        if not url:
            return ''
        url = url.strip()
        if url.startswith('http://') or url.startswith('https://'):
            return url
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return self.host + url
        from urllib.parse import urljoin
        return urljoin(self.host + '/', url)

    def cleanText(self, src):
        if not src:
            return ''
        src = re.sub(r'<[^>]+>', '', str(src))
        return re.sub(r'\s+', ' ', src).strip()

    # ===================== TVBox Interfaces =====================
    def homeContent(self, filter):
        classes = [{'type_id': tid, 'type_name': name} for name, tid in self.CATES]
        result = {'class': classes, 'list': []}
        try:
            first_tid = self.CATES[0][1]
            cat = self.categoryContent(first_tid, '1', 0, {})
            result['list'] = cat.get('list', [])[:12]
        except Exception:
            pass
        return result

    def homeVideoContent(self):
        return self.categoryContent(self.CATES[0][1], '1', 0, {})

    def categoryContent(self, tid, pg, filter, ext):
        page = int(pg) if pg else 1
        result = {'list': [], 'page': page, 'pagecount': 1, 'limit': 20, 'total': 0}

        tid_str = str(tid)
        if '_' in tid_str:
            parts = tid_str.split('_', 1)
            cid = parts[0]
            tag = parts[1]
        else:
            cid = tid_str
            tag = ''

        req_data = {'page': page, 'pageSize': self.PAGE_SIZE, 'sort': 1, 'cid': cid}
        if tag:
            req_data['tag'] = tag

        resp = self._post_api(self.API_LIST, req_data)
        if not resp:
            return result

        if 'records' in resp:
            movie_list = resp.get('records', [])
            result['pagecount'] = resp.get('pageCount', 1) or 1
            result['total'] = (resp.get('pageCount', 1) or 1) * (resp.get('pageSize', self.PAGE_SIZE) or self.PAGE_SIZE)
        elif resp.get('errCode', -1) == 0:
            data = resp.get('data', {})
            movie_list = data.get('movieList', []) or data.get('records', []) or data.get('list', [])
            result['pagecount'] = data.get('pageCount', 1) or 1
            result['total'] = data.get('total', 0) or data.get('count', 0)
        else:
            movie_list = resp.get('records', []) or resp.get('movieList', []) or resp.get('list', [])

        for item in movie_list:
            if not isinstance(item, dict):
                continue
            vod_id = str(item.get('viewKey', '') or item.get('id', ''))
            vod_name = self.cleanText(item.get('title', ''))
            img_domain = item.get('imgDomain', '')
            poster = item.get('poster', '')
            if img_domain and poster:
                vod_pic = 'https://%s%s' % (img_domain, poster)
            else:
                vod_pic = self.fixUrl(poster)

            result['list'].append({
                'vod_id': vod_id,
                'vod_name': vod_name,
                'vod_pic': self.get_proxy_image_url(vod_pic) if vod_pic else '',
                'vod_remarks': '',
            })

        result['limit'] = len(result['list'])
        if not result['total']:
            result['total'] = len(result['list'])
        return result

    def detailContent(self, ids):
        result = {'list': []}
        if not ids:
            return result
        view_key = str(ids[0])

        vod = {
            'vod_id': view_key,
            'vod_name': '',
            'vod_pic': '',
            'vod_content': '',
            'vod_remarks': '',
            'vod_year': '',
            'vod_area': '',
            'vod_actor': '',
            'vod_director': '',
            'type_name': '',
            'vod_play_from': '',
            'vod_play_url': '',
        }

        resp = self._get_api(self.API_DETAIL, {'viewKey': view_key})
        if not resp:
            self._log('detailContent empty resp for viewKey=%s' % view_key)
            return result

        if resp.get('errCode', -1) == 0:
            data = resp.get('data', {})
        elif 'data' in resp:
            data = resp.get('data', {})
        else:
            data = resp

        if not data:
            self._log('detailContent no data, resp keys=%s' % list(resp.keys())[:10])
            return result

        # 调试:看 data 里都有啥关键字段
        self._log('detailContent data keys=%s' % list(data.keys())[:20])
        self._log('detailContent playUrl=%s srcList=%d srcInfo=%s' % (
            data.get('playUrl', ''), len(data.get('sourceInfoListVO') or []),
            'yes' if data.get('sourceInfoVO') else 'no'
        ))

        vod['vod_name'] = self.cleanText(data.get('title', ''))

        # 播放源：sourceInfoListVO 优先，回退 sourceInfoVO
        src_list = data.get('sourceInfoListVO', []) or []
        src_info = data.get('sourceInfoVO', {})
        if not isinstance(src_info, dict):
            src_info = {}
        if not src_list and src_info:
            src_list = [src_info]

        play_url_path = data.get('playUrl', '')

        # ========== 多线路展开(整合 18av 思路)==========
        # 每个 src 一条线路;同一线路内可能有多清晰度(videoSources)
        play_from_list = []
        play_url_list = []

        def _extract_quality_episodes(play_domain, play_path, src):
            """从单个 source 提取所有清晰度,返回 episode 列表"""
            eps = []
            base_url = self._build_play_url(play_domain, play_path)
            # 2026-09:生成后统一做内容级探测,失败自动换可用 CDN(见 _ensure_playable)
            base_url = self._ensure_playable(base_url)

            # 1) 优先用 videoSources(多清晰度)
            video_sources = src.get('videoSources', []) or []
            if isinstance(video_sources, list) and video_sources:
                # 按清晰度倒序
                def _size_key(v):
                    if not isinstance(v, dict):
                        return 0
                    return int(v.get('size') or v.get('height') or 0)
                sorted_vs = sorted(video_sources, key=_size_key, reverse=True)
                for v in sorted_vs:
                    if not isinstance(v, dict):
                        continue
                    url = v.get('url') or v.get('src') or v.get('playUrl') or ''
                    if not url:
                        continue
                    if not url.startswith('http'):
                        url = self._build_play_url(play_domain, url)
                    url = self._ensure_playable(url)
                    if not url:
                        continue
                    label = v.get('name') or v.get('label') or ('%sp' % _size_key(v) if _size_key(v) else '播放')
                    eps.append('%s$%s' % (label, url))
                return eps

            # 2) 单条 m3u8
            if base_url:
                eps.append('播放$' + base_url)
            return eps

        for idx, src in enumerate(src_list):
            if not isinstance(src, dict):
                continue
            src_name = src.get('name', '') or '%s-线路%d' % (self.NAME, idx + 1)
            # 2026-09:详情接口 playDomain 返回已失效旧域(vdo-yinghua.ozuesa.cn→403),
            # imgDomain(goeusig.kwvqaj.cn)才是当前真实播放域,优先取用;
            # 即使两者都不可用,_ensure_playable 也会按备用 CDN 列表换域。
            play_domain = src.get('imgDomain', '') or src.get('playDomain', '') or src.get('domain', '')

            # 兜底:每个 src 都用抓包 CDN 试一遍(看哪个通)
            episodes = _extract_quality_episodes(play_domain, play_url_path, src)

            # 如果该 src 没拿到,尝试 CDN 兜底
            if not episodes and play_url_path:
                full_play = self._ensure_playable(self._build_play_url('', play_url_path))
                if full_play:
                    episodes = ['播放$' + full_play]

            if not episodes:
                continue

            # ========== 多线路输出(可在播放器内切换)==========
            # 线路1「樱花」    : m3u8 → 反代(默认 PLAY_MODE=proxy,切片含 key 全代理)
            # 线路2「樱花-直连」: 同一 m3u8 → 直连(不走代理,快但 CDN 校验严可能黑)
            # 线路3「樱花-H5」  : H5 播放页 → parse=1 嗅探兜底
            play_from_list.append(src_name)
            play_url_list.append('#'.join(episodes))

            play_from_list.append(src_name + '-直连')
            play_url_list.append('#'.join(episodes))

            _vk = data.get('viewKey') or view_key
            if _vk:
                _h5_pages = self._build_web_play_pages_all(_vk)
                if _h5_pages:
                    play_from_list.append(src_name + '-H5')
                    play_url_list.append('播放$' + _h5_pages[0])

        # 兜底:详情里完全没线路信息,展示多条 H5 嗅探候选(让用户能选)
        if not play_from_list:
            view_key = data.get('viewKey') or view_key
            # 终极兜底:从 data 里所有字段爬 URL
            wild_urls = self._harvest_urls(data)
            self._log('detailContent wild urls: %s' % wild_urls[:3])
            if wild_urls:
                for i, u in enumerate(wild_urls[:5]):
                    play_from_list.append('直链%d' % (i + 1))
                    play_url_list.append('播放$' + u)
            if view_key:
                candidates = self._build_web_play_pages_all(view_key)
                # 按 host 分组,每 host 一条线路标签
                host_seen = []
                for u in candidates:
                    # 抽 host
                    host = u.split('/movie')[0].split('/play')[0].split('/h5')[0].split('/detail')[0].split('?')[0]
                    if host not in host_seen:
                        host_seen.append(host)
                        tag = host.split('//')[-1].split('.')[0].upper() or 'H5'
                        play_from_list.append(tag)
                        play_url_list.append('播放$' + u)
            vod['_has_play_page'] = True

        vod['vod_play_from'] = '$$$'.join(play_from_list)
        vod['vod_play_url'] = '$$$'.join(play_url_list)

        # 封面
        poster = data.get('poster', '')
        img_domain = src_info.get('imgDomain', '')
        if img_domain and poster:
            _pic = 'https://%s%s' % (img_domain, poster)
        else:
            _pic = self.fixUrl(poster)
        vod['vod_pic'] = self.get_proxy_image_url(_pic) if _pic else ''

        vod['vod_content'] = self.cleanText(data.get('content', '') or data.get('desc', ''))
        vod['vod_year'] = str(data.get('year', '') or '')
        vod['vod_area'] = str(data.get('area', '') or data.get('country', '') or '')
        vod['vod_actor'] = self.cleanText(data.get('actor', '') or data.get('actors', ''))
        vod['vod_director'] = self.cleanText(data.get('director', ''))

        tags = data.get('tags', '')
        if tags:
            vod['type_name'] = str(tags)[:50]

        result['list'].append(vod)
        return result

    def searchContent(self, key, quick='', pg=1):
        page = int(pg) if pg else 1
        result = {'list': [], 'page': page, 'pagecount': 1, 'limit': 20, 'total': 0}
        if not key:
            return result

        resp = self._post_api(self.API_LIST, {
            'keyword': key,
            'page': page,
            'pageSize': self.PAGE_SIZE,
            'sort': 1,
        })
        if not resp:
            return result

        if 'records' in resp:
            movie_list = resp.get('records', [])
            result['pagecount'] = resp.get('pageCount', 1) or 1
        elif resp.get('errCode', -1) == 0:
            data = resp.get('data', {})
            movie_list = data.get('movieList', []) or data.get('records', []) or data.get('list', [])
            result['pagecount'] = data.get('pageCount', 1) or 1
        else:
            movie_list = resp.get('records', []) or resp.get('movieList', []) or resp.get('list', [])

        for item in movie_list:
            if not isinstance(item, dict):
                continue
            vod_id = str(item.get('viewKey', '') or item.get('id', ''))
            vod_name = self.cleanText(item.get('title', ''))
            img_domain = item.get('imgDomain', '')
            poster = item.get('poster', '')
            if img_domain and poster:
                vod_pic = 'https://%s%s' % (img_domain, poster)
            else:
                vod_pic = self.fixUrl(poster)

            result['list'].append({
                'vod_id': vod_id,
                'vod_name': vod_name,
                'vod_pic': self.get_proxy_image_url(vod_pic) if vod_pic else '',
                'vod_remarks': '',
            })

        result['limit'] = len(result['list'])
        result['total'] = len(result['list'])
        return result

    def searchContentPage(self, key, quick, page):
        return self.searchContent(key, quick, page)

    # ===================== 播放 =====================
    def _build_play_url(self, play_domain, play_url_path):
        """拼接 m3u8 直链：域名缺失时用已验证 CDN 兜底"""
        path = (play_url_path or '').strip()
        if not path:
            return ''
        if path.startswith('http://') or path.startswith('https://'):
            return path

        domain = (play_domain or '').strip().rstrip('/')
        if not domain:
            # 优先用已实测可用的 CDN(首次探测后缓存)
            domain = self._verified_cdn or self.PLAY_CDN
        if domain.startswith('//'):
            domain = 'https:' + domain
        elif not domain.startswith('http'):
            domain = 'https://' + domain

        return '%s/%s' % (domain, path.lstrip('/'))

    def _harvest_urls(self, obj, depth=0, max_depth=6):
        """
        递归爬任意对象,找出所有看起来像 m3u8 / 视频直链的 URL
        用于接口字段名变化时的兜底
        """
        out = []
        if depth > max_depth:
            return out
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = (k or '').lower()
                # 字段名看起来像 url 相关的
                if any(t in kl for t in ('url', 'm3u8', 'src', 'play', 'video', 'hls', 'stream')):
                    if isinstance(v, str) and v.startswith('http'):
                        out.append(v)
                out.extend(self._harvest_urls(v, depth + 1, max_depth))
        elif isinstance(obj, list):
            for it in obj:
                out.extend(self._harvest_urls(it, depth + 1, max_depth))
        elif isinstance(obj, str):
            # 抓字符串里的 m3u8
            import re as _re
            for m in _re.finditer(r'https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*', obj):
                out.append(m.group(0))
        return out

    def _resolve_play(self, raw):
        """
        把传入的播放标识还原成可直连的 m3u8 地址
        多种策略:
          1) 已经是 m3u8 直链 → 直接返回
          2) 详情接口拿 vod_play_url(多种字段名)
          3) 详情接口拿 sourceInfoListVO/playUrl
          4) 详情接口拿 playInfoListVO
          5) 重拉详情页 HTML 抓 m3u8 关键字(备用)
        """
        raw = (raw or '').strip()
        # 剥 "线路名$" 前缀(如 "播放$https://...")
        if '$' in raw and not raw.startswith('http'):
            raw = raw.split('$', 1)[-1].strip()
        if not raw:
            return ''
        if '.m3u8' in raw.lower():
            if raw.startswith('http'):
                return self._ensure_playable(raw)
            return self._ensure_playable(self._build_play_url('', raw))

        # 抠 viewKey
        view_key = ''
        m = re.search(r'viewKey=([^&#]+)', raw)
        if m:
            view_key = m.group(1)
        elif not raw.startswith('http'):
            view_key = raw
        if not view_key:
            return ''

        # 多次重试 detailContent
        for retry in range(2):
            try:
                detail = self.detailContent([view_key])
                lst = detail.get('list') or []
                if not lst:
                    continue
                vod = lst[0]
                self._log('_resolve_play detail keys=%s' % list(vod.keys()))

                # 策略 1: vod_play_url 里拼的 m3u8
                play_url = vod.get('vod_play_url', '') or ''
                if play_url:
                    # 拆 "播放$url$$$播放$url2"
                    for line in play_url.split('$$$'):
                        ep = line.split('$')[-1].strip()
                        if ep and ('.m3u8' in ep.lower() or ep.startswith('http')):
                            return ep

                # 策略 2: vod_play_url 为空,直接看是不是有隐藏字段
                for k in ('m3u8', 'play_url', 'playUrl', 'real_play_url',
                         'sourceUrl', 'source_url', 'videoUrl', 'video_url'):
                    v = vod.get(k, '')
                    if v and isinstance(v, str) and v.startswith('http'):
                        return v

                # 策略 3: detailContent 没给但有 _has_play_page 标记,走 H5
                if vod.get('_has_play_page'):
                    self._log('_resolve_play detail has no m3u8, will sniff H5')
                    return ''
            except Exception as e:
                self._log('_resolve_play retry=%d err=%s' % (retry, e))
                continue

        return ''

    # ===================== 播放模式开关 =====================
    # 'proxy'  = 强制播放反代(m3u8+ts 全代理,最稳,默认)
    # 'sniff'  = 强制嗅探 H5 播放页(parse=1,TVBox 内置浏览器抓 m3u8)
    # 'h5'     = 强制 H5 模式(parse=1,完整 H5 页面当 URL,有些播放器会直接当网页打开)
    # 'direct' = 强制直连 m3u8(快但 CDN 校验严会黑)
    # 'auto'   = 智能切换
    #
    # 2026-09 修复:默认从 'h5' 改为 'proxy'。
    # 原因:1) 站点 H5 播放页是 Nuxt 壳,浏览器里也长期 Loading 不出播放器,嗅探不可靠;
    #      2) 详情接口/data 里可直接拿到 playUrl(imgDomain 域),构造 m3u8 直链后
    #         内容级探测(#EXTM3U)确认可用,走反代最稳;3) h5/sniff 对拼接串
    #         "播放$https://..." 解析 viewKey 会失败,导致把站点主页当 URL 返回。
    PLAY_MODE = 'proxy'

    # 是否输出调试日志(在 TVBox 日志里看 [YINGHUA])
    DEBUG = True

    def _log(self, msg):
        if not self.DEBUG:
            return
        try:
            import sys as _s
            print('[YINGHUA] ' + str(msg), file=_s.stderr, flush=True)
        except Exception:
            pass

    def _build_web_play_page(self, view_key):
        """拼出 H5 播放页 URL(主站)"""
        if not view_key:
            return ""
        return "%s/movie?viewKey=%s" % (self.host.rstrip("/"), view_key)

    def _build_web_play_pages_all(self, view_key):
        """
        返回所有嗅探 URL 候选(含备用 host + 备用 path)
        优先主 host + 主 path,然后备用 host × 备用 path
        """
        if not view_key:
            return []
        results = []
        seen = set()
        hosts = [self.host] + [h for h in self.PLAY_HOST_BACKUP if h != self.host]
        for h in hosts:
            for p in self.PLAY_PAGE_PATHS:
                url = h.rstrip('/') + p.format(vk=view_key)
                if url not in seen:
                    seen.add(url)
                    results.append(url)
        return results

    def _extract_view_key(self, raw):
        """从传入的 id 抠 viewKey(先剥 "线路名$" 前缀)"""
        raw = (raw or "").strip()
        if not raw:
            return ""
        if "$" in raw and not raw.startswith("http"):
            raw = raw.split("$", 1)[-1].strip()
        m = re.search(r"viewKey=([^&#]+)", raw)
        if m:
            return m.group(1)
        if ".m3u8" in raw.lower():
            return ""
        if raw.startswith("http"):
            return ""
        return raw

    def _probe_m3u8(self, url, timeout=4):
        """探测 m3u8 是否可访问(返回 True/False)"""
        return self._probe_m3u8_full(url, timeout=timeout) is not None

    def _probe_m3u8_full(self, url, timeout=4):
        """
        探测 m3u8 是否可访问,顺带返回最佳请求头组合
        返回: (headers_dict) 或 None
        试多 UA + 多 Referer,且内容必须以 #EXTM3U 开头才算真 m3u8
        (2026-09:部分 CDN 对任意路径返回 200 的 SPA 壳页面,须内容级校验)
        """
        if not url or not _HAS_REQUESTS or self.session is None:
            return None
        candidates = []
        for ua in self.PLAY_UA_LIST:
            for ref in self.PLAY_REFERER_LIST:
                candidates.append({
                    "User-Agent": ua,
                    "Referer": ref,
                    "Origin": self.host,
                    "Accept": "*/*",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                })
        for hdr in candidates:
            try:
                r = self.session.get(url, headers=hdr, timeout=timeout, stream=True, allow_redirects=True)
                ok = (r.status_code == 200)
                if ok:
                    head = b''
                    try:
                        head = r.raw.read(24) if hasattr(r, 'raw') else b''
                    except Exception:
                        head = b''
                    # 内容级校验:必须是 m3u8 播放列表,不是 HTML 兜底页
                    ok = head.lstrip().startswith(b'#EXTM')
                try:
                    r.close()
                except Exception:
                    pass
                if ok:
                    return hdr
            except Exception:
                continue
        return None

    def _ensure_playable(self, m3u8_url, timeout=4):
        """
        确保 m3u8_url 指向真实可用的播放列表:
          1) 已缓存可用 CDN → 直接把域名替换为缓存域名(省一次网络请求)
          2) 未缓存 → 内容级探测当前 URL,可用则缓存域名并返回
          3) 不可用 → 依次尝试 PLAY_CDN_BACKUP 其它域名,命中则缓存
        全部失败返回原 URL(交给播放器层再失败)
        """
        if not m3u8_url:
            return ''
        if not _HAS_REQUESTS or self.session is None:
            return m3u8_url

        m = re.match(r'(https?://[^/]+)(/.*)', m3u8_url)
        if not m:
            return m3u8_url
        cur_domain, path = m.group(1), m.group(2)

        # 1) 已有已验证可用域,直接用(域名不同则替换)
        if self._verified_cdn:
            if self._verified_cdn == cur_domain:
                return m3u8_url
            return self._verified_cdn + path

        # 2) 当前域直接可用
        if self._probe_m3u8_full(m3u8_url, timeout=timeout):
            self._verified_cdn = cur_domain
            return m3u8_url

        # 3) 备用域逐个试
        for cdn in self.PLAY_CDN_BACKUP:
            cdn = (cdn or '').rstrip('/')
            if not cdn or cdn == cur_domain:
                continue
            test_url = cdn + path
            if self._probe_m3u8_full(test_url, timeout=timeout):
                self._verified_cdn = cdn
                return test_url
        return m3u8_url

    def _swap_cdn(self, m3u8_url):
        """兼容旧调用:内容级换域校验(M3U8 真正可达才换),命中即缓存"""
        return self._ensure_playable(m3u8_url, timeout=3)

    def _proxy_play(self, real_url):
        """反代播放:把 m3u8 URL 包成 TVBox 代理 URL,所有切片都从我这里过"""
        proxy_url = self._wrap_play_url(real_url)
        return {
            "parse": 0,
            "playUrl": "",
            "url": proxy_url,
            "header": {
                "User-Agent": self.PLAY_UA,
                "Referer": self.host + "/",
            },
        }

    def _direct_play(self, url, headers=None):
        """直连播放(可指定探测出来的最佳 headers)"""
        if headers is None:
            headers = {
                "User-Agent": self.PLAY_UA,
                "Referer": self.host + "/",
                "Origin": self.host,
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        return {
            "parse": 0,
            "playUrl": "",
            "url": url,
            "header": headers,
        }

    def _sniff_play(self, raw):
        """嗅探播放(parse=1),拼出 H5 播放页让播放器去抓 m3u8"""
        raw = (raw or "").strip()
        if "$" in raw and not raw.startswith("http"):
            raw = raw.split("$", 1)[-1].strip()
        view_key = self._extract_view_key(raw)
        if view_key:
            # 用所有候选 URL 的第一个(主 host + 主 path)
            candidates = self._build_web_play_pages_all(view_key)
            page_url = candidates[0] if candidates else self.host
        elif raw.startswith("http"):
            # 直链:嗅探页对它没意义,直接原样返回(parse=1,播放器会按网页处理)
            page_url = raw
        else:
            page_url = self.host
        self._log('_sniff_play url=%s' % page_url[:120])
        return {
            "parse": 1,
            "playUrl": "",
            "url": page_url,
            "header": {
                "User-Agent": self.PLAY_UA,
                "Referer": self.host + "/",
                "Origin": self.host,
            }
        }

    def _h5_play(self, raw):
        """
        H5 模式:直接把 H5 播放页 URL 给 TVBox,parse=1 让播放器当网页打开
        兜底:详情接口 / CDN 都不可用时,赌 H5 页面本身有内置播放器
        """
        raw = (raw or "").strip()
        if "$" in raw and not raw.startswith("http"):
            raw = raw.split("$", 1)[-1].strip()
        view_key = self._extract_view_key(raw)
        if view_key:
            candidates = self._build_web_play_pages_all(view_key)
            page_url = candidates[0] if candidates else self.host
        elif raw.startswith("http") and ".m3u8" in raw.lower():
            # m3u8 直链兜底:parse=1 交给播放器去解析
            page_url = raw
        else:
            page_url = self.host
        self._log('_h5_play url=%s' % page_url[:120])
        return {
            "parse": 1,
            "playUrl": "",
            "url": page_url,
            "header": {
                "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
                "Referer": self.host + "/",
            }
        }

    def playerContent(self, flags, id, vipFlags):
        """
        播放策略(线路名 flags 优先,PLAY_MODE 兜底):
          - flags 含「H5/嗅探」        → parse=1 打开 H5 播放页(站点自带播放器嗅探)
          - flags 含「直连/direct」    → parse=0 直连 m3u8(不走代理,快)
          - 其余/无 flags(默认)        → parse=0 反代(m3u8+ts+key 全代理,最稳)
        流程:
          1) 已有 m3u8 直链 → 校验后按 flags 播放
          2) 非 m3u8 → 详情解析直链 → 按 flags 播放
          3) 解析失败 → H5 兜底
        """
        raw = str(id or "")
        if not raw:
            return {"parse": 0, "url": "", "header": {}}

        flags = str(flags or "")
        mode = (self.PLAY_MODE or "proxy").lower()
        want_h5 = ('h5' in flags.lower() or '嗅探' in flags or 'probe' in flags.lower())
        want_direct = ('直连' in flags or 'direct' in flags.lower())
        self._log('playerContent mode=%s flags=%s id=%s' % (mode, flags, raw[:80]))

        # H5 线路:直接打开播放页(parse=1)
        if want_h5:
            return self._h5_play(raw)

        # 已经是 m3u8 直链:先剥 "线路名$" 前缀再播放
        if ".m3u8" in raw.lower():
            play_url = raw.split("$", 1)[-1].strip() if "$" in raw else raw
            if not play_url.startswith("http"):
                play_url = self._build_play_url("", play_url)
            play_url = self._ensure_playable(play_url)
            self._log('playerContent direct m3u8 -> %s' % play_url[:120])
            if mode == "direct" or want_direct:
                return self._direct_play(play_url)
            return self._proxy_play(play_url)

        # 非 m3u8:先去详情解析
        direct_url = self._resolve_play(raw)
        self._log('resolve_play -> %s' % (direct_url[:120] if direct_url else 'EMPTY'))

        if not direct_url:
            self._log('no m3u8 from detail, fallback to H5 page')
            if mode == "direct" or want_direct:
                return self._direct_play(raw)
            return self._h5_play(raw)

        # 拿到直链:按 flags/mode 播放(站点 H5 是 Nuxt 壳,播放器打开主页无法播)
        if mode == "direct" or want_direct:
            return self._direct_play(direct_url)
        return self._proxy_play(direct_url)

    # ===================== 图片代理(整合 18av 风格) =====================
    def _ensure_proxy_prefix(self):
        if getattr(self, '_proxy_prefix', ''):
            return
        try:
            base = self.getProxyUrl()
        except Exception:
            base = ''
        if not base:
            base = 'http://127.0.0.1:9980/proxy?do=py'
        if '?' not in base:
            base += '?do=py'
        elif not base.endswith('&'):
            base += '&'
        self._proxy_prefix = base + 'type=' + self.PROXY_TYPE + '&url='

    def get_proxy_image_url(self, img_url):
        """把图片 URL 套上代理前缀(给 TVBox 用)"""
        if not img_url or not self.USE_IMAGE_PROXY:
            return img_url or ''
        self._ensure_proxy_prefix()
        return self._proxy_prefix + quote(img_url, safe='')

    def localProxy(self, params):
        """TVBox 代理:图片 / 播放(m3u8+ts)"""
        try:
            ptype = params.get('type', '')

            # ===== 播放代理(m3u8 / ts 反代,关键!)=====
            if ptype == self.PROXY_TYPE_PLAY:
                play_url = params.get('url', '')
                if not play_url:
                    return [400, 'text/plain', 'missing url']
                play_url = unquote(play_url)
                range_header = params.get('Range') or params.get('range') or None
                return self._proxy_fetch(play_url, range_header=range_header)

            # ===== 图片代理 =====
            if ptype != self.PROXY_TYPE:
                return [404, 'text/plain', 'not found']

            img_url = params.get('url', '')
            if not img_url:
                return [400, 'text/plain', 'missing url']

            img_url = unquote(img_url)
            if not _HAS_REQUESTS:
                return [500, 'text/plain', 'requests not installed']

            r = self.session.get(
                img_url,
                headers={
                    'User-Agent': self.PLAY_UA,
                    'Referer': (self.host or '') + '/',
                },
                timeout=self.TIMEOUT,
            ) if self.session else requests.get(
                img_url,
                headers={
                    'User-Agent': self.PLAY_UA,
                    'Referer': (self.host or '') + '/',
                },
                timeout=self.TIMEOUT,
                verify=False,
            )

            if r.status_code != 200:
                return [404, 'text/plain', 'image not found']

            data = r.content
            if data[:2] == b'\xff\xd8':
                return [200, 'image/jpeg', data, {'Content-Length': str(len(data))}]
            elif data[:4] == b'\x89PNG':
                return [200, 'image/png', data, {'Content-Length': str(len(data))}]
            elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
                return [200, 'image/webp', data, {'Content-Length': str(len(data))}]
            else:
                mime = r.headers.get('Content-Type', 'image/jpeg')
                if mime.startswith('image/'):
                    return [200, mime, data, {'Content-Length': str(len(data))}]
                return [404, 'text/plain', 'invalid image format']
        except Exception as e:
            return [500, 'text/plain', 'proxy error: %s' % str(e)]

    # ===================== 播放反代(m3u8 / ts 切片) =====================
    def _ensure_play_proxy_prefix(self):
        """拿到 TVBox 播放代理 URL 前缀"""
        if getattr(self, '_play_proxy_prefix', ''):
            return
        try:
            base = self.getProxyUrl()
        except Exception:
            base = ''
        if not base:
            base = 'http://127.0.0.1:9980/proxy?do=py'
        if '?' not in base:
            base += '?do=py'
        elif not base.endswith('&'):
            base += '&'
        self._play_proxy_prefix = base + 'type=' + self.PROXY_TYPE_PLAY + '&url='

    def _wrap_play_url(self, real_url):
        """把真实 m3u8 URL 包成 TVBox 代理 URL(带 path 标识 t=m3u8/ts)"""
        if not real_url or not self.USE_PLAY_PROXY:
            return real_url
        self._ensure_play_proxy_prefix()
        # 标记这是 m3u8(切片类型会在代理里通过扩展名自动判断)
        return self._play_proxy_prefix + quote(real_url, safe='')

    def _proxy_fetch(self, url, range_header=None):
        """
        从源站拉内容(带完整反盗链头),返回 (status, content_type, body, extra_headers)
        - m3u8: 改写切片 URL 也走代理
        - ts:   直接转发
        """
        if not _HAS_REQUESTS:
            return [500, 'text/plain', b'requests not installed']

        self._log('proxy_fetch url=%s range=%s' % (url[:120], range_header or '-'))

        # 选 headers:多 UA × 多 Referer 挨个试
        chosen_hdr = None
        last_err = None
        sess = self.session if self.session else requests
        for hdr in self._iter_play_headers():
            try:
                test_hdr = dict(hdr)
                if range_header:
                    test_hdr['Range'] = range_header
                r = sess.get(url, headers=test_hdr, timeout=self.TIMEOUT,
                             stream=True, allow_redirects=True, verify=False)
                self._log('try ua=%s ref=%s -> %s' % (
                    test_hdr['User-Agent'][:30], test_hdr['Referer'] or '(none)', r.status_code))
                if r.status_code in (200, 206):
                    chosen_hdr = test_hdr
                    # 读前 4KB 探一下内容
                    head = r.raw.read(4096) if hasattr(r, 'raw') else r.content[:4096]
                    # ts 切片 m3u8 都得知道类型
                    ctype = r.headers.get('Content-Type', '')
                    # 判断是不是 m3u8:仅凭 Content-Type / 内容头 / 以 .m3u8 结尾。
                    # 不能用 'm3u8' in url 判断——key.dat 的路径含 /m3u8/ 会被误判,
                    # 导致 16B 的 AES key 被当成播放列表重写而无法解密(2026-09 修复)。
                    _url_no_q = url.split('?')[0].lower()
                    if ('mpegurl' in ctype.lower() or _url_no_q.endswith('.m3u8')
                            or head.lstrip().startswith(b'#EXTM3U')):
                        body = head + (r.raw.read() if hasattr(r, 'raw') else b'')
                        try:
                            r.close()
                        except Exception:
                            pass
                        new_body = self._rewrite_m3u8(body.decode('utf-8', errors='ignore'), url)
                        return [200, 'application/vnd.apple.mpegurl', new_body.encode('utf-8'),
                                {'Content-Length': str(len(new_body))}]
                    # ts / mp4 / 其他二进制
                    try:
                        r.close()
                    except Exception:
                        pass
                    # 重新拉完整流(避免 raw 重复读)
                    r2 = sess.get(url, headers=test_hdr, timeout=self.TIMEOUT,
                                  stream=True, allow_redirects=True, verify=False)
                    data = r2.content
                    try:
                        r2.close()
                    except Exception:
                        pass
                    return [r2.status_code, ctype or 'video/mp2t', data,
                            {'Content-Length': str(len(data))}]
                try:
                    r.close()
                except Exception:
                    pass
            except Exception as e:
                last_err = e
                continue
        self._log('all ua/ref combos failed, last_err=%s' % (last_err or 'none'))
        if last_err:
            return [502, 'text/plain', ('upstream error: %s' % str(last_err)).encode('utf-8')]
        return [502, 'text/plain', b'upstream unreachable']

    def _iter_play_headers(self):
        """生成所有 UA × Referer 组合"""
        for ua in self.PLAY_UA_LIST:
            for ref in self.PLAY_REFERER_LIST:
                yield {
                    "User-Agent": ua,
                    "Referer": ref,
                    "Origin": self.host,
                    "Accept": "*/*",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                }

    def _rewrite_m3u8(self, content, base_url):
        """
        改写 m3u8 内部的 key / 切片 / 子列表 URL,全部走代理
        2026-09 修复:新增 #EXT-X-KEY 行的 URI 重写。
        站内 HLS 带 AES-128(URI="key.dat" 相对路径),若不重写,
        播放器会用反代 URL 相对解析 key 而失败,导致解密黑屏。
        """
        if not content:
            return content
        lines = content.splitlines()
        out = []
        from urllib.parse import urljoin
        for ln in lines:
            s = ln.strip()
            # ---- #EXT-X-KEY 行:重写 URI ----
            if s.startswith('#EXT-X-KEY') and 'URI=' in s:
                m = re.search(r'URI="([^"]+)"', s)
                if m:
                    uri = m.group(1)
                    if uri.startswith('http'):
                        full = uri
                    else:
                        full = urljoin(base_url, uri)
                    _new = self._wrap_play_url(full)
                    s = s[:m.start(1)] + _new + s[m.end(1):]
                out.append(s)
                continue
            # ---- 其它 # 开头行原样保留 ----
            if not s or s.startswith('#'):
                out.append(ln)
                continue
            # ---- 切片 / 子列表 URL ----
            # 绝对 URL
            if s.startswith('http://') or s.startswith('https://'):
                full = s
            elif s.startswith('//'):
                full = 'https:' + s
            else:
                full = urljoin(base_url, s)
            out.append(self._wrap_play_url(full))
        return '\n'.join(out)
