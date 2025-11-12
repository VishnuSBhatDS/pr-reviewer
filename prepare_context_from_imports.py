#!/usr/bin/env python3
import os
import re
import tempfile
import shutil
from git import Repo

# --- Regex patterns ---
IMPORT_RE = re.compile(r'^\s*import\s+([a-zA-Z0-9_.*]+)\s*;\s*$', re.MULTILINE)
PACKAGE_RE = re.compile(r'^\s*package\s+([\w.]+)\s*;', re.MULTILINE)
TYPE_RE = re.compile(
    r'(?:@\w+(?:\([^)]*\))?\s*)*'  # annotations
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
            for root, _, files in os.walk(full_dir):
                for f in files:
                    if f.endswith(".java"):
                        results.append(os.path.join(root, f))
    else:
        file_path = os.path.join(base_src, java_package_to_path(import_name) + ".java")
        if os.path.exists(file_path):
            results.append(file_path)
    return results


def extract_full_type(code):
    """Extracts a full class/interface/enum/record definition with braces."""
    match = TYPE_RE.search(code)
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
def find_reverse_dependencies(repo_path, target_fqn, include_tests=False):
    """
    Find all Java files that reference or implement/extend a given type.
    Includes direct imports, implements, extends, annotations, generics, etc.
    Works for classes, interfaces, enums, and records.
    """
    base_name = target_fqn.split(".")[-1]
    package_name = ".".join(target_fqn.split(".")[:-1])

    patterns = [
        rf'import\s+{re.escape(target_fqn)}\s*;',                 # exact import
        rf'\bimplements\b[\s\S]*?\b{re.escape(base_name)}\b',     # implements
        rf'\bextends\b[\s\S]*?\b{re.escape(base_name)}\b',        # extends
        rf'new\s+{re.escape(base_name)}\s*\(',                     # constructor usage
        rf'@Autowired[\s\S]*?\b{re.escape(base_name)}\b',          # @Autowired
        rf'@Inject[\s\S]*?\b{re.escape(base_name)}\b',             # @Inject
        rf'@Qualifier\s*\(\s*["\']{re.escape(base_name)}["\']\s*\)',  # @Qualifier("Base")
        rf'<\s*{re.escape(base_name)}\s*>',                        # generics <Base>
        rf'\b{re.escape(base_name)}\s+[A-Za-z_][A-Za-z0-9_]*\b',   # variable declarations
        rf'\b{re.escape(base_name)}\s*\.',                         # static access
    ]

    combined_re = re.compile("|".join(patterns), re.MULTILINE | re.DOTALL)
    results = []

    for root, _, files in os.walk(repo_path):
        for f in files:
            if not f.endswith(".java"):
                continue

            # 🔒 Skip test files unless explicitly included
            if not include_tests and re.search(r'(?i)test\.java$', f):
                continue

            path = os.path.join(root, f)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as src:
                    text = src.read()

                    # same-package implementations (no import)
                    pkg_match = PACKAGE_RE.search(text)
                    file_pkg = pkg_match.group(1) if pkg_match else None
                    if file_pkg == package_name:
                        if re.search(rf'\b(implements|extends)\b[\s\S]*?\b{re.escape(base_name)}\b', text):
                            results.append(path)
                            continue

                    if combined_re.search(text):
                        results.append(path)
            except Exception:
                continue

    return list(set(results))


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
                        ("@Configuration" in text and f"new {target_class_name}" in text)
                        or ("@Bean" in text and target_class_name in text)
                        or re.search(rf'@Qualifier\(["\']{target_class_name}["\']\)', text)
                    ):
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


def recursive_reverse_dependencies(repo_path, target_fqn, depth, include_tests=False, limit=None, visited=None):
    """Find reverse dependencies up to a given depth."""
    if depth <= 0:
        return []
    if visited is None:
        visited = set()
    if target_fqn in visited:
        return []
    visited.add(target_fqn)

    results = []
    files = find_reverse_dependencies(repo_path, target_fqn, include_tests=include_tests)

    # Apply reverse dependency limit per level
    if limit:
        files = files[:limit]

    for f in files:
        results.append(f)
        try:
            code = open(f, "r", encoding="utf-8", errors="ignore").read()
            pkg = PACKAGE_RE.search(code)
            cls = TYPE_RE.search(code)
            if pkg and cls:
                fqn = f"{pkg.group(1)}.{cls.group(2)}"
                results.extend(
                    recursive_reverse_dependencies(repo_path, fqn, depth - 1, include_tests, limit, visited)
                )
        except Exception:
            continue
    return list(set(results))


