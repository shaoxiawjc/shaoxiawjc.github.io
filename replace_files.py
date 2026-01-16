#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


IMAGE_MD_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
# 非标准写法：!(alt)[path] 或 !(alt)(path)
WEIRD_SQUARE_RE = re.compile(r"!\(([^)]*)\)\[([^\]]+)\]")
WEIRD_PAREN_RE = re.compile(r"!\(([^)]*)\)\(([^)]+)\)")
# Obsidian 写法：![[path]]（可能带 |宽度 等参数）
OBSIDIAN_RE = re.compile(r"!\[\[([^\]]+)\]\]")


SKIP_PREFIXES = (
	"http://",
	"https://",
	"data:",
	"//",
)


@dataclass(frozen=True)
class Ref:
	kind: str  # md | weird_square | weird_paren | obsidian
	raw_path: str
	alt: str


@dataclass
class MovePlan:
	src: Path
	dst: Path
	url: str
	note: str = ""


def _is_fence(line: str) -> bool:
	stripped = line.lstrip()
	return stripped.startswith("```") or stripped.startswith("~~~")


def _clean_ref_path(raw: str) -> str:
	s = raw.strip().strip("\"").strip("'").strip()
	if s.startswith("<") and s.endswith(">"):
		s = s[1:-1].strip()
	# Obsidian: path|width 或 path#anchor
	s = s.split("|", 1)[0].strip()
	s = s.split("#", 1)[0].strip()
	return s


def _should_skip(raw_path: str) -> bool:
	p = _clean_ref_path(raw_path)
	if not p:
		return True
	if p.startswith(SKIP_PREFIXES):
		return True
	# 已经是站点绝对路径：/assets/images/... 或用户写的 /assert/image...
	if p.startswith("/assets/images") or p.startswith("/assert/image"):
		return True
	return False


def _slug_from_post_filename(post_md: Path) -> str:
	return post_md.stem


def _unique_destination_path(dst: Path) -> Path:
	if not dst.exists():
		return dst
	base = dst.stem
	suffix = dst.suffix
	parent = dst.parent
	for i in range(1, 1000):
		candidate = parent / f"{base}-{i}{suffix}"
		if not candidate.exists():
			return candidate
	raise RuntimeError(f"Destination collision: {dst}")


def resolve_source_path(repo_root: Path, post_md: Path, ref_path: str) -> Optional[Path]:
	p = _clean_ref_path(ref_path)
	if not p:
		return None

	# 处理 /./xxx 这种奇怪路径
	if p.startswith("/./"):
		p = p[3:]

	candidates: List[Path] = []

	# 1) 相对 post 文件
	candidates.append((post_md.parent / p).resolve())

	# 2) _posts 根
	candidates.append((repo_root / "_posts" / p.lstrip("/")).resolve())

	# 3) repo 根（去掉前导 /）
	candidates.append((repo_root / p.lstrip("/")).resolve())

	for c in candidates:
		if c.exists() and c.is_file():
			return c
	return None


def plan_moves_for_post(
	repo_root: Path,
	posts_dir: Path,
	dest_root: Path,
	post_md: Path,
	refs: List[Ref],
) -> Tuple[Dict[str, MovePlan], List[str]]:
	slug = _slug_from_post_filename(post_md)
	dest_dir = (repo_root / dest_root / slug)

	plans_by_raw: Dict[str, MovePlan] = {}
	warnings: List[str] = []

	for ref in refs:
		raw_path = ref.raw_path
		if _should_skip(raw_path):
			continue

		src = resolve_source_path(repo_root, post_md, raw_path)
		if src is None:
			warnings.append(f"Unresolved image path in {post_md.name}: {raw_path}")
			continue

		dest_dir.mkdir(parents=True, exist_ok=True)
		dst = dest_dir / src.name
		dst = _unique_destination_path(dst)
		url = "/" + str((dest_root / slug / dst.name).as_posix())
		plans_by_raw[raw_path] = MovePlan(src=src, dst=dst, url=url)

	return plans_by_raw, warnings


def extract_refs_from_line(line: str) -> List[Ref]:
	refs: List[Ref] = []

	for m in IMAGE_MD_RE.finditer(line):
		refs.append(Ref(kind="md", alt=m.group(1), raw_path=m.group(2)))
	for m in WEIRD_SQUARE_RE.finditer(line):
		refs.append(Ref(kind="weird_square", alt=m.group(1), raw_path=m.group(2)))
	for m in WEIRD_PAREN_RE.finditer(line):
		refs.append(Ref(kind="weird_paren", alt=m.group(1), raw_path=m.group(2)))
	for m in OBSIDIAN_RE.finditer(line):
		refs.append(Ref(kind="obsidian", alt="", raw_path=m.group(1)))

	return refs


