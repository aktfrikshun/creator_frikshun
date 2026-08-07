import re


def split_tags(value):
    if not value:
        return []
    if isinstance(value, list):
        return compact_tags(value)

    value = str(value)
    if value.count("#") > 1:
        return compact_tags(re.findall(r"#([^#,\s]+)", value))
    return compact_tags(part.strip() for part in value.split(","))


def compact_tags(tags):
    seen = set()
    compacted = []
    for tag in tags:
        normalized = str(tag).strip().lstrip("#")
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        compacted.append(normalized.replace(" ", ""))
    return compacted
