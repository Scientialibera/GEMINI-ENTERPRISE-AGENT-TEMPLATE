"""Named recipe alternatives with step-specific checklists."""

from pptx.util import Inches

from .drawing import add_box, add_checkbox, add_text, wrapped_line_count
from .footer import add_footer
from .theme import CHAR_WIDTH_RATIO, HEAD_FONT, C


def add_customization_slides(prs, recipe):
    """Paginate full instructions instead of clipping a fixed variations panel."""
    for option in recipe.get("customizations", []):
        slide = None
        panel = None
        y = 20.0
        for change in option["steps"]:
            for index, instruction in enumerate(change["instructions"]):
                height = max(
                    0.32, wrapped_line_count(instruction, 8.2, 12, CHAR_WIDTH_RATIO) * 0.22 + 0.10
                )
                if y + height + 0.40 > 12.30:
                    if panel is not None:
                        panel.height = Inches(y - 1.1 + 0.25)
                    slide = prs.slides.add_slide(prs.slide_layouts[6])
                    add_text(
                        slide,
                        "Customized Steps",
                        0.4,
                        0.35,
                        9.1,
                        0.55,
                        font_face=HEAD_FONT,
                        font_size=26,
                        color=C["dark_blue"],
                    )
                    panel = add_box(slide, 0.4, 1.1, 9.1, 11.2, C["cream"], radius=True)
                    add_text(
                        slide,
                        option["name"].upper(),
                        0.65,
                        1.30,
                        8.6,
                        0.35,
                        font_size=16,
                        bold=True,
                        color=C["dark_blue"],
                    )
                    replaced = ", ".join(option.get("replaces", []))
                    add_text(
                        slide,
                        f"Replace: {replaced}" if replaced else "Optional addition",
                        0.65,
                        1.75,
                        8.5,
                        0.4,
                        font_size=11,
                    )
                    add_footer(slide, recipe)
                    y = 2.30
                    new_page = True
                else:
                    new_page = False
                if index == 0 or new_page:
                    add_text(
                        slide,
                        f"STEP {change['step']}",
                        0.65,
                        y,
                        8.4,
                        0.25,
                        font_size=11,
                        bold=True,
                        color=C["dark_blue"],
                    )
                    y += 0.35
                add_checkbox(slide, 0.65, y + 0.04, 0.12)
                add_text(slide, instruction, 0.90, y, 8.2, height, font_size=12, fit=False)
                y += height
        if panel is not None:
            panel.height = Inches(y - 1.1 + 0.25)
