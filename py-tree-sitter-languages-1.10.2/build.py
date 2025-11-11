#!/usr/bin/env python3
"""
Fixed build script for py-tree-sitter-languages on macOS ARM (M1/M2/M3)
Forces use of Homebrew LLVM clang++ and patches distutils to link correctly.
"""

import os
import sysconfig
import setuptools._distutils.unixccompiler as unixccompiler
from tree_sitter import Language

# --------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------
LLVM_PATH = "/opt/homebrew/opt/llvm/bin/clang++"

LANGUAGES_SO_PATH = "tree_sitter_languages/languages.so"

LANGUAGE_REPOS = [
    'vendor/tree-sitter-bash',
    'vendor/tree-sitter-c',
    'vendor/tree-sitter-c-sharp',
    'vendor/tree-sitter-commonlisp',
    'vendor/tree-sitter-cpp',
    'vendor/tree-sitter-css',
    'vendor/tree-sitter-dockerfile',
    'vendor/tree-sitter-dot',
    'vendor/tree-sitter-elisp',
    'vendor/tree-sitter-elixir',
    'vendor/tree-sitter-elm',
    'vendor/tree-sitter-embedded-template',
    'vendor/tree-sitter-erlang',
    'vendor/tree-sitter-fixed-form-fortran',
    'vendor/tree-sitter-fortran',
    'vendor/tree-sitter-go',
    'vendor/tree-sitter-go-mod',
    'vendor/tree-sitter-hack',
    'vendor/tree-sitter-haskell',
    'vendor/tree-sitter-hcl',
    'vendor/tree-sitter-html',
    'vendor/tree-sitter-java',
    'vendor/tree-sitter-javascript',
    'vendor/tree-sitter-jsdoc',
    'vendor/tree-sitter-json',
    'vendor/tree-sitter-julia',
    'vendor/tree-sitter-kotlin',
    'vendor/tree-sitter-lua',
    'vendor/tree-sitter-make',
    'vendor/tree-sitter-markdown',
    'vendor/tree-sitter-objc',
    'vendor/tree-sitter-ocaml/ocaml',
    'vendor/tree-sitter-perl',
    'vendor/tree-sitter-php',
    'vendor/tree-sitter-python',
    'vendor/tree-sitter-ql',
    'vendor/tree-sitter-r',
    'vendor/tree-sitter-regex',
    'vendor/tree-sitter-rst',
    'vendor/tree-sitter-ruby',
    'vendor/tree-sitter-rust',
    'vendor/tree-sitter-scala',
    'vendor/tree-sitter-sql',
    'vendor/tree-sitter-sqlite',
    'vendor/tree-sitter-toml',
    'vendor/tree-sitter-tsq',
    'vendor/tree-sitter-typescript/tsx',
    'vendor/tree-sitter-typescript/typescript',
    'vendor/tree-sitter-yaml',
]

# --------------------------------------------------------------------
# Force macOS LLVM clang++ toolchain
# --------------------------------------------------------------------
os.environ["CC"] = "/usr/bin/clang"
os.environ["CXX"] = LLVM_PATH
os.environ["CFLAGS"] = "-std=c++17 -fPIC -O3"
os.environ["CPPFLAGS"] = "-I/opt/homebrew/opt/llvm/include"
os.environ["LDFLAGS"] = "-L/opt/homebrew/opt/llvm/lib -dynamiclib -undefined dynamic_lookup"

cfg_vars = sysconfig.get_config_vars()
for key in ("CC", "CXX", "LDSHARED"):
    cfg_vars[key] = f"{LLVM_PATH} -shared -undefined dynamic_lookup"

print("🔧 Forcing compiler:", LLVM_PATH)
print("🔧 Using linker flags:", os.environ["LDFLAGS"])

# --------------------------------------------------------------------
# Monkeypatch distutils.spawn to always use clang++
# --------------------------------------------------------------------
def force_clang_spawn(cmd, **kwargs):
    """Intercept compiler calls and redirect /usr/bin/c++ → clang++"""
    if cmd and isinstance(cmd, list) and cmd[0] == "/usr/bin/c++":
        cmd[0] = LLVM_PATH
        cmd.insert(1, "-dynamiclib")
        cmd.insert(2, "-undefined")
        cmd.insert(3, "dynamic_lookup")
        print("⚙️  Redirected compiler command →", " ".join(cmd))
    from subprocess import check_call
    return check_call(cmd, **kwargs)

unixccompiler.spawn = force_clang_spawn

# --------------------------------------------------------------------
# Build library
# --------------------------------------------------------------------
print("\n🏗️  Building Tree-sitter languages shared library...\n")
Language.build_library(LANGUAGES_SO_PATH, LANGUAGE_REPOS)
print(f"\n✅ Build complete → {LANGUAGES_SO_PATH}\n")
