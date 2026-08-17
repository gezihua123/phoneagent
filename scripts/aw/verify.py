"""verify 命令 + 判定逻辑——AndroidWorld is_successful() 的 shell 等价实现。

AndroidWorld 的 is_successful() 分几类：
  SQLite:  pull DB → Python sqlite3 SELECT → 对比前后
  File:    find file / cat content
  Contact: content query --uri content://contacts/phones/
  SMS:     content query --uri content://sms/sent
  System:  settings get global <key>

fastaget 等价做法：全部用 shell 命令 + expect/expect_re/min_lines 判定。
"""
from __future__ import annotations

import re

from scripts.aw import data


_NO_EXPECT = object()

def _verify_spec(command: str, expect: object = _NO_EXPECT, expect_re: str = "",
                 min_lines: int = 0, not_contain: str = "",
                 ui_contains: str = "", ui_not_contains: str = "") -> dict:
    """构建 verify spec dict。pass expect="" 表示期望空输出。

    ui_contains/ui_not_contains：走 pf.observe() 的 UI 路径（fastaget/verify.py
    的 AndroidWorld env.get_state().ui_elements 对齐实现）。屏幕状态检查（时钟
    按钮、联系人表单、浏览器 Success!）必须用它——系统 `uiautomator dump` 会被
    phonefast daemon 的 a11y 服务抢占 kill（rc=137），不可用。
    """
    spec: dict = {"command": command}
    if expect is not _NO_EXPECT:
        spec["expect"] = expect
    if expect_re:
        spec["expect_re"] = expect_re
    if min_lines:
        spec["min_lines"] = min_lines
    if not_contain:
        spec["not_contain"] = not_contain
    if ui_contains:
        spec["ui_contains"] = ui_contains
    if ui_not_contains:
        spec["ui_not_contains"] = ui_not_contains
    return spec


# ═══════════════════════════════════════════════════════════
# Recipe verify
# ═══════════════════════════════════════════════════════════

def recipe_delete_single_verify() -> list[dict]:
    """验证 Spicy Tuna Wraps 已从数据库删除（COUNT=0）。"""
    db = data.DB_PATHS["broccoli"]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes WHERE title='{data.RECIPE_SPICY_TUNA['title']}';\"",
            expect="0",
        ),
    ]


def recipe_delete_multiple_verify() -> list[dict]:
    """验证两个食谱都已删除。"""
    db = data.DB_PATHS["broccoli"]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes WHERE title IN "
            f"('{data.RECIPE_SPICY_TUNA['title']}','{data.RECIPE_AVOCADO_TOAST['title']}');\"",
            expect="0",
        ),
    ]


def recipe_add_single_verify() -> list[dict]:
    """验证目标食谱已添加到数据库。"""
    db = data.DB_PATHS["broccoli"]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes WHERE title='{data.RECIPE_SPICY_TUNA['title']}';\"",
            expect_re=r"[1-9][0-9]*",  # >= 1
        ),
    ]


# ═══════════════════════════════════════════════════════════
# Expense verify
# ═══════════════════════════════════════════════════════════

def expense_delete_single_verify() -> list[dict]:
    db = data.DB_PATHS["expense"]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM expense WHERE name='{data.EXPENSE_LUNCH['name']}';\"",
            expect="0",
        ),
    ]


def expense_delete_multiple_verify() -> list[dict]:
    db = data.DB_PATHS["expense"]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM expense WHERE name IN "
            f"('{data.EXPENSE_LUNCH['name']}','{data.EXPENSE_COFFEE['name']}',"
            f"'{data.EXPENSE_TAXI['name']}');\"",
            expect="0",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# Contact verify
# ═══════════════════════════════════════════════════════════

def contacts_add_verify() -> list[dict]:
    """对齐 AW AddContact：phones 表中同时存在 name 和 number。

    AW 用 contacts_utils.clean_phone_number 归一化号码（去非数字）后比对——
    实测 provider 原样存 "555-0100"（带横线），故 number 检查先 tr 去非数字。
    """
    query = ("content query --uri content://contacts/phones/ "
             "--projection display_name:number 2>/dev/null || echo NO_CONTACT")
    digits = ("content query --uri content://contacts/phones/ "
              "--projection display_name:number 2>/dev/null | tr -dc '0-9'")
    return [
        _verify_spec(query, expect_re=data.CONTACT_ALICE["name"]),
        _verify_spec(digits, expect_re=data.CONTACT_ALICE["number"].replace("-", "")),
    ]


def contacts_draft_verify() -> list[dict]:
    """对齐 AW ContactsNewContactDraft._contact_info_is_entered：
    - 表单已填 First/Last/Phone，标签选 Home（AW 断言 label != Mobile）
    - phones 表中不得有 Alice——证明未保存（Do NOT hit save）"""
    first, last = data.CONTACT_ALICE["name"].split(" ", 1)
    phone = data.CONTACT_ALICE["number"]
    return [
        _verify_spec("", ui_contains=f'text="{first}"'),
        _verify_spec("", ui_contains=f'text="{last}"'),
        _verify_spec("", ui_contains=f'text="{phone}"'),
        _verify_spec("", ui_contains='desc="Home Phone"'),
        _verify_spec(
            "content query --uri content://contacts/phones/ "
            "--projection display_name:number 2>/dev/null || echo NO_CONTACT",
            not_contain=data.CONTACT_ALICE["name"],
        ),
    ]


# ═══════════════════════════════════════════════════════════
# SMS verify
# ═══════════════════════════════════════════════════════════

def _sms_sent_to_5550100_spec() -> dict:
    """SENT 中发往 555-0100（AW was_sent 对号码去横线比较，两种格式都接受）。"""
    return _verify_spec(
        "content query --uri content://sms/sent 2>/dev/null | grep -E 'address=555-?0100'",
        expect_re=r"555-?0100",
    )


def sms_send_verify() -> list[dict]:
    """对齐 AW SimpleSMSSendSms.is_successful（was_sent on content://sms/sent +
    in_correct_app）：收件人 555-0100 + 正文匹配 + 当前前台是 Simple SMS
    Messenger，缺一不可（不再只查 body）。"""
    return [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r"smsmessenger",
        ),
        _sms_sent_to_5550100_spec(),
        _verify_spec(
            "content query --uri content://sms/sent 2>/dev/null | grep body",
            expect_re=data.SMS_HELLO["message"],
        ),
    ]


# ═══════════════════════════════════════════════════════════
# File verify
# ═══════════════════════════════════════════════════════════

def file_delete_verify() -> list[dict]:
    return [
        _verify_spec(
            f"find /sdcard/Download -name '{data.FILE_DELETE['file_name']}' 2>/dev/null",
            expect="",  # 空输出 = 文件不存在
        ),
    ]


def file_move_verify() -> list[dict]:
    return [
        _verify_spec(
            f"ls /sdcard/{data.FILE_MOVE['destination_folder']}/{data.FILE_MOVE['file_name']} 2>/dev/null",
            expect_re=data.FILE_MOVE["file_name"],
        ),
        _verify_spec(
            f"ls /sdcard/{data.FILE_MOVE['source_folder']}/{data.FILE_MOVE['file_name']} 2>/dev/null",
            expect="",  # 源位置不应存在
        ),
    ]


# ═══════════════════════════════════════════════════════════
# System verify
# ═══════════════════════════════════════════════════════════

def sys_bluetooth_off_verify() -> list[dict]:
    return [_verify_spec("settings get global bluetooth_on", expect="0")]


def sys_bluetooth_on_verify() -> list[dict]:
    return [_verify_spec("settings get global bluetooth_on", expect="1")]


def sys_wifi_off_verify() -> list[dict]:
    return [_verify_spec("settings get global wifi_on", expect="0")]


def sys_wifi_on_verify() -> list[dict]:
    return [_verify_spec("settings get global wifi_on", expect_re=r"[12]")]


def sys_brightness_max_verify() -> list[dict]:
    return [_verify_spec("settings get system screen_brightness", expect="255")]


def sys_brightness_min_verify() -> list[dict]:
    return [_verify_spec("settings get system screen_brightness", expect="1")]


def sys_clipboard_verify() -> list[dict]:
    """对齐 AW SystemCopyToClipboard.is_successful（fuzzy_match(clipboard_content)）：
    clipper.get 广播返回的剪贴板文本必须包含 data.SYS_CLIPBOARD_CONTENT（init
    已重置为哨兵值 '~~~RESET~~~'，未复制的旧内容不会通过）。"""
    return [
        _verify_spec(
            "am broadcast -a clipper.get 2>/dev/null",
            expect_re=re.escape(data.SYS_CLIPBOARD_CONTENT),
        ),
    ]


# ═══════════════════════════════════════════════════════════
# Camera verify
# ═══════════════════════════════════════════════════════════

def camera_photo_verify() -> list[dict]:
    """对齐 AW CameraTakePhoto：/sdcard/Pictures 顶层恰有 1 个 .jpg。

    AW is_successful 用非递归 ls 对比前后集合——隐藏目录 .thumbnails/ 里的
    缩略图不进集合。find 默认递归会数进 .thumbnails/*.jpg 导致恒 >1，
    必须加 -maxdepth 1（toybox 支持）。"""
    return [
        _verify_spec(
            "find /sdcard/Pictures -maxdepth 1 -name '*.jpg' 2>/dev/null | wc -l",
            expect="1",
        ),
    ]


