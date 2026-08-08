# -*- coding: utf-8 -*-
import html as html_lib
import re
import urllib.parse
import requests

try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider:
        pass


class Spider(BaseSpider):
    BASE_URL = "https://jable.sbs"
    FALLBACK_URLS = ["https://jable.sbs", "https://jable.tv"]
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": BASE_URL + "/",
    }
    TIMEOUT = 15

    def __init__(self):
        super().__init__()
        self.name = "JableTV"
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._class_cache = None

    # ---------- TVBox 标准接口 ----------

    def init(self, extend="{}"):
        return None

    def getName(self):
        return self.name

    def description(self):
        return self.name

    def isVideoFormat(self, url):
        return ".m3u8" in (url or "") or ".mp4" in (url or "")

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return [404, "text/plain", "Not Found"]

    def homeContent(self, filter):
        html = self._fetch(self.BASE_URL + "/latest-updates/")
        result = self._list_result(html, 1)
        result["class"] = self._classes()
        return result

    def homeVideoContent(self):
        return {"list": self._parse_list(self._fetch(self.BASE_URL + "/latest-updates/") or "")}

    def categoryContent(self, tid, pg, filter, extend):
        page = self._to_int(pg, 1)
        path = str(tid or "latest-updates").strip("/")

        # 主题&标签：返回文件夹列表
        if path == "categories":
            return self._categories_folder()

        url = self._page_url(path, page)
        html = self._fetch(url)
        if not html or self._is_gate(html):
            return {"page": page, "pagecount": 0, "limit": 24, "total": 0, "list": []}
        return self._list_result(html, page)

    def detailContent(self, ids):
        result = {"list": [], "parse": 0, "jx": 0}
        value = ids[0] if isinstance(ids, list) and ids else ids
        if not value:
            return result
        url = self._absolute(str(value)) if not str(value).startswith("http") else self._fix_url(str(value))
        page = self._fetch(url)
        if not page or self._is_gate(page):
            return result

        title = self._first(page, r'<section[^>]+class=["\'][^"\']*video-info[^"\']*["\'][^>]*>.*?<h4[^>]*>(.*?)</h4>')
        title = self._clean(title) or self._clean(self._first(page, r'<h4[^>]*>(.*?)</h4>'))
        title = title or self._clean(self._first(page, r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)'))
        title = title or self._clean(self._first(page, r'<title[^>]*>(.*?)</title>').split("-")[0])

        pic = self._first(page, r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)')
        pic = pic or self._first(page, r'<video[^>]+poster=["\']([^"\']+)')
        pic = pic or self._first(page, r'<img[^>]+(?:data-src|src)=["\']([^"\']+)')

        tags = ",".join([self._clean(x) for x in re.findall(r'<a[^>]+href=["\'][^"\']*/tags/[^"\']+["\'][^>]*>(.*?)</a>', page, re.S)])
        actor = re.findall(r'<a[^>]+class=["\'][^"\']*model[^"\']*["\'][^>]*>.*?<span[^>]+(?:title|data-original-title)=["\']([^"\']+)', page, re.S | re.I)
        actor = ",".join(dict.fromkeys(self._clean(x) for x in actor if self._clean(x))) or tags

        publish = self._clean(self._first(page, r'上市于\s*([^<]+)'))
        remarks = self._clean(" ".join(re.findall(r'<h6[^>]*>(.*?)</h6>', page, re.S)[:3]))
        content = self._clean(self._first(page, r'<div[^>]+class=["\'][^"\']*(?:description|info|text)[^"\']*["\'][^>]*>(.*?)</div>')) or remarks or title

        m3u8 = self._m3u8(page)
        result["list"].append({
            "vod_id": url,
            "vod_name": title or url.rstrip("/").split("/")[-1],
            "vod_pic": self._absolute(pic),
            "type_name": tags,
            "vod_year": publish,
            "vod_area": "日本",
            "vod_remarks": remarks,
            "vod_actor": actor,
            "vod_director": "",
            "vod_content": content,
            "vod_play_from": "Jable",
            "vod_play_url": "正片$" + (m3u8 or url),
        })
        return result

    def searchContent(self, key, quick, pg="1"):
        page = self._to_int(pg, 1)
        q = urllib.parse.quote(str(key or ""))
        url = f"{self.BASE_URL}/search/?q={q}"
        if page > 1:
            url += f"&page={page}"
        return self._list_result(self._fetch(url), page)

    def playerContent(self, flag, id, vipFlags):
        result = {"parse": 0, "playUrl": "", "url": id or "", "jx": 0,
                  "header": {"User-Agent": self.HEADERS["User-Agent"], "Referer": self.BASE_URL + "/"}}
        value = str(id or "")
        if not value:
            return result
        if self.isVideoFormat(value):
            return result
        play_page = self._absolute(value) if not value.startswith("http") else self._fix_url(value)
        page = self._fetch(play_page)
        m3u8 = self._m3u8(page)
        if m3u8:
            result["url"] = m3u8
            result["header"] = {"User-Agent": self.HEADERS["User-Agent"], "Referer": play_page, "Origin": self.BASE_URL}
        else:
            result["url"] = play_page
            result["parse"] = 1
        return result

    # ---------- 分类 ----------

    def _classes(self):
        if self._class_cache:
            return self._class_cache
        self._class_cache = [
            {"type_id": "latest-updates", "type_name": "最近更新"},
            {"type_id": "hot", "type_name": "热门影片"},
            {"type_id": "categories/chinese-subtitle", "type_name": "中文字幕"},
            {"type_id": "new-release", "type_name": "全新上市"},
            {"type_id": "categories", "type_name": "主题&标签"},
        ]
        return self._class_cache

    def _categories_folder(self):
        """返回主题分类和标签列表作为文件夹"""
        result = {"list": [], "page": 1, "pagecount": 1, "limit": 200, "total": 200}

        cat_html = self._fetch(self.BASE_URL + "/categories/")
        if cat_html and not self._is_gate(cat_html):
            for m in re.finditer(
                r'<a[^>]*href=["\'](?:https?://jable\.(?:sbs|tv))?(/categories/([^"\']+))["\'][^>]*>'
                r'([\s\S]*?)</a>',
                cat_html, re.I | re.S
            ):
                cat_path = m.group(1).strip("/")
                block = m.group(3)
                pic = ""
                img_m = re.search(r'<img[^>]*src=["\']([^"\']+)["\']', block, re.I)
                if img_m:
                    pic = img_m.group(1)
                    if pic.startswith("//"):
                        pic = "https:" + pic
                name = ""
                count = ""
                center = re.search(r'<div[^>]*class=["\'][^"\']*absolute-center[^"\']*["\'][^>]*>(.*?)</div>', block, re.I | re.S)
                if center:
                    center_text = center.group(1)
                    name = re.sub(r'<small[^>]*>.*?</small>', '', center_text, flags=re.I).strip()
                    cnt_m = re.search(r'<small[^>]*>\s*([\d,]+)\s*(?:部|个)?\s*</small>', center_text, re.I)
                    if cnt_m:
                        count = cnt_m.group(1) + "部"
                if not name:
                    name = self._clean(m.group(4) if m.lastindex >= 4 else "")
                if name:
                    result["list"].append({
                        "vod_id": cat_path,
                        "vod_name": self._clean(name),
                        "vod_pic": pic,
                        "vod_remarks": count or "主题",
                        "vod_tag": "folder",
                        "style": {"type": "rect", "ratio": 1.4}
                    })

        # 兜底：静态主题数据（网络抓取失败或站点改版时使用）
        if not any(item["vod_id"].startswith("categories/") for item in result["list"]):
            static_cats = [
                ("categories/chinese-subtitle", "中文字幕",
                 "https://imgcdn18.piccdn1.cfd/assets-cdn.jable.tv/contents/categories/12/s1_chinese-subtitle.jpg", "20843部"),
                ("categories/roleplay", "角色剧情",
                 "https://imgcdn18.piccdn1.cfd/assets-cdn.jable.tv/contents/categories/9/s1_roleplay.jpg", "31733部"),
                ("categories/uniform", "制服诱惑",
                 "https://imgcdn18.piccdn1.cfd/assets-cdn.jable.tv/contents/categories/10/s1_uniform.jpg", "11883部"),
                ("categories/pantyhose", "丝袜美腿",
                 "https://imgcdn18.piccdn1.cfd/assets-cdn.jable.tv/contents/categories/3/s1_pantyhose.jpg", "7126部"),
                ("categories/bdsm", "主奴调教",
                 "https://imgcdn18.piccdn1.cfd/assets-cdn.jable.tv/contents/categories/14/s1_sm.jpg", "5312部"),
                ("categories/sex-only", "直接开啪",
                 "https://imgcdn18.piccdn1.cfd/assets-cdn.jable.tv/contents/categories/13/s1_sex-only.jpg", "6516部"),
                ("categories/insult", "凌辱快感",
                 "https://imgcdn18.piccdn1.cfd/assets-cdn.jable.tv/contents/categories/11/s1_rape.jpg", "3538部"),
                ("categories/pov", "男友视角",
                 "https://imgcdn18.piccdn1.cfd/assets-cdn.jable.tv/contents/categories/5/s1_pov.jpg", "4063部"),
                ("categories/groupsex", "多P群交",
                 "https://imgcdn18.piccdn1.cfd/assets-cdn.jable.tv/contents/categories/4/s1_groupsex.jpg", "5406部"),
                ("categories/lesbian", "女同欢愉",
                 "https://imgcdn18.piccdn1.cfd/assets-cdn.jable.tv/contents/categories/2/s1_lesbian.jpg", "425部"),
                ("categories/uncensored", "无码解放",
                 "https://imgcdn18.piccdn1.cfd/assets-cdn.jable.tv/contents/categories/6/s1_uncensored.jpg", "266部"),
                ("categories/private-cam", "盗摄偷拍",
                 "https://imgcdn18.piccdn1.cfd/assets-cdn.jable.tv/contents/categories/8/s1_s1_private-cam.jpg", "520部"),
            ]
            for cid, cname, cpic, ccount in static_cats:
                result["list"].append({
                    "vod_id": cid,
                    "vod_name": cname,
                    "vod_pic": cpic,
                    "vod_remarks": ccount,
                    "vod_tag": "folder",
                    "style": {"type": "rect", "ratio": 1.4}
                })

        # 追加标签列表
        tags_html = self._fetch(self.BASE_URL + "/latest-updates/")
        if tags_html and not self._is_gate(tags_html):
            seen = set()
            for m in re.finditer(r'href=["\'](?:https?://jable\.(?:sbs|tv))?(/tags/[^"\']+)["\'][^>]*>([^<]+)</a>', tags_html, re.I):
                tag_path = m.group(1).strip("/")
                tag_name = self._clean(m.group(2))
                if tag_path not in seen and tag_name:
                    seen.add(tag_path)
                    result["list"].append({
                        "vod_id": tag_path,
                        "vod_name": tag_name,
                        "vod_pic": "",
                        "vod_remarks": "标签",
                        "vod_tag": "folder",
                        "style": {"type": "rect", "ratio": 1}
                    })

        return result

    # ---------- 列表解析 ----------

    def _list_result(self, page, number):
        data = self._parse_list(page or "") if page and not self._is_gate(page) else []
        count = self._page_count(page or "")
        return {"page": number, "pagecount": max(count, number if len(data) >= 10 else number),
                "limit": 24, "total": count * 24 if count else 99999, "list": data, "parse": 0, "jx": 0}

    def _parse_list(self, page):
        result, seen = [], set()

        # 优先按新版 Bootstrap 卡片结构解析
        cards = re.findall(
            r'<div[^>]+class=["\'][^"\']*\bcol-6\b[^"\']*\bcol-sm-4\b[^"\']*["\'][^>]*>.*?(?=<div[^>]+class=["\'][^"\']*\bcol-6\b[^"\']*\bcol-sm-4\b|</section>)',
            page or "", re.S | re.I,
        )
        if cards:
            for card in cards:
                links = re.findall(r'<a[^>]+href=["\']([^"\']*/videos/[^"\']+)["\'][^>]*>', card, re.I)
                href = links[-1] if links else ""
                title = self._first(card, r'<h6[^>]*class=["\'][^"\']*title[^"\']*["\'][^>]*>.*?<a[^>]*>(.*?)</a>')
                pic = self._first(card, r'<img[^>]+(?:data-src|data-original|src)=["\']([^"\']+)["\']')
                if "placeholder" in pic:
                    pic = self._first(card, r'data-src=["\']([^"\']+)["\']') or pic
                duration = self._first(card, r'class=["\'][^"\']*absolute-bottom-right[^"\']*["\'][^>]*>.*?(\d+:\d+(?::\d+)?)')
                if not href or not title:
                    continue
                url = self._absolute(href)
                if url in seen:
                    continue
                seen.add(url)
                result.append({"vod_id": url, "vod_name": self._clean(title), "vod_pic": self._absolute(pic), "vod_remarks": duration})
            return result

        # 兜底：旧版结构 / 结构变化时的通用匹配
        fallback_cards = re.findall(r'(<div[^>]+class=["\'][^"\']*video-img-box[^"\']*["\'][\s\S]*?</h6>[\s\S]*?</div>\s*</div>)', page or "", re.S | re.I)
        if not fallback_cards:
            fallback_cards = re.findall(r'(<a[^>]+href=["\'][^"\']*/videos/[^"\']+["\'][\s\S]*?</a>)', page or "", re.S | re.I)
        for item in fallback_cards:
            href = self._first(item, r'href=["\']([^"\']*/videos/[^"\']+)["\']')
            if not href:
                continue
            name = self._clean(self._first(item, r'<h6[^>]*class=["\'][^"\']*title[^"\']*["\'][^>]*>\s*<a[^>]*>(.*?)</a>') or self._first(item, r'title=["\']([^"\']+)') or self._first(item, r'alt=["\']([^"\']+)'))
            pic = self._first(item, r'(?:data-src|data-original|data-lazy-src|data-lazyload)=["\']([^"\']+)') or self._first(item, r'<img[^>]+src=["\']([^"\']+)')
            remarks = self._clean(self._first(item, r'<span[^>]+class=["\'][^"\']*(?:duration|label|badge)[^"\']*["\'][^>]*>(.*?)</span>') or self._first(item, r'(\d{1,2}:\d{2}(?::\d{2})?)'))
            full = self._absolute(href)
            if full not in seen and name and not re.fullmatch(r'\d{1,2}:\d{2}(?::\d{2})?', name):
                seen.add(full)
                result.append({"vod_id": full, "vod_name": name, "vod_pic": self._absolute(pic), "vod_remarks": remarks})
        return result

    def _page_url(self, path, page):
        path = path.strip("/") or "latest-updates"
        if page > 1:
            return f"{self.BASE_URL}/{path}/{page}/"
        return f"{self.BASE_URL}/{path}/"

    def _page_count(self, page_html):
        """从分页链接中提取最大页码"""
        nums = re.findall(r'/latest-updates/(\d+)/', page_html, re.I)
        if not nums:
            nums = re.findall(r'/(?:hot|categories/.+?|tags/.+?|new-release)/(\d+)/', page_html, re.I)
        if not nums:
            nums = re.findall(r'<a[^>]+href=["\'][^"\']*/(\d+)/["\']', page_html, re.I)
        if nums:
            return max(int(x) for x in nums)
        nums2 = re.findall(r'[?&]page=(\d+)', page_html, re.I)
        if nums2:
            return max(int(x) for x in nums2)
        return 1

    # ---------- 网络请求 ----------

    def _fetch(self, url, headers=None):
        for real in self._candidates(self._fix_url(url)):
            h = dict(self.HEADERS)
            h["Referer"] = self.BASE_URL + "/"
            if headers:
                h.update(headers)
            try:
                r = self.session.get(real, headers=h, timeout=self.TIMEOUT, verify=False)
                r.encoding = "utf-8"
                if r.status_code < 400 and "Just a moment" not in r.text and "cf-browser-verification" not in r.text:
                    return r.text
            except Exception as exc:
                print("[Jable] fetch failed:", real, exc)
                continue
        return ""

    def _candidates(self, url):
        if not url:
            return []
        urls = [url]
        for host in self.FALLBACK_URLS:
            p = urllib.parse.urlparse(url)
            if p.netloc and host not in url:
                urls.append(host + p.path + ("?" + p.query if p.query else ""))
        return list(dict.fromkeys(urls))

    def _fix_url(self, url):
        return str(url or "").replace("https://jable.tv", self.BASE_URL).replace("http://jable.tv", self.BASE_URL).replace("https://www.jable.tv", self.BASE_URL)

    def _absolute(self, value):
        return urllib.parse.urljoin(self.BASE_URL + "/", self._fix_url(value)) if value else ""

    def _is_gate(self, page):
        return "继续访问" in page and ("/enter" in page or "continue-button" in page)

    def _m3u8(self, html):
        return self._first(html, r'var\s+hlsUrl\s*=\s*["\']([^"\']+\.m3u8[^"\']*)') or self._first(html, r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']')

    # ---------- 工具函数 ----------

    def _first(self, text, pattern):
        m = re.search(pattern, text or "", re.S | re.I)
        return m.group(1).strip() if m else ""

    def _clean(self, value):
        value = html_lib.unescape(value or "")
        value = re.sub(r"<[^>]+>", "", value)
        value = value.replace("&nbsp;", " ")
        return re.sub(r"\s+", " ", value).strip()

    def _to_int(self, value, default=0):
        try:
            return int(value)
        except Exception:
            return default
