#!/usr/bin/env python3
"""
扫描暂存区中的 _posts/*.md 文件，处理图片语法：
 - 忽略 http(s) 链接和以 /assets/images/ 开头的路径
 - 对其他本地相对路径：将图片移到 assets/images/，并把 markdown 中的路径替换为以 /assets/images/ 开头的绝对路径
 - 将修改后的 markdown 和被移动的图片加入暂存区（git add）

用于配合本地 pre-commit hook，实现提交前自动整理图片到统一目录。
"""

import re
import os
import sys
import shutil
import hashlib
import subprocess
import argparse
import glob

RE_IMG = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
ASSETS_DIR = "assets/images"
PROCESSED_IMAGES = []


def run(cmd):
    return subprocess.check_output(cmd, shell=True).decode().strip()


def staged_md_files():
    try:
        out = run("git diff --cached --name-only --diff-filter=AM")
    except subprocess.CalledProcessError:
        return []
    return [p for p in out.splitlines() if p.startswith("_posts/") and p.lower().endswith('.md')]


def all_md_files():
    # 返回工作区下的所有 _posts 下的 markdown 文件（递归）
    files = glob.glob(os.path.join("_posts", "**", "*.md"), recursive=True)
    # 规范化路径
    return [os.path.normpath(f) for f in files]


def make_name_collision_free(dest_dir, basename, src_path=None):
    name = basename
    dest = os.path.join(dest_dir, name)
    if not os.path.exists(dest):
        return name
    # if exists, try appending short hash of file content (source if available, otherwise existing name)
    try:
        if src_path and os.path.exists(src_path):
            h = hashlib.sha1(open(src_path, 'rb').read()).hexdigest()[:8]
        else:
            h = hashlib.sha1(name.encode()).hexdigest()[:8]
    except Exception:
        h = hashlib.sha1(name.encode()).hexdigest()[:8]
    name2 = f"{os.path.splitext(name)[0]}-{h}{os.path.splitext(name)[1]}"
    return name2


def is_remote(path):
    return path.startswith("http://") or path.startswith("https://")


def is_assets_path(path):
    return path.startswith("/assets/images/") or path.startswith("assets/images/")


def ensure_assets():
    os.makedirs(ASSETS_DIR, exist_ok=True)


def process_file(path):
    changed = False
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        return False

    def repl(m):
        nonlocal changed
        alt = m.group(1)
        target = m.group(2).strip()
        # 如果有 title（例如: path "title"），只取第一个部分作为路径
        target_path = target.split()[0]
        # 去掉可能被包裹的 <>
        if target_path.startswith('<') and target_path.endswith('>'):
            target_path = target_path[1:-1]
        if is_remote(target_path) or is_assets_path(target_path) or target_path.startswith('/'):
            return m.group(0)
        # 相对路径，基于 markdown 文件所在目录
        md_dir = os.path.dirname(path)
        src_path = os.path.normpath(os.path.join(md_dir, target_path))
        if not os.path.exists(src_path):
            # 未找到文件，原样保留
            print(f"[move_images_in_posts] 警告: 未找到图片文件 {src_path}，跳过处理。")
            return m.group(0)
        ensure_assets()
        basename = os.path.basename(src_path)
        safe_name = make_name_collision_free(ASSETS_DIR, basename, src_path=src_path)
        dest_path = os.path.join(ASSETS_DIR, safe_name)
        # 打印将要处理的图片路径
        print(f"[move_images_in_posts] 处理图片: {src_path} -> /{ASSETS_DIR}/{safe_name}")
        # 移动源文件到目标
        try:
            shutil.move(src_path, dest_path)
            PROCESSED_IMAGES.append((src_path, dest_path))
        except Exception as e:
            # 如果移动失败，尝试复制
            try:
                shutil.copy2(src_path, dest_path)
                PROCESSED_IMAGES.append((src_path, dest_path))
            except Exception:
                return m.group(0)
        changed = True
        new_target = f"/{ASSETS_DIR}/{safe_name}"
        return f"![{alt}]({new_target})"

    new_text = RE_IMG.sub(repl, text)
    if changed and new_text != text:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_text)
        # 将修改加入暂存区
        try:
            run(f'git add "{path}"')
        except Exception:
            pass
        # 将新增的 assets 文件加入暂存区
        try:
            run(f'git add "{ASSETS_DIR}"')
        except Exception:
            pass
    else:
        print(f"[move_images_in_posts] 文件 {path} 中未发现需要移动的本地图片。")
    return changed


def main():
    parser = argparse.ArgumentParser(description='Move images referenced in _posts to assets/images')
    parser.add_argument('--all', action='store_true', help='Process all _posts/*.md files in the working tree (not only staged)')
    args = parser.parse_args()

    files = all_md_files() if args.all else staged_md_files()
    if not files:
        if args.all:
            print("[move_images_in_posts] 未发现工作区中的 _posts/*.md 文件，跳过处理。")
        else:
            print("[move_images_in_posts] 未发现暂存的 _posts/*.md 文件，跳过处理。")
        return 0
    print(f"[move_images_in_posts] 将处理的 Markdown 文件: {files}")
    any_changed = False
    for f in files:
        if process_file(f):
            any_changed = True
    if any_changed:
        print("[move_images_in_posts] 已将本地图片移动到 assets/images/ 并更新 Markdown 引用，已把更改加入暂存区。")
        print("请检查更改并继续提交 (git commit)。")
        if PROCESSED_IMAGES:
            print("[move_images_in_posts] 处理摘要：")
            for src, dst in PROCESSED_IMAGES:
                print(f"  - {src} -> {dst}")
    else:
        print("[move_images_in_posts] 未发现需要移动的本地图片。")
    return 0


if __name__ == '__main__':
    sys.exit(main())
