# -*- coding: utf-8 -*-
# ============================================================
#  海角社区 TVBox 爬虫（奈非工厂形态 · 标准 catvod Spider）
#  目标站: https://haijiao.com  (Vue SPA + API)
#
#  播放链路（关键设计）:
#    - playerContent 返回本地代理 m3u8 URL + Referer header
#    - 本地代理只做两件事:
#        1) m3u8: 抓原 m3u8 → 把 URI="enc_xxx.key" 重写为本地代理 key URL
#                  → 分片保留 CDN 原 URL（直连, 不经代理）
#        2) key : 抓 enc key 文件 → XOR 静态种子 → 返回真实 16B AES key
#    - 播放器(ExoPlayer/IJK)原生 AES-128-CBC 解密分片, 无需 cryptography
#
#  零第三方解密依赖: 仅 requests + 标准库
# ============================================================
import sys, re, json, base64, threading, time
from urllib.parse import quote, unquote, urljoin
try:
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider: pass
try:
    import requests
except ImportError:
    requests = None

H = "https://haijiao.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"

# ---------- 账号(可选, 用于解锁需登录的视频) ----------
# 部分视频(如"海角视频"分类) remoteUrl 为空, 需登录后调 /api/attachment 换真实流
HJ_USER = "anyitu"
HJ_PASS = "qwer1234"

# ---------- 海角加密常量 ----------
# 种子 = m3u8 URL 换 .jpg 后缀取到的内容（base64 文本, 全站静态, 硬编码避免每视频抓取）
SEED_B64 = "bW9uZ29kYjovL2FkbWluOlMzY1VyM19QNHNzXzIwMjZANi45MC4xMC4xOToyNzAxNy9hdXRo"

# 短视频分类 特殊 id（走全站视频流 type=7&nodeId=0）
SHORT_VID = "__short__"


