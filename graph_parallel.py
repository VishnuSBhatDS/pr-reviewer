#!/usr/bin/env python3
import os
import re
import json
import tempfile
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from git import Repo
import multiprocessing

# --- Spring stereotypes ---
SPRING_ANNOTATIONS = {
    "Controller": "controller",
    "RestController": "controller",
    "Service": "service",
    "Repository": "repository",
    "Component": "component",
    "Configuration": "configuration",
}

# --- Regex patterns ---
PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
CLASS_RE = re.compile(
    r"(?:@\w+(?:\([^)]*\))?\s*)*"
    r"(?:public|protected|private)?\s*"
    r"(?:abstract|final|static)?\s*"
    r"(class|interface|enum|record)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)
AUTOWIRED_FIELD_RE = re.compile(
    r"@Autowired\b(?:\s*\([^)]*\))?\s*"
    r"(?:@Qualifier\([^\)]*\)\s*)*"
    r"(?:private|protected|public)?\s*"
    r"([\w\<\>\.\,\s\?\[\]]+?)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*;",
    re.MULTILINE,
)
METHOD_HEADER_RE = re.compile(
    r"(?:@\w+(?:\([^)]*\))?\s*)*"
    r"(?:public|protected|private)?\s*"
    r"(?:static|final|synchronized|abstract|default)?\s*"
    r"([\w\<\>\.\[\],\s\?]+)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*"
    r"\([^)]*\)\s*"
    r"(?:throws\s+[^{]+)?\s*\{",
    re.MULTILINE,
)
CONSTRUCTOR_RE_TEMPLATE = (
    r"(?:@\w+(?:\([^)]*\))?\s*)*(?:public|protected|private)?\s*{cls}\s*\([^)]*\)\s*\{{"
)
CALL_RE = re.compile(
    r"(?:\bthis\.|\bsuper\.|[A-Za-z_][A-Za-z0-9_]*\.)?([A-Za-z_][A-Za-z0-9_]*)\s*\("
)
CONTROL_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "throw", "new"}

ALL_DEFINED_METHODS = set()


# --------------------------- Repo Utils ---------------------------
def clone_repo(repo_url, branch="master"):
    temp_dir = tempfile.mkdtemp(prefix="spring_repo_")
    print(f"📥 Cloning {repo_url} (branch: {branch}) → {temp_dir}")
    repo = Repo.clone_from(repo_url, temp_dir)
    repo.git.checkout(branch)
    return temp_dir


# --------------------------- Parser Core ---------------------------
def regex_parse_java(file_path, code, collect_methods_only=False):
    relations = []
    package = "default"
    pm = PACKAGE_RE.search(code)
    if pm:
        package = pm.group(1)

    for cm in CLASS_RE.finditer(code):
        cls_kind, cls_name = cm.group(1), cm.group(2)
        fqn_class = f"{package}.{cls_name}"
        prefix_start = max(0, cm.start() - 400)
        prefix = code[prefix_start:cm.start()]
        role = "class"
        annos = re.findall(r"@([A-Za-z0-9_\.]+)", prefix)
        for a in annos:
            for k, v in SPRING_ANNOTATIONS.items():
                if k.lower() in a.lower():
                    role = v
                    break
            if role != "class":
                break

        if not collect_methods_only:
            relations.append(
                {"from": fqn_class, "to": None, "type": "declares", "role": role}
            )

        body_start = code.find("{", cm.end())
        if body_start == -1:
            continue
        end_idx = min(len(code), body_start + 8000)  # ⏱ cap body search window
        class_body = code[body_start:end_idx]

        # methods
        for mm in METHOD_HEADER_RE.finditer(class_body):
            method_name = mm.group(2)
            if method_name in CONTROL_KEYWORDS:
                continue
            fqn_method = f"{fqn_class}.{method_name}"
            ALL_DEFINED_METHODS.add(method_name)
            ALL_DEFINED_METHODS.add(fqn_method)
            if not collect_methods_only:
                relations.append(
                    {"from": fqn_class, "to": fqn_method, "type": "has_method", "role": role}
                )

        if collect_methods_only:
            continue

        # autowired
        for am in AUTOWIRED_FIELD_RE.finditer(class_body):
            field_type = re.sub(r"\s+", " ", am.group(1).strip())
            relations.append(
                {"from": fqn_class, "to": field_type, "type": "autowired", "role": role}
            )

        # constructors
        constructor_re = re.compile(
            CONSTRUCTOR_RE_TEMPLATE.format(cls=re.escape(cls_name)), re.MULTILINE
        )
        for _ in constructor_re.finditer(class_body):
            ctor_name = f"{fqn_class}.{cls_name}"
            relations.append(
                {"from": fqn_class, "to": ctor_name, "type": "has_constructor", "role": role}
            )

        # method calls
        for mm in METHOD_HEADER_RE.finditer(class_body):
            method_name = mm.group(2)
            fqn_method = f"{fqn_class}.{method_name}"
            method_text = class_body[mm.end() - 1 : mm.end() + 4000]  # cap 4k per method
            for call_m in CALL_RE.finditer(method_text):
                call_name = call_m.group(1)
                if call_name in CONTROL_KEYWORDS or call_name == method_name:
                    continue
                if call_name in ALL_DEFINED_METHODS:
                    relations.append(
                        {"from": fqn_method, "to": call_name, "type": "calls", "role": role}
                    )
    return relations