def camera_video_verify() -> list[dict]:
    """对齐 AW CameraTakeVideo：/sdcard/Movies 顶层恰有 1 个非隐藏文件。

    AW is_successful 用非递归 ls 对比前后集合——隐藏文件（.pending-*.mp4、
    .thumbnails/、.nomedia 等）不进集合。find 递归计数会恒 >1，必须
    -maxdepth 1 且排除隐藏文件。"""
    return [
        _verify_spec(
            "find /sdcard/Movies -maxdepth 1 -type f -not -name '.*' 2>/dev/null | wc -l",
            expect="1",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# Markor verify
# ═══════════════════════════════════════════════════════════

def markor_create_note_verify() -> list[dict]:
    """验证 Markor 笔记已创建且内容匹配目标文本（对齐 AW CreateFile.check_file_content）。"""
    fn = data.MARKOR_NOTE_CREATE["file_name"]
    return [
        _verify_spec(
            f"cat /sdcard/Documents/Markor/{fn} 2>/dev/null",
            expect_re=re.escape(data.MARKOR_NOTE_CREATE["text"]),
        ),
    ]


# ═══════════════════════════════════════════════════════════
# Recipe verify — complete all 13 cases
# ═══════════════════════════════════════════════════════════

def recipe_delete_single_verify() -> list[dict]:
    db = data.DB_PATHS["broccoli"]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes WHERE title='{data.RECIPE_SPICY_TUNA['title']}';\"",
            expect="0",
        ),
    ]


def recipe_delete_single_with_noise_verify() -> list[dict]:
    """验证目标已删除 + 噪声行仍存在。"""
    db = data.DB_PATHS["broccoli"]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes WHERE title='{data.RECIPE_SPICY_TUNA['title']}';\"",
            expect="0",
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes;\"",
            expect="5",  # 5 noise rows remain
        ),
    ]


def recipe_delete_multiple_verify() -> list[dict]:
    db = data.DB_PATHS["broccoli"]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes WHERE title IN "
            f"('{data.RECIPE_SPICY_TUNA['title']}','{data.RECIPE_AVOCADO_TOAST['title']}',"
            f"'{data.RECIPE_GREEK_SALAD['title']}');\"",
            expect="0",
        ),
    ]


def recipe_delete_multiple_with_noise_verify() -> list[dict]:
    """3 个目标全部删除 + 总数 ≥ 29（29 噪声保留——floor 拒绝过度删除，
    对齐 AW validate_rows_removal_integrity：只删目标行，噪声行必须留下）。"""
    db = data.DB_PATHS["broccoli"]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes WHERE title IN "
            f"('{data.RECIPE_SPICY_TUNA['title']}','{data.RECIPE_AVOCADO_TOAST['title']}',"
            f"'{data.RECIPE_GREEK_SALAD['title']}');\"",
            expect="0",
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes;\"",
            expect_re=r"^(2[9]|[3-9][0-9])$",  # >= 29 noise rows remain (floor)
        ),
    ]


def recipe_delete_with_constraint_verify() -> list[dict]:
    """含盐目标全部删除（directions 含 'salt' 的行 = 0）+ 总数 ≥ 6
    （6 个盐-free 噪声保留——floor 拒绝过度删除；漏删目标则第一条失败）。"""
    db = data.DB_PATHS["broccoli"]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes WHERE directions LIKE '%salt%';\"",
            expect="0",
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes;\"",
            expect_re=r"[6-9]",  # 6 salt-free noise rows remain (floor)
        ),
    ]


def recipe_delete_duplicates_verify() -> list[dict]:
    db = data.DB_PATHS["broccoli"]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes WHERE title='{data.RECIPE_SPICY_TUNA['title']}';\"",
            expect="1",  # one instance remains
        ),
    ]


def _recipe_identity_where(r: dict) -> str:
    """食谱精确行身份条件（对齐 AW dataclass 全字段相等，含 favorite）。"""
    return (
        f"title='{r['title']}' AND description='{r['description']}' "
        f"AND servings='{r['servings']}' AND preparationTime='{r['preparationTime']}' "
        f"AND source='{r['source']}' AND ingredients='{r['ingredients']}' "
        f"AND directions='{r['directions']}' AND favorite={r['favorite']}"
    )


def recipe_delete_duplicates2_verify() -> list[dict]:
    """精确行身份：目标食谱（8 字段全等）恰剩 1 行 + 总数 11（init 12 行删 1 重复）。
    对齐 AW validate_rows_removal_integrity：只删 1 个重复行，其余行不动。"""
    db = data.DB_PATHS["broccoli"]
    t = data.RECIPE_SPICY_TUNA
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes WHERE "
            f"{_recipe_identity_where(t)};\"",
            expect="1",
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes;\"",
            expect="11",
        ),
    ]


def recipe_delete_duplicates3_verify() -> list[dict]:
    """精确行身份：目标食谱恰剩 1 行 + 总数 31（init 32 行删 1 重复）。"""
    db = data.DB_PATHS["broccoli"]
    t = data.RECIPE_SPICY_TUNA
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes WHERE "
            f"{_recipe_identity_where(t)};\"",
            expect="1",
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes;\"",
            expect="31",
        ),
    ]


def _recipe_field_count(rows: list[dict]) -> list[dict]:
    """每个目标食谱按字段级精确匹配 COUNT==1（对齐 AW compare_fields：
    title/description/servings/preparationTime/source/ingredients/directions；
    不含 favorite——app 写入默认 0，避免 schema 默认值差异导致假阴）。"""
    db = data.DB_PATHS["broccoli"]
    specs = []
    for r in rows:
        cond = (f"title='{r['title']}' AND description='{r['description']}' "
                f"AND servings='{r['servings']}' AND preparationTime='{r['preparationTime']}' "
                f"AND source='{r['source']}' AND ingredients='{r['ingredients']}' "
                f"AND directions='{r['directions']}'")
        specs.append(_verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes WHERE {cond};\"",
            expect="1",
        ))
    return specs


def _recipe_total(db: str, n: str) -> dict:
    """总数校验：AW len(after)==len(before)+n_rows（无多余添加/删除）。"""
    return _verify_spec(
        f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes;\"",
        expect=n,
    )


def recipe_add_single_verify() -> list[dict]:
    """目标食谱字段级 COUNT==1 + 总数 11（10 噪声 + 1 目标）。"""
    db = data.DB_PATHS["broccoli"]
    specs = _recipe_field_count([data.RECIPE_SPICY_TUNA])
    specs.append(_recipe_total(db, "11"))
    return specs


def recipe_add_multiple_verify() -> list[dict]:
    """3 个目标食谱各字段级 COUNT==1 + 总数 13（10 噪声 + 3 目标）。"""
    db = data.DB_PATHS["broccoli"]
    targets = [data.RECIPE_CHOCOLATE_CAKE, data.RECIPE_CHICKEN_SOUP,
               data.RECIPE_PASTA_PRIMAVERA]
    specs = _recipe_field_count(targets)
    specs.append(_recipe_total(db, "13"))
    return specs


def recipe_add_from_markor_verify() -> list[dict]:
    return recipe_add_multiple_verify()


def recipe_add_from_markor2_verify() -> list[dict]:
    """3 个 '30 mins' 目标：title IN (targets) AND preparationTime='30 mins' 恰 3 行
    + 总数 13（10 噪声 + 3 目标）。"""
    db = data.DB_PATHS["broccoli"]
    targets = [data.RECIPE_GREEK_SALAD, data.RECIPE_QUINOA_BOWL,
               data.RECIPE_TERIYAKI_SALMON]
    titles = "','".join(t["title"] for t in targets)
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM recipes WHERE title IN ('{titles}') "
            f"AND preparationTime='30 mins';\"",
            expect="3",
        ),
        _recipe_total(db, "13"),
    ]


def recipe_add_from_image_verify() -> list[dict]:
    return recipe_add_multiple_verify()


# ═══════════════════════════════════════════════════════════
# Expense verify — complete all 9 cases
# ═══════════════════════════════════════════════════════════

def expense_delete_single_verify() -> list[dict]:
    db = data.DB_PATHS["expense"]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM expense WHERE name='{data.EXPENSE_LUNCH['name']}';\"",
            expect="0",
        ),
    ]


def expense_delete_multiple_verify() -> list[dict]:
    db = data.DB_PATHS["expense"]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM expense WHERE name IN "
            f"('{data.EXPENSE_LUNCH['name']}','{data.EXPENSE_COFFEE['name']}',"
            f"'{data.EXPENSE_TAXI['name']}');\"",
            expect="0",
        ),
    ]


def expense_delete_multiple2_verify() -> list[dict]:
    """3 目标（Lunch/Coffee/Taxi Ride）按名直查全为 0 + 总行数 = 50
    （init 共 50 噪声 + 3 目标 = 53 行）——镜像 expense_delete_multiple_verify
    的目标直查 + 总数完整性双保险（误删噪声行也会破坏总数）。"""
    db = data.DB_PATHS["expense"]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM expense WHERE name IN "
            f"('{data.EXPENSE_LUNCH['name']}','{data.EXPENSE_COFFEE['name']}',"
            f"'{data.EXPENSE_TAXI['name']}');\"",
            expect="0",
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM expense;\"",
            expect="50",
        ),
    ]