# --- Main context builder ---
def prepare_context_multi(repo_path, target_files, output_file="context_full.txt", depth=1, include_tests=False, reverse_limit=None):
    seen_files = set()
    output_chunks = []

    for target_file_path in target_files:
        target_full_path = os.path.join(repo_path, target_file_path)
        if not os.path.exists(target_full_path):
            print(f"⚠️ Skipping missing file: {target_file_path}")
            continue

        print(f"📦 Analyzing {target_file_path}")
        code = open(target_full_path, "r", encoding="utf-8", errors="ignore").read()
        imports, used_identifiers = extract_imports_and_used(code)
        print(f"📦 Found {len(imports)} imports, {len(used_identifiers)} used identifiers")

        pkg_match = PACKAGE_RE.search(code)
        type_match = TYPE_RE.search(code)
        current_pkg = pkg_match.group(1) if pkg_match else None
        current_class = type_match.group(2) if type_match else None
        current_fqn = f"{current_pkg}.{current_class}" if current_pkg and current_class else None

        # --- Level 1: Direct imports ---
        for imp in imports:
            resolved_files = resolve_import(imp, repo_path)
            if not resolved_files:
                continue

            if imp.endswith(".*"):
                # Only import wildcard classes actually used
                for file_path in resolved_files:
                    if file_path in seen_files:
                        continue
                    try:
                        code_text = open(file_path, "r", encoding="utf-8", errors="ignore").read()
                        match = TYPE_RE.search(code_text)
                        if not match:
                            continue
                        class_name = match.group(2)
                        if class_name not in used_identifiers:
                            continue
                        seen_files.add(file_path)
                        output_chunks.append(
                            f"=== IMPORT {imp}::{class_name} ===\n# File: {file_path}\n\n{extract_full_type(code_text)}\n\n"
                        )
                    except Exception:
                        continue
            else:
                for file_path in resolved_files:
                    if file_path in seen_files:
                        continue
                    seen_files.add(file_path)
                    code_text = open(file_path, "r", encoding="utf-8", errors="ignore").read()
                    output_chunks.append(
                        f"=== IMPORT {imp} ===\n# File: {file_path}\n\n{extract_full_type(code_text)}\n\n"
                    )

        # --- Level 4: Inheritance/interfaces ---
        for f in find_inheritance_dependencies(code, repo_path):
            if f in seen_files:
                continue
            seen_files.add(f)
            src = open(f, "r", encoding="utf-8", errors="ignore").read()
            output_chunks.append(f"=== EXTENDS / IMPLEMENTS ===\n# File: {f}\n\n{src}\n\n")

        # --- Level 2: Reverse dependencies ---
        if current_fqn:
            reverse_files = recursive_reverse_dependencies(
                repo_path, current_fqn, depth, include_tests, reverse_limit
            )
            for fpath in reverse_files:
                if fpath in seen_files:
                    continue
                seen_files.add(fpath)
                src = open(fpath, "r", encoding="utf-8", errors="ignore").read()
                output_chunks.append(f"=== REVERSE DEPENDENCY ===\n# File: {fpath}\n\n{src}\n\n")

        # --- Level 3: Bean/config references ---
        if current_class:
            bean_files = find_bean_configurations(repo_path, current_class)
            for fpath in bean_files:
                if fpath in seen_files:
                    continue
                seen_files.add(fpath)
                src = open(fpath, "r", encoding="utf-8", errors="ignore").read()
                output_chunks.append(f"=== BEAN / CONFIGURATION ===\n# File: {fpath}\n\n{src}\n\n")

    if not output_chunks:
        print("⚠️ No relevant context found.")
        return

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"# Context for {len(target_files)} files\n# Repo: {repo_path}\n\n")
        for chunk in output_chunks:
            f.write(chunk)

    print(f"✅ Context file written: {output_file} ({len(output_chunks)} code blocks, {len(seen_files)} unique files)")


# --- CLI entry ---
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate full Java context with imports, inheritance, reverse deps, and beans")
    parser.add_argument("--repo-url", help="GitHub repo URL")
    parser.add_argument("--branch", default="master")
    parser.add_argument("--repo", help="Local repo path")
    parser.add_argument("--files", nargs="+", required=True, help="Target Java files (relative to repo root)")
    parser.add_argument("--output", default="context_full.txt")
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--include-tests", action="store_true", help="Include test files (*Test.java) in reverse dependency search")
    parser.add_argument("--reverse-limit", type=int, help="Limit number of reverse dependency files per target file")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    repo_path = args.repo
    temp_repo = None
    if args.repo_url:
        repo_path = clone_repo(args.repo_url, args.branch)
        temp_repo = repo_path

    prepare_context_multi(
        repo_path,
        args.files,
        args.output,
        depth=args.depth,
        include_tests=args.include_tests,
        reverse_limit=args.reverse_limit,
    )

    if args.cleanup and temp_repo:
        print(f"🧹 Cleaning up {temp_repo}")
        shutil.rmtree(temp_repo)