# --------------------------- Repo Graph ---------------------------
def build_repo_graph(repo_path):
    java_files = [
        os.path.join(root, f)
        for root, _, files in os.walk(repo_path)
        for f in files if f.endswith(".java")
    ]
    print(f"📄 Found {len(java_files)} Java files")

    # Pass 1: collect all method names (parallel)
    print("🔍 Pass 1: Collecting method names...")
    with ThreadPoolExecutor(max_workers=multiprocessing.cpu_count()) as ex:
        futures = {ex.submit(open, path, "r", encoding="utf-8", errors="ignore"): path for path in java_files}
        for fut in as_completed(futures):
            path = futures[fut].name if hasattr(futures[fut], 'name') else futures[fut]
            try:
                code = fut.result().read()
                regex_parse_java(path, code, collect_methods_only=True)
            except Exception as e:
                print(f"⚠️ Error scanning {path}: {e}")

    # Pass 2: build relations (parallel)
    print("🔗 Pass 2: Building relations...")
    all_relations = []
    with ThreadPoolExecutor(max_workers=multiprocessing.cpu_count()) as ex:
        futures = {
            ex.submit(
                lambda p: regex_parse_java(
                    p,
                    open(p, "r", encoding="utf-8", errors="ignore").read()
                ),
                path,
            ): path
            for path in java_files
        }
        for fut in as_completed(futures):
            try:
                rels = fut.result()
                all_relations.extend(rels)
            except Exception as e:
                print(f"⚠️ Error parsing {futures[fut]}: {e}")

    return all_relations


# --------------------------- Export ---------------------------
def export_json(relations, output_prefix="repo_graph"):
    json_path = f"{output_prefix}.json"
    data = {"relations": relations}
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"✅ Exported JSON: {json_path}")


# --------------------------- Main ---------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build Java repo dependency graph (parallel, JSON only)")
    parser.add_argument("--repo-url", help="Git repo URL")
    parser.add_argument("--branch", default="master")
    parser.add_argument("--repo", help="Local repo path")
    parser.add_argument("--output", default="repo_graph")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    repo_path = args.repo
    temp_repo = None
    if args.repo_url:
        repo_path = clone_repo(args.repo_url, args.branch)
        temp_repo = repo_path

    if not repo_path or not os.path.exists(repo_path):
        raise ValueError("❌ Provide --repo (local path) or --repo-url (remote Git URL)")

    print(f"📦 Building dependency graph for repo: {repo_path}")
    relations = build_repo_graph(repo_path)
    print(f"🧩 Found {len(relations)} relations")
    export_json(relations, args.output)

    if args.cleanup and temp_repo:
        print(f"🧹 Cleaning up {temp_repo}")
        shutil.rmtree(temp_repo)

    print("✅ Done!")
