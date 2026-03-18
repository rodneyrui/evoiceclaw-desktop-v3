"""PDF 读取工具 — read_pdf

读取 PDF 文件内容，支持文本层提取 + 扫描件 OCR（软依赖）。
返回给 LLM 的内容经过 CognitiveIsolator 隐私脱敏。

依赖：
- pdfplumber（必需）：文本层 PDF 解析
- rapidocr-onnxruntime（可选）：扫描件 OCR，加载失败时跳过
"""

import logging
from pathlib import Path

from app.kernel.tools.protocol import SkillProtocol

logger = logging.getLogger("evoiceclaw.tool.pdf_reader")

# 最大输出字符数
MAX_OUTPUT_CHARS = 32000
# 默认最大页数
MAX_PAGES = 50
# OCR 触发阈值：某页文字量低于此值时尝试 OCR
OCR_CHAR_THRESHOLD = 20


def _parse_pages_arg(pages_str: str, total_pages: int) -> list[int]:
    """解析页码参数，返回 0-based 页码列表。

    支持格式：
    - "1-3"   → [0, 1, 2]
    - "1,3,5" → [0, 2, 4]
    - "2-4,7" → [1, 2, 3, 6]
    """
    result: set[int] = set()
    for part in pages_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_str, end_str = part.split("-", 1)
            start = int(start_str.strip())
            end = int(end_str.strip())
            for p in range(start, end + 1):
                if 1 <= p <= total_pages:
                    result.add(p - 1)
        else:
            p = int(part.strip())
            if 1 <= p <= total_pages:
                result.add(p - 1)
    return sorted(result)


def _try_load_ocr():
    """尝试加载 RapidOCR 引擎，失败返回 None。"""
    try:
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()
        logger.info("[PDF] RapidOCR 加载成功，OCR 功能可用")
        return ocr
    except ImportError:
        logger.info("[PDF] rapidocr-onnxruntime 未安装，OCR 功能不可用")
        return None
    except Exception as e:
        logger.warning("[PDF] RapidOCR 加载失败（可能 CPU 不支持 AVX）: %s", e)
        return None


# 延迟加载 OCR 引擎（模块级单例）
_ocr_engine = None
_ocr_checked = False


def _get_ocr_engine():
    """获取 OCR 引擎单例（首次调用时加载）。"""
    global _ocr_engine, _ocr_checked
    if not _ocr_checked:
        _ocr_engine = _try_load_ocr()
        _ocr_checked = True
    return _ocr_engine


