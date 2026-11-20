#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import re
import json
import base64
import urllib.request
import urllib.parse
from urllib.parse import urlencode, quote, unquote
import http.cookiejar
import gzip
import zlib
import ssl

try:
    from base.spider import Spider as SpiderBase
except ImportError:
    class SpiderBase(object):
        pass


class Spider(SpiderBase):
    def __init__(self):
        super(Spider, self).__init__()
        self.base = "https://tingyou.fm"
        self.api_hosts = [
            "https://appp.fdhtbz.cn/api/h5/listening",
            "https://tingyou.fm/listening-api"
        ]
        self._ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        self.brandActor = "🦋 TG群: @tvshare23"
        self.brandDirector = "🦋 蝴蝶影视"
        self.ref = "https://tingyou.fm/"
        self.options = {}

        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=self.ctx)
        )

        self.block_kw = (
            "幼女", "幼齿", "萝莉", "未成年", "小学生", "中学生", "儿童色情",
            "强奸", "轮奸", "迷奸", "兽交", "人兽"
        )

    def init(self, extend=""):
        if isinstance(extend, dict):
            self.options = extend
        elif extend:
            try:
                self.options = json.loads(extend)
            except Exception:
                self.options = {}
        return True

    def getName(self):
        return "听友听书"

    def isVideoFormat(self, url):
        if not url:
            return False
        return bool(re.search(r"\.(m3u8|mp4|flv|mkv|avi|ts|m4a|mp3|aac)(\?|$)", url, re.I))

    def manualVideoCheck(self):
        return False

    def destroy(self):
        self.options = {}

    def _dict(self, v):
        if isinstance(v, dict):
            return v
        if isinstance(v, (str, bytes)):
            try:
                d = json.loads(v)
                return d if isinstance(d, dict) else {}
            except Exception:
                return {}
        return {}

    def _list(self, v):
        if isinstance(v, (list, tuple)):
            return [str(i) for i in v]
        if isinstance(v, (str, bytes)):
            try:
                d = json.loads(v)
                if isinstance(d, (list, tuple)):
                    return [str(i) for i in d]
            except Exception:
                pass
            return [str(v)]
        return []

    def _blocked(self, text):
        if not text:
            return False
        t = str(text).lower()
        for k in self.block_kw:
            if k in t:
                return True
        return False

    def _pic(self, url):
        if not url:
            return ""
        if url.startswith("//"):
            return "https:" + url
        return url

    def _api_get(self, path, prefer_proxy=False, req_timeout=4):
        hosts = list(self.api_hosts)
        if prefer_proxy:
            hosts = hosts[::-1]

        for host in hosts:
            url = host.rstrip("/") + "/" + path.lstrip("/")
            headers = {
                "User-Agent": self._ua,
                "Referer": self.ref,
                "Origin": self.base,
                "Accept": "application/json, text/plain, */*",
                "Connection": "close"
            }
            try:
                req = urllib.request.Request(url, headers=headers)
                with self.opener.open(req, timeout=req_timeout) as resp:
                    if resp.getcode() != 200:
                        continue
                    raw = resp.read()
                    enc = getattr(resp, "headers", {}).get("Content-Encoding", "")
                    if raw.startswith(b"\x1f\x8b") or enc == "gzip":
                        raw = gzip.decompress(raw)
                    elif enc == "deflate":
                        try:
                            raw = zlib.decompress(raw)
                        except Exception:
                            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                    text = raw.decode("utf-8", errors="ignore").strip()
                    if text and text[0] in "{[":
                        return json.loads(text)
            except Exception:
                continue
        return {}

    def _api_post(self, path, body, req_timeout=5):
        hosts = list(self.api_hosts)
        data_bytes = json.dumps(body).encode("utf-8")

        for host in hosts:
            url = host.rstrip("/") + "/" + path.lstrip("/")
            headers = {
                "User-Agent": self._ua,
                "Referer": self.ref,
                "Origin": self.base,
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Connection": "close"
            }
            try:
                req = urllib.request.Request(url, data=data_bytes, headers=headers)
                with self.opener.open(req, timeout=req_timeout) as resp:
                    if resp.getcode() != 200:
                        continue
                    raw = resp.read()
                    enc = getattr(resp, "headers", {}).get("Content-Encoding", "")
                    if raw.startswith(b"\x1f\x8b") or enc == "gzip":
                        raw = gzip.decompress(raw)
                    elif enc == "deflate":
                        try:
                            raw = zlib.decompress(raw)
                        except Exception:
                            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                    text = raw.decode("utf-8", errors="ignore").strip()
                    if text and text[0] in "{[":
                        return json.loads(text)
            except Exception:
                continue
        return {}

    def homeContent(self, filter=False):
        classes = [
            {"type_name": "全部", "type_id": "all"},
            {"type_name": "有声小说", "type_id": "有声小说"},
            {"type_name": "评书", "type_id": "评书"}
        ]

        sort_filter = {
            "key": "sort",
            "name": "排序",
            "value": [
                {"n": "综合排序", "v": "comprehensive"},
                {"n": "播放最多", "v": "popular"},
                {"n": "最近更新", "v": "updated"},
                {"n": "最新发布", "v": "new"}
            ]
        }

        status_filter = {
            "key": "status",
            "name": "状态",
            "value": [
                {"n": "全部", "v": ""},
                {"n": "连载中", "v": "1"},
                {"n": "已完结", "v": "0"}
            ]
        }

        novel_type_values = [
            {"n": "全部类型", "v": ""},
            {"n": "玄幻奇幻", "v": "46"},
            {"n": "武侠小说", "v": "11"},
            {"n": "言情通俗", "v": "19"},
            {"n": "相声小品", "v": "21"},
            {"n": "恐怖惊悚", "v": "14"},
            {"n": "官场商战", "v": "17"},
            {"n": "历史军事", "v": "15"},
            {"n": "百家讲坛", "v": "9"},
            {"n": "刑侦反腐", "v": "16"},
            {"n": "有声文学", "v": "10"},
            {"n": "人物纪实", "v": "18"},
            {"n": "广播剧", "v": "36"},
            {"n": "英文读物", "v": "22"},
            {"n": "轻音清心", "v": "23"},
            {"n": "二人转", "v": "31"},
            {"n": "健康养生", "v": "33"},
            {"n": "综艺娱乐", "v": "34"},
            {"n": "头条", "v": "40"},
            {"n": "戏曲", "v": "38"},
            {"n": "脱口秀", "v": "41"},
            {"n": "商业财经", "v": "42"},
            {"n": "亲子教育", "v": "43"},
            {"n": "教育培训", "v": "44"},
            {"n": "时尚生活", "v": "45"},
            {"n": "童话寓言", "v": "20"},
            {"n": "未分类", "v": "47"}
        ]

        pingshu_type_values = [
            {"n": "单田芳", "v": "1"},
            {"n": "刘兰芳", "v": "2"},
            {"n": "田连元", "v": "3"},
            {"n": "袁阔成", "v": "4"},
            {"n": "连丽如", "v": "5"},
            {"n": "孙一", "v": "8"},
            {"n": "王子封臣", "v": "30"},
            {"n": "马长辉", "v": "25"},
            {"n": "昊儒书场", "v": "26"},
            {"n": "王军", "v": "27"},
            {"n": "王玥波", "v": "28"},
            {"n": "石连君", "v": "29"},
            {"n": "粤语评书", "v": "12"},
            {"n": "关永超", "v": "35"},
            {"n": "张少佐", "v": "6"},
            {"n": "田战义", "v": "7"},
            {"n": "其他评书", "v": "13"}
        ]

        all_type_values = [{"n": "全部类型", "v": ""}] + [
            item for item in novel_type_values[1:]
        ] + [
            item for item in pingshu_type_values
        ]

        filters = {
            "all": [
                {"key": "type", "name": "类型", "value": all_type_values},
                sort_filter,
                status_filter
            ],
            "有声小说": [
                {"key": "type", "name": "类型", "value": novel_type_values},
                sort_filter,
                status_filter
            ],
            "评书": [
                {"key": "type", "name": "名家", "value": pingshu_type_values, "init": "1"},
                sort_filter,
                status_filter
            ]
        }

        return {
            "class": classes,
            "filters": filters,
            "list": []
        }

    def homeVideoContent(self):
        return self._list_page(cat="", sub_type="", sort="popular", page=1, status="")

    def categoryContent(self, tid, pg, filter=False, extend=None, *args, **kwargs):
        try:
            page_num = max(1, int(str(pg).strip() or 1))
        except Exception:
            page_num = 1

        f = {}
        ff = self._dict(filter)
        if ff:
            f.update(ff)
        fe = self._dict(extend)
        if fe:
            f.update(fe)

        for k in ("extend", "ext", "filter"):
            if k in kwargs:
                f.update(self._dict(kwargs.get(k)))

        raw_tid = str(tid).strip()
        cat = "" if raw_tid == "all" else raw_tid
        sub_type = str(f.get("type") or "").strip()
        sort_by = str(f.get("sort") or "comprehensive").strip()
        status_val = str(f.get("status") or "").strip()

        if cat == "评书" and not sub_type:
            sub_type = "1"

        return self._list_page(cat=cat, sub_type=sub_type, sort=sort_by, page=page_num, status=status_val)

    def _list_page(self, cat="", sub_type="", sort="comprehensive", page=1, status=""):
        params = {
            "sort": sort or "comprehensive",
            "page": str(page)
        }
        if cat:
            params["cat"] = cat
        if sub_type:
            params["type"] = sub_type
        if status != "" and status is not None:
            params["status"] = str(status)

        qs = urlencode(params)
        data = self._api_get("category?" + qs, req_timeout=5)

        items = []
        pagecount = 1
        if isinstance(data, dict):
            try:
                pagecount = int(data.get("pages") or 1)
            except Exception:
                pagecount = 1

            for it in (data.get("data") or []):
                if not isinstance(it, dict):
                    continue
                name = str(it.get("title") or "").strip()
                if not name or self._blocked(name):
                    continue
                vid = str(it.get("id") or "")
                if not vid:
                    continue
                pic = str(it.get("cover_url") or "")
                st = it.get("status")
                cnt = it.get("count") or 0
                remarks = ""
                if st == 1:
                    remarks = "连载中"
                elif st == 0:
                    remarks = "已完结"
                if cnt:
                    remarks = (remarks + " · " if remarks else "") + "%s集" % cnt

                clean_remarks = remarks.strip()
                final_remarks = "蝴蝶影视 | %s" % clean_remarks if clean_remarks else "蝴蝶影视"

                items.append({
                    "vod_id": vid,
                    "vod_name": name[:80],
                    "vod_pic": self._pic(pic),
                    "vod_remarks": final_remarks,
                    "style": {"type": "rect", "ratio": 0.75}
                })

        final_pagecount = max(pagecount, 1)
        total_count = int(page * len(items) + 100) if items else 0

        return {
            "page": int(page),
            "pagecount": final_pagecount,
            "limit": 20,
            "total": total_count,
            "list": items
        }

    def detailContent(self, ids):
        raw_ids = self._list(ids)
        vid = raw_ids[0] if raw_ids else ""
        if not vid:
            return {"list": []}

        album = self._api_get("album/" + vid, req_timeout=3)
        if not isinstance(album, dict) or not album.get("id"):
            album = self._api_get("album/" + vid, prefer_proxy=True, req_timeout=3)
        if not isinstance(album, dict) or not album.get("id"):
            return {"list": []}

        title = str(album.get("title") or "").strip()
        if self._blocked(title):
            return {"list": []}

        author = str(album.get("author") or "").strip()
        teller = str(album.get("teller") or "").strip()
        pic = str(album.get("cover_url") or "")
        synopsis = str(album.get("synopsis") or "").strip()
        typ = str(album.get("type") or "")
        cat = str(album.get("cat") or "")
        cnt = album.get("count") or 0
        try:
            total_count = int(cnt)
        except Exception:
            total_count = 0

        st = album.get("status")
        status_txt = "连载中" if st == 1 else ("已完结" if st == 0 else "")
        type_name = "/".join([x for x in (typ, cat) if x])

        chapters = []
        if total_count <= 400:
            chapters = self._fetch_chapters(vid)

        play_urls = []
        if chapters:
            for ch in chapters:
                idx = ch.get("index") or 0
                ctitle = str(ch.get("title") or ("第%s集" % idx)).strip()
                clean_ctitle = re.sub(r"[\$\#\r\n\t]+", " ", ctitle).strip()
                if not clean_ctitle:
                    clean_ctitle = "第%s集" % idx
                play_urls.append("%s$%s_%s" % (clean_ctitle, vid, idx))
        else:
            limit_n = max(total_count, 1)
            if limit_n > 5000:
                limit_n = 5000
            for idx in range(1, limit_n + 1):
                play_urls.append("第%d集$%s_%d" % (idx, vid, idx))

        play_url = "#".join(play_urls)

        actor = teller
        if author and author != teller:
            actor = ("%s / %s" % (author, teller)) if teller else author
        for sep in ("_免费听书", "|免费", "免费收听"):
            if sep in actor:
                actor = actor.split(sep)[0].strip()

        group_info = "【🔥 官方交流群: %s】" % self.brandActor
        custom_notice = "【💡 听友听书专线加速播放，极速音质。】"
        if synopsis:
            full_content = "%s\n\n%s\n\n%s" % (group_info, custom_notice, synopsis)
        else:
            full_content = "%s\n\n%s\n\n暂无详细简介。" % (group_info, custom_notice)

        remarks_meta = (status_txt + (" · %s集" % total_count if total_count else "")).strip(" ·")
        final_remarks = "蝴蝶影视 · %s" % remarks_meta if remarks_meta else "蝴蝶影视"

        vod = {
            "vod_id": vid,
            "vod_name": title[:100],
            "vod_pic": self._pic(pic),
            "type_name": type_name[:40],
            "vod_remarks": final_remarks,
            "vod_actor": "%s | %s" % (actor[:40], self.brandActor) if actor else self.brandActor,
            "vod_director": self.brandDirector,
            "vod_content": full_content,
            "vod_play_from": "听友专线",
            "vod_play_url": play_url
        }
        return {"list": [vod]}

    def _fetch_chapters(self, album_id):
        data = self._api_get("chapters/" + str(album_id), prefer_proxy=True, req_timeout=2)
        chs = []
        if isinstance(data, dict):
            for c in (data.get("chapters") or []):
                if not isinstance(c, dict):
                    continue
                idx = c.get("index")
                if idx is None:
                    continue
                chs.append({
                    "id": c.get("id"),
                    "index": int(idx),
                    "title": str(c.get("title") or ("第%s集" % idx)),
                    "duration": c.get("duration") or 0
                })
        chs.sort(key=lambda x: x["index"])
        return chs

    def searchContent(self, key, quick, pg="1"):
        try:
            page_num = max(1, int(str(pg).strip() or 1))
        except Exception:
            page_num = 1

        if not key or self._blocked(key):
            return {"list": [], "page": page_num, "pagecount": 1, "limit": 20, "total": 0}

        body = {"keyword": key, "page": page_num}
        data = self._api_post("search", body, req_timeout=5)

        items = []
        has_more = False
        if isinstance(data, dict):
            has_more = bool(data.get("has_more"))
            for it in (data.get("results") or data.get("data") or []):
                if not isinstance(it, dict):
                    continue
                name = str(it.get("title") or "").strip()
                if not name or self._blocked(name):
                    continue
                vid = str(it.get("id") or "")
                if not vid:
                    continue
                pic = str(it.get("cover_url") or "")
                st = it.get("status")
                cnt = it.get("count") or 0
                remarks = ""
                if st == 1:
                    remarks = "连载中"
                elif st == 0:
                    remarks = "已完结"
                if cnt:
                    remarks = (remarks + " · " if remarks else "") + "%s集" % cnt

                clean_remarks = remarks.strip()
                final_remarks = "蝴蝶影视 | %s" % clean_remarks if clean_remarks else "蝴蝶影视"

                items.append({
                    "vod_id": vid,
                    "vod_name": name[:80],
                    "vod_pic": self._pic(pic),
                    "vod_remarks": final_remarks,
                    "style": {"type": "rect", "ratio": 0.75}
                })

        final_pagecount = int(page_num + 1) if has_more else int(page_num)
        total_items = int(page_num * len(items) + 100) if items else 0

        return {
            "page": int(page_num),
            "pagecount": final_pagecount,
            "limit": 20,
            "total": total_items,
            "list": items
        }

    def playerContent(self, flag, id, vipFlags):
        parse, url = 0, ""
        try:
            raw_id = str(id).strip()
            parts = raw_id.rsplit("_", 1)
            if len(parts) == 2:
                album_id, chapter_idx = parts[0], int(parts[1])
            else:
                album_id, chapter_idx = raw_id, 1

            body = {"album_id": str(album_id), "chapter_idx": int(chapter_idx)}
            data = self._api_post("play", body, req_timeout=6)
            if isinstance(data, dict):
                play_url = str(data.get("play_url") or "").strip()
                if play_url.startswith("http"):
                    url = play_url
                    parse = 0
        except Exception:
            pass

        if not url:
            parse = 1
            url = "%s/listening/album/%s" % (self.base, str(id).split("_")[0])

        headers = {
            "User-Agent": self._ua,
            "Referer": self.ref,
            "Origin": self.base
        }
        return {
            "parse": parse,
            "playUrl": "",
            "url": url,
            "header": headers
        }

    def localProxy(self, param):
        return [404, "text/plain; charset=utf-8", "Proxy not configured"]
