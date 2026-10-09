"""Snapshot upstream without merging; prepare and validate a separate publication.

Only a validated snapshot is committed by the workflow. This module never pushes.
Uses the Python standard library; upstream blobs remain byte-for-byte intact.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

PROTECTED = {".git", ".github", "_mirror", "README.md", ".gitignore", "CNAME"}
REQUIRED = ("index.html", "VLN-Papers/index.html", "research/index.html", "home/index.html", "about/index.html")


def git(root, *args, data=None):
    return subprocess.run(["git", "-C", str(root), *args], input=data,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout


def safe_path(root, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(p in ("..", ".git") for p in path.parts):
        raise ValueError(f"Unsafe path: {relative}")
    if "\\" in relative or ":" in relative:
        raise ValueError(f"Unsupported path: {relative}")
    root = Path(root).resolve()
    target = root.joinpath(*path.parts)
    if not target.resolve().is_relative_to(root):
        raise ValueError(f"Path escapes workspace: {relative}")
    return target


def protected(path):
    return PurePosixPath(path).parts[0] in PROTECTED


def tree(root, ref):
    files = {}
    for entry in git(root, "ls-tree", "-rz", "--full-tree", ref).split(b"\0"):
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        mode, kind, sha = metadata.decode().split()
        name = name.decode("utf-8")
        safe_path(root, name)
        if protected(name):
            continue
        if kind != "blob" or mode not in ("100644", "100755"):
            raise ValueError(f"Unsupported upstream symlink/submodule: {name}")
        files[name] = sha
    return files


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def preserve_manual_edits(root, previous, current):
    """Keep later root edits as build overlays instead of silently losing them."""
    state_path = root / "_mirror/state.json"
    if not state_path.exists():  # One-time migration of the previously customized fork.
        return
    delete_path = root / "_mirror/deleted.json"
    deleted = set(json.loads(delete_path.read_text(encoding="utf-8"))) if delete_path.exists() else set()
    for name in sorted(set(previous) | set(current)):
        if previous.get(name) == current.get(name):
            continue
        if name not in current:
            deleted.add(name)
        else:
            target = safe_path(root / "_mirror/overrides", name)
            source = safe_path(root, name)
            if target.exists() and target.read_bytes() != source.read_bytes():
                raise ValueError(f"Both root and override changed: {name}; reconcile the two copies first.")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            deleted.discard(name)
        print(f"Preserved personal edit: {name}")
    if deleted or delete_path.exists():
        write_json(delete_path, sorted(deleted))


def snapshot(root, ref):
    root = root.resolve()
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise ValueError("Snapshot requires a clean checkout; commit personal edits first.")
    sha = git(root, "rev-parse", f"{ref}^{{commit}}").decode().strip()
    incoming, current = tree(root, sha), tree(root, "HEAD")
    if "_config.yml" not in incoming or not any(p.startswith("_posts/") for p in incoming):
        raise ValueError("Upstream is not a complete Jekyll research site.")
    state_path = root / "_mirror/state.json"
    previous_state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    preserve_manual_edits(root, previous_state.get("files", {}), current)
    # Only files already tracked as upstream-owned may be removed. Local untracked files are not deleted.
    for name in sorted(set(current) - set(incoming)):
        path = safe_path(root, name)
        if path.is_file():
            path.unlink()
    # Stream one archive, not a git merge and not individual network requests per image.
    with tempfile.TemporaryFile() as archive:
        subprocess.run(["git", "-C", str(root), "archive", sha], stdout=archive, check=True)
        archive.seek(0)
        with tarfile.open(fileobj=archive, mode="r|") as tar:
            for member in tar:
                if member.isdir() or protected(member.name):
                    continue
                if member.name not in incoming or not member.isfile():
                    raise ValueError(f"Unexpected archive entry: {member.name}")
                target = safe_path(root, member.name)
                if target.is_dir():
                    target.rmdir()  # Only an empty directory left by removed tracked files.
                if member.name not in current and target.exists():
                    raise ValueError(f"Untracked file would be overwritten: {member.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                target.chmod(member.mode & 0o777)
    # Retain upstream documentation while keeping the mirror's maintenance instructions independent.
    (root / "_mirror/upstream-README.md").write_bytes(git(root, "show", f"{sha}:README.md"))
    # A weekly successful-check record also prevents inactivity from disabling the schedule.
    today = dt.datetime.now(dt.timezone.utc).date()
    week = (today - dt.timedelta(days=today.weekday())).isoformat()
    write_json(state_path, {"upstream": "TingdeLiu/tingdeliu.github.io", "revision": sha,
                           "checked_week": week, "files": incoming})
    print(f"Prepared upstream {sha}: {len(incoming)} files; no Git merge involved.")


def prepare(root):
    root = root.resolve()
    build = root / "_mirror/build"
    if build.exists():
        raise ValueError("Build directory already exists; use a fresh checkout for every run.")
    state = json.loads((root / "_mirror/state.json").read_text(encoding="utf-8"))
    build.mkdir(parents=True)
    for name in state["files"]:
        source, target = safe_path(root, name), safe_path(build, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    override = root / "_mirror/overrides"
    if override.exists():
        for source in sorted(override.rglob("*")):
            if source.is_symlink():
                raise ValueError(f"Overrides must be regular files: {source}")
            if source.is_file():
                target = safe_path(build, source.relative_to(override).as_posix())
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    delete_path = root / "_mirror/deleted.json"
    if delete_path.exists():
        for name in json.loads(delete_path.read_text(encoding="utf-8")):
            safe_path(build, name).unlink(missing_ok=True)
    # JSON is a YAML subset accepted by Jekyll's --config option.
    shutil.copy2(root / "_mirror/config.json", build / "_mirror.yml")
    (build / "Gemfile.lock").unlink(missing_ok=True)  # Upstream lock may contain Windows platforms.
    print(f"Build source prepared separately at {build}")


def brand_html(text, relative, config):
    source = config["source_url"].rstrip("/")
    target = config["url"].rstrip("/") + config.get("baseurl", "")
    text = text.replace(source, target)
    text = re.sub(r"(https://(?:api\.)?github\.com/(?:repos/)?)TingdeLiu/(?:Tingde\.Liu|tingdeliu)\.github\.io",
                  lambda m: m[1] + config["repository"], text, flags=re.I)
    # Upstream's search-console identity must not be published as the mirror owner's.
    text = re.sub(r'<meta\b(?=[^>]*\bname=[\"\']google-site-verification[\"\'])[^>]*>', "", text, flags=re.I)
    if not re.search(r"<body\b", text, flags=re.I):
        return text
    author = html.escape(config["content_author"])
    owner = html.escape(config["name"])
    original = source + "/" + re.sub(r"index\.html$", "", relative)
    note = (f'Learning mirror maintained by {owner}. Original content by {author}. '
            'Projects and biography belong to the original author. Original text: CC BY 4.0; '
            'third-party figures retain their original rights.') if relative.startswith("en/") else (
            f'本站由 {owner} 维护，原文作者为 {author}。项目与个人经历属于原作者。'
            '原创文字采用 CC BY 4.0；第三方论文配图保留原有权利与出处。')
    banner = ('\n<aside id="mirror-attribution" style="box-sizing:border-box;max-width:1040px;'
              'margin:16px auto;padding:12px 18px;border:1px solid #b8d4e8;border-radius:8px;'
              'background:#f5faff;color:#334155;font-size:13px;line-height:1.65">'
              + note + f' <a href="{html.escape(original, quote=True)}">Original / 原文</a> · '
              '<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a></aside>\n')
    container = r'(<main\b[^>]*>|<div\b(?=[^>]*\bid=[\"\']main[\"\'])[^>]*>)'
    insertion = container if re.search(container, text, flags=re.I) else r"(<body\b[^>]*>)"
    return re.sub(insertion, lambda m: m[1] + banner, text, count=1, flags=re.I)


def finalize(root):
    config = json.loads((root / "_mirror/config.json").read_text(encoding="utf-8"))
    site = root / "_mirror/build/_site"
    for path in site.rglob("*"):
        if path.is_file() and path.suffix in (".html", ".xml", ".json"):
            raw = path.read_text(encoding="utf-8")
            text = brand_html(raw, path.relative_to(site).as_posix(), config) if path.suffix == ".html" else raw.replace(config["source_url"], config["url"])
            path.write_text(text, encoding="utf-8")
    for name in REQUIRED:
        page = safe_path(site, name)
        if not page.is_file() or page.stat().st_size < 500:
            raise ValueError(f"Required page is missing or empty: {name}")
        text = page.read_text(encoding="utf-8")
        if 'id="mirror-attribution"' not in text:
            raise ValueError(f"Original-author attribution missing: {name}")
        if "G-KXKFYB0T0H" in text:
            raise ValueError(f"Original author's analytics still enabled: {name}")
    styles = [p for p in site.rglob("*.css") if p.stat().st_size > 1000]
    if not styles:
        raise ValueError("Compiled stylesheet missing; refusing to publish an unstyled site.")
    state = json.loads((root / "_mirror/state.json").read_text(encoding="utf-8"))
    write_json(site / "mirror-status.json", {"upstream_revision": state["revision"],
               "source": config["source_url"], "mirror": config["url"]})
    print(f"Publication validated: {len(list(site.rglob('*.html')))} HTML files, attribution and CSS present.")


def stage(root):
    """Stage every managed blob, including new files matching local ignore rules."""
    state = json.loads((root / "_mirror/state.json").read_text(encoding="utf-8"))
    paths = list(state["files"])
    override = root / "_mirror/overrides"
    if override.exists():
        paths.extend(p.relative_to(root).as_posix() for p in override.rglob("*") if p.is_file())
    git(root, "add", "-A")
    git(root, "add", "-f", "--pathspec-from-file=-", "--pathspec-file-nul",
        data=b"\0".join(p.encode("utf-8") for p in paths) + b"\0")
    candidate = git(root, "write-tree").decode().strip()
    if tree(root, candidate) != state["files"]:
        raise ValueError("Staged upstream files differ from the downloaded snapshot; refusing to commit.")
    print(f"Verified all {len(state['files'])} staged upstream blobs against their original Git hashes.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("snapshot", "prepare", "finalize", "stage"))
    parser.add_argument("--ref", default="refs/remotes/upstream/main")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.command == "snapshot":
        snapshot(root, args.ref)
    elif args.command == "prepare":
        prepare(root)
    elif args.command == "finalize":
        finalize(root)
    else:
        stage(root)


if __name__ == "__main__":
    main()
