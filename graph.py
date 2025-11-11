#!/usr/bin/env python3
import re

# --- Spring stereotypes for detection ---
SPRING_ANNOTATIONS = {
    "Controller": "controller",
    "RestController": "controller",
    "Service": "service",
    "Repository": "repository",
    "Component": "component",
    "Configuration": "configuration"
}

PACKAGE_RE = re.compile(r'^\s*package\s+([\w.]+)\s*;', re.MULTILINE)
CLASS_RE = re.compile(
    r'(?:@\w+(?:\([^)]*\))?\s*)*'
    r'(?:public|protected|private)?\s*'
    r'(?:abstract|final|static)?\s*'
    r'(class|interface|enum|record)\s+'
    r'([A-Za-z_][A-Za-z0-9_]*)',
    re.MULTILINE
)
AUTOWIRED_FIELD_RE = re.compile(
    r'@Autowired\b(?:\s*\([^)]*\))?\s*'
    r'(?:@Qualifier\([^\)]*\)\s*)*'
    r'(?:private|protected|public)?\s*'
    r'([\w\<\>\.\,\s\?\[\]]+?)\s+'
    r'([A-Za-z_][A-Za-z0-9_]*)\s*;',
    re.MULTILINE
)
METHOD_HEADER_RE = re.compile(
    r'(?:@\w+(?:\([^)]*\))?\s*)*'
    r'(?:public|protected|private)?\s*'
    r'(?:static|final|synchronized|abstract|default)?\s*'
    r'([\w\<\>\.\[\],\s\?]+)\s+'   # return type
    r'([A-Za-z_][A-Za-z0-9_]*)\s*' # method name
    r'\([^)]*\)\s*'
    r'(?:throws\s+[^{]+)?\s*'
    r'\{',
    re.MULTILINE
)
CONSTRUCTOR_RE_TEMPLATE = (
    r'(?:@\w+(?:\([^)]*\))?\s*)*(?:public|protected|private)?\s*{cls}\s*\([^)]*\)\s*\{{'
)

# detect simple method calls within body
CALL_RE = re.compile(
    r'(?:\bthis\.|\bsuper\.|[A-Za-z_][A-Za-z0-9_]*\.)?([A-Za-z_][A-Za-z0-9_]*)\s*\('
)

CONTROL_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "throw", "new"}


def regex_parse_java(file_path, code):
    relations = []
    package = "default"
    pm = PACKAGE_RE.search(code)
    if pm:
        package = pm.group(1)

    for cm in CLASS_RE.finditer(code):
        cls_kind = cm.group(1)
        cls_name = cm.group(2)
        fqn_class = f"{package}.{cls_name}"

        prefix_start = max(0, cm.start() - 400)
        prefix = code[prefix_start:cm.start()]
        role = "class"
        annos = re.findall(r'@([A-Za-z0-9_\.]+)', prefix)
        for a in annos:
            for k, v in SPRING_ANNOTATIONS.items():
                if k.lower() in a.lower():
                    role = v
                    break
            if role != "class":
                break

        relations.append({"from": fqn_class, "to": None, "type": "declares", "role": role})

        tail_region = code[cm.end():cm.end() + 400]
        ext_m = re.search(r'\bextends\s+([A-Za-z0-9_\.<>]+)', tail_region)
        if ext_m:
            relations.append({"from": fqn_class, "to": ext_m.group(1), "type": "extends", "role": role})
        impl_m = re.search(r'\bimplements\s+([A-Za-z0-9_\<\>\.,\s]+)', tail_region)
        if impl_m:
            impls = [s.strip() for s in impl_m.group(1).split(",")]
            for impl in impls:
                relations.append({"from": fqn_class, "to": impl, "type": "implements", "role": "interface"})

        body_start = code.find('{', cm.end())
        if body_start == -1:
            continue
        i = body_start
        depth = 0
        end_idx = len(code)
        while i < len(code):
            if code[i] == '{':
                depth += 1
            elif code[i] == '}':
                depth -= 1
                if depth == 0:
                    end_idx = i
                    break
            i += 1
        class_body = code[body_start:end_idx + 1]

        # autowired fields
        for am in AUTOWIRED_FIELD_RE.finditer(class_body):
            field_type = re.sub(r'\s+', ' ', am.group(1).strip())
            relations.append({"from": fqn_class, "to": field_type, "type": "autowired", "role": role})

        # constructors
        constructor_re = re.compile(CONSTRUCTOR_RE_TEMPLATE.format(cls=re.escape(cls_name)), re.MULTILINE)
        for _ in constructor_re.finditer(class_body):
            ctor_name = f"{fqn_class}.{cls_name}"
            relations.append({"from": fqn_class, "to": ctor_name, "type": "has_constructor", "role": role})

        # methods
        for mm in METHOD_HEADER_RE.finditer(class_body):
            method_name = mm.group(2)
            if method_name in CONTROL_KEYWORDS:
                continue
            fqn_method = f"{fqn_class}.{method_name}"
            relations.append({"from": fqn_class, "to": fqn_method, "type": "has_method", "role": role})

            # Extract method body
            start_pos = mm.end() - 1
            j = start_pos
            depth2 = 0
            method_end = start_pos
            while j < len(class_body):
                if class_body[j] == '{':
                    depth2 += 1
                elif class_body[j] == '}':
                    depth2 -= 1
                    if depth2 == 0:
                        method_end = j
                        break
                j += 1
            method_text = class_body[start_pos:method_end + 1]

            # find method calls inside body
            for call_m in CALL_RE.finditer(method_text):
                call_name = call_m.group(1)
                if call_name in CONTROL_KEYWORDS or call_name == method_name:
                    continue
                relations.append({"from": fqn_method, "to": call_name, "type": "calls", "role": role})

    return relations


# === test ===
if __name__ == "__main__":
    file_path = "/Users/dealshare/Downloads/cart-service/src/main/java/com/dealshare/service/cartservice/services/impl/CartConfigV2ServiceImpl.java"

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        code = f.read()

    rels = regex_parse_java(file_path, code)
    print(f"✅ Parsed {len(rels)} relations:")
    for r in rels:
        print(f"{r['type']:>12} | {r['from']} -> {r.get('to','')} ({r['role']})")
