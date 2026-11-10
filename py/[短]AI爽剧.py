# -*- coding: utf-8 -*-
"""
TVBox Python 爬虫 - AI爽剧网 (iirjpml.com)
支持: 一级分类 / 二级分类筛选(题材+排序) / 搜索 / 详情 / 直接m3u8播放

站点结构:
  - 首页: https://iirjpml.com/
  - 列表页: /list/all/1 (分页: /list/all/1/page/N)
  - AI成人短剧: /adult-list/all/1 (分页: /adult-list/all/1/page/N)
  - 排行榜: /rank
  - 今日更新: /today-update
  - 今日推荐: /more/1 (分页: /more/1/page/N)
  - 详情页: /detail/{slug}
  - 播放页: /play/{slug}/{chapter-id}
  - 搜索页: /search/{keyword} (分页: /search/{keyword}/page/N)

速度优化:
  1. Session 复用 + 连接池, 减少 TCP 握手
  2. 预编译正则, 避免运行时编译开销
  3. 卡片按 poster-card 切块解析, 单卡失败不影响其他卡片
  4. 直接提取 m3u8 地址 (parse=0), 无需嗅探, 播放秒开
  5. 优先从 JSON-LD contentUrl 提取完整 m3u8 URL, 次选 DPlayer data-url
"""

import sys
import re
import json
import base64
import html as _html
from urllib.parse import quote, unquote

sys.path.append('..')

try:
    import requests as _requests
except ImportError:
    _requests = None

from base.spider import Spider