def expense_delete_duplicates_verify() -> list[dict]:
    db = data.DB_PATHS["expense"]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM expense WHERE name='{data.EXPENSE_LUNCH['name']}';\"",
            expect="1",  # one instance remains
        ),
    ]


def expense_delete_duplicates2_verify() -> list[dict]:
    """精确行身份 COUNT==1（2 个完全相同 Lunch 目标须剩 1 个）+ 总数 41（init 42 行）。
    对齐 AW validate_rows_removal_integrity：只删 1 个重复行，其余行不动。"""
    db = data.DB_PATHS["expense"]
    e = data.EXPENSE_LUNCH
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM expense WHERE name='{e['name']}' "
            f"AND amount={e['amount']} AND category={e['category']};\"",
            expect="1",
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM expense;\"",
            expect="41",
        ),
    ]


def expense_add_single_verify() -> list[dict]:
    """目标行精确 1 行（对齐 AW validate_rows_addition_integrity 的
    compare_fields=['name','amount','category','note']）+ 总数完整性
    （init 9 噪声 + 1 目标 = 10 行）。"""
    db = data.DB_PATHS["expense"]
    e = data.EXPENSE_LUNCH
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM expense WHERE name='{e['name']}' "
            f"AND amount={e['amount']} AND category={e['category']};\"",
            expect="1",
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM expense;\"",
            expect="10",
        ),
    ]


def _expense_target_counts(rows: list[dict], note_like: str = "") -> list[dict]:
    """每个目标按 name+amount+category（+可选 note LIKE）精确 COUNT==1。
    对齐 AW compare_fields=['name','amount','category','note']。"""
    db = data.DB_PATHS["expense"]
    specs = []
    for e in rows:
        sql = (f"SELECT COUNT(*) FROM expense WHERE name='{e['name']}' "
               f"AND amount={e['amount']} AND category={e['category']}")
        if note_like:
            sql += f" AND note LIKE '%{note_like}%'"
        specs.append(_verify_spec(f"sqlite3 {db} \"{sql};\"", expect="1"))
    return specs


def expense_add_multiple_verify() -> list[dict]:
    """3 目标各恰 1 行 + 总数恰 13（init 10 噪声 + 3 目标）——多记/漏记都失败，
    对齐 AW validate_rows_addition_integrity（after-before 不得有参考行以外的行）。"""
    db = data.DB_PATHS["expense"]
    specs = _expense_target_counts([data.EXPENSE_LUNCH, data.EXPENSE_COFFEE,
                                    data.EXPENSE_TAXI])
    specs.append(_verify_spec(
        f"sqlite3 {db} \"SELECT COUNT(*) FROM expense;\"",
        expect="13",
    ))
    return specs


def expense_add_from_markor_verify() -> list[dict]:
    """2 个 Reimbursable 目标各恰 1 行（note 含 Reimbursable）+ 总数恰 102
    （init 100 噪声 + 2 目标）——多记额外交易也失败，对齐 AW
    validate_rows_addition_integrity。"""
    db = data.DB_PATHS["expense"]
    specs = _expense_target_counts([data.EXPENSE_LUNCH, data.EXPENSE_COFFEE],
                                   note_like="Reimbursable")
    specs.append(_verify_spec(
        f"sqlite3 {db} \"SELECT COUNT(*) FROM expense;\"",
        expect="102",
    ))
    return specs


def expense_add_from_gallery_verify() -> list[dict]:
    """expenses.jpg 中的 3 个目标各恰 1 行。"""
    return _expense_target_counts([data.EXPENSE_LUNCH, data.EXPENSE_COFFEE,
                                   data.EXPENSE_TAXI])


# ═══════════════════════════════════════════════════════════
# Calendar verify — complete all 17 cases
# ═══════════════════════════════════════════════════════════

def _calendar_day_epoch_s(day: int) -> int:
    """2023-10-{day} 00:00 UTC 的 epoch 秒（device TZ=UTC，对齐 AW
    device_constants.TIMEZONE='UTC'）。2023-10-15 00:00 UTC = 1697328000。"""
    return 1697328000 + (day - 15) * 86400


def _calendar_row_checks(start_ts: int, title: str = "Test Meeting") -> list[dict]:
    """单事件创建验证：start/end/description 精确匹配 + 总数恰 1（无副作用）。
    对齐 AW validate_event_addition_integrity（逐字段对比 after-before）。"""
    db = data.DB_PATHS.get("calendar", "/data/data/com.simplemobiletools.calendar.pro/databases/events.db")
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT start_ts FROM events WHERE title='{title}';\" 2>/dev/null",
            expect=str(start_ts),
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT end_ts FROM events WHERE title='{title}';\" 2>/dev/null",
            expect=str(start_ts + 3600),
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT description FROM events WHERE title='{title}';\" 2>/dev/null",
            expect="Automated test event",
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM events;\" 2>/dev/null",
            expect="1",
        ),
    ]


def calendar_add_one_event_verify() -> list[dict]:
    """对齐 AW SimpleCalendarAddOneEvent：goal 2023-10-15 14h → start_ts =
    2023-10-15 14:00 UTC = 1697378400，时长 60 min（end-start=3600），总数 1。"""
    return _calendar_row_checks(_calendar_day_epoch_s(15) + 14 * 3600)


def calendar_add_one_event_relative_day_verify() -> list[dict]:
    """'this Thursday'（2023-10-19，设备日期 2023-10-15 周日后的 AW Mon-Sat
    区间内）at 14h → 1697724000，时长 60 min，总数 1。"""
    return _calendar_row_checks(_calendar_day_epoch_s(19) + 14 * 3600)


def calendar_add_one_event_tomorrow_verify() -> list[dict]:
    """'tomorrow'（2023-10-16）at 14h → 1697464800，时长 60 min，总数 1。"""
    return _calendar_row_checks(_calendar_day_epoch_s(16) + 14 * 3600)


def calendar_add_one_event_in_two_weeks_verify() -> list[dict]:
    """'in two weeks from today'（2023-10-29）at 14h → 1698588000，时长 60 min，总数 1。"""
    return _calendar_row_checks(_calendar_day_epoch_s(29) + 14 * 3600)


def calendar_add_repeating_event_verify() -> list[dict]:
    """对齐 AW SimpleCalendarAddRepeatingEvent（AW 显式对比 repeat_rule /
    repeat_interval）：daily → repeat_interval=86400、repeat_rule=0；
    起始 2023-10-15 14:00 UTC，时长 60 min，总数 1。"""
    db = data.DB_PATHS.get("calendar", "/data/data/com.simplemobiletools.calendar.pro/databases/events.db")
    specs = _calendar_row_checks(_calendar_day_epoch_s(15) + 14 * 3600)
    specs[1:1] = [
        _verify_spec(
            f"sqlite3 {db} \"SELECT repeat_interval FROM events WHERE title='Test Meeting';\" 2>/dev/null",
            expect="86400",
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT repeat_rule FROM events WHERE title='Test Meeting';\" 2>/dev/null",
            expect="0",
        ),
    ]
    return specs


def calendar_delete_events_verify() -> list[dict]:
    """对齐 AW SimpleCalendarDeleteEvents（n_rows=3 / n_rows_noise=20）：
    3 个目标（同在 2023-10-15）全部删除 + 总数 = 20 + 标题去重数 = 20
    （20 个噪声标题互异且在其他日期，必须全部保留——防误删/防补写）。"""
    db = data.DB_PATHS.get("calendar", "/data/data/com.simplemobiletools.calendar.pro/databases/events.db")
    specs = []
    for t in ["Test Meeting", "Team Lunch", "Project Review"]:
        specs.append(_verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM events WHERE title='{t}';\" 2>/dev/null",
            expect="0",
        ))
    specs.append(_verify_spec(
        f"sqlite3 {db} \"SELECT COUNT(*) FROM events;\" 2>/dev/null",
        expect="20",  # noise rows outside the goal date remain
    ))
    specs.append(_verify_spec(
        f"sqlite3 {db} \"SELECT COUNT(DISTINCT title) FROM events;\" 2>/dev/null",
        expect="20",  # none of the distinct noise titles removed/added
    ))
    return specs


def calendar_delete_one_event_verify() -> list[dict]:
    db = data.DB_PATHS.get("calendar", "/data/data/com.simplemobiletools.calendar.pro/databases/events.db")
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM events WHERE title='Test Meeting';\" 2>/dev/null",
            expect="0",
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM events;\" 2>/dev/null",
            expect_re=r"[1-9]",  # 旧事件应保留
        ),
    ]