def rewrite_line(line: str, plans_by_raw: Dict[str, MovePlan]) -> str:
	def repl_md(m: re.Match) -> str:
		alt = m.group(1)
		raw = m.group(2)
		plan = plans_by_raw.get(raw)
		if plan is None:
			return m.group(0)
		return f"![{alt}]({plan.url})"

	def repl_weird_square(m: re.Match) -> str:
		alt = m.group(1)
		raw = m.group(2)
		plan = plans_by_raw.get(raw)
		if plan is None:
			return m.group(0)
		return f"![{alt}]({plan.url})"

	def repl_weird_paren(m: re.Match) -> str:
		alt = m.group(1)
		raw = m.group(2)
		plan = plans_by_raw.get(raw)
		if plan is None:
			return m.group(0)
		return f"![{alt}]({plan.url})"

	def repl_obsidian(m: re.Match) -> str:
		raw = m.group(1)
		plan = plans_by_raw.get(raw)
		if plan is None:
			return m.group(0)
		alt = Path(_clean_ref_path(raw)).stem
		return f"![{alt}]({plan.url})"

	line = IMAGE_MD_RE.sub(repl_md, line)
	line = WEIRD_SQUARE_RE.sub(repl_weird_square, line)
	line = WEIRD_PAREN_RE.sub(repl_weird_paren, line)
	line = OBSIDIAN_RE.sub(repl_obsidian, line)
	return line


def collect_post_markdown_files(posts_dir: Path) -> List[Path]:
	md_files: List[Path] = []
	for p in posts_dir.iterdir():
		if p.is_file() and p.suffix.lower() == ".md":
			md_files.append(p)
	md_files.sort()
	return md_files


def apply_move_plans(plans: Iterable[MovePlan], apply: bool) -> Tuple[int, int, List[str]]:
	moved = 0
	copied = 0
	notes: List[str] = []

	# 同一个 src 可能被多个 post 使用：第一次 move，之后 copy
	src_to_first_dst: Dict[Path, Path] = {}

	for plan in plans:
		if not apply:
			continue
		if plan.dst.exists():
			continue

		plan.dst.parent.mkdir(parents=True, exist_ok=True)

		first_dst = src_to_first_dst.get(plan.src)
		if first_dst is None:
			shutil.move(str(plan.src), str(plan.dst))
			src_to_first_dst[plan.src] = plan.dst
			moved += 1
		else:
			shutil.copy2(str(first_dst), str(plan.dst))
			copied += 1
			notes.append(f"Copied (multi-ref): {plan.src.name} -> {plan.dst}")

	return moved, copied, notes


def main() -> int:
	parser = argparse.ArgumentParser(
		description=(
			"Scan _posts markdown files, migrate local images into assets/images/<post>/, "
			"and rewrite markdown image references."
		)
	)
	parser.add_argument("--repo-root", default=".", help="Repo root (default: current dir)")
	parser.add_argument("--posts-dir", default="_posts", help="Posts directory (default: _posts)")
	parser.add_argument(
		"--dest-root",
		default="assets/images",
		help="Destination root dir under repo (default: assets/images)",
	)
	parser.add_argument(
		"--apply",
		action="store_true",
		help="Actually move/copy files and rewrite markdown (default: dry-run)",
	)
	args = parser.parse_args()

	repo_root = Path(args.repo_root).resolve()
	posts_dir = (repo_root / args.posts_dir).resolve()
	dest_root = Path(args.dest_root)

	if not posts_dir.exists():
		raise SystemExit(f"Posts dir not found: {posts_dir}")

	md_files = collect_post_markdown_files(posts_dir)
	if not md_files:
		print(f"No markdown files found under: {posts_dir}")
		return 0

	all_plans: List[MovePlan] = []
	all_warnings: List[str] = []
	changed_files: List[Path] = []

	for post_md in md_files:
		lines = post_md.read_text(encoding="utf-8").splitlines(keepends=True)
		in_code = False
		refs: List[Ref] = []
		for line in lines:
			if _is_fence(line):
				in_code = not in_code
			if in_code:
				continue
			refs.extend(extract_refs_from_line(line))

		plans_by_raw, warnings = plan_moves_for_post(
			repo_root=repo_root,
			posts_dir=posts_dir,
			dest_root=dest_root,
			post_md=post_md,
			refs=refs,
		)
		all_warnings.extend(warnings)
		if not plans_by_raw:
			continue

		new_lines: List[str] = []
		in_code = False
		modified = False
		for line in lines:
			if _is_fence(line):
				in_code = not in_code
				new_lines.append(line)
				continue
			if in_code:
				new_lines.append(line)
				continue

			new_line = rewrite_line(line, plans_by_raw)
			if new_line != line:
				modified = True
			new_lines.append(new_line)

		if modified:
			changed_files.append(post_md)
			if args.apply:
				post_md.write_text("".join(new_lines), encoding="utf-8")

		all_plans.extend(plans_by_raw.values())

	# 执行搬运
	moved, copied, notes = apply_move_plans(all_plans, apply=args.apply)

	# 输出摘要
	mode = "APPLY" if args.apply else "DRY-RUN"
	print(f"[{mode}] Posts scanned: {len(md_files)}")
	print(f"[{mode}] Markdown files to change: {len(changed_files)}")
	print(f"[{mode}] Image operations planned: {len(all_plans)}")
	if args.apply:
		print(f"[{mode}] Moved: {moved}, Copied: {copied}")

	if all_warnings:
		print("\nWarnings:")
		for w in all_warnings:
			print(f"- {w}")

	if notes:
		print("\nNotes:")
		for n in notes:
			print(f"- {n}")

	if not args.apply:
		print("\nTip: run again with --apply to perform changes.")

	return 0


if __name__ == "__main__":
	raise SystemExit(main())
