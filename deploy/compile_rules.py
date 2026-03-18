#!/usr/bin/env python3
"""Cython 编译脚本 — 将 evaluation/rules/ 源码编译为二进制 .so/.pyd

用途：开源发布前将规则生成逻辑（IP 核心）编译为二进制，防止源码泄露。

用法：
    cd backend
    python ../deploy/compile_rules.py              # 仅编译
    python ../deploy/compile_rules.py --verify      # 编译 + import 验证
    python ../deploy/compile_rules.py --clean --verify  # 编译 + 删除源码 + 验证

注意：必须在 backend/ 目录下运行（因为模块路径为 app.evaluation.rules.*）
"""

import argparse
import glob
import os
import platform
import shutil
import sys

# 需要编译的文件（排除 r1_prompt.py — 设计文档，非运行时代码）
RULES_DIR = os.path.join("app", "evaluation", "rules")
EXCLUDE_FILES = {"r1_prompt.py"}

# Cython 编译产物后缀
SO_EXT = ".pyd" if platform.system() == "Windows" else ".so"


def get_source_files():
    """收集需要编译的 .py 文件"""
    pattern = os.path.join(RULES_DIR, "*.py")
    sources = []
    for filepath in sorted(glob.glob(pattern)):
        filename = os.path.basename(filepath)
        if filename in EXCLUDE_FILES:
            continue
        sources.append(filepath)
    return sources


def compile_rules():
    """使用 Cython + setuptools 编译所有规则源文件为 .so/.pyd"""
    try:
        from Cython.Build import cythonize
    except ImportError:
        print("错误：未安装 Cython，请先运行 pip install cython", file=sys.stderr)
        sys.exit(1)

    from setuptools import Extension, setup
    from setuptools.dist import Distribution

    sources = get_source_files()
    if not sources:
        print("错误：未找到需要编译的源文件", file=sys.stderr)
        sys.exit(1)

    print(f"找到 {len(sources)} 个源文件待编译：")
    for s in sources:
        print(f"  - {s}")

    # 构建 Extension 列表
    # 模块名需要与 import 路径一致，如 app.evaluation.rules.rule_generator
    extensions = []
    for filepath in sources:
        # app/evaluation/rules/xxx.py -> app.evaluation.rules.xxx
        module_name = filepath.replace(os.sep, ".").replace("/", ".").removesuffix(".py")
        extensions.append(Extension(module_name, [filepath]))

    # 使用 cythonize 编译
    print("\n开始 Cython 编译...")
    ext_modules = cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",  # Python 3 语法
        },
        quiet=False,
    )

    # 通过 setuptools 构建
    # 使用 build_ext --inplace 将 .so 文件放在源文件旁边
    dist = Distribution({"ext_modules": ext_modules})
    dist.script_args = ["build_ext", "--inplace"]

    # 抑制 setuptools 的命令行解析
    old_argv = sys.argv
    sys.argv = ["setup.py", "build_ext", "--inplace"]
    try:
        dist.parse_command_line()
        dist.run_commands()
    finally:
        sys.argv = old_argv

    print("\n编译完成！")

    # 清理中间文件
    cleanup_build_artifacts()

    # 列出生成的 .so/.pyd 文件
    compiled = glob.glob(os.path.join(RULES_DIR, f"*{SO_EXT}"))
    print(f"\n生成 {len(compiled)} 个二进制文件：")
    for f in sorted(compiled):
        size_kb = os.path.getsize(f) / 1024
        print(f"  - {f} ({size_kb:.1f} KB)")

    return compiled


def cleanup_build_artifacts():
    """清理编译产生的中间文件（.c 文件、build/ 目录）"""
    # 删除 .c 中间文件
    c_files = glob.glob(os.path.join(RULES_DIR, "*.c"))
    for f in c_files:
        os.remove(f)
        print(f"  清理: {f}")

    # 删除 build/ 目录
    if os.path.exists("build"):
        shutil.rmtree("build")
        print("  清理: build/")

    # 删除 *.egg-info
    for d in glob.glob("*.egg-info"):
        shutil.rmtree(d)
        print(f"  清理: {d}")


def clean_source_files(sources):
    """删除已编译的 .py 源文件（模拟开源发布环境）"""
    print("\n删除源文件（--clean 模式）：")
    for filepath in sources:
        if os.path.exists(filepath):
            os.remove(filepath)
            print(f"  删除: {filepath}")


def verify_import():
    """验证编译后的模块是否可以正常 import"""
    print("\n验证 import...")

    # 确保当前目录在 sys.path 中（backend/）
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())

    # 清除已缓存的模块，强制重新加载
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

        # 验证核心类存在
        assert RuleGenerator is not None, "RuleGenerator 导入失败"
        assert RulesHotReloader is not None, "RulesHotReloader 导入失败"
        assert UsageTrigger is not None, "UsageTrigger 导入失败"
        assert callable(detect_reasoning_model), "detect_reasoning_model 不可调用"
        assert callable(init_rule_generator), "init_rule_generator 不可调用"
        assert callable(init_hot_reloader), "init_hot_reloader 不可调用"
        assert callable(init_usage_trigger), "init_usage_trigger 不可调用"
        assert callable(get_rule_generator), "get_rule_generator 不可调用"
        assert callable(get_hot_reloader), "get_hot_reloader 不可调用"
        assert callable(get_usage_trigger), "get_usage_trigger 不可调用"

        print("  ✓ app.evaluation.rules 导入成功")
        print("  ✓ 所有公共 API 验证通过")
        return True

    except Exception as e:
        print(f"  ✗ 导入失败: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Cython 编译 evaluation/rules/ 源码")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="编译成功后删除 .py 源文件（模拟开源发布环境）",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="编译后验证 import 是否正常",
    )
    args = parser.parse_args()

    # 检查工作目录
    if not os.path.isdir(RULES_DIR):
        print(
            f"错误：找不到 {RULES_DIR}\n请在 backend/ 目录下运行此脚本",
            file=sys.stderr,
        )
        sys.exit(1)

    sources = get_source_files()
    if not sources:
        print("错误：没有找到需要编译的源文件", file=sys.stderr)
        sys.exit(1)

    # 编译
    compiled = compile_rules()
    if not compiled:
        print("错误：编译未生成任何文件", file=sys.stderr)
        sys.exit(1)

    # 清理源文件（可选）
    if args.clean:
        clean_source_files(sources)

    # 验证（可选）
    if args.verify:
        success = verify_import()
        if not success:
            sys.exit(1)

    print("\n全部完成！")


if __name__ == "__main__":
    main()