class Spider(BaseSpider):
    def init(self, e=""):
        self.host = H
        self.headers = self._build_headers()
        self.session = requests.Session() if requests else None
        if self.session:
            self.session.headers.update(self.headers)
        self.cache = {}
        self._proxy_started = False
        self.proxy_port = 0
        self._login_done = False
        self.auth_headers = {}
        self._start_proxy()
        # 自动登录 (获取 X-User-Token / X-User-Id, 用于解锁需认证的视频)
        if HJ_USER and HJ_PASS:
            self._login()

    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self.init()

    # ---------- 基础 ----------

    def getName(self):
        return "海角社区"

    def isVideoFormat(self, url):
        return ".m3u8" in url or ".mp4" in url

    def manualVideoCheck(self):
        return False

    def _build_headers(self, referer=None):
        return {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": referer or H + "/",
            "Origin": H,
        }

    def _login(self):
        """登录海角社区, 拿 X-User-Token/X-User-Id, 用于解锁需认证的视频"""
        try:
            r = self.session.post(self.host + "/api/login/signin",
                                  json={"username": HJ_USER, "password": HJ_PASS},
                                  headers=self.headers, timeout=15)
            if r.status_code != 200:
                return False
            d = r.json()
            if not d.get("isEncrypted"):
                return False
            dec = json.loads(base64.b64decode(base64.b64decode(base64.b64decode(d["data"]))))
            token = dec.get("token") or ""
            uid = (dec.get("user") or {}).get("id") or ""
            if token and uid:
                self.auth_headers = dict(self.headers)
                self.auth_headers["X-User-Token"] = str(token)
                self.auth_headers["X-User-Id"] = str(uid)
                self.auth_headers["pcVer"] = "2"
                self._login_done = True
                return True
        except Exception:
            pass
        return False

    def _get_real_remoteUrl(self, att_id, topic_id):
        """对空 remoteUrl 的视频, 调 /api/attachment 换真实 remoteUrl (需登录)"""
        try:
            if not self._login_done:
                self._login()
            if not self.auth_headers:
                return ""
            body = {"id": int(att_id), "resource_id": int(topic_id),
                    "resource_type": "topic", "line": ""}
            r = self.session.post(self.host + "/api/attachment",
                                  json=body, headers=self.auth_headers, timeout=15)
            if r.status_code != 200:
                return ""
            d = r.json()
            if not d.get("isEncrypted"):
                return ""
            dec = json.loads(base64.b64decode(base64.b64decode(base64.b64decode(d["data"]))))
            return (dec.get("remoteUrl") or "") if isinstance(dec, dict) else ""
        except Exception:
            return ""

    # ---------- 海角 API 工具 ----------

    @staticmethod
    def bare_decode(text):
        """JSON.parse(atob(atob(atob(text))))"""
        try:
            t = base64.b64decode(base64.b64decode(base64.b64decode(text)))
            return json.loads(t)
        except Exception:
            return None

    def _api_get(self, path, params=None):
        """GET API 并自动解密"""
        try:
            res = self.session.get(self.host + path, params=params, headers=self.headers, timeout=15)
            data = res.json()
            if data.get("isEncrypted") and data.get("data"):
                dec = self.bare_decode(data["data"])
                if dec is not None:
                    return dec
            return data.get("data") if "data" in data else data
        except Exception:
            return None

    # ---------- 列表解析 ----------

    def _fix_pic(self, url):
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = self.host + url
        return url

    def _clean_title(self, raw):
        if not raw:
            return "未知标题"
        text = re.sub(r"<[^>]+>", "", str(raw))
        text = re.sub(r"\[door\]\d+\[/door\]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text or "未知标题"

    def _topics_to_videos(self, results, only_video=False):
        videos = []
        for r in results or []:
            try:
                if not r.get("title"):
                    continue
                # only_video=True 时只保留 hasVideo 条目（视频才算）
                if only_video and not r.get("hasVideo"):
                    continue
                pic = ""
                for a in (r.get("attachments") or []):
                    if a.get("category") == "images" and a.get("remoteUrl"):
                        pic = a["remoteUrl"]
                        break
                if not pic:
                    pic = H + "/images/common/project/favicon.ico"
                remark = ""
                if r.get("money_type") == 2:
                    remark = "💰付费"
                elif r.get("hasVideo"):
                    remark = "🎬视频"
                if r.get("is_original"):
                    remark = (remark + "原创") if remark else "原创"
                videos.append({
                    "vod_id": str(r.get("topicId", "")),
                    "vod_name": self._clean_title(r.get("title", "")),
                    "vod_pic": self._fix_pic(pic),
                    "vod_remarks": remark or r.get("viewCountStr") or "",
                })
            except Exception:
                continue
        return videos

    # ---------- 播放地址提取 ----------

    def _find_video_attachment(self, detail):
        """从详情取 video attachment, 返回 remoteUrl 或 attachment id (前端调 /api/attachment 拿真实流)"""
        for a in (detail.get("attachments") or []):
            if a.get("category") == "video":
                ru = a.get("remoteUrl") or ""
                if ru:
                    return ru
                if a.get("id"):
                    return a["id"]
        return ""

    def _derive_full_m3u8(self, preview_url, topic_id=None):
        """预览流 → 完整流: 分片 xxx_i0.ts → xxx_i.m3u8
        支持前端调 /api/attachment 拿真实 remoteUrl 后推导"""
        try:
            if not preview_url:
                return ""
            # 如果是 attachment id (数字), 走 /api/attachment 拿真实 remoteUrl
            if isinstance(preview_url, str) and preview_url.isdigit():
                try:
                    body={"id":preview_url,"resource_id":topic_id,"resource_type":"topic","line":""}
                    r=self.session.post(self.host+"/api/attachment", json=body, headers=self.headers, timeout=15)
                    if r.status_code==200:
                        d=r.json()
                        if d.get("isEncrypted"):
                            dec=json.loads(base64.b64decode(base64.b64decode(base64.b64decode(d["data"]))))
                            # 结构可能是 list 或 dict
                            if isinstance(dec, list):
                                for ln in dec:
                                    u=(ln.get("url") or "")
                                    if u: return u
                            ru=(dec.get("remoteUrl") if isinstance(dec,dict) else "") or ""
                            if ru and ".m3u8" in ru:
                                return ru
                except Exception:
                    pass
            # 正常 preview 流
            res = self.session.get(preview_url, headers=self.headers, timeout=15)
            text = res.text
            if "#EXTM3U" not in text:
                return ""
            for line in text.splitlines():
                s = line.strip()
                if s and not s.startswith("#") and ".ts" in s.lower():
                    ts_name = s.split("?")[0].split("/")[-1]
                    m = re.match(r"^(.*?)(\d+)\.ts$", ts_name, re.I)
                    if m:
                        base = preview_url[:preview_url.rfind("/") + 1]
                        return base + m.group(1) + ".m3u8"
                    break
        except Exception:
            pass
        return ""

    def _decrypt_key(self, key_bytes, m3u8_url=None):
        """key 文件 XOR 种子前16字节 → 真实 AES key
        种子优先动态抓取（m3u8 换 .jpg，userscript 同款），失败回退硬编码 SEED_B64
        """
        try:
            seed = self._load_seed(m3u8_url)
            return bytes(a ^ b for a, b in zip(key_bytes[:16], seed[:16]))
        except Exception:
            return key_bytes

    def _load_seed(self, m3u8_url=None):
        """动态种子：m3u8 换 .jpg 后缀 → 内容 base64 解码；失败用硬编码兜底"""
        try:
            if m3u8_url and ".m3u8" in m3u8_url:
                jpg_url = re.sub(r"\.m3u8(\?.*)?$", ".jpg", m3u8_url)
                r = self.session.get(jpg_url, headers=self.headers, timeout=15)
                text = r.text.strip()
                if len(text) >= 16:
                    try:
                        return base64.b64decode(text)[:16]
                    except Exception:
                        return text.encode("utf-8", "ignore")[:16]
        except Exception:
            pass
        return base64.b64decode(SEED_B64)[:16]

    # ---------- m3u8 清洗（海角专用） ----------
    # 分片 1-1.25s（短视频站）不能按时长判广告; 附件 ID 随机串(如 lgFCG2AD)含 "ad"
    # 子串, 不能裸词匹配。仅精确关键词过滤 + 开头 12 段主源判定。
    AD_HJ = ["advert", "preroll", "片头", "广告", "/gg/", "banner", "promo", "casino", "博彩", "充值", "_ad.", "/ad/"]

    def _clean_m3u8_hj(self, text, m3u8_url):
        lines = text.splitlines()
        header_lines = []
        segments = []
        current_seg = None
        seq = 0
        target = 3.0
        for line in lines:
            s = line.strip()
            if s.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                seq = int(s.split(":")[1])
            elif s.startswith("#EXT-X-TARGETDURATION:"):
                try:
                    target = float(s.split(":")[1])
                except Exception:
                    pass
            elif s.startswith("#EXTINF:"):
                current_seg = {"tags": [line], "dur": target, "uri": ""}
                try:
                    current_seg["dur"] = float(re.search(r'#EXTINF:([\d.]+)', line).group(1))
                except Exception:
                    pass
            elif current_seg is not None and not s.startswith("#"):
                current_seg["uri"] = s
                segments.append(current_seg)
                current_seg = None
            elif s.startswith("#EXT-X-ENDLIST"):
                pass
            elif not current_seg:
                header_lines.append(line)
        if not segments:
            return text
        stat = {}
        for seg in segments:
            key = self._segment_key(seg["uri"], m3u8_url)
            stat[key] = stat.get(key, 0.0) + float(seg.get("dur", target))
        main_key = max(stat.items(), key=lambda x: x[1])[0] if stat else ("", "")
        cleaned, removed = [], 0
        for idx, seg in enumerate(segments):
            uri = seg["uri"]
            is_ad = False
            if any(k in uri.lower() for k in self.AD_HJ):
                is_ad = True
            if idx < 12 and self._segment_key(uri, m3u8_url) != main_key:
                is_ad = True
            if is_ad:
                removed += 1
                continue
            cleaned.append(seg)
        out = header_lines[:]
        out.append("#EXT-X-MEDIA-SEQUENCE:%d" % (seq + removed))
        for seg in cleaned:
            out.extend(seg["tags"])
            out.append(seg["uri"])
        out.append("#EXT-X-ENDLIST")
        return "\n".join(out)

    def _segment_key(self, uri, base_url):
        p = urljoin(base_url, uri)
        path = p.split("?")[0]
        slash = path.rfind("/")
        return (p[:p.find("://") + 3], path[:slash] if slash >= 0 else path)

    # ---------- 本地代理（key 替换方案, 零解密库） ----------

    def _start_proxy(self):
        if self._proxy_started:
            return
        from http.server import HTTPServer, BaseHTTPRequestHandler
        from socketserver import ThreadingMixIn
        import socket

        spider = self

        class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
            daemon_threads = True

        class ProxyHandler(BaseHTTPRequestHandler):
            def do_GET(self2):
                try:
                    raw = unquote(self2.path[1:])
                    if not raw.startswith("http"):
                        raw = "http://" + raw
                    path = raw.split("?")[0]
                    if ".m3u8" in path:
                        text = spider._fetch_m3u8(raw)
                        self2.send_response(200)
                        self2.send_header("Content-Type", "application/vnd.apple.mpegurl")
                        self2.send_header("Access-Control-Allow-Origin", "*")
                        self2.end_headers()
                        self2.wfile.write(text.encode("utf-8"))
                    elif ".key" in path or "enc_" in path:
                        key = spider._fetch_key(raw)
                        self2.send_response(200)
                        self2.send_header("Content-Type", "application/octet-stream")
                        self2.send_header("Content-Length", str(len(key)))
                        self2.send_header("Access-Control-Allow-Origin", "*")
                        self2.end_headers()
                        self2.wfile.write(key)
                    else:
                        r = spider.session.get(raw, headers=spider.headers, timeout=20)
                        self2.send_response(200)
                        self2.send_header("Content-Type", r.headers.get("Content-Type", "application/octet-stream"))
                        self2.send_header("Content-Length", str(len(r.content)))
                        self2.send_header("Access-Control-Allow-Origin", "*")
                        self2.end_headers()
                        self2.wfile.write(r.content)
                except Exception:
                    try:
                        self2.send_response(500)
                        self2.end_headers()
                    except Exception:
                        pass

            def log_message(self2, *args):
                pass

        sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
        sk.close()
        server = ThreadedHTTPServer(("127.0.0.1", port), ProxyHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.proxy_port = port
        self._proxy_started = True

    def _proxy_url(self, url):
        return "http://127.0.0.1:%d/%s" % (self.proxy_port, quote(url, safe=""))

    def _fetch_m3u8(self, m3u8_url):
        """抓原 m3u8 → 清洗 → key URI 重写为本地代理 → 分片绝对化直连"""
        res = self.session.get(m3u8_url, headers=self.headers, timeout=20)
        text = res.text
        if "#EXTM3U" not in text:
            return text
        text = self._clean_m3u8_hj(text, m3u8_url)
        out = []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("#EXT-X-KEY:"):
                def rep(m):
                    key_url = urljoin(m3u8_url, m.group(1))
                    return 'URI="%s"' % self._proxy_url(key_url)
                out.append(re.sub(r'URI="([^"]+)"', rep, s))
            elif s and not s.startswith("#"):
                out.append(urljoin(m3u8_url, s))
            else:
                out.append(line)
        return "\n".join(out)

    def _fetch_key(self, key_url, m3u8_url=None):
        """抓 enc key 文件 → XOR 种子 → 真实 16B AES key"""
        kr = self.session.get(key_url, headers=self.headers, timeout=15)
        return self._decrypt_key(kr.content, m3u8_url)

    # ---------- 标准 catvod 接口 ----------

    def homeContent(self, filter=False):
        try:
            # 实测视频分类白名单（按 hasVideo 密度筛选，2026-08-06 实测）
            # 排除纯文本/讨论/楼凤/小说/公告等无视频分类，避免点进去空白
            classes = [
                {"type_id": SHORT_VID, "type_name": "短视频"},
                {"type_id": "13", "type_name": "海角视频"},
                {"type_id": "1001", "type_name": "收费视频"},
                {"type_id": "972", "type_name": "销魂视频"},
                {"type_id": "973", "type_name": "激情时刻"},
                {"type_id": "971", "type_name": "耳目盛宴"},
                {"type_id": "258", "type_name": "大事纪实"},
                {"type_id": "999", "type_name": "福利姬"},
                {"type_id": "300", "type_name": "海角认证"},
            ]
            return {"class": classes}
        except Exception as e:
            print("[HJ] homeContent:", e)
            return {"class": self._fallback_classes()}

    def _fallback_classes(self):
            return [
                {"type_id": "13", "type_name": "海角视频"},
                {"type_id": "1001", "type_name": "收费视频"},
                {"type_id": "972", "type_name": "销魂视频"},
                {"type_id": "973", "type_name": "激情时刻"},
            ]


    def categoryContent(self, tid, pg=1, filter=False, extend=None):
        try:
            # 短视频分类: 全站视频流 type=7&nodeId=0
            is_short = (tid == SHORT_VID)
            video_type = 7 if is_short else 0
            node = "0" if is_short else tid
            results = self._api_get("/api/topic/node/topics", {
                "page": int(pg) if pg else 1,
                "nodeId": node,
                "type": video_type,
                "limit": 50,
            })
            if isinstance(results, dict):
                results = results.get("results") or results.get("list") or []
            # 视频源只保留视频帖
            videos = self._topics_to_videos(results, only_video=True)
            return {"list": videos, "page": int(pg) if pg else 1, "pagecount": 9999, "limit": 50, "total": 99999}
        except Exception as e:
            print("[HJ] categoryContent:", e)
            return {"list": [], "page": int(pg) if pg else 1, "pagecount": 1, "limit": 0, "total": 0}

    def detailContent(self, ids):
        try:
            vid = str(ids[0])
            m = re.search(r"(\d+)", vid)
            vid = m.group(1) if m else vid
            detail = self._api_get("/api/topic/" + vid)
            if not detail:
                return {"list": []}
            title = self._clean_title(detail.get("title", ""))
            pic = ""
            for a in (detail.get("attachments") or []):
                if a.get("category") == "images" and a.get("remoteUrl"):
                    pic = self._fix_pic(a["remoteUrl"])
                    break
            desc = self._clean_title(detail.get("liteContent", "")) or ""
            content_raw = detail.get("content", "")
            if not desc:
                k = content_raw
                if isinstance(k, str):
                    desc = self._clean_title(re.sub(r"<[^>]+>", " ", k))
            remarks = ""
            if detail.get("money_type") == 2:
                remarks = "💰付费"
            elif detail.get("hasVideo"):
                remarks = "🎬视频"
            if detail.get("is_original"):
                remarks = (remarks + " 原创") if remarks else "原创"

            video_url = self._find_video_attachment(detail)

            play_url = ""
            if not video_url:
                return {"list": []}
            # 空 remoteUrl 的视频，_find_video_attachment 返回 int attachment id
            # -> 需登录后调 /api/attachment 换真实 remoteUrl
            if isinstance(video_url, int) or (isinstance(video_url, str) and video_url.isdigit()):
                ru = self._get_real_remoteUrl(str(video_url), vid)
                if ru and ".m3u8" in ru:
                    video_url = ru
                else:
                    # 认证失败或拿不到流，无法播放
                    return {"list": []}
            su = video_url if isinstance(video_url, str) else str(video_url)
            if "preview" in su.lower():
                play_url = self._derive_full_m3u8(su, vid) or su
            else:
                play_url = su
            vod = {
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": remarks,
                "vod_content": desc or "",
                "vod_play_from": "海角",
                "vod_play_url": "完整$" + play_url,
            }
            return {"list": [vod]}
        except Exception as e:
            print("[HJ] detailContent:", e)
            return {"list": []}

    def playerContent(self, flag, id, vipFlags=None):
        try:
            if ".m3u8" in id:
                url = self._proxy_url(id)
                header = json.dumps({"User-Agent": UA, "Referer": H + "/"})
                return {"parse": 0, "url": url, "header": header}
            return {"parse": 0, "url": id, "header": {}}
        except Exception as e:
            print("[HJ] playerContent:", e)
            return {"parse": 0, "url": id, "header": {}}

    def searchContent(self, key, quick=False, pg="1"):
        try:
            results = self._api_get("/api/topic/search", {
                "keyword": key, "page": int(pg) if pg else 1,
            })
            if isinstance(results, dict):
                results = results.get("results") or results.get("list") or []
            videos = self._topics_to_videos(results, only_video=True)
            return {"list": videos, "page": int(pg) if pg else 1, "pagecount": 9999}
        except Exception as e:
            print("[HJ] searchContent:", e)
            return {"list": [], "page": 1}

    def localProxy(self, param):
        """TVBox 标准 localProxy 兜底（主路径走自建 HTTP 代理）"""
        try:
            url = unquote(param.get("url", ""))
            if ".m3u8" in url:
                text = self._fetch_m3u8(url)
                return [200, "application/vnd.apple.mpegurl", text.encode("utf-8")]
            if ".key" in url or "enc_" in url:
                return [200, "application/octet-stream", self._fetch_key(url)]
            r = self.session.get(url, headers=self.headers, timeout=20)
            return [200, r.headers.get("Content-Type", "application/octet-stream"), r.content]
        except Exception as e:
            return [500, "text/plain", str(e).encode("utf-8")]

    def homeVideoContent(self):
        try:
            results = self._api_get("/api/topic/hot/topics", {"page": 1})
            if isinstance(results, dict):
                results = results.get("results") or results.get("list") or []
            # 首页也只保留视频条目
            videos = self._topics_to_videos(results, only_video=True)
            return {"list": videos}
        except Exception:
            return {"list": []}
