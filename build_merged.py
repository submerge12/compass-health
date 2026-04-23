#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build merged meal-plan workbook with 每日食谱查询 lookup sheet.
"""
import re
import copy
import openpyxl
from openpyxl import load_workbook
from openpyxl.styles import (Font, PatternFill, Alignment, Border, Side,
                              GradientFill)
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

# ── colour palette (from existing file) ────────────────────────────────────
C_NAVY      = "FF1B2A4A"   # 30天计划 header bg / dark section bg
C_RED       = "FFE74C3C"   # 采购清单 main title
C_BLUE      = "FF2E86AB"   # 采购清单 sub-header
C_LBLUE     = "FFD6EAF8"   # 30天计划 data rows
C_PURPLE    = "FF9B59B6"   # 食谱 title
C_ORANGE    = "FFFF8C00"   # lunch accent
C_GREEN     = "FF27AE60"   # dinner accent
C_YELLOWI   = "FFFFF2CC"   # input cell
C_LGREEN    = "FFE8F5E9"   # dinner section bg
C_LORANGE   = "FFFFF3E0"   # lunch section bg
C_WHITE     = "FFFFFFFF"
C_LGRAY     = "FFF5F5F5"
C_MIDGRAY   = "FFD0D0D0"
C_GOLD      = "FFFFC000"   # ingredient label bg
C_TEAL      = "FF00897B"   # step label bg

def fill(hex_color):
    return PatternFill("solid", fgColor=hex_color)

def font(bold=False, size=11, color="FF000000", name="微软雅黑"):
    return Font(bold=bold, size=size, color=color, name=name)

def align(h="left", v="center", wrap=False):
    return Alignment(horizontal=h, vertical=v, wrap_text=wrap)

def thin_border():
    s = Side(style="thin", color="FFBDBDBD")
    return Border(left=s, right=s, top=s, bottom=s)

def thick_border_bottom(color="FF1B2A4A"):
    s = Side(style="medium", color=color)
    t = Side(style="thin", color="FFBDBDBD")
    return Border(left=t, right=t, top=t, bottom=s)

# ═══════════════════════════════════════════════════════════════════════════
# 1. PARSE 各菜品食材详情 → dict  full_dish_name → ingredient_text
# ═══════════════════════════════════════════════════════════════════════════
def parse_ingredients(ws):
    """Return dict: full dish name (with + 米饭 etc.) → formatted ingredient string."""
    results = {}
    current_dish = None
    pairs = []        # list of (left_ingredient, left_qty, right_ingredient, right_qty)
    header_re = re.compile(r'^\d+\.\s+(.+?)\s+\|')

    def flush():
        if current_dish and pairs:
            lines = []
            for li, lq, ri, rq in pairs:
                if li and lq:
                    lines.append(f"• {li}：{lq}")
                if ri and rq:
                    lines.append(f"• {ri}：{rq}")
            results[current_dish] = "\n".join(lines)

    for row in ws.iter_rows(values_only=True):
        a = str(row[0]).strip() if row[0] else ""
        b = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        c = str(row[2]).strip() if len(row) > 2 and row[2] else ""
        e = str(row[4]).strip() if len(row) > 4 and row[4] else ""
        f = str(row[5]).strip() if len(row) > 5 and row[5] else ""

        m = header_re.match(a)
        if m:
            flush()
            current_dish = m.group(1).strip()
            pairs = []
            continue

        # skip the 食材/用量 header row
        if b == "食材" and c == "用量":
            continue

        # ingredient data rows
        if current_dish and (b or e):
            left_ing  = b if b not in ("食材", "") else ""
            left_qty  = c if c not in ("用量", "") else ""
            right_ing = e if e not in ("食材", "") else ""
            right_qty = f if f not in ("用量", "") else ""
            if left_ing or right_ing:
                pairs.append((left_ing, left_qty, right_ing, right_qty))

    flush()
    return results

# ═══════════════════════════════════════════════════════════════════════════
# 2. PARSE 食谱 → dict  short_name → recipe_text
# ═══════════════════════════════════════════════════════════════════════════
def parse_recipes(ws):
    """Return dict: short dish name → full recipe text (ingredients + steps)."""
    results = {}
    current_name = None
    for row in ws.iter_rows(values_only=True):
        a = row[0]
        b = row[1] if len(row) > 1 else None
        # Detect dish-number row: col A is a digit string (or int)
        if a is not None and str(a).strip().isdigit():
            current_name = str(b).strip() if b else None
        elif current_name and b and str(b).strip():
            results[current_name] = str(b).strip()
            current_name = None
    return results

# ═══════════════════════════════════════════════════════════════════════════
# 3. MAP short name → full name
# ═══════════════════════════════════════════════════════════════════════════
def map_short_to_full(short_names, full_names):
    mapping = {}
    for short in short_names:
        for full in full_names:
            if short in full:
                mapping[short] = full
                break
    return mapping

# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════
wb = load_workbook("c:/Users/Holly/compass-health/30天膳食计划.xlsx")

ws_detail = wb["各菜品食材详情"]
ws_recipe = wb["食谱"]
ws_plan   = wb["30天计划"]

ingredient_map = parse_ingredients(ws_detail)   # full_name → ingredient text
recipe_map     = parse_recipes(ws_recipe)        # short_name → recipe text

# Build short→full name mapping
short_to_full = map_short_to_full(list(recipe_map.keys()), list(ingredient_map.keys()))

# Combine: for each full dish name, gather ingredients + cooking steps
dish_data = {}  # full_name → (ingredient_text, steps_text)
for short, full in short_to_full.items():
    ing   = ingredient_map.get(full, "")
    steps = recipe_map.get(short, "")
    dish_data[full] = (ing, steps)

# Also handle any full names that have no recipe mapping
for full, ing in ingredient_map.items():
    if full not in dish_data:
        dish_data[full] = (ing, "")

print("Dishes in database:")
for k in sorted(dish_data.keys()):
    ing, steps = dish_data[k]
    print(f"  [{k}]  ing_lines={ing.count(chr(10))+1 if ing else 0}  steps={'yes' if steps else 'no'}")

# ═══════════════════════════════════════════════════════════════════════════
# 4. CREATE 菜品数据库 SHEET  (hidden helper)
# ═══════════════════════════════════════════════════════════════════════════
DB_SHEET = "菜品数据库"
if DB_SHEET in wb.sheetnames:
    del wb[DB_SHEET]

ws_db = wb.create_sheet(DB_SHEET)
ws_db.sheet_state = "hidden"

# Headers
headers = ["菜品全名", "食材清单", "烹饪步骤"]
for c, h in enumerate(headers, 1):
    cell = ws_db.cell(1, c, h)
    cell.fill = fill(C_NAVY)
    cell.font = font(bold=True, color=C_WHITE)
    cell.alignment = align("center")

ws_db.column_dimensions["A"].width = 40
ws_db.column_dimensions["B"].width = 50
ws_db.column_dimensions["C"].width = 80

# Data rows
for r, (dish_name, (ing_text, steps_text)) in enumerate(sorted(dish_data.items()), 2):
    ws_db.cell(r, 1, dish_name).alignment = align()
    ing_cell = ws_db.cell(r, 2, ing_text)
    ing_cell.alignment = align(wrap=True)
    steps_cell = ws_db.cell(r, 3, steps_text)
    steps_cell.alignment = align(wrap=True)
    # Auto row height (approximate)
    lines = max(ing_text.count("\n") + 1 if ing_text else 1,
                steps_text.count("\n") + 1 if steps_text else 1)
    ws_db.row_dimensions[r].height = max(15, lines * 15)

db_last_row = len(dish_data) + 1
print(f"\n菜品数据库 built: {db_last_row - 1} dishes, rows 2–{db_last_row}")

# ═══════════════════════════════════════════════════════════════════════════
# 5. CREATE 每日食谱查询 SHEET
# ═══════════════════════════════════════════════════════════════════════════
LOOKUP_SHEET = "每日食谱查询"
if LOOKUP_SHEET in wb.sheetnames:
    del wb[LOOKUP_SHEET]

ws_lk = wb.create_sheet(LOOKUP_SHEET, 0)   # insert at front

# ── column widths ──────────────────────────────────────────────────────────
ws_lk.column_dimensions["A"].width = 18
ws_lk.column_dimensions["B"].width = 55
ws_lk.column_dimensions["C"].width = 15
ws_lk.column_dimensions["D"].width = 15

# helper: style a cell in-place
def sc(ws, row, col, value=None, bold=False, size=11, color="FF000000",
       bg=None, h="left", v="center", wrap=False, border=False,
       font_name="微软雅黑"):
    c = ws.cell(row, col)
    if value is not None:
        c.value = value
    c.font = Font(bold=bold, size=size, color=color, name=font_name)
    if bg:
        c.fill = fill(bg)
    c.alignment = Alignment(horizontal=h, vertical=v, wrap_text=wrap)
    if border:
        c.border = thin_border()
    return c

# ── ROW 1: main title ──────────────────────────────────────────────────────
ws_lk.row_dimensions[1].height = 45
ws_lk.merge_cells("A1:D1")
sc(ws_lk, 1, 1,
   value="📅  每日食谱查询",
   bold=True, size=18, color=C_WHITE, bg=C_RED,
   h="center", v="center")

# ── ROW 2: subtitle / instructions ───────────────────────────────────────
ws_lk.row_dimensions[2].height = 22
ws_lk.merge_cells("A2:D2")
sc(ws_lk, 2, 1,
   value="根据天数自动显示当日午餐和晚餐菜品的食材用量及烹饪步骤",
   bold=False, size=10, color="FF666666", bg="FFF8F8F8",
   h="center", v="center")

# ── ROW 3: day input ──────────────────────────────────────────────────────
ws_lk.row_dimensions[3].height = 36
sc(ws_lk, 3, 1,
   value="请输入天数 (1–30)：",
   bold=True, size=12, color=C_NAVY, bg=C_LBLUE,
   h="right", v="center")

# Input cell B3 — user enters day number here
input_cell = ws_lk.cell(3, 2, 1)   # default = Day 1
input_cell.font  = Font(bold=True, size=14, color=C_NAVY, name="微软雅黑")
input_cell.fill  = fill(C_YELLOWI)
input_cell.alignment = Alignment(horizontal="center", vertical="center")
s = Side(style="medium", color=C_ORANGE)
input_cell.border = Border(left=s, right=s, top=s, bottom=s)

# Drop-down validation 1–30
dv = DataValidation(type="whole", operator="between",
                    formula1="1", formula2="30",
                    showErrorMessage=True,
                    errorTitle="无效天数",
                    error="请输入 1 到 30 之间的整数")
ws_lk.add_data_validation(dv)
dv.add(input_cell)

sc(ws_lk, 3, 3, value="（输入 1–30）",
   bold=False, size=10, color="FF999999", bg="FFF8F8F8",
   h="left", v="center")

# ── ROW 4: spacer ─────────────────────────────────────────────────────────
ws_lk.row_dimensions[4].height = 10

# ══════════════════════════════════════════════════════════════════════════
# LUNCH SECTION  (rows 5–13)
# ══════════════════════════════════════════════════════════════════════════
# Row 5: section header
ws_lk.row_dimensions[5].height = 30
ws_lk.merge_cells("A5:D5")
sc(ws_lk, 5, 1, value="🍜  午 餐",
   bold=True, size=14, color=C_WHITE, bg=C_ORANGE,
   h="center", v="center")

# Row 6: dish name label + XLOOKUP formula
ws_lk.row_dimensions[6].height = 30
sc(ws_lk, 6, 1, value="菜品名称",
   bold=True, size=11, color=C_NAVY, bg=C_LORANGE,
   h="center", v="center", border=True)

ws_lk.merge_cells("B6:D6")
lunch_name_cell = ws_lk.cell(6, 2)
lunch_name_cell.value = (
    "=IFERROR(XLOOKUP($B$3,'30天计划'!$A$2:$A$31,"
    "'30天计划'!$C$2:$C$31),\"— 请输入有效天数 —\")"
)
lunch_name_cell.font      = Font(bold=True, size=12, color=C_NAVY, name="微软雅黑")
lunch_name_cell.fill      = fill(C_LORANGE)
lunch_name_cell.alignment = Alignment(horizontal="left", vertical="center",
                                      wrap_text=False)
lunch_name_cell.border    = thin_border()

# Row 7: ingredients label
ws_lk.row_dimensions[7].height = 24
sc(ws_lk, 7, 1, value="食材用量",
   bold=True, size=11, color=C_WHITE, bg=C_GOLD,
   h="center", v="center", border=True)

ws_lk.merge_cells("B7:D7")
sc(ws_lk, 7, 2, bg=C_GOLD,
   value="（每份所需食材，括号内为用量）",
   bold=False, size=9, color="FF555555",
   h="left", v="center")

# Row 8: ingredients content
ws_lk.row_dimensions[8].height = 130
sc(ws_lk, 8, 1, value="",
   bg=C_LORANGE, border=True)

ws_lk.merge_cells("B8:D8")
lunch_ing_cell = ws_lk.cell(8, 2)
lunch_ing_cell.value = (
    "=IFERROR(XLOOKUP(B6,"
    "菜品数据库!$A$2:$A$20,"
    "菜品数据库!$B$2:$B$20),\"暂无食材数据\")"
)
lunch_ing_cell.font      = Font(size=10, name="微软雅黑", color="FF333333")
lunch_ing_cell.fill      = fill(C_WHITE)
lunch_ing_cell.alignment = Alignment(horizontal="left", vertical="top",
                                     wrap_text=True)
lunch_ing_cell.border    = thin_border()

# Row 9: steps label
ws_lk.row_dimensions[9].height = 24
sc(ws_lk, 9, 1, value="烹饪步骤",
   bold=True, size=11, color=C_WHITE, bg=C_TEAL,
   h="center", v="center", border=True)

ws_lk.merge_cells("B9:D9")
sc(ws_lk, 9, 2, bg=C_TEAL,
   value="（详细烹饪方法与保存建议）",
   bold=False, size=9, color="FFFFFFFF",
   h="left", v="center")

# Row 10: steps content
ws_lk.row_dimensions[10].height = 160
sc(ws_lk, 10, 1, value="",
   bg=C_LORANGE, border=True)

ws_lk.merge_cells("B10:D10")
lunch_steps_cell = ws_lk.cell(10, 2)
lunch_steps_cell.value = (
    "=IFERROR(XLOOKUP(B6,"
    "菜品数据库!$A$2:$A$20,"
    "菜品数据库!$C$2:$C$20),\"暂无烹饪步骤数据\")"
)
lunch_steps_cell.font      = Font(size=10, name="微软雅黑", color="FF333333")
lunch_steps_cell.fill      = fill(C_WHITE)
lunch_steps_cell.alignment = Alignment(horizontal="left", vertical="top",
                                       wrap_text=True)
lunch_steps_cell.border    = thin_border()

# Row 11: spacer
ws_lk.row_dimensions[11].height = 12

# ══════════════════════════════════════════════════════════════════════════
# DINNER SECTION  (rows 12–20)
# ══════════════════════════════════════════════════════════════════════════
# Row 12: section header
ws_lk.row_dimensions[12].height = 30
ws_lk.merge_cells("A12:D12")
sc(ws_lk, 12, 1, value="🥗  晚 餐",
   bold=True, size=14, color=C_WHITE, bg=C_GREEN,
   h="center", v="center")

# Row 13: dish name label + XLOOKUP formula
ws_lk.row_dimensions[13].height = 30
sc(ws_lk, 13, 1, value="菜品名称",
   bold=True, size=11, color=C_NAVY, bg=C_LGREEN,
   h="center", v="center", border=True)

ws_lk.merge_cells("B13:D13")
dinner_name_cell = ws_lk.cell(13, 2)
dinner_name_cell.value = (
    "=IFERROR(XLOOKUP($B$3,'30天计划'!$A$2:$A$31,"
    "'30天计划'!$H$2:$H$31),\"— 请输入有效天数 —\")"
)
dinner_name_cell.font      = Font(bold=True, size=12, color=C_NAVY, name="微软雅黑")
dinner_name_cell.fill      = fill(C_LGREEN)
dinner_name_cell.alignment = Alignment(horizontal="left", vertical="center")
dinner_name_cell.border    = thin_border()

# Row 14: ingredients label
ws_lk.row_dimensions[14].height = 24
sc(ws_lk, 14, 1, value="食材用量",
   bold=True, size=11, color=C_WHITE, bg=C_GOLD,
   h="center", v="center", border=True)

ws_lk.merge_cells("B14:D14")
sc(ws_lk, 14, 2, bg=C_GOLD,
   value="（每份所需食材，括号内为用量）",
   bold=False, size=9, color="FF555555",
   h="left", v="center")

# Row 15: ingredients content
ws_lk.row_dimensions[15].height = 130
sc(ws_lk, 15, 1, value="",
   bg=C_LGREEN, border=True)

ws_lk.merge_cells("B15:D15")
dinner_ing_cell = ws_lk.cell(15, 2)
dinner_ing_cell.value = (
    "=IFERROR(XLOOKUP(B13,"
    "菜品数据库!$A$2:$A$20,"
    "菜品数据库!$B$2:$B$20),\"暂无食材数据\")"
)
dinner_ing_cell.font      = Font(size=10, name="微软雅黑", color="FF333333")
dinner_ing_cell.fill      = fill(C_WHITE)
dinner_ing_cell.alignment = Alignment(horizontal="left", vertical="top",
                                      wrap_text=True)
dinner_ing_cell.border    = thin_border()

# Row 16: steps label
ws_lk.row_dimensions[16].height = 24
sc(ws_lk, 16, 1, value="烹饪步骤",
   bold=True, size=11, color=C_WHITE, bg=C_TEAL,
   h="center", v="center", border=True)

ws_lk.merge_cells("B16:D16")
sc(ws_lk, 16, 2, bg=C_TEAL,
   value="（详细烹饪方法与保存建议）",
   bold=False, size=9, color="FFFFFFFF",
   h="left", v="center")

# Row 17: steps content
ws_lk.row_dimensions[17].height = 160
sc(ws_lk, 17, 1, value="",
   bg=C_LGREEN, border=True)

ws_lk.merge_cells("B17:D17")
dinner_steps_cell = ws_lk.cell(17, 2)
dinner_steps_cell.value = (
    "=IFERROR(XLOOKUP(B13,"
    "菜品数据库!$A$2:$A$20,"
    "菜品数据库!$C$2:$C$20),\"暂无烹饪步骤数据\")"
)
dinner_steps_cell.font      = Font(size=10, name="微软雅黑", color="FF333333")
dinner_steps_cell.fill      = fill(C_WHITE)
dinner_steps_cell.alignment = Alignment(horizontal="left", vertical="top",
                                        wrap_text=True)
dinner_steps_cell.border    = thin_border()

# Row 18: footer note
ws_lk.row_dimensions[18].height = 20
ws_lk.merge_cells("A18:D18")
sc(ws_lk, 18, 1,
   value="💡 提示：修改 B3 单元格中的天数（1–30）即可查询对应当天的食谱。",
   bold=False, size=9, color="FF777777", bg="FFF8F8F8",
   h="center", v="center")

# ── freeze panes below title row ──────────────────────────────────────────
ws_lk.freeze_panes = "A4"

# ── tab colour ────────────────────────────────────────────────────────────
ws_lk.sheet_properties.tabColor = "E74C3C"

# ═══════════════════════════════════════════════════════════════════════════
# 6. REORDER SHEETS: 每日食谱查询 first, then existing sheets
# ═══════════════════════════════════════════════════════════════════════════
# Move 每日食谱查询 to position 0
desired_order = [LOOKUP_SHEET] + [s for s in wb.sheetnames if s not in (LOOKUP_SHEET, DB_SHEET)] + [DB_SHEET]
for i, name in enumerate(desired_order):
    wb.move_sheet(name, offset=wb.sheetnames.index(name) - i)

# ═══════════════════════════════════════════════════════════════════════════
# 7. SAVE
# ═══════════════════════════════════════════════════════════════════════════
out_path = "c:/Users/Holly/compass-health/膳食计划合并版.xlsx"
wb.save(out_path)
print(f"\n✅  Saved → {out_path}")
print(f"   Sheets: {wb.sheetnames}")