def calendar_delete_events_on_relative_day_verify() -> list[dict]:
    """对齐 AW SimpleCalendarDeleteEventsOnRelativeDay：'this Saturday' = 2023-10-21
    的 2 个目标事件全部删除；噪声（周五 Birthday / 周日 Brunch / 18 个其他日期
    事件，init 共 20 噪声）必须原样保留 → 总数恰 20（同 AW
    validate_event_removal_integrity：目标行外不得有任何增删）。"""
    db = data.DB_PATHS.get("calendar", "/data/data/com.simplemobiletools.calendar.pro/databases/events.db")
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM events WHERE title='Saturday Brunch';\" 2>/dev/null",
            expect="0",  # target removed
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM events WHERE title='Weekend Market Trip';\" 2>/dev/null",
            expect="0",  # target removed
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM events WHERE title='Alice Smith Birthday';\" 2>/dev/null",
            expect="1",  # non-target preserved
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM events;\" 2>/dev/null",
            expect="20",  # noise must remain exactly (2 targets + 20 noise seeded)
        ),
    ]


def calendar_query_any_events_on_date_verify() -> list[dict]:
    """对齐 AW SimpleCalendarAnyEventsOnDate：提问日期 2023-10-15 恰有 3 个
    事件（答案必为这 3 个标题，逗号分隔）；噪声事件在其他日期不影响回答。
    （框架无 answer 通道，以 DB 状态校验答案内容：3 标题各恰 1 个 + 当日总数 3。）"""
    db = data.DB_PATHS.get("calendar", "/data/data/com.simplemobiletools.calendar.pro/databases/events.db")
    day_lo = _calendar_day_epoch_s(15)
    day_hi = _calendar_day_epoch_s(16)
    specs = [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r"calendar",
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM events WHERE start_ts >= {day_lo} "
            f"AND start_ts < {day_hi};\" 2>/dev/null",
            expect="3",
        ),
    ]
    for t in ["Test Meeting", "Team Lunch", "Project Review"]:
        specs.append(_verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM events WHERE title='{t}' "
            f"AND start_ts >= {day_lo} AND start_ts < {day_hi};\" 2>/dev/null",
            expect="1",
        ))
    return specs


def _calendar_rows_exist(rows: list[tuple[str, int]]) -> list[dict]:
    """断言 (title, start_ts 秒) 行各恰 1 条仍在 events.db。

    查询类任务的弱验证：shell 框架无法读取 agent 的文本答案，至少保证
    seed 数据在 run 后原样存在（idle 状态过不了前台 activity 检查，也
    过不了这里的行级检查）。残余限制：无法校验 agent 回答的文本内容。
    """
    db = data.DB_PATHS.get("calendar", "/data/data/com.simplemobiletools.calendar.pro/databases/events.db")
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM events WHERE title='{t}' "
            f"AND start_ts={ts};\" 2>/dev/null",
            expect="1",
        )
        for t, ts in rows
    ]


