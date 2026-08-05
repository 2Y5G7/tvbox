import os
import json
import requests
from datetime import datetime

SRC_OWNER = "FGBLH"
SRC_REPO = "HKL"
SRC_PATH = "py"
SRC_BRANCH = "main"

# 同步到你自己仓库里的目录
DEST_DIR = "synced/py"

API_BASE = "https://api.github.com"
HEADERS = {}
token = os.environ.get("GITHUB_TOKEN")
if token:
    HEADERS["Authorization"] = f"token {token}"


def get_files():
    url = f"{API_BASE}/repos/{SRC_OWNER}/{SRC_REPO}/contents/{SRC_PATH}?ref={SRC_BRANCH}"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return [item for item in resp.json() if item["type"] == "file"]


def get_last_commit_date(file_path):
    url = f"{API_BASE}/repos/{SRC_OWNER}/{SRC_REPO}/commits"
    params = {"path": file_path, "sha": SRC_BRANCH, "per_page": 1}
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    data = resp.json()
    return data[0]["commit"]["committer"]["date"] if data else None


def download_file(download_url, dest_path):
    resp = requests.get(download_url, headers=HEADERS)
    resp.raise_for_status()
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(resp.content)


def main():
    files = get_files()
    results = []

    for f in files:
        file_path = f["path"]
        date = get_last_commit_date(file_path)
        dest_path = os.path.join(DEST_DIR, f["name"])

        # 下载文件到本仓库
        download_file(f["download_url"], dest_path)

        results.append({
            "name": f["name"],
            "local_path": dest_path,
            "source_path": file_path,
            "last_modified": date,
        })

    # 按最后修改时间从新到旧排序
    results.sort(key=lambda x: x["last_modified"] or "", reverse=True)

    os.makedirs(DEST_DIR, exist_ok=True)

    # 生成 JSON 索引
    with open(os.path.join(DEST_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 生成 Markdown 索引
    with open(os.path.join(DEST_DIR, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write(f"# {SRC_OWNER}/{SRC_REPO}/{SRC_PATH} 同步文件（按时间从新到旧）\n\n")
        f.write(f"> 更新时间: {datetime.utcnow().isoformat()}Z\n\n")
        f.write("| 文件名 | 最后修改时间 |\n")
        f.write("|---|---|\n")
        for r in results:
            f.write(f"| [{r['name']}]({r['name']}) | {r['last_modified']} |\n")

    print(f"同步完成，共 {len(results)} 个文件。")


if __name__ == "__main__":
    main()
