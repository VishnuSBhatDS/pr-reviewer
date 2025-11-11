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
    r'(?:@\w+(?:\([^)]*\))?\s*)*'  # annotations
    r'(?:public|protected|private)?\s*'
    r'(?:static|final|synchronized|abstract|default)?\s*'
    r'[\w<>\[\],\s]+\s+'
    r'([A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*\{',  # method name + body
    re.MULTILINE
)
CLASS_RE = re.compile(
    r'(?:@\w+(?:\([^)]*\))?\s*)*'
    r'(?:public|protected|private)?\s*'
    r'(?:abstract|final|static)?\s*'
    r'(class|interface|enum|record)\s+([A-Za-z_][A-Za-z0-9_]*)'
)

# --- Helpers ---
def clone_repo(repo_url, branch="master"):
    tmp = tempfile.mkdtemp(prefix="context_repo_")
    print(f"📥 Cloning {repo_url} (branch: {branch}) → {tmp}")
    repo = Repo.clone_from(repo_url, tmp)
    repo.git.checkout(branch)
    return tmp


def java_package_to_path(package_name: str):
    return package_name.replace(".", "/")


def extract_imports_and_used(code):
    """Extract imports and identifiers used (methods, classes)."""
    imports = IMPORT_RE.findall(code)
    identifiers = re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\b', code)
    # Exclude Java keywords and control flow
    ignore = {
        "if", "for", "while", "switch", "catch", "return", "throw", "new",
        "class", "public", "private", "protected", "static", "final", "void",
        "int", "float", "double", "boolean", "extends", "implements", "try"
    }
    identifiers = set(i for i in identifiers if i not in ignore)
    return imports, identifiers


def resolve_import(import_name, repo_path):
    """Resolve import → local file(s)"""
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
    """Extract entire method block including annotations."""
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
                        return code[start:i+1]
                    depth -= 1
            return code[start:]
    return None


def extract_full_class(code):
    """Return full class/interface/enum."""
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
                return code[start:i+1]
    return code


def prepare_context(repo_path, target_file_path, output_file="context_filtered.txt"):
    target_full_path = os.path.join(repo_path, target_file_path)
    if not os.path.exists(target_full_path):
        raise FileNotFoundError(f"❌ Target file not found: {target_full_path}")

    print(f"📦 Analyzing {target_file_path}")
    code = open(target_full_path, "r", encoding="utf-8", errors="ignore").read()
    imports, used_identifiers = extract_imports_and_used(code)
    print(f"📦 Found {len(imports)} imports, {len(used_identifiers)} used identifiers")

    output_chunks = []

    for imp in imports:
        resolved_files = resolve_import(imp, repo_path)
        if not resolved_files:
            continue  # ❌ skip if nothing found

        if imp.endswith(".*"):
            # Wildcard import → filter by actually used classes in that package
            for file_path in resolved_files:
                try:
                    code_text = open(file_path, "r", encoding="utf-8", errors="ignore").read()
                    class_match = CLASS_RE.search(code_text)
                    if not class_match:
                        continue
                    class_name = class_match.group(2)
                    if class_name not in used_identifiers:
                        continue  # skip unused
                    class_block = extract_full_class(code_text)
                    if class_block.strip():
                        output_chunks.append(
                            f"=== IMPORT {imp}::{class_name} ===\n# File: {file_path}\n\n{class_block}\n\n"
                        )
                except Exception as e:
                    print(f"⚠️ Error reading {file_path}: {e}")
        else:
            # Direct import (specific class)
            for file_path in resolved_files:
                try:
                    code_text = open(file_path, "r", encoding="utf-8", errors="ignore").read()
                    class_match = CLASS_RE.search(code_text)
                    class_block = extract_full_class(code_text)
                    class_name = class_match.group(2) if class_match else None

                    # Find used methods from this class
                    method_names = re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(', code_text)
                    used_methods = [m for m in method_names if m in used_identifiers]

                    # If no methods are used, include full class
                    if not used_methods:
                        if class_block.strip():
                            output_chunks.append(
                                f"=== IMPORT {imp} (FULL CLASS) ===\n# File: {file_path}\n\n{class_block}\n\n"
                            )
                    else:
                        for m in used_methods:
                            method_code = extract_full_method(code_text, m)
                            if method_code and method_code.strip():
                                output_chunks.append(
                                    f"=== IMPORT {imp}.{m} (METHOD) ===\n# File: {file_path}\n\n{method_code}\n\n"
                                )
                except Exception as e:
                    print(f"⚠️ Error parsing {file_path}: {e}")

    # Only write if there are any chunks
    if not output_chunks:
        print("⚠️ No relevant imports found.")
        return

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"# Context for {target_file_path}\n# Repo: {repo_path}\n\n")
        for chunk in output_chunks:
            f.write(chunk)

    print(f"✅ Context file written: {output_file} ({len(output_chunks)} code blocks)")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate filtered import context with code")
    parser.add_argument("--repo-url", help="GitHub repo URL")
    parser.add_argument("--branch", default="master")
    parser.add_argument("--repo", help="Local repo path")
    parser.add_argument("--file", required=True, help="Target Java file path relative to repo root")
    parser.add_argument("--output", default="context_filtered.txt")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    repo_path = args.repo
    temp_repo = None
    if args.repo_url:
        repo_path = clone_repo(args.repo_url, args.branch)
        temp_repo = repo_path

    prepare_context(repo_path, args.file, args.output)

    if args.cleanup and temp_repo:
        print(f"🧹 Cleaning up {temp_repo}")
        shutil.rmtree(temp_repo)
