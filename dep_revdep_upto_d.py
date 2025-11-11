#!/usr/bin/env python3
import os
import re
import tempfile
import shutil
from git import Repo

# --- Regex patterns ---
IMPORT_RE = re.compile(r'^\s*import\s+([a-zA-Z0-9_.*]+);\s*$', re.MULTILINE)
PACKAGE_RE = re.compile(r'^\s*package\s+([\w.]+)\s*;', re.MULTILINE)
METHOD_RE = re.compile(
    r'(?:@\w+(?:\([^)]*\))?\s*)*'
    r'(?:public|protected|private)?\s*'
    r'(?:static|final|synchronized|abstract|default)?\s*'
    r'[\w<>\[\],\s]+\s+'
    r'([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*\{',
    re.MULTILINE
)
CLASS_RE = re.compile(
    r'(?:@\w+(?:\([^)]*\))?\s*)*'
    r'(?:public|protected|private)?\s*'
    r'(?:abstract|final|static)?\s*'
    r'(class|interface|enum|record)\s+([A-Za-z_][A-Za-z0-9_]*)'
)

# --- Repo utils ---
def clone_repo(repo_url, branch="master"):
    tmp = tempfile.mkdtemp(prefix="context_repo_")
    print(f"📥 Cloning {repo_url} (branch: {branch}) → {tmp}")
    repo = Repo.clone_from(repo_url, tmp)
    try:
        repo.git.checkout(branch)
    except Exception:
        print(f"⚠️ Branch '{branch}' not found — using default branch instead.")
    return tmp


def java_package_to_path(package_name: str):
    return package_name.replace(".", "/")


def extract_imports_and_used(code):
    imports = IMPORT_RE.findall(code)
    identifiers = re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\b', code)
    ignore = {
        "if", "for", "while", "switch", "catch", "return", "throw", "new",
        "class", "public", "private", "protected", "static", "final", "void",
        "int", "float", "double", "boolean", "extends", "implements", "try"
    }
    identifiers = set(i for i in identifiers if i not in ignore)
    return imports, identifiers


def resolve_import(import_name, repo_path):
    base_src = os.path.join(repo_path, "src/main/java")
    results = []
    if import_name.endswith(".*"):
        pkg_path = java_package_to_path(import_name[:-2])
        full_dir = os.path.join(base_src, pkg_path)
        if os.path.isdir(full_dir):
            for f in os.listdir(full_dir):
                if f.endswith(".java"):
                    results.append(os.path.join(full_dir, f))
    else:
        file_path = os.path.join(base_src, java_package_to_path(import_name) + ".java")
        if os.path.exists(file_path):
            results.append(file_path)
    return results


def extract_full_method(code, method_name):
    for m in METHOD_RE.finditer(code):
        name = m.group(1)
        if name == method_name:
            start = m.start()
            depth = 0
            for i in range(m.end(), len(code)):
                if code[i] == '{':
                    depth += 1
                elif code[i] == '}':
                    if depth == 0:
                        return code[start:i + 1]
                    depth -= 1
            return code[start:]
    return None


def extract_full_class(code):
    match = CLASS_RE.search(code)
    if not match:
        return code
    start = match.start()
    depth = 0
    for i in range(match.end(), len(code)):
        if code[i] == '{':
            depth += 1
        elif code[i] == '}':
            depth -= 1
            if depth == 0:
                return code[start:i + 1]
    return code


# --- Level 2: Reverse dependencies ---
def find_reverse_dependencies(repo_path, target_fqn):
    base_name = target_fqn.split(".")[-1]
    results = []
    for root, _, files in os.walk(repo_path):
        for f in files:
            if not f.endswith(".java"):
                continue
            path = os.path.join(root, f)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as src:
                    text = src.read()
                    if (f"import {target_fqn}" in text
                        or re.search(rf'\b{base_name}\b', text)
                        or re.search(rf'@Autowired\s+[A-Za-z_]+\s*{base_name}', text)):
                        results.append(path)
            except Exception:
                continue
    return results


# --- Level 3: Bean/config references ---
def find_bean_configurations(repo_path, target_class_name):
    results = []
    for root, _, files in os.walk(repo_path):
        for f in files:
            if not f.endswith(".java"):
                continue
            path = os.path.join(root, f)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as src:
                    text = src.read()
                    if (
                        "@Configuration" in text and f"new {target_class_name}" in text
                    ) or ("@Bean" in text and target_class_name in text):
                        results.append(path)
                    elif re.search(rf'@Qualifier\(["\']{target_class_name}["\']\)', text):
                        results.append(path)
            except Exception:
                continue
    return results


# --- Level 4: Inheritance/interfaces ---
def find_inheritance_dependencies(code, repo_path):
    """Find extended or implemented classes/interfaces."""
    matches = re.findall(r'(?:extends|implements)\s+([A-Za-z0-9_.,\s<>]+)', code)
    deps = []
    for m in matches:
        for part in re.split(r'[,\s]+', m.strip()):
            if not part:
                continue
            results = resolve_import(part, repo_path)
            deps.extend(results)
    return deps