def calendar_query_event_on_date_at_time_verify() -> list[dict]:
    """对齐 AW SimpleCalendarEventOnDateAtTime：'October 15 2023 at 18:00'
    → 答案 'Test Meeting'（seed 中该时刻唯一事件，start_ts=1697392800）。"""
    ev = data.CAL_EVENT_TEAM_MEETING
    return calendar_query_activity_verify() + _calendar_rows_exist(
        [(ev["title"], int(ev["dtstart"]) // 1000)])


def calendar_query_events_in_next_week_verify() -> list[dict]:
    """对齐 AW SimpleCalendarEventsInNextWeek：'next week'（Mon 2023-10-16 ~
    Sun 10-22）内恰 2 个种子事件（Team Lunch 10-16 14:00 + Project Review
    10-17 10:00）仍存在——答案 = 这 2 个标题。（V5 限制：shell 框架无法读取
    agent 的文本答案，以 DB 状态校验答案内容；与 AW 的答案检查对比时需知悉。）"""
    rows = [(ev["title"], int(ev["dtstart"]) // 1000)
            for ev in (data.CAL_EVENT_LUNCH, data.CAL_EVENT_REVIEW)]
    return calendar_query_activity_verify() + _calendar_rows_exist(rows)


def calendar_query_events_in_time_range_verify() -> list[dict]:
    """对齐 AW SimpleCalendarEventsInTimeRange：'between 10:00 and 8pm
    October 16 2023' → 答案 'Team Lunch'（10-16 唯一事件，14:00-15:00 在窗内）。"""
    ev = data.CAL_EVENT_LUNCH
    return calendar_query_activity_verify() + _calendar_rows_exist(
        [(ev["title"], int(ev["dtstart"]) // 1000)])


def calendar_query_events_on_date_verify() -> list[dict]:
    """对齐 AW SimpleCalendarEventsOnDate：'October 15 2023' → 答案
    'Test Meeting'（当日唯一事件，start_ts=1697392800）。"""
    ev = data.CAL_EVENT_TEAM_MEETING
    return calendar_query_activity_verify() + _calendar_rows_exist(
        [(ev["title"], int(ev["dtstart"]) // 1000)])


# Query tasks: V5 verification (activity + content)
def calendar_query_activity_verify() -> list[dict]:
    """V5: 验证日历应用在前台（db 已有数据，agent 应能查询到）。"""
    return [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r"calendar",
        ),
    ]


def calendar_query_first_event_after_start_verify() -> list[dict]:
    """对齐 AW SimpleCalendarFirstEventAfterStartTime：'after 14:00 Oct 15 2023'
    → 答案 'Test Meeting'（18:00，14:00 后第一个事件）。shell 框架无法读 agent
    文本答案——以 DB 断言答案行仍在 + 前台 activity 校验（残余限制：答案文本
    内容不可校验，仅校验答案所依据的数据未变）。"""
    ev = data.CAL_EVENT_TEAM_MEETING
    return calendar_query_activity_verify() + _calendar_rows_exist(
        [(ev["title"], int(ev["dtstart"]) // 1000)])


def calendar_query_location_verify() -> list[dict]:
    """对齐 AW SimpleCalendarLocationOfEvent：答案 'Conference Room A'（seed 的
    location 列）。DB 断言 location 字段 + 前台 activity。"""
    db = data.DB_PATHS.get("calendar",
                           "/data/data/com.simplemobiletools.calendar.pro/databases/events.db")
    return calendar_query_activity_verify() + [
        _verify_spec(
            f"sqlite3 {db} \"SELECT location FROM events WHERE title='Test Meeting';\" 2>/dev/null",
            expect_re="Conference Room A",
        ),
    ]


def calendar_query_next_event_verify() -> list[dict]:
    """对齐 AW SimpleCalendarNextEvent：设备时间 15:34 Oct 15，'next upcoming
    event' → 答案 'Test Meeting'（18:00，唯一的未来 Oct 15 事件，与 AW 的
    exclusion 语义一致）。DB 断言答案行仍在（打开日历 app 本身不通过该检查）。"""
    ev = data.CAL_EVENT_TEAM_MEETING
    return calendar_query_activity_verify() + _calendar_rows_exist(
        [(ev["title"], int(ev["dtstart"]) // 1000)])


def calendar_query_next_meeting_with_person_verify() -> list[dict]:
    """对齐 AW SimpleCalendarNextMeetingWithPerson：标题含 'Alice Smith' 的下一事件
    → 'Drinks with Alice Smith'（Oct 20 09:00）。DB 断言答案行仍在。"""
    return calendar_query_activity_verify() + _calendar_rows_exist(
        [("Drinks with Alice Smith", _calendar_day_epoch_s(20) + 9 * 3600)])


# ═══════════════════════════════════════════════════════════
# Retro Music verify — 4 cases
# ═══════════════════════════════════════════════════════════

def retro_activity_verify() -> list[dict]:
    return [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r".",
        ),
    ]


def _retro_playlist_song_spec(p: dict) -> list[dict]:
    """playlist 存在 + 歌曲按 song_key 顺序逐行匹配（^...$ 锚定 = 精确歌单，
    多/缺/乱序歌都失败）。对齐 AW verify_playlist / _get_playlist_info_query。"""
    db = data.DB_PATHS["retro_playlist"]
    ordered = "^" + r"\s*\n".join(
        re.escape(f"{p['name']}|{t}") for t in p["songs"]) + r"\s*$"
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM PlaylistEntity "
            f"WHERE playlist_name='{p['name']}';\" 2>/dev/null",
            expect="1",
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT pe.playlist_name, se.title "
            f"FROM PlaylistEntity pe JOIN SongEntity se "
            f"ON pe.playlist_id = se.playlist_creator_id "
            f"WHERE pe.playlist_name='{p['name']}' "
            f"ORDER BY pe.playlist_name, se.song_key;\" 2>/dev/null",
            expect_re=ordered,
        ),
    ]


def retro_playlist_verify() -> list[dict]:
    """对齐 AW RetroCreatePlaylist.is_successful（_get_playlist_info_query）：
    playlist.db 中 'Test Playlist jwt' 恰 1 个，且 3 首目标歌按 song_key
    顺序 0/1/2 存在（join 输出逐行匹配 = 顺序敏感）。"""
    p = data.RETRO_PLAYLIST
    return _retro_playlist_song_spec(p)


def retro_playing_queue_verify() -> list[dict]:
    """对齐 AW RetroPlayingQueue.is_successful：SELECT title FROM playing_queue
    恰等于目标歌单（顺序一致，^...$ 锚定禁止多/缺歌）。"""
    db = data.DB_PATHS["retro_playback"]
    titles = data.RETRO_PLAYLIST["songs"]
    exact = "^" + r"\s*\n\s*".join(re.escape(t) for t in titles) + r"\s*$"
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT title FROM playing_queue;\" 2>/dev/null",
            expect_re=exact,
        ),
    ]


def retro_playlist_duration_verify() -> list[dict]:
    """对齐 AW RetroPlaylistDuration.is_successful：目标 playlist 歌曲时长总和
    落在 [2700000, 3000000] ms（45-50 min）。init 预置 10 首目标歌总和恰为
    2850000 ms——存在正确答案。"""
    db = data.DB_PATHS["retro_playlist"]
    p = data.RETRO_PLAYLIST_PED
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT SUM(se.duration) "
            f"FROM PlaylistEntity pe JOIN SongEntity se "
            f"ON pe.playlist_id = se.playlist_creator_id "
            f"WHERE pe.playlist_name='{p['name']}';\" 2>/dev/null",
            expect_re=r"^(2[7-9][0-9]{5}|3000000)$",  # 2700000..3000000
        ),
    ]


def retro_save_playlist_verify() -> list[dict]:
    """对齐 AW RetroSavePlaylist.is_successful（super() 的 playlist DB 校验 +
    check_file_exists(DOWNLOAD, '<name>.m3u') 各占 0.5）：
    'Test Playlist fet' 恰 1 个 + 3 首歌按序 + Download 下 m3u 导出存在。"""
    p = data.RETRO_PLAYLIST_SAVE
    specs = _retro_playlist_song_spec(p)
    specs.append(_verify_spec(
        f"ls \"/sdcard/Download/{p['name']}.m3u\" 2>/dev/null || echo NOT_FOUND",
        expect_re=re.escape(p["name"]),
    ))
    return specs


# ═══════════════════════════════════════════════════════════
# VLC verify — 2 cases
# ═══════════════════════════════════════════════════════════

def vlc_activity_verify() -> list[dict]:
    return [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r".",
        ),
    ]


def _vlc_playlist_song_spec(p: dict) -> list[dict]:
    """playlist 存在 + 视频按 position 顺序逐行匹配（^...$ 锚定 = 精确歌单，
    多/缺/乱序视频都失败）。对齐 AW verify_playlist（name+filename+position 三列
    全等、顺序敏感）与 _get_playlist_info_query 的 join 输出格式。

    走 sqlite3_cat 宿主查询：设备端 sqlite3 3.32 无法解析 VLC 新版 SQLite 生成的
    UPDATE...FROM 触发器（malformed database schema），on-device 查询必然失败；
    fastaget/verify.py 对该前缀支持 cat+base64 拉到宿主、用宿主 sqlite3 执行。"""
    db = data.DB_PATHS["vlc"]
    ordered = "^" + r"\s*\n".join(
        re.escape(f"{p['name']}|{f}|{i}") for i, f in enumerate(p["videos"])) + r"\s*$"
    return [
        _verify_spec(
            f"sqlite3_cat:{db}::SELECT COUNT(*) FROM Playlist "
            f"WHERE name='{p['name']}';",
            expect="1",
        ),
        _verify_spec(
            f"sqlite3_cat:{db}::SELECT Playlist.name, Media.filename, "
            f"PlaylistMediaRelation.position FROM PlaylistMediaRelation "
            f"INNER JOIN Playlist ON Playlist.id_playlist = PlaylistMediaRelation.playlist_id "
            f"INNER JOIN Media ON Media.id_media = PlaylistMediaRelation.media_id "
            f"WHERE Playlist.name='{p['name']}' "
            f"ORDER BY Playlist.name, PlaylistMediaRelation.position;",
            expect_re=ordered,
        ),
    ]


def vlc_create_playlist_verify() -> list[dict]:
    """对齐 AW VlcCreatePlaylist.is_successful（verify_playlist）：
    'Test Playlist wjj' 恰 1 个，且 3 个目标视频按 position 0/1/2 顺序存在
    （join 输出逐行匹配 = 顺序敏感；噪声视频 other_video_*.mp4 不得入 playlist）。"""
    return _vlc_playlist_song_spec(data.VLC_PLAYLIST)


def vlc_create_two_playlists_verify() -> list[dict]:
    """对齐 AW VlcCreateTwoPlaylists.is_successful（两个 playlist 各占 0.5）：
    'Playlist Alpha mor'（demo_1/demo_2 按序）+ 'Playlist Beta vnx'
    （demo_3/demo_4 按序），每个 join 输出逐行锚定。"""
    return (_vlc_playlist_song_spec(data.VLC_PLAYLIST_ALPHA)
            + _vlc_playlist_song_spec(data.VLC_PLAYLIST_BETA))


# ═══════════════════════════════════════════════════════════
# Tasks app verify — 7 cases (V5)
# ═══════════════════════════════════════════════════════════

def tasks_activity_verify() -> list[dict]:
    """查询类任务的前台校验：agent 须停在 Tasks app 内作答（对齐 calendar
    查询任务的 calendar 锚点模式——只停在任意界面过不了）。"""
    return [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r"org\.tasks",
        ),
    ]


def _task_titles_expect(titles: list[str]) -> str:
    r"""多标题输出的 expect_re：^t1\s*\n\s*t2...$（对齐 opentracks_on_date 的
    '^Running\s*\n\s*Biking$' 匹配风格）。"""
    return "^" + r"\s*\n\s*".join(re.escape(t) for t in titles) + "$"


def tasks_due_on_date_verify() -> list[dict]:
    """对齐 AW TasksDueOnDate：due 2026-07-17 的固定任务恰 3 条且标题匹配
    （答案 3 标题的 DB 前提）；噪声任务都在其他日期。"""
    db = data.DB_PATHS["tasks"]
    lo = data.TASK_DUE_2026_07_17_MS
    hi = lo + 86400000
    titles = [t["title"] for t in data.TASKS_DUE_ON_DATE]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT title FROM tasks WHERE dueDate >= {lo} "
            f"AND dueDate < {hi} ORDER BY _id;\" 2>/dev/null",
            expect_re=_task_titles_expect(titles),
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM tasks WHERE dueDate >= {lo} "
            f"AND dueDate < {hi};\" 2>/dev/null",
            expect="3",
        ),
    ]


def tasks_completed_for_date_verify() -> list[dict]:
    """对齐 AW TasksCompletedTasksForDate：due 2026-07-17 且已完成（completed!=0）
    的固定任务恰 3 条、标题匹配（答案 3 标题的 DB 前提）；due 同日未完成的
    噪声任务不得计入。"""
    db = data.DB_PATHS["tasks"]
    lo = data.TASK_DUE_2026_07_17_MS
    hi = lo + 86400000
    titles = [t["title"] for t in data.TASKS_DUE_ON_DATE]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT title FROM tasks WHERE dueDate >= {lo} "
            f"AND dueDate < {hi} AND completed != 0 ORDER BY _id;\" 2>/dev/null",
            expect_re=_task_titles_expect(titles),
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM tasks WHERE dueDate >= {lo} "
            f"AND dueDate < {hi} AND completed != 0;\" 2>/dev/null",
            expect="3",
        ),
    ]


def tasks_due_next_week_verify() -> list[dict]:
    """对齐 AW TasksDueNextWeek：下一周窗口 [2023-10-16, 2023-10-23) 内恰 6 条
    固定任务（答案=6）；噪声任务在本周/再下周。"""
    db = data.DB_PATHS["tasks"]
    lo = data.TASK_NEXT_WEEK_START_MS
    hi = lo + 7 * 86400000
    titles = [t["title"] for t in data.TASKS_DUE_NEXT_WEEK]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM tasks WHERE dueDate >= {lo} "
            f"AND dueDate < {hi};\" 2>/dev/null",
            expect="6",
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT title FROM tasks WHERE dueDate >= {lo} "
            f"AND dueDate < {hi} ORDER BY _id;\" 2>/dev/null",
            expect_re=_task_titles_expect(titles),
        ),
    ]


def tasks_high_priority_verify() -> list[dict]:
    """对齐 AW TasksHighPriorityTasks：importance=0 的固定任务恰 3 条、标题匹配
    （答案 3 标题的 DB 前提）；噪声任务 importance 1-3 不得计入。"""
    db = data.DB_PATHS["tasks"]
    titles = [t["title"] for t in data.TASKS_HIGH_PRIORITY]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT title FROM tasks WHERE importance=0 "
            f"ORDER BY _id;\" 2>/dev/null",
            expect_re=_task_titles_expect(titles),
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM tasks WHERE importance=0;\" 2>/dev/null",
            expect="3",
        ),
    ]


def tasks_high_priority_due_on_date_verify() -> list[dict]:
    """对齐 AW TasksHighPriorityTasksDueOnDate：due 2023-10-17 且 importance=0
    的固定任务恰 1 条、标题匹配（答案标题的 DB 前提）；噪声任务在其他日期
    或 importance 1-3，不得计入。"""
    db = data.DB_PATHS["tasks"]
    lo = data.TASK_OCT17_2023_MS
    hi = lo + 86400000
    title = data.TASK_FINISH_REPORT["title"]
    specs = tasks_activity_verify()
    specs.append(_verify_spec(
        f"sqlite3 {db} \"SELECT title FROM tasks WHERE importance=0 "
        f"AND dueDate >= {lo} AND dueDate < {hi} ORDER BY _id;\" 2>/dev/null",
        expect_re=re.escape(title),
    ))
    specs.append(_verify_spec(
        f"sqlite3 {db} \"SELECT COUNT(*) FROM tasks WHERE importance=0 "
        f"AND dueDate >= {lo} AND dueDate < {hi};\" 2>/dev/null",
        expect="1",
    ))
    return specs


