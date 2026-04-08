from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable, List, Sequence


DEFAULT_FILES = [
    "main.blocks",
    "main.ts",
    "README.md",
    "assets.json",
    "tilemap.g.jres",
    "tilemap.g.ts",
    "images.g.jres",
    "images.g.ts",
]


class GenerateError(Exception):
    pass


def http_get_json(url: str) -> dict | list:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "pxt-generate",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def http_get_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "pxt-generate"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8")


def parse_dependency_input(raw: str) -> List[str]:
    text = raw.strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1]
    else:
        inner = text
    parts = [part.strip().strip("\"'") for part in inner.split(",")]
    return [part for part in parts if part]


def load_dependency_specs(arg_value: str | None, file_path: Path | None) -> List[str]:
    specs: List[str] = []
    if arg_value:
        specs.extend(parse_dependency_input(arg_value))
    if file_path:
        specs.extend(parse_dependency_input(file_path.read_text(encoding="utf-8")))
    return specs


def normalize_repo_slug(spec: str) -> str:
    value = spec.strip()
    value = re.sub(r"^github:", "", value, flags=re.IGNORECASE)
    value = value.split("#", 1)[0]
    value = value.strip("/")
    if value.count("/") != 1:
        raise GenerateError(f"Invalid dependency repo format: {spec}")
    return value


def pick_latest_ref(owner: str, repo: str) -> str:
    try:
        release = http_get_json(f"https://api.github.com/repos/{owner}/{repo}/releases/latest")
        if isinstance(release, dict) and release.get("tag_name"):
            return str(release["tag_name"])
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise GenerateError(f"Failed to query latest release for {owner}/{repo}: {exc}") from exc

    try:
        tags = http_get_json(f"https://api.github.com/repos/{owner}/{repo}/tags?per_page=100")
    except urllib.error.HTTPError as exc:
        raise GenerateError(f"Failed to query tags for {owner}/{repo}: {exc}") from exc

    if isinstance(tags, list) and tags:
        def version_key(tag_name: str) -> tuple:
            match = re.search(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", tag_name)
            if match:
                return tuple(int(part or 0) for part in match.groups())
            return (-1, -1, -1)

        names = [str(item.get("name")) for item in tags if isinstance(item, dict) and item.get("name")]
        names.sort(key=version_key, reverse=True)
        if names:
            return names[0]

    repo_info = http_get_json(f"https://api.github.com/repos/{owner}/{repo}")
    if isinstance(repo_info, dict) and repo_info.get("default_branch"):
        return str(repo_info["default_branch"])
    raise GenerateError(f"Could not determine a usable ref for {owner}/{repo}")


def validate_arcade_extension(owner: str, repo: str, ref: str) -> str:
    encoded_ref = urllib.parse.quote(ref, safe="")
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{encoded_ref}/pxt.json"
    try:
        manifest_text = http_get_text(url)
    except urllib.error.HTTPError as exc:
        raise GenerateError(f"{owner}/{repo}@{ref} does not expose pxt.json") from exc

    try:
        manifest = json.loads(manifest_text)
    except json.JSONDecodeError as exc:
        raise GenerateError(f"{owner}/{repo}@{ref} has an invalid pxt.json") from exc

    supported = manifest.get("supportedTargets")
    if supported is not None:
        if not isinstance(supported, list) or "arcade" not in [str(item) for item in supported]:
            raise GenerateError(f"{owner}/{repo}@{ref} is not marked as an Arcade extension")

    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise GenerateError(f"{owner}/{repo}@{ref} does not look like a valid MakeCode extension")

    return f"github:{owner}/{repo}#{ref}"


def resolve_dependencies(specs: Iterable[str]) -> dict:
    resolved = {"device": "*"}
    for spec in specs:
        slug = normalize_repo_slug(spec)
        owner, repo = slug.split("/", 1)
        ref = pick_latest_ref(owner, repo)
        resolved[repo] = validate_arcade_extension(owner, repo, ref)
    return resolved


def default_main_blocks() -> str:
    return '<xml xmlns="https://developers.google.com/blockly/xml"></xml>\n'


def default_images_g_jres() -> str:
    return json.dumps(
        {
            "*": {
                "mimeType": "image/x-mkcd-f4",
                "dataEncoding": "base64",
                "namespace": "myImages",
            }
        },
        indent=4,
    ) + "\n"


def default_images_g_ts() -> str:
    return "// Auto-generated code. Do not edit.\nnamespace myImages {\n\n}\n"


def default_tilemap_g_jres() -> str:
    return json.dumps(
        {
            "transparency16": {
                "data": "hwQQABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==",
                "mimeType": "image/x-mkcd-f4",
                "tilemapTile": True,
            },
            "*": {
                "mimeType": "image/x-mkcd-f4",
                "dataEncoding": "base64",
                "namespace": "myTiles",
            },
        },
        indent=4,
    ) + "\n"


def default_tilemap_g_ts() -> str:
    return (
        "// Auto-generated code. Do not edit.\n"
        "namespace myTiles {\n"
        "    //% fixedInstance jres blockIdentity=images._tile\n"
        "    export const transparency16 = image.ofBuffer(hex``)\n"
        "}\n"
    )


def scaffold_files(name: str, description: str, dependencies: dict) -> dict:
    pxt_json = {
        "name": name,
        "description": description,
        "dependencies": dependencies,
        "files": DEFAULT_FILES,
        "supportedTargets": ["arcade"],
        "preferredEditor": "tsprj",
    }
    return {
        "pxt.json": json.dumps(pxt_json, indent=4) + "\n",
        "main.ts": "",
        "main.blocks": default_main_blocks(),
        "README.md": f"# {name}\n\n{description}\n" if description else f"# {name}\n",
        "assets.json": "",
        "images.g.jres": default_images_g_jres(),
        "images.g.ts": default_images_g_ts(),
        "tilemap.g.jres": default_tilemap_g_jres(),
        "tilemap.g.ts": default_tilemap_g_ts(),
    }


def create_project(output_dir: Path, name: str, description: str, dependency_specs: List[str], force: bool) -> None:
    dependencies = resolve_dependencies(dependency_specs)
    files = scaffold_files(name, description, dependencies)

    if output_dir.exists():
        if not force:
            raise GenerateError(f"Output directory already exists: {output_dir}")
        for path in sorted(output_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
    output_dir.mkdir(parents=True, exist_ok=True)

    for rel, content in files.items():
        target = output_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a new MakeCode Arcade project scaffold with validated latest-version dependencies."
    )
    parser.add_argument("output_dir", type=Path, help="Directory to create")
    parser.add_argument("--name", default="Untitled", help="Project name")
    parser.add_argument("--description", default="", help="Project description")
    parser.add_argument("--dependencies", help="Dependency list like [microsoft/arcade-text, githubuser/validextension]")
    parser.add_argument("--dependency-file", type=Path, help="Path to a file containing the dependency list")
    parser.add_argument("--force", action="store_true", help="Replace an existing output directory")
    args = parser.parse_args(list(argv))

    try:
        specs = load_dependency_specs(args.dependencies, args.dependency_file)
        create_project(args.output_dir, args.name, args.description, specs, args.force)
    except GenerateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"error: dependency validation failed due to network issue: {exc}", file=sys.stderr)
        return 1

    print(f"Generated project scaffold in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