def recursive_reverse_dependencies(repo_path, target_fqn, depth, visited=None):
    """Find reverse dependencies up to a given depth."""
    if depth <= 0:
        return []
    if visited is None:
        visited = set()
    if target_fqn in visited:
        return []
    visited.add(target_fqn)

    results = []
    files = find_reverse_dependencies(repo_path, target_fqn)
    for f in files:
        results.append(f)
        code = open(f, "r", encoding="utf-8", errors="ignore").read()
        pkg = PACKAGE_RE.search(code)
        cls = re.search(r'class\s+([A-Za-z_][A-Za-z0-9_]*)', code)
        if pkg and cls:
            fqn = f"{pkg.group(1)}.{cls.group(1)}"
            results.extend(recursive_reverse_dependencies(repo_path, fqn, depth - 1, visited))
    return list(set(results))


# --- Main context builder ---
def prepare_context(repo_path, target_file_path, output_file="context_full.txt", depth=1):
    target_full_path = os.path.join(repo_path, target_file_path)
    if not os.path.exists(target_full_path):
        raise FileNotFoundError(f"❌ Target file not found: {target_full_path}")

    print(f"📦 Analyzing {target_file_path}")
    code = open(target_full_path, "r", encoding="utf-8", errors="ignore").read()
    imports, used_identifiers = extract_imports_and_used(code)
    print(f"📦 Found {len(imports)} imports, {len(used_identifiers)} used identifiers")

    # Identify current class & FQN
    pkg_match = PACKAGE_RE.search(code)
    class_match = re.search(r'class\s+([A-Za-z_][A-Za-z0-9_]*)', code)
    current_pkg = pkg_match.group(1) if pkg_match else None
    current_class = class_match.group(1) if class_match else None
    current_fqn = f"{current_pkg}.{current_class}" if current_pkg and current_class else None

    output_chunks = []

    # --- Level 1: Direct imports ---
    for imp in imports:
        resolved_files = resolve_import(imp, repo_path)
        if not resolved_files:
            continue
        for file_path in resolved_files:
            code_text = open(file_path, "r", encoding="utf-8", errors="ignore").read()
            output_chunks.append(f"=== IMPORT {imp} ===\n# File: {file_path}\n\n{extract_full_class(code_text)}\n\n")

    # --- Level 4: Inheritance/interfaces ---
    inheritance_files = find_inheritance_dependencies(code, repo_path)
    for f in inheritance_files:
        src = open(f, "r", encoding="utf-8", errors="ignore").read()
        output_chunks.append(f"=== EXTENDS / IMPLEMENTS ===\n# File: {f}\n\n{src}\n\n")

    # --- Level 2: Reverse dependencies (recursive) ---
    if current_fqn:
        reverse_files = recursive_reverse_dependencies(repo_path, current_fqn, depth)
        for fpath in reverse_files:
            src = open(fpath, "r", encoding="utf-8", errors="ignore").read()
            output_chunks.append(f"=== REVERSE DEPENDENCY ===\n# File: {fpath}\n\n{src}\n\n")

    # --- Level 3: Bean/config references ---
    if current_class:
        bean_files = find_bean_configurations(repo_path, current_class)
        for fpath in bean_files:
            src = open(fpath, "r", encoding="utf-8", errors="ignore").read()
            output_chunks.append(f"=== BEAN / CONFIGURATION ===\n# File: {fpath}\n\n{src}\n\n")

    # --- Write output ---
    if not output_chunks:
        print("⚠️ No relevant context found.")
        return

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"# Context for {target_file_path}\n# Repo: {repo_path}\n\n")
        for chunk in output_chunks:
            f.write(chunk)

    print(f"✅ Context file written: {output_file} ({len(output_chunks)} code blocks)")


# --- CLI entry ---
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate full Java context with imports, inheritance, reverse deps, and beans")
    parser.add_argument("--repo-url", help="GitHub repo URL")
    parser.add_argument("--branch", default="master")
    parser.add_argument("--repo", help="Local repo path")
    parser.add_argument("--file", required=True, help="Target Java file path relative to repo root")
    parser.add_argument("--output", default="context_full.txt")
    parser.add_argument("--depth", type=int, default=1, help="Depth for recursive reverse dependency traversal")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    repo_path = args.repo
    temp_repo = None
    if args.repo_url:
        repo_path = clone_repo(args.repo_url, args.branch)
        temp_repo = repo_path

    prepare_context(repo_path, args.file, args.output, args.depth)

    if args.cleanup and temp_repo:
        print(f"🧹 Cleaning up {temp_repo}")
        shutil.rmtree(temp_repo)
