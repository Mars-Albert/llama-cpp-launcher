# -*- coding: utf-8 -*-
"""Check .github/workflows/release.yml without running CI.

Why this exists: the notes step is a `run: |` block whose body contains a bash
heredoc, and an edit that leaves stray mapping keys (draft:/prerelease:) below it
parses as *valid YAML* - the keys just get swallowed into the shell script and
each fail at run time as `draft:: command not found`. That happened twice while
fixing the v1.9.1 release, and only a run of the extracted script caught it. It
also byte-compiles the two embedded python blocks, which YAML will happily
accept however broken they are.

Usage: python tools/_check_release_wf.py   (writes the extracted scripts to temp)
"""
import io
import py_compile
import sys
import tempfile

try:
    import yaml
except ModuleNotFoundError:  # dev-only check tool; not a runtime dependency
    sys.exit("needs PyYAML (dev-only): pip install pyyaml")

sys.stdout.reconfigure(encoding="utf-8")
WF = ".github/workflows/release.yml"
OUT = tempfile.gettempdir()

d = yaml.safe_load(io.open(WF, encoding="utf-8"))
steps = d["jobs"]["build"]["steps"]
by_name = {s.get("name"): s for s in steps}
print("steps:", [s.get("name") for s in steps])

rel = by_name["Create GitHub Release"]["with"]
print("release action inputs:", sorted(rel))

notes = by_name["Write release notes from the tag message"]["run"]
notes = notes.replace("${{ steps.version.outputs.TAG }}", "v1.9.1")
enf = by_name["Enforce the release body and prove it landed"]["run"]
enf = enf.replace("${{ steps.version.outputs.TAG }}", "v1.9.1")
io.open(OUT + r"\s_notes.sh", "w", encoding="utf-8", newline="\n").write(notes)
io.open(OUT + r"\s_enf.sh", "w", encoding="utf-8", newline="\n").write(enf)

for tag, script in (("notes", notes), ("enforce", enf)):
    lines = script.split("\n")
    start = next(i for i, l in enumerate(lines) if "<<'PY'" in l)
    body = []
    for line in lines[start + 1:]:
        if line.strip() == "PY":
            break
        body.append(line)
    end = next(i for i, l in enumerate(lines) if l.strip() == "PY")
    trailing = [l for l in lines[end + 1:] if l.strip()]
    print(f"{tag}: python {len(body)} lines, script trailing lines after heredoc: "
          f"{len(trailing)} {trailing[:2]}")
    path = tempfile.mktemp(suffix=".py")
    io.open(path, "w", encoding="utf-8", newline="\n").write("\n".join(body))
    py_compile.compile(path, doraise=True)
    print(f"{tag}: python compiles ok")