def tasks_incomplete_tasks_on_date_verify() -> list[dict]:
    """对齐 AW TasksIncompleteTasksOnDate：due 2023-10-17 且未完成（completed=0）
    的固定任务恰 3 条、标题匹配（答案 3 标题的 DB 前提）；噪声任务晚于 10-17
    或已完成，不得计入。"""
    db = data.DB_PATHS["tasks"]
    lo = data.TASK_OCT17_2023_MS
    hi = lo + 86400000
    titles = [t["title"] for t in data.TASKS_DUE_ON_DATE]
    specs = tasks_activity_verify()
    specs.append(_verify_spec(
        f"sqlite3 {db} \"SELECT title FROM tasks WHERE completed=0 "
        f"AND dueDate >= {lo} AND dueDate < {hi} ORDER BY _id;\" 2>/dev/null",
        expect_re=_task_titles_expect(titles),
    ))
    specs.append(_verify_spec(
        f"sqlite3 {db} \"SELECT COUNT(*) FROM tasks WHERE completed=0 "
        f"AND dueDate >= {lo} AND dueDate < {hi};\" 2>/dev/null",
        expect="3",
    ))
    return specs


# ═══════════════════════════════════════════════════════════
# OpenTracks verify — 7 cases (V5)
# ═══════════════════════════════════════════════════════════

def opentracks_activity_verify() -> list[dict]:
    return [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r".",
        ),
    ]


def _ot_day_epoch_ms(day: int) -> int:
    """2023-10-{day} 00:00 UTC 的 epoch 毫秒（与 init 的 _ot_day_ms 同源）。"""
    return (1697328000 + (day - 15) * 86400) * 1000


def opentracks_activities_count_for_week_verify() -> list[dict]:
    """对齐 AW SportsTrackerActivitiesCountForWeek：week Mon 10-09 ~ Sun 10-15
    内 Running 恰 2 条（COUNT=2，即答案 '2' 的 DB 前提——只打开 app 不通过）。
    残余限制：答案文本内容不可校验，仅校验答案所依据的 DB 状态。"""
    lo = _ot_day_epoch_ms(9)
    hi = _ot_day_epoch_ms(16)
    return [
        _verify_spec(
            f"sqlite3 {data.DB_PATHS['opentracks']} \"SELECT COUNT(*) FROM tracks "
            f"WHERE category='Running' AND starttime >= {lo} AND starttime < {hi};\" "
            f"2>/dev/null",
            expect="2",
        ),
    ]


def opentracks_activities_on_date_verify() -> list[dict]:
    """对齐 AW SportsTrackerActivitiesOnDate：10-12 当日按开始时间排序的类目恰为
    Running/Biking（答案 'Running, Biking' 的 DB 前提，顺序确定）。"""
    lo = _ot_day_epoch_ms(12)
    hi = _ot_day_epoch_ms(13)
    return [
        _verify_spec(
            f"sqlite3 {data.DB_PATHS['opentracks']} \"SELECT category FROM tracks "
            f"WHERE starttime >= {lo} AND starttime < {hi} ORDER BY starttime;\" "
            f"2>/dev/null",
            expect_re=r"^Running\s*\n\s*Biking\s*$",
        ),
    ]


def opentracks_activity_duration_verify() -> list[dict]:
    """对齐 AW SportsTrackerActivityDuration：10-12 的 Running 活动时长恰 30 分钟
    （(stoptime-starttime)/60000=30，即答案 '30' 的 DB 前提）。"""
    lo = _ot_day_epoch_ms(12)
    hi = _ot_day_epoch_ms(13)
    return [
        _verify_spec(
            f"sqlite3 {data.DB_PATHS['opentracks']} \"SELECT (stoptime-starttime)/60000 "
            f"FROM tracks WHERE category='Running' AND starttime >= {lo} "
            f"AND starttime < {hi};\" 2>/dev/null",
            expect="30",
        ),
    ]


def opentracks_longest_distance_verify() -> list[dict]:
    """对齐 AW SportsTrackerLongestDistanceActivity：周内 Running 最大距离 = 5000 米
    （CAST AS INTEGER 对齐 'rounded to the nearest integer'，即答案 '5000' 的 DB 前提）。"""
    lo = _ot_day_epoch_ms(9)
    hi = _ot_day_epoch_ms(16)
    return [
        _verify_spec(
            f"sqlite3 {data.DB_PATHS['opentracks']} \"SELECT CAST(MAX(totaldistance) "
            f"AS INTEGER) FROM tracks WHERE category='Running' AND starttime >= {lo} "
            f"AND starttime < {hi};\" 2>/dev/null",
            expect="5000",
        ),
    ]


def opentracks_total_distance_verify() -> list[dict]:
    """对齐 AW SportsTrackerTotalDistanceForCategoryOverInterval：区间 Oct 9 ~ Oct 15
    内 Running 距离总和 = 8000 米（CAST AS INTEGER 对齐 rounded to the nearest
    integer，即答案 '8000' 的 DB 前提）。"""
    lo = _ot_day_epoch_ms(9)
    hi = _ot_day_epoch_ms(16)
    return [
        _verify_spec(
            f"sqlite3 {data.DB_PATHS['opentracks']} \"SELECT CAST(SUM(totaldistance) "
            f"AS INTEGER) FROM tracks WHERE category='Running' AND starttime >= {lo} "
            f"AND starttime < {hi};\" 2>/dev/null",
            expect="8000",
        ),
    ]


def opentracks_total_duration_verify() -> list[dict]:
    """对齐 AW SportsTrackerTotalDurationForCategoryThisWeek：week Mon 10-09 ~
    Sun 10-15 内 Running 时长总和 = 50 分钟（30+20=50，即答案 '50' 的 DB 前提）；
    噪声（周内 Biking / 周外 Running）被类别与周窗口双重排除。"""
    lo = _ot_day_epoch_ms(9)
    hi = _ot_day_epoch_ms(16)
    return [
        _verify_spec(
            f"sqlite3 {data.DB_PATHS['opentracks']} \"SELECT SUM((stoptime-starttime)"
            f"/60000) FROM tracks WHERE category='Running' AND starttime >= {lo} "
            f"AND starttime < {hi};\" 2>/dev/null",
            expect="50",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# Joplin Notes verify — 4 cases (V5)
# ═══════════════════════════════════════════════════════════

def notes_activity_verify() -> list[dict]:
    return [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r".",
        ),
    ]


def notes_is_todo_verify() -> list[dict]:
    """目标笔记恰 1 行且 is_todo=0（AW 期望答案 'False' 的 DB 前提）。"""
    db = data.DB_PATHS["joplin"]
    n = data.JOPLIN_RECIPE_NOTE
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM notes WHERE title='{n['title']}' "
            f"AND is_todo={n['is_todo']};\" 2>/dev/null",
            expect="1",
        ),
    ]


def notes_meeting_attendee_count_verify() -> list[dict]:
    """目标笔记恰 1 行 + body 含 5 位参会者（AW 期望答案 5 的 DB 前提）。"""
    db = data.DB_PATHS["joplin"]
    n = data.JOPLIN_MEETING_NOTE
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM notes WHERE title='{n['title']}';\" 2>/dev/null",
            expect="1",
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT body FROM notes WHERE title='{n['title']}';\" 2>/dev/null",
            expect_re=re.escape("5 participants"),  # attendee_count（对齐 AW body 模板）
        ),
    ]


def notes_recipe_ingredient_count_verify() -> list[dict]:
    """目标食谱笔记恰 1 行 + body 含答案 '3 tablespoons salt'（对齐 AW
    success_criteria: {ingredient_quantity} {ingredient} = '3 tablespoons salt'）。"""
    db = data.DB_PATHS["joplin"]
    n = data.JOPLIN_RECIPE_GAE
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM notes WHERE title='{n['title']}';\" 2>/dev/null",
            expect="1",
        ),
        _verify_spec(
            f"sqlite3 {db} \"SELECT body FROM notes WHERE title='{n['title']}';\" 2>/dev/null",
            expect_re=re.escape("3 tablespoons salt"),
        ),
    ]


def notes_todo_item_count_verify() -> list[dict]:
    """'Personal' 文件夹中 is_todo=1 的笔记恰 3 条（AW 期望答案 3 的 DB 前提）。"""
    db = data.DB_PATHS["joplin"]
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM notes WHERE is_todo=1 AND "
            f"parent_id=(SELECT id FROM folders WHERE title='Personal');\" 2>/dev/null",
            expect="3",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# OsmAnd verify — 3 cases
# ═══════════════════════════════════════════════════════════

