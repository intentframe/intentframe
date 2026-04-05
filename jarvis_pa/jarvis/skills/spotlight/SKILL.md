---
name: spotlight
description: Spotlight search via mdfind
version: "1.0"
metadata:
  requires:
    bins: ["mdfind"]
  os: ["darwin"]
---

# Spotlight

Use `mdfind` to search the local filesystem via Spotlight.

## Usage

- `mdfind "query"` – full-text search
- `mdfind -name "filename"` – search by name
- `mdfind "kMDItemContentType == 'com.adobe.pdf'"` – by file type

Use `search_spotlight` tool or `run_command` with mdfind.