class ReadPdfTool(SkillProtocol):
    """读取 PDF 文件内容（支持文本层提取 + 扫描件 OCR + 隐私脱敏）"""

    @property
    def name(self) -> str:
        return "read_pdf"

    @property
    def description(self) -> str:
        return (
            "读取 PDF 文件内容。输入文件的绝对路径，返回提取的文本内容（已脱敏）。"
            "支持文本层 PDF 直接提取；对扫描件或图片型 PDF 自动尝试 OCR 识别。"
            "可通过 pages 参数指定页码范围（如 '1-3' 或 '1,3,5'），不指定则读取全部（最多 50 页）。"
            "返回内容经过隐私脱敏处理，敏感信息（身份证号、手机号等）会被替换为占位符。"
        )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "PDF 文件的绝对路径",
                },
                "pages": {
                    "type": "string",
                    "description": "页码范围（可选），如 '1-3' 或 '1,3,5'，不指定则读取全部页（最多 50 页）",
                },
                "ocr": {
                    "type": "boolean",
                    "description": "是否强制对所有页面进行 OCR（可选，默认仅对文字量不足的页面 OCR）",
                },
            },
            "required": ["path"],
        }

    @property
    def required_permissions(self) -> list[str]:
        return ["read_file"]

    @property
    def capability_brief(self) -> str:
        return "读取 PDF 文件内容（支持扫描件 OCR + 隐私脱敏）"

    @property
    def tool_timeout(self) -> int:
        return 120  # OCR 较慢，给足超时

    async def execute(self, arguments: dict) -> str:
        path = arguments.get("path", "")
        pages_arg = arguments.get("pages", "")
        force_ocr = arguments.get("ocr", False)

        if not path:
            return "错误：请提供 PDF 文件路径"

        target = Path(path).expanduser()

        # 安全检查：复用 filesystem 的统一路径安全检查
        from app.kernel.tools.builtin.filesystem import _is_safe_path
        if not _is_safe_path(target, [Path("/")]):
            logger.warning("[PDF] 读取被拒绝（敏感路径）: %s", path)
            return (
                f"拒绝访问：{path} 属于系统敏感或凭据路径，无法读取。\n"
                "被保护的路径包括：系统目录（/etc、/System 等）、"
                "凭据目录（.ssh、.aws 等）、敏感文件（.env、私钥等）。"
            )

        if not target.exists():
            return f"文件不存在：{path}"

        if not target.is_file():
            return f"这不是一个文件：{path}"

        if target.suffix.lower() != ".pdf":
            return f"不是 PDF 文件（扩展名为 {target.suffix}），请提供 .pdf 文件"

        # 检查 pdfplumber 是否可用
        try:
            import pdfplumber
        except ImportError:
            return (
                "错误：PDF 解析库 pdfplumber 未安装。\n"
                "请在后端环境执行: pip install pdfplumber"
            )

        # 打开 PDF 并提取文本
        try:
            with pdfplumber.open(str(target)) as pdf:
                total_pages = len(pdf.pages)
                logger.info("[PDF] 打开文件: %s（共 %d 页）", path, total_pages)

                # 确定要处理的页码
                if pages_arg:
                    try:
                        page_indices = _parse_pages_arg(pages_arg, total_pages)
                    except (ValueError, TypeError):
                        return f"页码格式错误：'{pages_arg}'，支持格式如 '1-3' 或 '1,3,5'"
                    if not page_indices:
                        return f"指定的页码范围无效，PDF 共 {total_pages} 页"
                else:
                    page_indices = list(range(min(total_pages, MAX_PAGES)))

                if total_pages > MAX_PAGES and not pages_arg:
                    logger.warning(
                        "[PDF] 页数超限: %d > %d，仅处理前 %d 页",
                        total_pages, MAX_PAGES, MAX_PAGES,
                    )

                # 逐页提取文本
                page_texts: list[str] = []
                ocr_pages: list[int] = []  # 记录使用了 OCR 的页码
                ocr_engine = _get_ocr_engine() if (force_ocr or True) else None
                # 注：始终尝试获取 OCR 引擎（懒加载），是否实际使用取决于 force_ocr 和文字量

                for idx in page_indices:
                    page = pdf.pages[idx]
                    page_num = idx + 1  # 1-based 显示

                    # 文本层提取
                    text = (page.extract_text() or "").strip()

                    # OCR 判断：强制 OCR 或文字量不足
                    need_ocr = force_ocr or len(text) < OCR_CHAR_THRESHOLD
                    if need_ocr and ocr_engine is not None:
                        ocr_text = self._ocr_page(page, ocr_engine)
                        if ocr_text:
                            text = ocr_text
                            ocr_pages.append(page_num)

                    if text:
                        page_texts.append(f"--- 第 {page_num} 页 ---\n{text}")
                    else:
                        page_texts.append(f"--- 第 {page_num} 页 ---\n[此页无可提取的文本内容]")

                full_text = "\n\n".join(page_texts)

                # 诊断：如果所有页面都没提取到文本，给出明确提示
                has_any_text = any(
                    "[此页无可提取的文本内容]" not in pt for pt in page_texts
                )
                if not has_any_text:
                    ocr_available = _get_ocr_engine() is not None
                    if not ocr_available:
                        full_text += (
                            "\n\n[诊断] 这是一份扫描版图片 PDF，所有页面均无文本层。"
                            "\n需要 OCR 识别才能提取文字，但当前环境未安装 rapidocr-onnxruntime。"
                            "\n请在后端环境执行: pip install rapidocr-onnxruntime"
                            "\n安装后重启服务，再次读取即可自动 OCR。"
                        )
                    else:
                        full_text += (
                            "\n\n[诊断] 这是一份扫描版图片 PDF，OCR 已启用但未能识别出文字。"
                            "\n可能原因：图片分辨率过低、文字模糊、或非标准字体。"
                        )

        except PermissionError:
            return f"权限不足，无法读取：{path}"
        except Exception as e:
            logger.error("[PDF] 解析失败: %s — %s", path, e)
            return f"PDF 解析失败：{e}"

        # 隐私脱敏
        pii_warning = ""
        try:
            from app.pipeline.cognitive_isolator import CognitiveIsolator
            isolator = CognitiveIsolator()
            result = isolator.isolate(full_text)
            if result.detected_count > 0:
                full_text = result.clean_text
                pii_warning = (
                    f"\n\n[隐私保护] 检测并脱敏了 {result.detected_count} 项敏感信息"
                    f"（{', '.join(f'{k}:{v}' for k, v in result.stats.items())}）。"
                    "\n占位符格式为 __REDACTED_xxx__，请勿尝试还原具体内容。"
                )
                logger.info(
                    "[PDF] 隐私脱敏: %d 项 stats=%s",
                    result.detected_count, result.stats,
                )
        except Exception as e:
            logger.warning("[PDF] 隐私脱敏失败，返回原始文本: %s", e)
            pii_warning = "\n\n[警告] 隐私脱敏未能执行，返回内容可能包含敏感信息。请谨慎处理。"

        # 截断
        if len(full_text) > MAX_OUTPUT_CHARS:
            full_text = full_text[:MAX_OUTPUT_CHARS] + "\n\n[... 内容过长，已截断至 32000 字符 ...]"

        # 构建摘要头
        summary_parts = [f"文件: {path}", f"总页数: {total_pages}"]
        if pages_arg:
            summary_parts.append(f"读取页码: {pages_arg}")
        else:
            summary_parts.append(f"读取页数: {len(page_indices)}")
        if ocr_pages:
            summary_parts.append(f"OCR 页: {ocr_pages}")
        elif force_ocr and ocr_engine is None:
            summary_parts.append("OCR: 不可用（rapidocr-onnxruntime 未安装或加载失败）")
        summary = " | ".join(summary_parts)

        return f"[PDF 读取结果] {summary}\n\n{full_text}{pii_warning}"

    def _ocr_page(self, page, ocr_engine) -> str:
        """对单页执行 OCR，返回识别文本。失败返回空字符串。"""
        try:
            # pdfplumber 页面转图片
            img = page.to_image(resolution=300)
            # to_image() 返回 PageImage，其 .original 属性是 PIL Image
            pil_img = img.original

            # RapidOCR 接受 numpy array
            import numpy as np
            img_array = np.array(pil_img)

            result, _ = ocr_engine(img_array)
            if result:
                # result 是 list of [bbox, text, confidence]
                texts = [item[1] for item in result]
                return "\n".join(texts)
        except Exception as e:
            logger.warning("[PDF] OCR 页面失败: %s", e)
        return ""
