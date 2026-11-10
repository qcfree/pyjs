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

    # 抓包确认的视频 CDN：https://vdo-yinghua.ozuesa.cn/m3u8/2026-07-28/005/<id>/index.m3u8
    # 当详情接口没有返回 playDomain 时用它兜底
    PLAY_CDN = 'https://vdo-yinghua.ozuesa.cn'

    def __init__(self):
        self.host = self.HOST
        self._token = ''
        self._token_time = 0
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

        payload = json.dumps(enc_body)

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
        payload = json.dumps(enc_body)
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
                'vod_pic': vod_pic,
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
            return result

        if resp.get('errCode', -1) == 0:
            data = resp.get('data', {})
        elif 'data' in resp:
            data = resp.get('data', {})
        else:
            data = resp

        if not data:
            return result

        vod['vod_name'] = self.cleanText(data.get('title', ''))

        # 播放源：sourceInfoListVO 优先，回退 sourceInfoVO
        src_list = data.get('sourceInfoListVO', []) or []
        src_info = data.get('sourceInfoVO', {})
        if not isinstance(src_info, dict):
            src_info = {}
        if not src_list and src_info:
            src_list = [src_info]

        play_url_path = data.get('playUrl', '')

        play_from_list = []
        play_url_list = []
        for src in src_list:
            if not isinstance(src, dict):
                continue
            src_name = src.get('name', '') or self.NAME
            play_domain = src.get('playDomain', '') or src.get('domain', '')
            full_play = self._build_play_url(play_domain, play_url_path)
            if not full_play:
                continue
            play_from_list.append(src_name)
            play_url_list.append('播放$' + full_play)

        if not play_from_list:
            # 详情没给播放域名时，用抓包到的 CDN 兜底
            full_play = self._build_play_url('', play_url_path)
            if full_play:
                play_from_list.append(src_info.get('name', '') or self.NAME)
                play_url_list.append('播放$' + full_play)

        vod['vod_play_from'] = '$$$'.join(play_from_list)
        vod['vod_play_url'] = '$$$'.join(play_url_list)

        # 封面
        poster = data.get('poster', '')
        img_domain = src_info.get('imgDomain', '')
        if img_domain and poster:
            vod['vod_pic'] = 'https://%s%s' % (img_domain, poster)
        else:
            vod['vod_pic'] = self.fixUrl(poster)

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
                'vod_pic': vod_pic,
                'vod_remarks': '',
            })

        result['limit'] = len(result['list'])
        result['total'] = len(result['list'])
        return result

    def searchContentPage(self, key, quick, page):
        return self.searchContent(key, quick, page)

    # ===================== 播放 =====================
    def _build_play_url(self, play_domain, play_url_path):
        """拼接 m3u8 直链：域名缺失时用抓包确认的 CDN 兜底"""
        path = (play_url_path or '').strip()
        if not path:
            return ''
        if path.startswith('http://') or path.startswith('https://'):
            return path

        domain = (play_domain or '').strip().rstrip('/')
        if not domain:
            domain = self.PLAY_CDN
        if domain.startswith('//'):
            domain = 'https:' + domain
        elif not domain.startswith('http'):
            domain = 'https://' + domain

        return '%s/%s' % (domain, path.lstrip('/'))

    def _resolve_play(self, raw):
        """把传入的播放标识还原成可直连的 m3u8 地址"""
        raw = (raw or '').strip()
        if not raw:
            return ''
        if '.m3u8' in raw:
            return raw if raw.startswith('http') else self._build_play_url('', raw)

        # 网页壳子地址(/movie?viewKey=xxx)或裸 viewKey -> 重拉详情取真实地址
        view_key = ''
        m = re.search(r'viewKey=([^&#]+)', raw)
        if m:
            view_key = m.group(1)
        elif not raw.startswith('http'):
            view_key = raw
        if not view_key:
            return ''
        try:
            detail = self.detailContent([view_key])
            lst = detail.get('list') or []
            if lst:
                play_url = lst[0].get('vod_play_url', '') or ''
                if play_url:
                    return play_url.split('$$$')[0].split('$')[-1]
        except Exception:
            pass
        return ''

    def playerContent(self, flags, id, vipFlags):
        # m3u8 直链：CDN(Cloudflare) 对播放请求不做防盗链校验（抓包确认裸链 206），
        # 请求头与 H5 播放页 hls.js 一致即可
        url = self._resolve_play(str(id))
        return {
            'parse': 0,
            'playUrl': '',
            'url': url,
            'header': {
                'User-Agent': self.PLAY_UA,
                'Referer': self.host + '/',
                'Origin': self.host,
            }
        }
