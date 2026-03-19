#!/usr/bin/env python3
"""Cython compile script - compile evaluation/rules/ source to binary .so/.pyd

Usage:
    cd backend
    python ../deploy/compile_rules.py              # compile only
    python ../deploy/compile_rules.py --verify      # compile + import verify
    python ../deploy/compile_rules.py --clean --verify  # compile + delete source + verify

Note: must run from backend/ directory (module path is app.evaluation.rules.*)
"""

import argparse
import glob
import os
import platform
import shutil
import sys

# Files to compile (exclude r1_prompt.py - design doc, not runtime code;
# exclude __init__.py - package marker, no IP to protect)
RULES_DIR = os.path.join("app", "evaluation", "rules")
EXCLUDE_FILES = {"r1_prompt.py", "__init__.py"}

# Cython output extension
SO_EXT = ".pyd" if platform.system() == "Windows" else ".so"


def get_source_files():
    """Collect .py files to compile"""
    pattern = os.path.join(RULES_DIR, "*.py")
    sources = []
    for filepath in sorted(glob.glob(pattern)):
        filename = os.path.basename(filepath)
        if filename in EXCLUDE_FILES:
            continue
        sources.append(filepath)
    return sources


def compile_rules():
    """Compile all rule source files to .so/.pyd using Cython + setuptools"""
    try:
        from Cython.Build import cythonize
    except ImportError:
        print("Error: Cython not installed, run: pip install cython", file=sys.stderr)
        sys.exit(1)

    from setuptools import Extension
    from setuptools.dist import Distribution

    sources = get_source_files()
    if not sources:
        print("No source files to compile (only __init__.py and excluded files), skipping")
        return []

    print(f"Found {len(sources)} source files to compile:")
    for s in sources:
        print(f"  - {s}")

    # Build Extension list
    # Module name must match import path, e.g. app.evaluation.rules.rule_generator
    extensions = []
    for filepath in sources:
        # app/evaluation/rules/xxx.py -> app.evaluation.rules.xxx
        module_name = filepath.replace(os.sep, ".").replace("/", ".").removesuffix(".py")
        extensions.append(Extension(module_name, [filepath]))

    # Cythonize
    print("\nStarting Cython compilation...")
    ext_modules = cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",  # Python 3 syntax
        },
        quiet=False,
    )

    # Build via setuptools (build_ext --inplace puts .so next to source)
    dist = Distribution({"ext_modules": ext_modules})
    dist.script_args = ["build_ext", "--inplace"]

    old_argv = sys.argv
    sys.argv = ["setup.py", "build_ext", "--inplace"]
    try:
        dist.parse_command_line()
        dist.run_commands()
    finally:
        sys.argv = old_argv

    print("\nCompilation done!")

    # Clean intermediate files
    cleanup_build_artifacts()

    # List generated .so/.pyd files
    compiled = glob.glob(os.path.join(RULES_DIR, f"*{SO_EXT}"))
    print(f"\nGenerated {len(compiled)} binary files:")
    for f in sorted(compiled):
        size_kb = os.path.getsize(f) / 1024
        print(f"  - {f} ({size_kb:.1f} KB)")

    return compiled


def cleanup_build_artifacts():
    """Clean intermediate files (.c files, build/ directory)"""
    # Delete .c intermediate files
    c_files = glob.glob(os.path.join(RULES_DIR, "*.c"))
    for f in c_files:
        os.remove(f)
        print(f"  cleaned: {f}")

    # Delete build/ directory
    if os.path.exists("build"):
        shutil.rmtree("build")
        print("  cleaned: build/")

    # Delete *.egg-info
    for d in glob.glob("*.egg-info"):
        shutil.rmtree(d)
        print(f"  cleaned: {d}")


def clean_source_files(sources):
    """Delete compiled .py source files (simulate open-source release)"""
    print("\nDeleting source files (--clean mode):")
    for filepath in sources:
        if os.path.exists(filepath):
            os.remove(filepath)
            print(f"  deleted: {filepath}")


def verify_import():
    """Verify compiled modules can be imported"""
    print("\nVerifying import...")

    # Ensure cwd is in sys.path (backend/)
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())

    # Clear cached modules to force reload
    modules_to_clear = [k for k in sys.modules if k.startswith("app.evaluation.rules")]
    for m in modules_to_clear:
        del sys.modules[m]

    try:
        from app.evaluation.rules import (
            RuleGenerator,
            RulesHotReloader,
            UsageTrigger,
            detect_reasoning_model,
            get_hot_reloader,
            get_rule_generator,
            get_usage_trigger,
            init_hot_reloader,
            init_rule_generator,
            init_usage_trigger,
        )

        # Verify core classes exist
        assert RuleGenerator is not None, "RuleGenerator import failed"
        assert RulesHotReloader is not None, "RulesHotReloader import failed"
        assert UsageTrigger is not None, "UsageTrigger import failed"
        assert callable(detect_reasoning_model), "detect_reasoning_model not callable"
        assert callable(init_rule_generator), "init_rule_generator not callable"
        assert callable(init_hot_reloader), "init_hot_reloader not callable"
        assert callable(init_usage_trigger), "init_usage_trigger not callable"
        assert callable(get_rule_generator), "get_rule_generator not callable"
        assert callable(get_hot_reloader), "get_hot_reloader not callable"
        assert callable(get_usage_trigger), "get_usage_trigger not callable"

        print("  ok: app.evaluation.rules imported successfully")
        print("  ok: all public APIs verified")
        return True

    except Exception as e:
        print(f"  FAIL: import error: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Cython compile evaluation/rules/ source")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete .py source files after successful compilation",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify import after compilation",
    )
    args = parser.parse_args()

    # Check working directory
    if not os.path.isdir(RULES_DIR):
        print(
            f"Error: {RULES_DIR} not found\nRun this script from the backend/ directory",
            file=sys.stderr,
        )
        sys.exit(1)

    sources = get_source_files()
    if not sources:
        print("No source files to compile (only __init__.py and excluded files), skipping")
        print("\nDone!")
        sys.exit(0)

    # Compile
    compiled = compile_rules()
    if not compiled:
        print("Warning: no compiled output, skipping remaining steps")
        print("\nDone!")
        sys.exit(0)

    # Clean source files (optional)
    if args.clean:
        clean_source_files(sources)

    # Verify (optional)
    if args.verify:
        success = verify_import()
        if not success:
            sys.exit(1)

    print("\nDone!")


if __name__ == "__main__":
    main()
