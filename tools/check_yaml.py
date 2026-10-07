#!/usr/bin/env python3
"""Prüft alle YAML-Dateien im Repo: gültiges YAML (mit !input/!secret/!include),
Jinja-Templates syntaktisch korrekt, Blueprints mit Pflichtfeldern.

Aufruf: python3 tools/check_yaml.py   (Rückgabewert 1 bei Fehlern)
"""

from __future__ import annotations

import pathlib
import sys

import jinja2
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP = {".git", "node_modules"}


class Loader(yaml.SafeLoader):
    pass


for tag in ("!input", "!secret", "!include", "!include_dir_named", "!include_dir_merge_named",
            "!include_dir_list", "!include_dir_merge_list", "!env_var"):
    Loader.add_constructor(tag, lambda loader, node: f"<{node.tag}:{loader.construct_scalar(node)}>")


def templates(obj):
    if isinstance(obj, dict):
        for value in obj.values():
            yield from templates(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from templates(value)
    elif isinstance(obj, str) and ("{{" in obj or "{%" in obj):
        yield obj


def main() -> int:
    env = jinja2.Environment(extensions=["jinja2.ext.loopcontrols"])
    errors = 0
    files = [p for p in ROOT.rglob("*") if p.suffix in (".yaml", ".yml", ".example")
             and not SKIP & set(p.parts) and p.is_file()]
    for path in sorted(files):
        rel = path.relative_to(ROOT)
        try:
            data = yaml.load(path.read_text(encoding="utf-8"), Loader=Loader)
        except yaml.YAMLError as err:
            print(f"FEHLER {rel}: {err}")
            errors += 1
            continue
        if rel.parts[0] == "blueprints":
            bp = (data or {}).get("blueprint", {})
            for key in ("name", "domain", "input"):
                if key not in bp:
                    print(f"FEHLER {rel}: blueprint.{key} fehlt")
                    errors += 1
        if rel.parts[0] == ".github":
            continue
        for tpl in templates(data):
            try:
                env.parse(tpl)
            except jinja2.TemplateSyntaxError as err:
                print(f"FEHLER {rel}: Template: {err.message}\n  {tpl[:120]!r}")
                errors += 1
    print(f"{len(files)} Dateien geprüft, {errors} Fehler")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