def osmand_favorite_verify() -> list[dict]:
    """验证 favorites.gpx 的 waypoint name 含目标位置（对齐 AW location in
    name.text——OsmAnd 写入 <name>Ruggell, Liechtenstein</name>）。"""
    fp = "/storage/emulated/0/Android/data/net.osmand/files/favorites/favorites.gpx"
    name = data.OSMAND_FAVORITE["name"]
    return [
        _verify_spec(
            f"cat {fp} 2>/dev/null | grep -ci '<name>{name}' || echo '0'",
            expect_re=r"[1-9]",
        ),
    ]


def osmand_marker_verify() -> list[dict]:
    """验证 map_markers 中存在与目标坐标差 <0.001° 的标记（对齐 AW delta_deg=0.001
    Chebyshev 距离）。"""
    db = data.DB_PATHS["osmand_markers"]
    m = data.OSMAND_MARKER
    return [
        _verify_spec(
            f"sqlite3 {db} \"SELECT COUNT(*) FROM map_markers WHERE "
            f"ABS(marker_lat-{m['lat']})<0.001 AND ABS(marker_lon-{m['lon']})<0.001;\" "
            f"2>/dev/null",
            expect_re=r"[1-9]",
        ),
    ]


def osmand_track_verify() -> list[dict]:
    """对齐 AW _track_matches：按 trkpt 顺序，先出现 Ruggell 坐标再出现 Bendern
    坐标（各与目标坐标 Chebyshev 差 <0.001°；用平方形式避免 awk abs 依赖）。
    只按名称 grep 会放过"乱序"或"错位"的 track，必须校验坐标序列。"""
    fp = "/storage/emulated/0/Android/data/net.osmand/files/tracks"
    w0, w1 = data.OSMAND_WAYPOINTS[0], data.OSMAND_WAYPOINTS[1]
    # awk: 每个 <trkpt lat=".." lon=".."> 解析坐标；Ruggell 先命中后，后续
    # trkpt 命中 Bendern → 输出 TRACK_MATCH（顺序敏感，与 AW 一致）
    awk_script = (
        "/<trkpt/ {\n"
        '  line = $0\n'
        '  sub(/^.*lat="/, "", line); sub(/".*$/, "", line); lat = line + 0\n'
        '  line = $0\n'
        '  sub(/^.*lon="/, "", line); sub(/".*$/, "", line); lon = line + 0\n'
        f"  if ((lat-{w0['lat']})*(lat-{w0['lat']}) + (lon-{w0['lon']})*(lon-{w0['lon']}) < 0.000002) f = 1\n"
        f"  if (f && (lat-{w1['lat']})*(lat-{w1['lat']}) + (lon-{w1['lon']})*(lon-{w1['lon']}) < 0.000002) {{ print \"TRACK_MATCH\"; exit }}\n"
        "}\n"
    )
    return [
        _verify_spec(
            f"cat {fp}/*.gpx 2>/dev/null | awk '{awk_script}' || echo '0'",
            expect_re=r"TRACK_MATCH",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# Markor verify — complete all remaining 12 cases
# ═══════════════════════════════════════════════════════════

def markor_add_note_header_verify() -> list[dict]:
    """新文件名存在且内容 = header + 空行 + 原文（对齐 AW exact_match
    header+'\\n\\n'+original），原文件必须已删除（expect=''）。"""
    h = data.MARKOR_NOTE_HEADER
    return [
        _verify_spec(
            f"ls /sdcard/Documents/Markor/{h['file_name']} 2>/dev/null",
            expect="",
        ),
        _verify_spec(
            f"cat /sdcard/Documents/Markor/{h['new_name']} 2>/dev/null",
            expect_re=re.escape(h["header"]) + r"\s*\n\s*\n" + re.escape(h["text"]),
            min_lines=3,  # header + 空行 + 原文
        ),
    ]


def markor_change_note_content_verify() -> list[dict]:
    """新文件名存在且内容含 updated_content，原文件必须已删除（expect=''）。"""
    c = data.MARKOR_NOTE_CHANGE
    return [
        _verify_spec(
            f"cat /sdcard/Documents/Markor/{c['new_name']} 2>/dev/null",
            expect_re=re.escape(c["updated_content"]),
        ),
        _verify_spec(
            f"ls /sdcard/Documents/Markor/{c['file_name']} 2>/dev/null",
            expect="",
        ),
    ]


def markor_create_folder_verify() -> list[dict]:
    return [
        _verify_spec(
            "ls /sdcard/Documents/Markor/ 2>/dev/null",
            expect_re=r"folder_dip",
        ),
    ]


def markor_create_note_and_sms_verify() -> list[dict]:
    """笔记文件存在且含目标文本 + sent SMS 收件人 555-0100 且正文匹配笔记文本。
    （对齐 AW SimpleSMSSendSms：address 与 body 分别校验）"""
    n = data.MARKOR_NOTE_AND_SMS
    return [
        _verify_spec(
            f"cat /sdcard/Documents/Markor/{n['file_name']} 2>/dev/null",
            expect_re=re.escape(n["text"]),
        ),
        _verify_spec(
            "content query --uri content://sms/sent --projection address:body 2>/dev/null",
            expect_re=n["number"].replace("-", r"-?"),  # 555-0100 或 5550100
        ),
        _verify_spec(
            "content query --uri content://sms/sent --projection address:body 2>/dev/null",
            expect_re=re.escape(n["text"]),
        ),
    ]


def markor_create_note_from_clipboard_verify() -> list[dict]:
    """笔记文件存在且内容 = init 预置的剪贴板文本。"""
    c = data.MARKOR_CLIPBOARD
    return [
        _verify_spec(
            f"cat /sdcard/Documents/Markor/{c['file_name']} 2>/dev/null",
            expect_re=re.escape(c["text"]),
        ),
    ]


def markor_delete_all_notes_verify() -> list[dict]:
    return [
        _verify_spec(
            "ls /sdcard/Documents/Markor/*.md 2>/dev/null | wc -l",
            expect="0",
        ),
    ]


def markor_delete_newest_note_verify() -> list[dict]:
    """init 创建 old_note_0..3（3 为最新），删除最新后剩 3 个 md 且 old_note_3.md 消失。"""
    return [
        _verify_spec(
            "ls /sdcard/Documents/Markor/*.md 2>/dev/null | wc -l",
            expect="3",  # 4 个种子 - 1
        ),
        _verify_spec(
            "ls /sdcard/Documents/Markor/old_note_3.md 2>/dev/null",
            expect="",
        ),
    ]


def markor_delete_note_verify() -> list[dict]:
    return [
        _verify_spec(
            f"ls /sdcard/Documents/Markor/{data.MARKOR_NOTE_DELETE['file_name']} 2>/dev/null || echo NOT_FOUND",
            not_contain=data.MARKOR_NOTE_DELETE["file_name"],
        ),
    ]


def markor_edit_note_verify() -> list[dict]:
    """header 加在文件顶部（^ 锚定）+ 原文紧随其后（对齐 AW
    expected=header+'\\n'+content，fuzzy_match）。只写 '# Test Header' 覆盖全文
    的 agent 会失败——原文必须仍在。"""
    e = data.MARKOR_NOTE_EDIT
    return [
        _verify_spec(
            f"cat /sdcard/Documents/Markor/{e['file_name']} 2>/dev/null",
            expect_re="^" + re.escape(e["header"]) + r"\s*\n\s*" + re.escape(e["text"]),
        ),
    ]


def markor_merge_notes_verify() -> list[dict]:
    """合并文件结构 = f1 + 空行 + f2 + 空行 + f3，顺序固定（对齐 AW
    is_successful 的 split 检查：5 段且第 2/4 段为空）。"""
    texts = [data.MARKOR_NOTE_MERGE_1["text"],
             data.MARKOR_NOTE_MERGE_2["text"],
             data.MARKOR_NOTE_MERGE_3["text"]]
    merged = (re.escape(texts[0]) + r"\s*\n\s*\n"
              + re.escape(texts[1]) + r"\s*\n\s*\n"
              + re.escape(texts[2]))
    return [
        _verify_spec(
            f"cat /sdcard/Documents/Markor/{data.MARKOR_NOTE_MERGE_NEW['file_name']} 2>/dev/null",
            expect_re=merged,
            min_lines=5,  # 3 段内容 + 2 个空行
        ),
    ]


def markor_move_note_verify() -> list[dict]:
    """目标文件在 Markor 数据目录（/sdcard/Documents/Markor）存在 +
    源位置（/sdcard/Documents）已消失（对齐 file_move_verify 的源缺失检查）。"""
    m = data.MARKOR_NOTE_MOVE
    return [
        _verify_spec(
            f"ls /sdcard/Documents/Markor/{m['file_name']} 2>/dev/null",
            expect_re=m["file_name"],
        ),
        _verify_spec(
            f"ls /sdcard/Documents/{m['file_name']} 2>/dev/null || echo NOT_FOUND",
            not_contain=m["file_name"],
        ),
    ]


def markor_transcribe_receipt_verify() -> list[dict]:
    """receipt.md 含表头 'Date, Item, Amount'（至少 2 行 = 表头 + >=1 交易）
    + 全部固定交易行。"""
    specs = [
        _verify_spec(
            f"cat /sdcard/Documents/Markor/{data.RECEIPT['md_file']} 2>/dev/null",
            expect_re=re.escape(data.RECEIPT["header"]),
            min_lines=2,
        ),
    ]
    for d, item, amt in data.RECEIPT["transactions"]:
        specs.append(_verify_spec(
            f"cat /sdcard/Documents/Markor/{data.RECEIPT['md_file']} 2>/dev/null",
            expect_re=re.escape(f"{d}, {item}, {amt}"),
        ))
    return specs


def markor_transcribe_video_verify() -> list[dict]:
    """test_note_ozfg.md 含 init 视频中字符串按逗号连接的序列（逗号后空格可选，
    对齐 AW text=','.join(messages) 与 fuzzy_match）。"""
    v = data.MARKOR_VIDEO
    pattern = ", ?".join(re.escape(m) for m in v["messages"])
    return [
        _verify_spec(
            f"cat /sdcard/Documents/Markor/{v['file_name']} 2>/dev/null",
            expect_re=pattern,
        ),
    ]


# ═══════════════════════════════════════════════════════════
# Browser verify — 3 cases
# ═══════════════════════════════════════════════════════════

def browser_activity_verify() -> list[dict]:
    """对齐 AW BrowserTask.is_successful：chrome 前台 + 页面出现 'Success!'。"""
    return [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r"chrome|browser",
        ),
        # AW 的裁决点：element.text == 'Success!'。走 UI 路径（pf.observe，
        # 与 AW env.get_state().ui_elements 同源）——系统 uiautomator dump
        # 会被 daemon 的 a11y 服务抢占 kill。
        _verify_spec("", ui_contains="Success!"),
    ]


# ═══════════════════════════════════════════════════════════
# Audio Recorder verify — 2 cases
# ═══════════════════════════════════════════════════════════

def audio_recorder_verify() -> list[dict]:
    """对齐 AW AudioRecorderRecordAudio：目录中恰有 1 个非空新文件（init 已清空目录）。"""
    return [
        _verify_spec(
            f"find {data.AUDIO_RECORDING['dir']} -type f -size +0c 2>/dev/null | wc -l",
            expect="1",
        ),
    ]


def audio_recorder_with_name_verify() -> list[dict]:
    """对齐 AW AudioRecorderRecordAudioWithFileName：固定文件名恰存在 1 个。"""
    return [
        _verify_spec(
            f"find {data.AUDIO_RECORDING['dir']} -name '{data.AUDIO_RECORDING['name']}*' 2>/dev/null | wc -l",
            expect="1",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# Simple Draw / Simple Gallery verify
# ═══════════════════════════════════════════════════════════

def simple_draw_create_drawing_verify() -> list[dict]:
    return [
        _verify_spec(
            "ls /sdcard/Pictures/*.png 2>/dev/null | head -3 || echo NOT_FOUND",
            expect_re=r"test_note_ufvu",
        ),
    ]


def save_copy_of_receipt_verify() -> list[dict]:
    """对齐 AW SaveCopyOfReceiptTaskEval.is_successful：
    check_file_or_folder_exists(DOWNLOAD_DATA, file_name)——Download 下存在
    同名副本 receipt_ewvv.jpg。"""
    fname = data.SIMPLE_GALLERY_COPY["file_name"]
    return [
        _verify_spec(
            f"ls /sdcard/Download/{fname} 2>/dev/null || echo NOT_FOUND",
            expect_re=re.escape(fname),
        ),
    ]


# ═══════════════════════════════════════════════════════════
# SMS verify — remaining cases
# ═══════════════════════════════════════════════════════════

def sms_reply_verify() -> list[dict]:
    """对齐 AW SimpleSmsReply.is_successful（was_sent on content://sms/sent +
    in_correct_app）：SENT 中必须有发往 555-0100 且正文为 goal message 的回复，
    且当前前台 app 是 Simple SMS Messenger（com.simplemobiletools.smsmessenger，
    镜像 AW sms_validators.py is_successful 的 in_correct_app 条件）。"""
    return [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r"smsmessenger",
        ),
        _sms_sent_to_5550100_spec(),
        _verify_spec(
            "content query --uri content://sms/sent 2>/dev/null | grep body",
            expect_re=data.SMS_HELLO["message"],
        ),
    ]


def sms_reply_most_recent_verify() -> list[dict]:
    """对齐 AW SimpleSmsReplyMostRecent（继承 SimpleSMSSendSms.is_successful 的
    was_sent + in_correct_app）：SENT 中必须有发往 555-0100、正文
    'Hello from automated test' 的回复（query content://sms/sent，不再是 bare
    min_lines——inbox 里预置的消息本身不通过 SENT 检查），且当前前台是
    Simple SMS Messenger。"""
    return [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r"smsmessenger",
        ),
        _sms_sent_to_5550100_spec(),
        _verify_spec(
            "content query --uri content://sms/sent 2>/dev/null | grep body",
            expect_re=data.SMS_HELLO["message"],
        ),
    ]


def sms_send_clipboard_content_verify() -> list[dict]:
    """对齐 AW SimpleSmsSendClipboardContent（is_successful 的 was_sent +
    in_correct_app）：SENT 中消息 body == 剪贴板文本、收件人 555-0100，且
    当前前台是 Simple SMS Messenger（与 sms_send_verify 同形，而非 bare
    min_lines=1）。"""
    return [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r"smsmessenger",
        ),
        _sms_sent_to_5550100_spec(),
        _verify_spec(
            "content query --uri content://sms/sent 2>/dev/null | grep body",
            expect_re=data.SMS_HELLO["message"],
        ),
    ]


