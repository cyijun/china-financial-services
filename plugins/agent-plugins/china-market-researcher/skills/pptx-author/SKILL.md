---
name: pptx-author
description: Produce a .pptx file on disk (headless) for Chinese A-share market research, using python-pptx with Chinese font support. For managed-agent sessions with no open Office app.
---

# pptx-author

Use this skill when running **headless** (managed-agent / CMA mode) and you need to deliver a Chinese market research PowerPoint deck as a **file artifact** rather than editing a live document via `mcp__office__powerpoint_*`.

## Output contract

- Write to `./out/<name>.pptx`. Create `./out/` if it does not exist.
- Return the relative path in your final message so the orchestration layer can collect it.

## How to build the deck

Write a short Python script and run it with Bash. Use `python-pptx`:

```python
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

prs = Presentation("./templates/firm-template.pptx")  # if a template is provided
# or: prs = Presentation()

slide = prs.slides.add_slide(prs.slide_layouts[5])    # title-only

# Set Chinese-friendly font
def set_chinese_font(run, font_name="微软雅黑", font_size=18, bold=False):
    font = run.font
    font.name = font_name
    font.size = Pt(font_size)
    font.bold = bold
    # For CJK fallback on non-Windows systems
    run._element.set("lang", "zh-CN")

title = slide.shapes.title
for paragraph in title.text_frame.paragraphs:
    paragraph.clear()
    run = paragraph.add_run()
    run.text = "A股新能源汽车行业深度"
    set_chinese_font(run, "微软雅黑", 28, bold=True)

# ... add tables / charts / text boxes with set_chinese_font() ...

prs.save("./out/china-sector-primer.pptx")
```

## Chinese context conventions

- **Fonts**: Default to 微软雅黑 (Microsoft YaHei) or SimHei for Chinese text; Times New Roman for English words and numbers. If the target system may lack 微软雅黑, fall back to SimHei or specify a system-available CJK font.
- **Language**: Slide titles and body text may be written in Chinese. Keep titles punchy and takeaway-oriented.
- **Numbers and units**: Use Chinese market conventions — e.g., 亿元人民币, 万亿元, 个百分点, PE(TTM), PB(LF).
- **Content conventions** (mirror the live-Office skill but for Chinese research reports):
  - **One idea per slide.** Title states the takeaway; body supports it.
  - **Every number traces to the model.** If a figure comes from Tushare, footnote the interface and date, e.g., `数据来源: Tushare daily_basic 2024-12-01`. If from a local workbook, cite the path and cell, e.g., `见 ./out/comps.xlsx Sheet1 B7`.
  - **Use the firm template** when one is mounted at `./templates/`; otherwise default layouts.
  - **Charts**: Prefer embedding a PNG rendered from the model over native pptx charts when fidelity matters. Save the PNG to `./out/` and insert it with `slide.shapes.add_picture()`.
  - **No external sends.** This skill writes a file; it never emails or uploads.

## When NOT to use

If `mcp__office__powerpoint_*` tools are available (Cowork plugin mode), use those instead — they drive the user's live document with review checkpoints. This skill is the file-producing fallback for headless runs.
