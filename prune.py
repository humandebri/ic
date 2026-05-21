#!/usr/bin/env python3

import sys
import subprocess
import tempfile
import os
import re
from pathlib import Path

def log(*args):
    print(*args, file=sys.stderr)

def run(cmd, **kwargs):
    loud = kwargs.pop("loud", False)
    if loud:
        log(f"Running: {' '.join(cmd)}")

    if not "stderr" in kwargs:
        kwargs.update({ 'capture_output': True, 'text': True })

    try:
        return subprocess.run(cmd, check=True, **kwargs)
    except subprocess.CalledProcessError as e:
        log(f"Error running: {' '.join(cmd)}")
        raise e

def extract_crate_names_from_log(log_path):
    crate_names = set()
    with open(log_path, 'r') as f:
        for line in f:
            m = re.search(r'resolving crate [`"]([^`"]+)[`"]', line)
            if m:
                crate_names.add(m.group(1))
    return sorted(crate_names)

def extract_deps_from_query_output(build_output):
    deps = []
    deps_block = re.search(r'deps\s*=\s*\[(.*?)\]', build_output, re.DOTALL)
    if deps_block:
        dep_list = deps_block.group(1)
        deps = [ target.strip()[1:-1] for target in dep_list.split(",") ]
        # Extract each string in quotes, even if separated by commas or newlines
        #deps = re.findall(r'"([^"]+)"', dep_list)
    return deps

target_to_crate = {}

def extract_crate_name_from_target(target):

    aliases = []

    global target_to_crate
    result = target_to_crate.get(target)
    if result:
        return result

    visited = set()

    while True:
        aliases.append(target)
        if target in visited:
            log(f"Cycle detected while resolving {target}")
            return None
        visited.add(target)

        result = run(["bazel", "query", target, "--output=build"])
        crate_name = None
        name = None
        actual = None

        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("actual ="):
                actual = line.split("=")[1].strip().strip(",").strip('"')
            elif line.startswith("crate_name ="):
                crate_name = line.split("=")[1].strip().strip(",").strip('"')
            elif line.startswith("name ="):
                name = line.split("=")[1].strip().strip(",").strip('"')

        if actual is not None:
            target = actual  # follow alias to real target
        elif crate_name or name:
            result = crate_name or name
            for alias in aliases:
                target_to_crate[alias] = result
            return result
        else:
            return None

def find_built_artifact(target):
    result = run(["bazel", "cquery", target, "--output=files"])
    files = result.stdout.strip().splitlines()
    # Pick the first file if there are multiple — adapt as needed
    return files[0] if files else None

def prune(target):


    try:
        # Step 2: Build the target once (to warm up dependencies)
        run(["bazel", "build", target,
             "--action_env=RUSTC_LOG=rustc_metadata=info",
             "--sandbox_debug"])
    except subprocess.CalledProcessError as e:
        # Print both stdout and stderr from the failed command
        print(f"bazel query failed with return code {e.returncode}", file=sys.stderr)
        print("stdout:\n" + e.stdout, file=sys.stderr)
        print("stderr:\n" + e.stderr, file=sys.stderr)
        raise e

    # Step 3: Find the built artifact
    artifact = find_built_artifact(target)
    if not artifact:
        log("Failed to locate built artifact.")
        sys.exit(1)

    # Step 4: Remove the artifact to force rebuild
    try:
        log(f"Removing artifact: {artifact}")
        os.remove(artifact)
    except FileNotFoundError:
        log("Artifact already removed.")

    # Step 5: Rebuild and capture log
    with tempfile.NamedTemporaryFile(delete=False, mode='w+', encoding='utf-8') as tmp:
        log(f"Capturing rustc log to: {tmp.name}")
        run([
            "bazel", "build", target,
            "--action_env=RUSTC_LOG=rustc_metadata=info",
            "--sandbox_debug",
            "--experimental_ui_max_stdouterr_bytes=20000000"
        ], stderr=tmp, loud=True)
        tmp.flush()

        # Step 6: Parse log to extract used crate names
        used_crates = extract_crate_names_from_log(tmp.name)


    # Step 7: Get deps from target's BUILD
    result = run(["bazel", "query", target, "--output=build"])
    deps = extract_deps_from_query_output(result.stdout)

    n_used_crates = len(used_crates)
    n_direct_deps = len(deps)
    log(f"\nDependencies: {n_direct_deps} ({n_used_crates} transitive)")
    # Step 8 + 9: For each dep, get crate_name or fallback to name, and check usage
    log(f"\nDependency Crate Usage for {target}:")
    unused = []
    for dep_target in deps:
        crate = extract_crate_name_from_target(dep_target)
        used = crate in used_crates
        message = "✅ used" if used else "❌ unused"
        if not used:
            unused.append(crate)
        log(f"  {crate:30} ({message})  ← {dep_target}")

    n_unused = len(unused)
    print(f"SUMMARY: {target} has {n_unused} unused crates")
    for c in unused:
        print(f" - {c}")

def main():
    if len(sys.argv) != 2:
        log("Usage: python3 script.py //path/to:target")
        sys.exit(1)

    root_package = sys.argv[1]
    query = (
        f"kind('rust_library|rust_binary|rust_test', {root_package}) "
        f"except attr(tags, 'manual', {root_package}) "
        f"except attr(tags, 'fuzz_test', {root_package})"
    )

    try:
        result = subprocess.run(
            ["bazel", "query", query],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        targets = result.stdout.strip().splitlines()
    except subprocess.CalledProcessError as e:
        # Print both stdout and stderr from the failed command
        print(f"bazel query failed with return code {e.returncode}", file=sys.stderr)
        print("stdout:\n" + e.stdout, file=sys.stderr)
        print("stderr:\n" + e.stderr, file=sys.stderr)
        sys.exit(1)

    for tgt in targets:
        log(f"Checking target {tgt}")
        prune(tgt)

if __name__ == "__main__":
    main()