class Spider(Spider):

    # ==================== 站点配置 ====================
    HOST = 'https://iirjpml.com'
    M3U8_CDN = 'https://aishuangju.com/h5/m3u8/'
    # 图片解密密钥 (来自 imgDecypt.js, XOR前100字节)
    IMG_KEY = b'2019ysapp7527'
    # 本地代理地址
    PROXY_HOST = 'http://127.0.0.1:9978'
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Referer': 'https://iirjpml.com/',
    }

    PER_PAGE = 18

    # ==================== 一级分类 ====================
    CATEGORIES = [
        {'type_id': 'home',  'type_name': '推荐'},
        {'type_id': 'list',  'type_name': '全部短剧'},
        {'type_id': 'adult', 'type_name': 'AI成人短剧'},
        {'type_id': 'rank',  'type_name': '排行榜'},
        {'type_id': 'today', 'type_name': '今日更新'},
        {'type_id': 'more',  'type_name': '今日推荐'},
    ]

    # ==================== 二级筛选配置 ====================
    # 题材筛选 (走搜索接口 /search/{tag})
    TAG_FILTER = {
        'key': 'tag',
        'name': '题材',
        'value': [
            {'n': '全部',   'v': ''},
            {'n': '都市',   'v': '都市'},
            {'n': '校园',   'v': '校园'},
            {'n': '古风',   'v': '古风'},
            {'n': '玄幻',   'v': '玄幻'},
            {'n': '逆袭',   'v': '逆袭'},
            {'n': '穿越',   'v': '穿越'},
            {'n': '霸总',   'v': '霸总'},
            {'n': '战神',   'v': '战神'},
            {'n': '系统',   'v': '系统'},
            {'n': '魔改',   'v': '魔改'},
            {'n': '真人',   'v': '真人'},
            {'n': '修仙',   'v': '修仙'},
            {'n': '古装',   'v': '古装'},
            {'n': '巨乳',   'v': '巨乳'},
            {'n': '制服',   'v': '制服'},
            {'n': 'NTR',   'v': 'NTR'},
            {'n': '重口',   'v': '重口'},
        ]
    }

    # 排序筛选 (替换列表URL中的 all 为 hot/new)
    SORT_FILTER = {
        'key': 'sort',
        'name': '排序',
        'value': [
            {'n': '默认', 'v': ''},
            {'n': '热门', 'v': 'hot'},
            {'n': '最新', 'v': 'new'},
        ]
    }

    # ==================== 预编译正则 ====================

    # ---- 列表页卡片 ----
    # 卡片根元素: <a class="poster-card" href="/detail/{slug}">
    # 搜索页: <a class="poster-card search-card" href="/detail/{slug}">
    # 封面图: <img class="poster-cover-img lazy" data-src="{url}">
    # 集数: <div class="episode-badge">{N}集</div>
    # 注意: 用 [ "] 精确匹配卡片根元素, 避免误匹配 poster-card-body 等子元素
    _RE_CARD_SPLIT = re.compile(r'class="poster-card[ "]')
    _RE_CARD_HREF = re.compile(r'href="/detail/([^"]+)"')
    _RE_CARD_IMG = re.compile(r'data-src="([^"]+)"')
    _RE_CARD_TITLE = re.compile(r'poster-card-title">([^<]+)<')
    _RE_CARD_REMARK = re.compile(r'episode-badge[^>]*>.*?(\d+\s*集)', re.S)

    # ---- 详情页 ----
    # 标题: <h1 class="detail-title">{title}</h1>
    # 简介: <p class="detail-intro">...</p>
    # 免费剧集: <a class="detail-episode" href="/play/{slug}/{cid}" data-ep="{N}">
    # 付费剧集: <a class="detail-episode" href="javascript:;" data-ep="{N}" data-playlet-slug="{slug}" data-chapter-id="{cid}">
    _RE_DETAIL_TITLE = re.compile(r'detail-title">([^<]+)<')
    _RE_DETAIL_PIC = re.compile(r'og:image"[^>]*content="([^"]+)"')
    _RE_DETAIL_PIC2 = re.compile(r'data-cover="([^"]+)"')
    _RE_DETAIL_PIC3 = re.compile(r'poster-cover-img[^>]*data-src="([^"]+)"')
    _RE_DETAIL_DESC = re.compile(r'detail-intro[^>]*>(.*?)</(?:p|div)>', re.S)
    _RE_EPISODE_FREE = re.compile(r'detail-episode[^>]*?href="/play/([^"]+)"[^>]*?data-ep="(\d+)"')
    _RE_EPISODE_PAID = re.compile(r'detail-episode[^>]*?href="javascript:;"[^>]*?data-ep="(\d+)"[^>]*?data-playlet-slug="([^"]+)"[^>]*?data-chapter-id="([^"]+)"')

    # ---- 播放页 m3u8 ----
    # JSON-LD: "contentUrl": "https://aishuangju.com/h5/m3u8/..."
    # DPlayer: data-url="v3/k12/...m3u8?id=...&amp;t=...&amp;ticket=..." (注意HTML实体)
    _RE_M3U8_JSONLD = re.compile(r'"contentUrl"\s*:\s*"([^"]+)"')
    _RE_M3U8_DATA = re.compile(r'data-url="([^"]+)"')

    # ---- 总数/分页 ----
    _RE_TOTAL = re.compile(r'共\s*(\d+)\s*部')
    _RE_PAGE_MAX = re.compile(r'href="/[^"]*page/(\d+)"')

    def _build_filters(self):
        """构建二级筛选器, 每个一级分类都带完整的二级筛选"""
        filters = {}
        for cat in self.CATEGORIES:
            filters[cat['type_id']] = [
                self.TAG_FILTER,
                self.SORT_FILTER,
            ]
        return filters

    # ==================== 基础方法 ====================

    def getName(self):
        return "AI爽剧网"

    def init(self, cfg=''):
        if _requests is not None:
            self.session = _requests.Session()
            self.session.headers.update(self.HEADERS)
            self.session.verify = False
            adapter = _requests.adapters.HTTPAdapter(
                pool_connections=10,
                pool_maxsize=10,
                max_retries=1
            )
            self.session.mount('https://', adapter)
            self.session.mount('http://', adapter)
        else:
            self.session = None
        return self

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def _fetch(self, url, timeout=8):
        """统一请求方法, Session 复用 + 连接池"""
        try:
            if self.session is not None:
                resp = self.session.get(url, timeout=timeout, allow_redirects=True)
                resp.encoding = 'utf-8'
                return resp.text
            return ''
        except Exception as e:
            print(f"[AI爽剧网] 请求失败: {url}, 错误: {str(e)}")
            return ''

    def _abs_url(self, url):
        if not url:
            return ''
        if url.startswith('http'):
            return url
        if url.startswith('//'):
            return 'https:' + url
        if url.startswith('/'):
            return self.HOST + url
        return self.HOST + '/' + url

    def _proxy_img_url(self, img_url):
        """将图片URL转换为本地代理URL, 用于解密加密图片"""
        if not img_url:
            return ''
        return '%s/proxy?do=img&url=%s' % (self.PROXY_HOST, quote(img_url, safe=''))

    def _decrypt_img(self, data):
        """XOR解密图片前100字节, 密钥来自 imgDecypt.js"""
        if not data:
            return data
        buf = bytearray(data)
        key = self.IMG_KEY
        for i in range(min(100, len(buf))):
            buf[i] ^= key[i % len(key)]
        return bytes(buf)

    def _fetch_img(self, img_url):
        """下载加密图片并解密, 返回解密后的bytes"""
        try:
            if self.session is not None:
                resp = self.session.get(img_url, timeout=8)
            elif _requests is not None:
                resp = _requests.get(img_url, timeout=8, headers=self.HEADERS)
            else:
                return None
            if resp.status_code == 200:
                return self._decrypt_img(resp.content)
        except Exception as e:
            print(f"[AI爽剧网] 图片下载失败: {img_url}, 错误: {str(e)}")
        return None

    # ==================== HTML 解析 ====================

    def _parse_video_list(self, html):
        """解析视频卡片列表, 按 poster-card 切块, 单卡失败不影响其他"""
        if not html:
            return []
        videos = []
        seen = set()
        chunks = self._RE_CARD_SPLIT.split(html)
        for chunk in chunks[1:]:
            m = self._RE_CARD_HREF.search(chunk)
            if not m:
                continue
            vid = m.group(1).strip()
            if not vid or vid in seen:
                continue
            m = self._RE_CARD_TITLE.search(chunk)
            title = m.group(1).strip() if m else ''
            if not title:
                continue
            m = self._RE_CARD_IMG.search(chunk)
            pic = self._proxy_img_url(self._abs_url(m.group(1).strip())) if m else ''
            m = self._RE_CARD_REMARK.search(chunk)
            remark = m.group(1).strip() if m else ''
            seen.add(vid)
            videos.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': remark,
            })
        return videos

    def _parse_total(self, html):
        """从 '共 N 部' 提取总数"""
        m = self._RE_TOTAL.search(html)
        if m:
            return int(m.group(1)) if m.group(1).isdigit() else 0
        return 0

    def _parse_page_count(self, html):
        """从分页按钮中提取最大页码"""
        nums = self._RE_PAGE_MAX.findall(html)
        if nums:
            return max(int(n) for n in nums if n.isdigit())
        return 0

    # ==================== 首页 ====================

    def homeContent(self, filter):
        result = {}
        result['class'] = [dict(item) for item in self.CATEGORIES]
        if filter:
            result['filters'] = self._build_filters()
        html = self._fetch(self.HOST)
        if html:
            videos = self._parse_video_list(html)
            if videos:
                result['list'] = videos
        return result

    def homeVideoContent(self):
        html = self._fetch(self.HOST)
        videos = self._parse_video_list(html) if html else []
        return {'list': videos}

    # ==================== 分类内容 ====================

    def categoryContent(self, tid, pg, filter, extend):
        result = {}
        page = int(pg) if pg else 1
        extend = extend or {}

        tag = extend.get('tag', '')
        sort = extend.get('sort', '')

        # 题材筛选 -> 走搜索接口 (搜索支持中文关键词)
        if tag:
            if page > 1:
                url = '%s/search/%s/page/%d' % (self.HOST, quote(tag), page)
            else:
                url = '%s/search/%s' % (self.HOST, quote(tag))
        elif tid == 'home':
            # 推荐无分页, 直接返回首页数据
            return self.homeVideoContent()
        elif tid == 'list':
            # 全部短剧 /list/{sort}/1, sort 默认 all
            sort_val = sort if sort else 'all'
            if page > 1:
                url = '%s/list/%s/1/page/%d' % (self.HOST, sort_val, page)
            else:
                url = '%s/list/%s/1' % (self.HOST, sort_val)
        elif tid == 'adult':
            # AI成人短剧 /adult-list/{sort}/1
            sort_val = sort if sort else 'all'
            if page > 1:
                url = '%s/adult-list/%s/1/page/%d' % (self.HOST, sort_val, page)
            else:
                url = '%s/adult-list/%s/1' % (self.HOST, sort_val)
        elif tid == 'rank':
            # 排行榜无分页
            url = '%s/rank' % self.HOST
        elif tid == 'today':
            # 今日更新无分页
            url = '%s/today-update' % self.HOST
        elif tid == 'more':
            # 今日推荐 /more/1/page/N
            if page > 1:
                url = '%s/more/1/page/%d' % (self.HOST, page)
            else:
                url = '%s/more/1' % self.HOST
        else:
            url = '%s/list/all/1' % self.HOST

        print(f"[AI爽剧网] 分类URL: {url}")
        html = self._fetch(url)
        if not html:
            return {'list': [], 'page': page, 'pagecount': 1, 'limit': 0, 'total': 0}

        videos = self._parse_video_list(html)
        total = self._parse_total(html)
        page_count = self._parse_page_count(html)

        # 计算总页数: 优先用分页按钮, 其次用总数推算
        if total > 0 and not page_count:
            page_count = (total + self.PER_PAGE - 1) // self.PER_PAGE
        elif not page_count:
            if len(videos) >= self.PER_PAGE:
                page_count = page + 1
            else:
                page_count = page

        result['list'] = videos
        result['page'] = page
        result['pagecount'] = page_count if page_count else 1
        result['limit'] = len(videos)
        result['total'] = total
        return result

    # ==================== 详情页 ====================

    def detailContent(self, ids):
        vid = ids[0]
        url = '%s/detail/%s' % (self.HOST, vid)
        html = self._fetch(url)
        if not html or len(html) < 200:
            print(f"[AI爽剧网] 详情页获取失败: {vid}")
            return {'list': []}

        vod = {'vod_id': vid}

        # 标题
        m = self._RE_DETAIL_TITLE.search(html)
        if m:
            vod['vod_name'] = m.group(1).strip()

        # 封面图 (多级回退, 加密图片需走代理)
        m = self._RE_DETAIL_PIC.search(html)
        if not m:
            m = self._RE_DETAIL_PIC2.search(html)
        if not m:
            m = self._RE_DETAIL_PIC3.search(html)
        if m:
            vod['vod_pic'] = self._proxy_img_url(self._abs_url(m.group(1).strip()))

        # 简介
        m = self._RE_DETAIL_DESC.search(html)
        if m:
            desc = re.sub(r'<[^>]+>', '', m.group(1))
            vod['vod_content'] = desc.strip()

        # 解析剧集列表: 只保留免费剧集 (付费剧集无m3u8, 播放会卡退)
        # 免费剧集: href="/play/{slug}/{cid}" data-ep="{N}"
        # 付费剧集: href="javascript:;" data-ep="{N}" data-playlet-slug="{slug}" data-chapter-id="{cid}"
        #         -> 跳过, 因为付费播放页无m3u8 (data-can-watch="0")
        ep_data = []  # [(play_path, ep_num), ...]

        for play_path, ep_num in self._RE_EPISODE_FREE.findall(html):
            ep_data.append((play_path, ep_num))

        play_from_list = []
        play_url_list = []

        if ep_data:
            seen = set()
            cleaned_eps = []
            for ep_path, ep_num in ep_data:
                if ep_path in seen:
                    continue
                seen.add(ep_path)
                cleaned_eps.append((ep_path, ep_num))

            cleaned_eps.sort(key=lambda x: int(x[1]) if str(x[1]).isdigit() else 999999)

            ep_list = []
            for ep_path, ep_num in cleaned_eps:
                ep_url = '/play/%s' % ep_path
                ep_list.append('第%s集$%s' % (ep_num, ep_url))

            if ep_list:
                play_from_list.append('AI爽剧网')
                play_url_list.append('#'.join(ep_list))
        else:
            # 无剧集信息时回退单集
            ep_list = ['第1集$/play/%s/1' % vid]
            play_from_list.append('AI爽剧网')
            play_url_list.append('#'.join(ep_list))

        vod['vod_play_from'] = '$$$'.join(play_from_list)
        vod['vod_play_url'] = '$$$'.join(play_url_list)
        return {'list': [vod]}

    # ==================== 搜索 ====================

    def searchContent(self, key, quick):
        encoded_key = quote(key)
        url = '%s/search/%s' % (self.HOST, encoded_key)
        print(f"[AI爽剧网] 搜索URL: {url}")
        html = self._fetch(url)
        if not html:
            return {'list': []}
        videos = self._parse_video_list(html)
        return {'list': [v for v in videos if v.get('vod_name')]}

    # ==================== 播放 ====================

    def playerContent(self, flag, id, vipFlags):
        """
        直接提取 m3u8 地址 (parse=0), 无需嗅探, 播放秒开。
        
        提取顺序:
          1. JSON-LD contentUrl (完整URL, 最可靠)
          2. DPlayer data-url (相对路径, 拼接CDN前缀)
          3. 回退 parse=1 嗅探 (兜底)
        """
        if id.startswith('http'):
            play_url = id
        else:
            play_url = self.HOST + (id if id.startswith('/') else '/' + id)

        print(f"[AI爽剧网] 播放页URL: {play_url}")
        html = self._fetch(play_url)

        m3u8_url = ''

        # 优先: JSON-LD contentUrl (完整URL, 最可靠)
        if html:
            m = self._RE_M3U8_JSONLD.search(html)
            if m:
                m3u8_url = _html.unescape(m.group(1).strip())

        # 次选: DPlayer data-url (可能是相对路径, 需拼接CDN, 需解码HTML实体)
        if not m3u8_url and html:
            m = self._RE_M3U8_DATA.search(html)
            if m:
                raw = _html.unescape(m.group(1).strip())
                if raw.startswith('http'):
                    m3u8_url = raw
                else:
                    m3u8_url = self.M3U8_CDN + raw

        header = {
            'User-Agent': self.HEADERS['User-Agent'],
            'Referer': self.HOST + '/',
        }

        if m3u8_url:
            # 直接播放 m3u8, 无需嗅探
            return {
                'parse': 0,
                'playUrl': '',
                'url': m3u8_url,
                'header': json.dumps(header),
            }
        else:
            # m3u8提取失败 (可能是付费集), 不回退嗅探避免卡退
            # 返回空URL, 播放器会提示无法播放
            print(f"[AI爽剧网] m3u8提取失败, 可能是付费集: {play_url}")
            return {
                'parse': 0,
                'playUrl': '',
                'url': '',
                'header': json.dumps(header),
            }

    def localProxy(self, params):
        """
        本地代理: 解密加密图片
        网站图片经过 XOR 加密 (前100字节, 密钥: 2019ysapp7527)
        需要通过本地代理解密后返回给播放器/列表显示
        """
        # params 可能是 dict 或 str
        if isinstance(params, str):
            from urllib.parse import parse_qs
            parsed = parse_qs(params)
            do = parsed.get('do', [''])[0]
            img_url = parsed.get('url', [''])[0]
        else:
            do = params.get('do', '')
            img_url = params.get('url', '')

        if do != 'img':
            return None

        # URL可能已解码或仍编码, 双重处理
        if img_url and '%' in img_url:
            img_url = unquote(img_url)

        if not img_url:
            return None

        try:
            data = self._fetch_img(img_url)
            if data:
                return {
                    'response': {
                        'body': data,
                        'headers': {
                            'Content-Type': 'image/jpeg',
                            'Access-Control-Allow-Origin': '*',
                            'Cache-Control': 'max-age=86400',
                        },
                        'what': 'binary',
                    }
                }
        except Exception as e:
            print(f"[AI爽剧网] 图片代理失败: {img_url}, 错误: {str(e)}")

        return None