def sms_send_received_address_verify() -> list[dict]:
    """对齐 AW SimpleSmsSendReceivedAddress（is_successful 的 was_sent +
    in_correct_app）：SENT 中发往 555-0100（Alice Smith）的消息包含 Bob Jones
    发来的地址文本，且当前前台是 Simple SMS Messenger。"""
    return [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r"smsmessenger",
        ),
        _sms_sent_to_5550100_spec(),
        _verify_spec(
            "content query --uri content://sms/sent 2>/dev/null | grep body",
            expect_re=re.escape(data.SMS_RECEIVED_ADDRESS),
        ),
    ]


def sms_resend_verify() -> list[dict]:
    """对齐 AW SimpleSmsResend.is_successful（重发消息与 seed 完全相等）：
    sent 表中 address=555-0100/5550100 且 body='init test message' 的消息必须 >= 2 条
    （init 预置 1 条 + agent 至少重发 1 条同正文同号码）。inbox 预置消息不进入
    sent 表；只重发任意其他正文/号码的消息也无法满足该组合计数。"""
    return [
        _verify_spec(
            "content query --uri content://sms/sent --projection address:body 2>/dev/null "
            f"| grep -cE 'address=555-?0100.*body={re.escape(data.SMS_RESEND_MESSAGE)}'",
            expect_re=r"^[2-9]$|^[1-9][0-9]+$",  # >= 2（original + resent）
        ),
    ]


# ═══════════════════════════════════════════════════════════
# Clock verify — 2 remaining
# ═══════════════════════════════════════════════════════════

def clock_stopwatch_running_verify() -> list[dict]:
    """对齐 AW _is_stopwatch_running：Pause + Lap 按钮同时存在。"""
    return [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r"[Dd]esk[Cc]lock",
        ),
        _verify_spec("", ui_contains='desc="Pause"'),
        _verify_spec("", ui_contains='desc="Lap"'),
    ]


def clock_stopwatch_paused_verify() -> list[dict]:
    """对齐 AW _is_stopwatch_paused：Start 按钮 + 当前在 Stopwatch 页。

    AW 的 n_stopwatch>=2 在 flatref 树里对应 Stopwatch 页的
    action_bar_title（标题 + 底部 tab 两个元素）；Start desc 在 Timer 页
    fab 上也存在，必须用标题锚点限定在 Stopwatch 页。
    """
    return [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r"[Dd]esk[Cc]lock",
        ),
        _verify_spec("", ui_contains='desc="Start"'),
        _verify_spec("", ui_contains='text="Stopwatch" id="action_bar_title"'),
    ]


def clock_timer_entry_verify() -> list[dict]:
    """对齐 AW _is_timer_set：timer 显示 0 hours, 5 minutes, 0 seconds（未启动）。"""
    return [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r"[Dd]esk[Cc]lock",
        ),
        _verify_spec("", ui_contains="0 hours, 5 minutes, 0 seconds"),
    ]


# ═══════════════════════════════════════════════════════════
# Composite verify
# ═══════════════════════════════════════════════════════════

def turn_off_wifi_turn_on_bluetooth_verify() -> list[dict]:
    return [
        _verify_spec("settings get global wifi_on", expect="0"),
        _verify_spec("settings get global bluetooth_on", expect="1"),
    ]


def turn_on_wifi_and_open_app_verify() -> list[dict]:
    return [
        _verify_spec("settings get global wifi_on", expect_re=r"[12]"),
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r"settings",
        ),
    ]


# ═══════════════════════════════════════════════════════════
# OpenApp
# ═══════════════════════════════════════════════════════════

def open_app_verify() -> list[dict]:
    return [
        _verify_spec(
            "dumpsys activity activities | grep topResumedActivity",
            expect_re=r"settings",
        ),
    ]
