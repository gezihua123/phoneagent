"""initialize 命令生成器——每个 task 生成 shell 命令预置数据。

SQLite 格式: sqlite3 {db} "INSERT INTO tbl(col1,col2) VALUES('v1','v2');"
  - 双引号包裹完整 SQL，单引号包裹值——保证值中的空格安全
"""
from __future__ import annotations

from scripts.aw import data


# ═══════════════════════════════════════════════════════════
# Recipe
# ═══════════════════════════════════════════════════════════

  # (original — replaced by recipe section versions)
def recipe_delete_single_init() -> list[str]:
    db = data.DB_PATHS["broccoli"]
    r = data.RECIPE_SPICY_TUNA
    return [
        f"sqlite3 {db} \"DELETE FROM recipes;\"",
        f"sqlite3 {db} \"INSERT INTO recipes(title,description,servings,"
        f"preparationTime,source,ingredients,directions,favorite) "
        f"VALUES('{r['title']}','{r['description']}','{r['servings']}',"
        f"'{r['preparationTime']}','{r['source']}','{r['ingredients']}',"
        f"'{r['directions']}',{r['favorite']});\"",
    ]


  # (original — replaced by recipe section versions)
def recipe_add_single_init() -> list[str]:
    db = data.DB_PATHS["broccoli"]
    r = data.RECIPE_GREEK_SALAD
    return [
        f"sqlite3 {db} \"DELETE FROM recipes;\"",
        f"sqlite3 {db} \"INSERT INTO recipes(title,description,servings,"
        f"preparationTime,source,ingredients,directions,favorite) "
        f"VALUES('{r['title']}','{r['description']}','{r['servings']}',"
        f"'{r['preparationTime']}','{r['source']}','{r['ingredients']}',"
        f"'{r['directions']}',{r['favorite']});\"",
    ]


# ═══════════════════════════════════════════════════════════
# Expense
# ═══════════════════════════════════════════════════════════

def expense_delete_single_init() -> list[str]:
    db = data.DB_PATHS["expense"]
    e = data.EXPENSE_LUNCH
    created = 1697385600000
    return [
        f"sqlite3 {db} \"DELETE FROM expense;\"",
        f"sqlite3 {db} \"INSERT INTO expense(name,amount,category,note,"
        f"created_date,modified_date) "
        f"VALUES('{e['name']}',{e['amount']},{e['category']},"
        f"'{e['note']}',{created},{created});\"",
    ]


# ═══════════════════════════════════════════════════════════
# Contact / SMS / File / System / Camera / Markor
# ═══════════════════════════════════════════════════════════

def contacts_add_init() -> list[str]:
    return ["pm clear com.android.providers.contacts 2>/dev/null || true"]


def contacts_draft_init() -> list[str]:
    return ["pm clear com.android.providers.contacts 2>/dev/null || true"]


def _contact_inserts(contacts: list[dict]) -> list[str]:
    """按固定 _id 插入联系人（对齐 AW contacts_utils.add_contact 的效果）：
    pm clear 后 raw_contacts._id 从 1 递增，每个联系人插 name + phone 两行 data。
    实测 authority 必须为 com.android.contacts、mimetype 键必须小写。"""
    cmds = ["pm clear com.android.providers.contacts 2>/dev/null || true"]
    for i, c in enumerate(contacts, start=1):
        first, last = (c["name"].rsplit(" ", 1) if " " in c["name"]
                       else (c["name"], ""))
        cmds.append(
            "content insert --uri content://com.android.contacts/raw_contacts "
            "--bind account_name:s:test --bind account_type:s:com.android.contacts.test "
            "2>/dev/null || true"
        )
        cmds.append(
            f"content insert --uri content://com.android.contacts/data "
            f"--bind raw_contact_id:i:{i} --bind mimetype:s:vnd.android.cursor.item/name "
            f"--bind data1:s:'{c['name']}' --bind data2:s:{first} --bind data3:s:{last} "
            f"2>/dev/null || true"
        )
        cmds.append(
            f"content insert --uri content://com.android.contacts/data "
            f"--bind raw_contact_id:i:{i} --bind mimetype:s:vnd.android.cursor.item/phone_v2 "
            f"--bind data1:s:{c['number']} --bind data2:s:2 2>/dev/null || true"
        )
    return cmds


def sms_send_init() -> list[str]:
    """对齐 AW SimpleSMSSendSms.initialize_task（toggle_airplane_mode off +
    clear_sms_and_threads）：关飞行模式（否则 agent 发不出短信）+ 清空
    sms 与 threads 两表（实测 content delete 在本 ROM 上不删行，必须 sqlite
    直删——_sms_clear 在下方定义，运行时解析）。"""
    return [
        "cmd connectivity airplane-mode disable 2>/dev/null || true",
        _sms_clear(),
    ]


def sms_reply_init() -> list[str]:
    """对齐 AW SimpleSmsReply.initialize_task：inbox 预置 5550100 发来的
    非目标正文消息——'Hello from automated test' 只应作为 agent 的回复正文
    出现在 SENT 表（sent 表检查是唯一通过路径）。"""
    return [
        "cmd connectivity airplane-mode disable 2>/dev/null || true",
        _sms_clear(),
        "adb emu sms send 5550100 'Can you confirm the meeting time?' 2>/dev/null || true",
    ]


def file_delete_init() -> list[str]:
    return [
        "mkdir -p /sdcard/Download",
        f"echo test > /sdcard/Download/{data.FILE_DELETE['file_name']}",
    ]


def file_move_init() -> list[str]:
    return [
        "mkdir -p /sdcard/Documents /sdcard/Markor",
        f"echo test > /sdcard/Documents/{data.FILE_MOVE['file_name']}",
    ]


def sys_bluetooth_off_init() -> list[str]:
    return ["svc bluetooth enable"]


def sys_bluetooth_on_init() -> list[str]:
    return ["svc bluetooth disable"]


def sys_wifi_off_init() -> list[str]:
    return ["svc wifi enable"]


def sys_wifi_on_init() -> list[str]:
    return ["svc wifi disable"]


def sys_brightness_max_init() -> list[str]:
    return ["settings put system screen_brightness 1"]


def sys_brightness_min_init() -> list[str]:
    return ["settings put system screen_brightness 255"]


# ── System Verify 变体（AW 的 ...Verify 任务：init 即预达成 goal 状态）──

def sys_bluetooth_off_verify_init() -> list[str]:
    """对齐 AW SystemBluetoothTurnOffVerify.initialize_task（toggle_bluetooth('off')）：
    预置蓝牙关闭——Verify 变体允许 init 预达成 goal（AW 同样如此）。"""
    return ["svc bluetooth disable"]


def sys_bluetooth_on_verify_init() -> list[str]:
    """对齐 AW SystemBluetoothTurnOnVerify.initialize_task（toggle_bluetooth('on')）。"""
    return ["svc bluetooth enable"]


def sys_brightness_max_verify_init() -> list[str]:
    """对齐 AW SystemBrightnessMaxVerify.initialize_task（set_brightness('max')）。"""
    return ["settings put system screen_brightness 255"]


def sys_brightness_min_verify_init() -> list[str]:
    """对齐 AW SystemBrightnessMinVerify.initialize_task（set_brightness('min')）。
    注意：勿复用 sys_brightness_min_init（那是非 Verify 变体的反向前置条件）。"""
    return ["settings put system screen_brightness 1"]


def sys_clipboard_init() -> list[str]:
    """对齐 AW SystemCopyToClipboard.initialize_task（set_clipboard_contents
    '~~~RESET~~~'）：重置剪贴板为哨兵值——agent 必须把目标文本复制进剪贴板
    （clipper.set 广播，与 markor_create_note_from_clipboard_init 同机制）。"""
    return [
        "pm grant ca.zgrs.clipper android.permission.READ_EXTERNAL_STORAGE 2>/dev/null || true",
        "am broadcast -a clipper.set -e text '~~~RESET~~~' 2>/dev/null || true",
    ]


def camera_photo_init() -> list[str]:
    # 清掉可见照片 + .thumbnails 缓存（否则复用设备上 verify 计数被缩略图污染）
    return [
        "rm -rf /sdcard/Pictures/*.jpg /sdcard/DCIM/Camera/*.jpg 2>/dev/null || true",
        "rm -rf /sdcard/Pictures/.thumbnails 2>/dev/null || true",
    ]


def camera_video_init() -> list[str]:
    # 整目录清空重建——隐藏文件（.pending-*.mp4/.thumbnails/.nomedia）一并清掉，
    # 保证 verify 的"顶层恰有 1 个非隐藏文件"成立（对齐 AW _clear_app_data）
    return [
        "rm -rf /sdcard/Movies 2>/dev/null || true",
        "mkdir -p /sdcard/Movies",
    ]


def markor_create_note_init() -> list[str]:
    return [
        "pm grant net.gsantner.markor android.permission.WRITE_EXTERNAL_STORAGE 2>/dev/null || true",
        "mkdir -p /sdcard/Documents/Markor",
        # 防止上一次运行残留同名文件干扰验证（对齐 AW clear_directory）
        f"rm -f /sdcard/Documents/Markor/{data.MARKOR_NOTE_CREATE['file_name']} 2>/dev/null || true",
    ]


# ═══════════════════════════════════════════════════════════
# Recipe — complete all 13 cases
# ═══════════════════════════════════════════════════════════
# 关键：Broccoli 用 Room ORM，sqlite3 直写后必须 force-stop 才能让 app 看到数据

def _recipe_reload() -> str:
    return "am force-stop com.flauschcode.broccoli 2>/dev/null || true"


def _ensure_db_launched(pkg: str, db_path: str, activity: str = "") -> str:
    """如果 DB 不存在，启动 app 来创建（然后关掉）。优先用 activity，fallback 用 launcher。"""
    if activity:
        launch = f"am start -n {activity} 2>/dev/null"
    else:
        launch = f"am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER {pkg} 2>/dev/null"
    return (
        f"if [ ! -f {db_path} ]; then "
        f"{launch}; "
        f"sleep 3; "
        f"am force-stop {pkg} 2>/dev/null; "
        f"fi"
    )


def _retro_restart() -> str:
    return "am force-stop code.name.monkey.retromusic 2>/dev/null || true"


def _vlc_restart() -> str:
    return "am force-stop org.videolan.vlc 2>/dev/null || true"


def _recipe_sqlite_insert(r: dict) -> str:
    db = data.DB_PATHS["broccoli"]
    return (
        f"sqlite3 {db} \"INSERT INTO recipes(title,description,servings,"
        f"preparationTime,source,ingredients,directions,favorite) "
        f"VALUES('{r['title']}','{r['description']}','{r['servings']}',"
        f"'{r['preparationTime']}','{r['source']}','{r['ingredients']}',"
        f"'{r['directions']}',{r['favorite']});\""
    )

def _recipe_clear_db() -> str:
    return f"sqlite3 {data.DB_PATHS['broccoli']} \"DELETE FROM recipes;\""


# ═══════════════════════════════════════════════════════════
# Recipe 文本表示与确定性变体（对齐 AW get_text_representation_of_rows）
# ═══════════════════════════════════════════════════════════

# AW _get_rows_as_text 的 fields（与 _RecipeAddMultipleRecipes 完全一致）
_RECIPE_TEXT_FIELDS = ["title", "description", "servings", "preparationTime",
                       "ingredients", "directions"]

_DESC_POOL = [
    "A quick and easy meal, perfect for busy weekdays.",
    "A delicious and healthy choice for any time of the day.",
    "An ideal recipe for experimenting with different flavors and ingredients.",
]
_SERVINGS_POOL = ["1 serving", "2 servings", "3-4 servings", "6 servings", "8 servings"]
_PREP_POOL = ["10 mins", "20 mins", "30 mins", "45 mins", "1 hrs", "2 hrs", "3 hrs", "4 hrs"]
_INGREDIENTS_POOL = ["see directions", "as per recipe", "varies", "to preference",
                     "quantities to taste", "as needed", "optional ingredients", "n/a"]
_DIRECTIONS_SUFFIX = [
    "Try adding a pinch of your favorite spices for extra flavor.",
    "Feel free to substitute with ingredients you have on hand.",
    "Garnish with fresh herbs for a more vibrant taste.",
]


def _recipe_csv(rows: list[dict]) -> str:
    """AW get_text_representation_of_rows csv 格式（header 同 AW 的 fields 顺序）。"""
    lines = ["|".join(_RECIPE_TEXT_FIELDS)]
    for r in rows:
        lines.append("|".join(str(r[f]) for f in _RECIPE_TEXT_FIELDS))
    return "\n".join(lines)


def _recipe_text_block(rows: list[dict], wrap_width: int | None = None) -> str:
    """AW text_block 格式：'Recipe: <title>' + ' <field>: <value>' 行。"""
    import textwrap
    blocks = []
    for r in rows:
        block = f"Recipe: {r['title']}\n"
        for f in _RECIPE_TEXT_FIELDS:
            if f == "title":
                continue
            value = r[f]
            if wrap_width is not None:
                value = "\n".join(textwrap.wrap(value, wrap_width))
            block += f" {f}: {value}\n"
        blocks.append(block)
    return "\n".join(blocks)


def _recipe_variant(base: dict, i: int, same_description: bool = False) -> dict:
    """base 的确定性变体：同 title，其余字段按索引 i 扰动——
    (a) 与 base 及同 title 的其他变体互不相同（删除类任务的精确行身份验证需要）；
    (b) 变体与目标行字段不同，不算 exact duplicate（对齐 AW get_random_items
    replacement=False + dataclasses.replace 扰动）。"""
    d = dict(base)
    d["description"] = base["description"] if same_description else _DESC_POOL[i % 3]
    d["servings"] = _SERVINGS_POOL[(i + 1) % 5]
    d["preparationTime"] = _PREP_POOL[(i + 1) % 8]
    d["ingredients"] = _INGREDIENTS_POOL[(i + 1) % 8]
    directions = base["directions"].rstrip()
    for s in _DIRECTIONS_SUFFIX:
        directions = directions.replace(" " + s, "").replace(s, "")
    d["directions"] = f"{directions} {_DIRECTIONS_SUFFIX[i % 3]}"
    return d


# 添加类任务（AddMultiple/AddSingle/FromMarkor/FromImage）的 DB 噪声池——
# 与各 case 的目标标题不重叠（对齐 AW filter_fn: r.title != target.title）
_RECIPE_ADD_NOISE_POOL = [
    data.RECIPE_SPICY_TUNA, data.RECIPE_AVOCADO_TOAST,
    data.RECIPE_GREEK_SALAD, data.RECIPE_BANANA_BREAD,
]


def _recipe_noise_rows(excluded_titles: set[str], count: int = 10) -> list[dict]:
    """确定性噪声行：从噪声池循环取 count 行，标题与 excluded_titles 不重叠。"""
    pool = [r for r in _RECIPE_ADD_NOISE_POOL if r["title"] not in excluded_titles]
    return [pool[i % len(pool)] for i in range(count)]


def _recipe_noise_variants(bases: list[dict], count: int) -> list[dict]:
    """确定性变体噪声行：对 bases 循环生成 _recipe_variant 变体（同 title、
    其余字段互异）。i < 120 时两两不同（desc 周期 3 × 字段周期 40），
    且字段文本均无单引号，可安全 INSERT。"""
    return [_recipe_variant(bases[i % len(bases)], i) for i in range(count)]


  # (original — replaced by recipe section versions)
def recipe_delete_single_init() -> list[str]:
    db = data.DB_PATHS["broccoli"]
    r = data.RECIPE_SPICY_TUNA
    return [
        f"sqlite3 {db} \"DELETE FROM recipes;\"",
        f"sqlite3 {db} \"INSERT INTO recipes(title,description,servings,"
        f"preparationTime,source,ingredients,directions,favorite) "
        f"VALUES('{r['title']}','{r['description']}','{r['servings']}',"
        f"'{r['preparationTime']}','{r['source']}','{r['ingredients']}',"
        f"'{r['directions']}',{r['favorite']});\"",
    ]


def recipe_delete_single_with_noise_init() -> list[str]:
    """单目标删除 + 5 噪声行。"""
    cmds = [_recipe_clear_db()]
    # 噪声
    for r in [data.RECIPE_AVOCADO_TOAST, data.RECIPE_GREEK_SALAD,
              data.RECIPE_CHOCOLATE_CAKE, data.RECIPE_CHICKEN_SOUP,
              data.RECIPE_PASTA_PRIMAVERA]:
        cmds.append(_recipe_sqlite_insert(r))
    # 目标
    cmds.append(_recipe_sqlite_insert(data.RECIPE_SPICY_TUNA))
    cmds.append(_recipe_reload())
    return cmds


def recipe_delete_multiple_init() -> list[str]:
    """删除多个 — 3 目标（对齐 AW n_rows=3）。"""
    cmds = [_recipe_clear_db()]
    cmds.append(_recipe_sqlite_insert(data.RECIPE_SPICY_TUNA))
    cmds.append(_recipe_sqlite_insert(data.RECIPE_AVOCADO_TOAST))
    cmds.append(_recipe_sqlite_insert(data.RECIPE_GREEK_SALAD))
    cmds.append(_recipe_reload())
    return cmds


def recipe_delete_multiple_with_noise_init() -> list[str]:
    """对齐 AW RecipeDeleteMultipleRecipesWithNoise（n_rows=3 / n_rows_noise=29）：
    3 个目标（goal 点名的标题）+ 29 个确定性噪声变体行（标题 ≠ 目标标题）。"""
    cmds = [_recipe_clear_db()]
    noise_bases = [data.RECIPE_CHOCOLATE_CAKE, data.RECIPE_CHICKEN_SOUP,
                   data.RECIPE_PASTA_PRIMAVERA, data.RECIPE_BANANA_BREAD,
                   data.RECIPE_QUINOA_BOWL, data.RECIPE_TERIYAKI_SALMON,
                   data.RECIPE_TOMATO_BASIL_BRUSCHETTA]
    for r in _recipe_noise_variants(noise_bases, 29):
        cmds.append(_recipe_sqlite_insert(r))
    for r in [data.RECIPE_SPICY_TUNA, data.RECIPE_AVOCADO_TOAST,
              data.RECIPE_GREEK_SALAD]:
        cmds.append(_recipe_sqlite_insert(r))
    cmds.append(_recipe_reload())
    return cmds


def recipe_delete_with_constraint_init() -> list[str]:
    """多食谱含盐——对齐 AW RecipeDeleteMultipleRecipesWithConstraint：
    3 个目标（directions 含 'salt'）+ 6 个盐-free 噪声（>=5；AW filter_fn:
    ingredient not in directions.lower()）。

    已逐常量核对 directions：
     含 'salt'（目标）: RECIPE_CHICKEN_SOUP "Add salt to taste"、
       RECIPE_AVOCADO_TOAST "salt, pepper, and chili flakes"、
       RECIPE_TOMATO_BASIL_BRUSCHETTA "salt, and pepper"
     不含 'salt'（噪声）: RECIPE_GREEK_SALAD / CHOCOLATE_CAKE / PASTA_PRIMAVERA
       / BANANA_BREAD / QUINOA_BOWL / TERIYAKI_SALMON
    """
    cmds = [_recipe_clear_db()]
    # 噪声 (不含 salt)
    for r in [data.RECIPE_GREEK_SALAD, data.RECIPE_CHOCOLATE_CAKE,
              data.RECIPE_PASTA_PRIMAVERA, data.RECIPE_BANANA_BREAD,
              data.RECIPE_QUINOA_BOWL, data.RECIPE_TERIYAKI_SALMON]:
        cmds.append(_recipe_sqlite_insert(r))
    # 目标 (directions 含 salt——3 个，对齐 AW n_rows=3)
    cmds.append(_recipe_sqlite_insert(data.RECIPE_CHICKEN_SOUP))  # "Add salt to taste"
    cmds.append(_recipe_sqlite_insert(data.RECIPE_AVOCADO_TOAST))  # "salt, pepper, and chili flakes"
    cmds.append(_recipe_sqlite_insert(data.RECIPE_TOMATO_BASIL_BRUSCHETTA))  # "salt, and pepper"
    cmds.append(_recipe_reload())
    return cmds


def recipe_delete_duplicates_init() -> list[str]:
    """重复食谱删除 v1 — 1 个重复目标 + 5 噪声。"""
    cmds = [_recipe_clear_db()]
    for r in [data.RECIPE_AVOCADO_TOAST, data.RECIPE_GREEK_SALAD,
              data.RECIPE_CHOCOLATE_CAKE, data.RECIPE_CHICKEN_SOUP,
              data.RECIPE_PASTA_PRIMAVERA]:
        cmds.append(_recipe_sqlite_insert(r))
    # 插入两次——创建重复
    cmds.append(_recipe_sqlite_insert(data.RECIPE_SPICY_TUNA))
    cmds.append(_recipe_sqlite_insert(data.RECIPE_SPICY_TUNA))
    cmds.append(_recipe_reload())
    return cmds


def recipe_delete_duplicates2_init() -> list[str]:
    """重复食谱删除 v2 — 对齐 AW RecipeDeleteDuplicateRecipes2：
    6 个唯一噪声 + 4 个同 title 变体 + 2 个完全相同的目标 = 12 行。
    （同 title 变体字段不同，不算 exact duplicate——精确行身份验证需要）"""
    cmds = [_recipe_clear_db()]
    # 6 个唯一噪声（title 各异，≠ 'Spicy Tuna Wraps'）
    for r in [data.RECIPE_AVOCADO_TOAST, data.RECIPE_GREEK_SALAD,
              data.RECIPE_CHOCOLATE_CAKE, data.RECIPE_CHICKEN_SOUP,
              data.RECIPE_PASTA_PRIMAVERA, data.RECIPE_BANANA_BREAD]:
        cmds.append(_recipe_sqlite_insert(r))
    # 4 个同 title 变体（description/servings/preparationTime/ingredients/directions 不同）
    for i in range(4):
        cmds.append(_recipe_sqlite_insert(
            _recipe_variant(data.RECIPE_SPICY_TUNA, i)))
    # 重复目标（2 行所有字段完全相同——对齐 AW ROW_OBJECTS=[target, target]）
    cmds.append(_recipe_sqlite_insert(data.RECIPE_SPICY_TUNA))
    cmds.append(_recipe_sqlite_insert(data.RECIPE_SPICY_TUNA))
    cmds.append(_recipe_reload())
    return cmds


def recipe_delete_duplicates3_init() -> list[str]:
    """重复食谱删除 v3 — 对齐 AW RecipeDeleteDuplicateRecipes3（32 行）：
    21 个唯一噪声（不含 'Avocado Toast with Egg'）+ 3 个 Avocado Toast 变体
    + 6 个目标 title+description 变体 + 2 个完全相同的目标。"""
    cmds = [_recipe_clear_db()]
    # 21 个唯一噪声：5 个基础食谱的确定性变体（title ≠ 'Avocado Toast with Egg'）
    dup3_noise_base = [data.RECIPE_GREEK_SALAD, data.RECIPE_CHOCOLATE_CAKE,
                       data.RECIPE_CHICKEN_SOUP, data.RECIPE_PASTA_PRIMAVERA,
                       data.RECIPE_BANANA_BREAD]
    for i in range(21):
        cmds.append(_recipe_sqlite_insert(
            _recipe_variant(dup3_noise_base[i % 5], i)))
    # 3 个 'Avocado Toast with Egg' 变体（列表顶部噪声，字段互不相同）
    for i in range(3):
        cmds.append(_recipe_sqlite_insert(
            _recipe_variant(data.RECIPE_AVOCADO_TOAST, i)))
    # 6 个目标变体：title+description 与目标相同，其余字段不同
    # （对齐 AW filter: title==target.title and description==target.description）
    for i in range(6):
        cmds.append(_recipe_sqlite_insert(
            _recipe_variant(data.RECIPE_SPICY_TUNA, i, same_description=True)))
    # 重复目标（2 行完全相同）
    cmds.append(_recipe_sqlite_insert(data.RECIPE_SPICY_TUNA))
    cmds.append(_recipe_sqlite_insert(data.RECIPE_SPICY_TUNA))
    cmds.append(_recipe_reload())
    return cmds


def recipe_add_single_init() -> list[str]:
    """单目标添加 — 对齐 AW RecipeAddSingleRecipe（n_rows=1, n_rows_noise=10）：
    DB 只预置 10 行噪声（title ≠ 'Spicy Tuna Wraps'），目标由 agent 添加。"""
    cmds = [_recipe_clear_db()]
    for r in _recipe_noise_rows({data.RECIPE_SPICY_TUNA["title"]}):
        cmds.append(_recipe_sqlite_insert(r))
    cmds.append(_recipe_reload())
    return cmds


def recipe_add_multiple_init() -> list[str]:
    """3 目标添加 — 对齐 AW RecipeAddMultipleRecipes（n_rows=3, n_rows_noise=10）：
    10 行噪声（title 与目标不重叠），目标由 agent 添加。"""
    cmds = [_recipe_clear_db()]
    targets = [data.RECIPE_CHOCOLATE_CAKE, data.RECIPE_CHICKEN_SOUP,
               data.RECIPE_PASTA_PRIMAVERA]
    for r in _recipe_noise_rows({t["title"] for t in targets}):
        cmds.append(_recipe_sqlite_insert(r))
    cmds.append(_recipe_reload())
    return cmds


def recipe_add_from_markor_init() -> list[str]:
    """对齐 AW RecipeAddMultipleRecipesFromMarkor.initialize_task：
    DB 清空 + 10 噪声行；recipes.txt = AW csv 格式（header + 3 目标行）。"""
    cmds = [_recipe_clear_db()]
    targets = [data.RECIPE_CHOCOLATE_CAKE, data.RECIPE_CHICKEN_SOUP,
               data.RECIPE_PASTA_PRIMAVERA]
    for r in _recipe_noise_rows({t["title"] for t in targets}):
        cmds.append(_recipe_sqlite_insert(r))
    cmds.append(
        "pm grant net.gsantner.markor android.permission.WRITE_EXTERNAL_STORAGE 2>/dev/null || true"
    )
    cmds.append("mkdir -p /sdcard/Documents/Markor 2>/dev/null || true")
    cmds.append(_write_text_asset(
        _recipe_csv(targets), "aw_recipes.txt",
        "/sdcard/Documents/Markor/recipes.txt",
    ))
    cmds.append(_recipe_reload())
    return cmds


def recipe_add_from_markor2_init() -> list[str]:
    """对齐 AW RecipeAddMultipleRecipesFromMarkor2（prep_time='30 mins'）：
    recipes.txt = AW csv：3 个目标（preparationTime='30 mins'）+ 10 行噪声
    （prep 时间 ≠ 30 mins，title 与目标不重叠）；DB 预置 10 行同条件噪声。"""
    cmds = [_recipe_clear_db()]
    targets = [data.RECIPE_GREEK_SALAD, data.RECIPE_QUINOA_BOWL,
               data.RECIPE_TERIYAKI_SALMON]
    noise = [data.RECIPE_SPICY_TUNA, data.RECIPE_AVOCADO_TOAST,
             data.RECIPE_CHOCOLATE_CAKE, data.RECIPE_CHICKEN_SOUP,
             data.RECIPE_PASTA_PRIMAVERA, data.RECIPE_BANANA_BREAD]
    for r in (noise * 2)[:10]:  # 10 行 DB 噪声（prep 均 ≠ 30 mins，title ≠ 目标）
        cmds.append(_recipe_sqlite_insert(r))
    cmds.append(
        "pm grant net.gsantner.markor android.permission.WRITE_EXTERNAL_STORAGE 2>/dev/null || true"
    )
    cmds.append("mkdir -p /sdcard/Documents/Markor 2>/dev/null || true")
    cmds.append(_write_text_asset(
        _recipe_csv(targets + (noise * 2)[:10]), "aw_recipes_markor2.txt",
        "/sdcard/Documents/Markor/recipes.txt",
    ))
    cmds.append(_recipe_reload())
    return cmds


def recipe_add_from_image_init() -> list[str]:
    """对齐 AW RecipeAddMultipleRecipesFromImage.initialize_task：
    DB 清空 + 10 噪声行；recipes.jpg = 真实 JPEG（PIL 渲染 text_block，wrap 60）。"""
    cmds = [_recipe_clear_db()]
    targets = [data.RECIPE_CHOCOLATE_CAKE, data.RECIPE_CHICKEN_SOUP,
               data.RECIPE_PASTA_PRIMAVERA]
    for r in _recipe_noise_rows({t["title"] for t in targets}):
        cmds.append(_recipe_sqlite_insert(r))
    cmds.append("mkdir -p /sdcard/DCIM 2>/dev/null || true")
    cmds.append("rm -f /sdcard/DCIM/recipes.jpg 2>/dev/null || true")
    cmds.append(_render_image_asset(
        _recipe_text_block(targets, wrap_width=60),
        "aw_recipes.jpg", "/sdcard/DCIM/recipes.jpg"))
    cmds.append(_recipe_reload())
    return cmds


# ═══════════════════════════════════════════════════════════
# Expense — complete all 9 cases
# ═══════════════════════════════════════════════════════════

def _expense_sqlite_insert(e: dict, ts: int = 1697385600000) -> str:
    db = data.DB_PATHS["expense"]
    return (
        f"sqlite3 {db} \"INSERT INTO expense(name,amount,category,note,"
        f"created_date,modified_date) "
        f"VALUES('{e['name']}',{e['amount']},{e['category']},"
        f"'{e['note']}',{ts},{ts});\""
    )


def _expense_clear_db() -> str:
    return f"sqlite3 {data.DB_PATHS['expense']} \"DELETE FROM expense;\""


def expense_delete_single_init() -> list[str]:
    db = data.DB_PATHS["expense"]
    e = data.EXPENSE_LUNCH
    created = 1697385600000
    return [
        f"sqlite3 {db} \"DELETE FROM expense;\"",
        f"sqlite3 {db} \"INSERT INTO expense(name,amount,category,note,"
        f"created_date,modified_date) "
        f"VALUES('{e['name']}',{e['amount']},{e['category']},"
        f"'{e['note']}',{created},{created});\"",
    ]


def expense_delete_multiple_init() -> list[str]:
    """删除多个 — 3 目标（对齐 AW n_rows=3）。"""
    cmds = [_expense_clear_db()]
    cmds.append(_expense_sqlite_insert(data.EXPENSE_LUNCH))
    cmds.append(_expense_sqlite_insert(data.EXPENSE_COFFEE))
    cmds.append(_expense_sqlite_insert(data.EXPENSE_TAXI))
    cmds.append("am force-stop com.arduia.expense 2>/dev/null || true")
    return cmds


def expense_delete_multiple2_init() -> list[str]:
    """删除多个 — 3 目标 + 50 噪声（噪声名与目标名不重叠）。"""
    cmds = [_expense_clear_db()]
    noise = [data.EXPENSE_DINNER, data.EXPENSE_GROCERIES, data.EXPENSE_GAS,
             data.EXPENSE_CONCERT, data.EXPENSE_RENT, data.EXPENSE_DOCTOR,
             data.EXPENSE_BOOK]  # 不含 Lunch/Coffee/Taxi Ride
    for i in range(50):
        e = noise[i % len(noise)]
        cmds.append(_expense_sqlite_insert(e, 1697385600000 + (i + 1) * 1000))
    # 3 target rows
    cmds.append(_expense_sqlite_insert(data.EXPENSE_LUNCH))
    cmds.append(_expense_sqlite_insert(data.EXPENSE_COFFEE))
    cmds.append(_expense_sqlite_insert(data.EXPENSE_TAXI))
    cmds.append("am force-stop com.arduia.expense 2>/dev/null || true")
    return cmds


def expense_delete_duplicates_init() -> list[str]:
    """重复支出删除 — 1 dup target + 5 noise。"""
    cmds = [_expense_clear_db()]
    for e in [data.EXPENSE_COFFEE, data.EXPENSE_TAXI, data.EXPENSE_DINNER,
              data.EXPENSE_GROCERIES, data.EXPENSE_GAS]:
        cmds.append(_expense_sqlite_insert(e))
    # duplicate
    cmds.append(_expense_sqlite_insert(data.EXPENSE_LUNCH))
    cmds.append(_expense_sqlite_insert(data.EXPENSE_LUNCH))
    return cmds


def expense_delete_duplicates2_init() -> list[str]:
    """重复支出删除 v2 — 对齐 AW ExpenseDeleteDuplicates2：
    37 噪声 + 3 个 Lunch 变体（amount 1550+扰动 50-999，独立时间戳）
    + 2 个完全相同 Lunch 目标 = 42 行。"""
    cmds = [_expense_clear_db()]
    base_ts = 1697385600000
    noise = [data.EXPENSE_COFFEE, data.EXPENSE_TAXI, data.EXPENSE_DINNER,
             data.EXPENSE_GROCERIES, data.EXPENSE_GAS, data.EXPENSE_CONCERT,
             data.EXPENSE_RENT, data.EXPENSE_BOOK]
    for i in range(37):
        e = noise[i % len(noise)]
        cmds.append(_expense_sqlite_insert(e, base_ts + (i + 1) * 1000))
    # 3 个目标变体：同 name=Lunch，amount 扰动，created/modified 独立
    for j, pert in enumerate(data.EXPENSE_DUP_PERTURBATIONS):
        v = dict(data.EXPENSE_LUNCH, amount=data.EXPENSE_LUNCH["amount"] + pert)
        ts = base_ts + (50 + j * 7) * 1000
        cmds.append(_expense_sqlite_insert(v, ts))
    # 重复目标（2 行所有字段完全相同，含 created/modified——对齐 AW _validate_candidates）
    cmds.append(_expense_sqlite_insert(data.EXPENSE_LUNCH, base_ts + 100 * 1000))
    cmds.append(_expense_sqlite_insert(data.EXPENSE_LUNCH, base_ts + 100 * 1000))
    cmds.append("am force-stop com.arduia.expense 2>/dev/null || true")
    return cmds


def expense_add_single_init() -> list[str]:
    cmds = [_expense_clear_db()]
    # 预置噪声行（无重复条目）
    for e in [data.EXPENSE_COFFEE, data.EXPENSE_TAXI, data.EXPENSE_DINNER,
              data.EXPENSE_GROCERIES, data.EXPENSE_GAS, data.EXPENSE_CONCERT,
              data.EXPENSE_RENT, data.EXPENSE_DOCTOR, data.EXPENSE_BOOK]:
        cmds.append(_expense_sqlite_insert(e))
    cmds.append("am force-stop com.arduia.expense 2>/dev/null || true")
    return cmds


# AW Expense.category_id_to_name（文本表示里用真名，如 Food/Housing/Transportation）
_CATEGORY_NAMES: dict[int, str] = {
    1: "Others", 2: "Income", 3: "Food", 4: "Housing", 5: "Social",
    6: "Entertainment", 7: "Transportation", 8: "Clothes",
    9: "Health Care", 10: "Education", 11: "Donation",
}


def _category_name(cat: int) -> str:
    return _CATEGORY_NAMES.get(cat, str(cat))


def _expense_text_block(rows: list[dict]) -> str:
    """AW get_text_representation_of_rows text_block 格式（fields 顺序同 AW）。"""
    blocks = []
    for r in rows:
        blocks.append(
            f"Expense: {r['name']}\n"
            f" amount_dollars: ${r['amount'] / 100}\n"
            f" category_name: {_category_name(r['category'])}\n"
            f" note: {r['note']}"
        )
    return "\n".join(blocks)


def _expense_csv(rows: list[dict]) -> str:
    """AW get_text_representation_of_rows csv 格式（header 同 AW）。"""
    lines = ["name|amount_dollars|category_name|note"]
    for r in rows:
        lines.append(
            f"{r['name']}|${r['amount'] / 100}|{_category_name(r['category'])}|{r['note']}"
        )
    return "\n".join(lines)


def _render_image_asset(text: str, local_name: str, device_path: str) -> str:
    """PIL 把多行文本渲染成真实 JPEG（对齐 AW write_to_gallery/_draw_text），
    落到宿主 fastaget/meta/assets/，返回 host 侧 adb push 命令。"""
    from pathlib import Path
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.load_default(size=24)
    lines = text.split("\n")
    max_w = max(font.getbbox(line)[2] for line in lines)
    total_h = 0
    for line in lines:
        total_h += font.getbbox(line)[3] if line.strip() else 12
    img = Image.new("RGB", (max_w + 20, total_h + 20), (255, 255, 255))
    d = ImageDraw.Draw(img)
    y = 10
    for line in lines:
        if line.strip():
            d.text((10, y), line, fill=(0, 0, 0), font=font)
            y += font.getbbox(line)[3]
        else:
            y += 12
    local_dir = Path(__file__).resolve().parent.parent.parent / _ASSET_DIR
    local_dir.mkdir(parents=True, exist_ok=True)
    img.save(local_dir / local_name)
    return f"adb push {_ASSET_DIR}/{local_name} {device_path}"


def expense_add_multiple_init() -> list[str]:
    """3 目标 (Lunch/Coffee/Taxi Ride) + 10 噪声——噪声名排除目标名（对齐 AW filter_fn）。"""
    cmds = [_expense_clear_db()]
    noise = [data.EXPENSE_DINNER, data.EXPENSE_GROCERIES, data.EXPENSE_GAS,
             data.EXPENSE_CONCERT, data.EXPENSE_RENT, data.EXPENSE_DOCTOR,
             data.EXPENSE_BOOK, data.EXPENSE_DINNER, data.EXPENSE_GROCERIES,
             data.EXPENSE_GAS]
    for e in noise:
        cmds.append(_expense_sqlite_insert(e, 1697385600000 + len(cmds) * 1000))
    return cmds


def expense_add_from_markor_init() -> list[str]:
    """对齐 AW ExpenseAddMultipleFromMarkor.initialize_task：
    DB 清空 + ~100 噪声行；my_expenses.txt = CSV header + 100 噪声行 + 2 个
    Reimbursable 目标行（确定性打乱，random.Random(42).shuffle 同 AW random.shuffle）。"""
    cmds = [_expense_clear_db()]
    noise_pool = [data.EXPENSE_DINNER, data.EXPENSE_GROCERIES, data.EXPENSE_GAS,
                  data.EXPENSE_CONCERT, data.EXPENSE_RENT, data.EXPENSE_DOCTOR,
                  data.EXPENSE_BOOK]
    noise_rows = [noise_pool[i % len(noise_pool)] for i in range(100)]
    for e in noise_rows:
        cmds.append(_expense_sqlite_insert(e, 1697385600000 + len(cmds) * 1000))
    # 目标行 note 追加 '. Reimbursable.'（同 AW dataclasses.replace）
    targets = [
        dict(data.EXPENSE_LUNCH, note=data.EXPENSE_LUNCH["note"] + ". Reimbursable."),
        dict(data.EXPENSE_COFFEE, note=data.EXPENSE_COFFEE["note"] + ". Reimbursable."),
    ]
    rows = noise_rows + targets
    import random
    random.Random(42).shuffle(rows)
    cmds.append(
        "pm grant net.gsantner.markor android.permission.WRITE_EXTERNAL_STORAGE 2>/dev/null || true"
    )
    cmds.append("mkdir -p /sdcard/Documents/Markor 2>/dev/null || true")
    cmds.append(_write_text_asset(
        _expense_csv(rows), "aw_my_expenses.txt",
        "/sdcard/Documents/Markor/my_expenses.txt",
    ))
    return cmds


def expense_add_from_gallery_init() -> list[str]:
    """对齐 AW ExpenseAddMultipleFromGallery.initialize_task：
    - DB: 清空 + 10 噪声行（名≠目标名）
    - Gallery: 真实 JPEG（PIL 渲染目标行文本）→ expenses.jpg；10 张噪声图 old_expenses_*.jpg"""
    cmds = [_expense_clear_db()]
    noise = [data.EXPENSE_DINNER, data.EXPENSE_GROCERIES, data.EXPENSE_GAS,
             data.EXPENSE_CONCERT, data.EXPENSE_RENT, data.EXPENSE_DOCTOR,
             data.EXPENSE_BOOK, data.EXPENSE_DINNER, data.EXPENSE_GROCERIES,
             data.EXPENSE_GAS]
    for e in noise:
        cmds.append(_expense_sqlite_insert(e, 1697385600000 + len(cmds) * 1000))
    targets = [data.EXPENSE_LUNCH, data.EXPENSE_COFFEE, data.EXPENSE_TAXI]
    cmds.append("mkdir -p /sdcard/DCIM 2>/dev/null || true")
    cmds.append("rm -f /sdcard/DCIM/expenses.jpg /sdcard/DCIM/old_expenses_*.jpg 2>/dev/null || true")
    cmds.append(_render_image_asset(
        _expense_text_block(targets), "aw_expenses.jpg", "/sdcard/DCIM/expenses.jpg"))
    noise_text = _expense_text_block(noise)
    for i in range(10):
        cmds.append(_render_image_asset(
            noise_text, f"aw_old_expenses_{i}.jpg", f"/sdcard/DCIM/old_expenses_{i}.jpg"))
    return cmds


# ═══════════════════════════════════════════════════════════
# Calendar — complete all 17 cases
# ═══════════════════════════════════════════════════════════

# Calendar：使用 SimpleCalendar 的 events.db (sqlite3)，不用 content provider
# SimpleCalendar 用秒级时间戳（非毫秒），首次启动自动创建 DB

CAL_DB = "/data/data/com.simplemobiletools.calendar.pro/databases/events.db"


def _calendar_ensure_db() -> str:
    return (
        "if [ ! -f /data/data/com.simplemobiletools.calendar.pro/databases/events.db ]; then "
        "am start -n com.simplemobiletools.calendar.pro/.activities.MainActivity 2>/dev/null; "
        "sleep 2; "
        "am force-stop com.simplemobiletools.calendar.pro 2>/dev/null; "
        "fi"
    )


def _calendar_sql_insert(ev: dict, offset_s: int = 0) -> str:
    """生成单条 events INSERT SQL（不含外层 sqlite3 调用）。

    单引号必须转义（''）——例如 CAL_EVENT_BIRTHDAY description
    "Alice's birthday party" 不转义会直接 SQL 语法错误导致 seed 失败。
    """
    st = int(ev["dtstart"]) // 1000 + offset_s
    et = int(ev["dtend"]) // 1000 + offset_s

    def _esc(s: str) -> str:
        return s.replace("'", "''")

    return (
        f"INSERT INTO events"
        f"(start_ts,end_ts,title,location,description,"
        f"reminder_1_minutes,reminder_2_minutes,reminder_3_minutes,"
        f"reminder_1_type,reminder_2_type,reminder_3_type,"
        f"repeat_interval,repeat_rule,repeat_limit,repetition_exceptions,"
        f"attendees,import_id,time_zone,flags,event_type,parent_id,"
        f"last_updated,source,availability,color,type) "
        f"VALUES({st},{et},'{_esc(ev['title'])}','{_esc(ev.get('location', ''))}',"
        f"'{_esc(ev.get('description', ''))}',10,-1,-1,1,0,0,0,0,0,"
        f"'','','','UTC',0,0,0,0,'',0,0,0);"
    )


def _calendar_sqlite_insert(ev: dict, offset_s: int = 0) -> str:
    """向 SimpleCalendar events.db 插入事件（时间戳单位=秒）。"""
    return (
        f"sqlite3 {CAL_DB} \"{_calendar_sql_insert(ev, offset_s)}\" "
        f"2>/dev/null || echo 'cal_insert_failed'"
    )


def _calendar_sqlite_insert_many(evs: list[dict]) -> str:
    """批量插入：单条 sqlite3 调用内执行多条 INSERT（避免 init 命令数膨胀）。"""
    sql = " ".join(_calendar_sql_insert(ev) for ev in evs)
    return f"sqlite3 {CAL_DB} \"{sql}\" 2>/dev/null || echo 'cal_insert_failed'"


_CAL_OCT15_DAY_EPOCH_S = 1697328000  # 2023-10-15 00:00 UTC（AW device_constants.DT 所在周）


def _calendar_day_event(title: str, description: str, location: str,
                        day: int, hour: int, duration_s: int = 3600) -> dict:
    """构建 2023-10-{day} 的事件 spec（毫秒时间戳，兼容 _calendar_sqlite_insert）。"""
    st = _CAL_OCT15_DAY_EPOCH_S + (day - 15) * 86400 + hour * 3600
    return {
        "title": title, "description": description, "location": location,
        "dtstart": str(st * 1000), "dtend": str((st + duration_s) * 1000),
    }


def _calendar_noise_events(count: int) -> list[dict]:
    """count 个确定性噪声事件：日期 10-16..10-31（≠ 目标日期 10-15），
    标题互异且不含 '（对齐 AW generate_noise_events：day ∉ 目标日期）。"""
    return [
        _calendar_day_event(f"Noise Event {i + 1}", "Automated noise event", "",
                            16 + i % 16, 8 + i % 10)
        for i in range(count)
    ]


def _calendar_ev_day(ev: dict) -> int:
    """从 dtstart(ms) 反推 2023-10-{day} 的 day（_CAL_OCT15_DAY_EPOCH_S 为基准）。"""
    return (int(ev["dtstart"]) // 1000 - _CAL_OCT15_DAY_EPOCH_S) // 86400 + 15


def _calendar_clear() -> str:
    return f"sqlite3 {CAL_DB} \"DELETE FROM events;\" 2>/dev/null || true"


def calendar_add_one_event_init() -> list[str]:
    return [_calendar_ensure_db(), _calendar_clear()]


def calendar_add_one_event_relative_day_init() -> list[str]:
    return [_calendar_ensure_db(), _calendar_clear()]


def calendar_add_one_event_tomorrow_init() -> list[str]:
    return [_calendar_ensure_db(), _calendar_clear()]


def calendar_add_one_event_in_two_weeks_init() -> list[str]:
    return [_calendar_ensure_db(), _calendar_clear()]


def calendar_add_repeating_event_init() -> list[str]:
    return [_calendar_ensure_db(), _calendar_clear()]


def calendar_delete_events_init() -> list[str]:
    """对齐 AW SimpleCalendarDeleteEvents（n_rows=3 / n_rows_noise=20）：
    3 个目标事件同在 goal 日期 2023-10-15 + 20 个噪声事件在其他日期。"""
    cmds = [_calendar_ensure_db(), _calendar_clear()]
    for ev in [
        _calendar_day_event("Test Meeting", "Automated test event",
                            "Conference Room A", 15, 9),
        _calendar_day_event("Team Lunch", "Monthly team lunch at Italian restaurant",
                            "Bella Italia", 15, 12),
        _calendar_day_event("Project Review", "Q3 project status review with stakeholders",
                            "Main Boardroom", 15, 16),
    ]:
        cmds.append(_calendar_sqlite_insert(ev))
    cmds.append(_calendar_sqlite_insert_many(_calendar_noise_events(20)))
    return cmds


def calendar_delete_one_event_init() -> list[str]:
    """预置 1 个旧事件 + 1 个目标事件。"""
    cmds = [_calendar_ensure_db(), _calendar_clear()]
    # 旧事件 (不是目标，使用旧时间戳 2020)
    old_ev = dict(data.CAL_EVENT_DENTAL)
    old_ev["dtstart"] = "1600000000000"  # 2020-09-13
    old_ev["dtend"] = "1600003600000"
    cmds.append(_calendar_sqlite_insert(old_ev))
    cmds.append(_calendar_sqlite_insert(data.CAL_EVENT_TEAM_MEETING))
    return cmds


def calendar_delete_events_on_relative_day_init() -> list[str]:
    """对齐 AW SimpleCalendarDeleteEventsOnRelativeDay（n_rows=2 / n_rows_noise=20）。

    设备日期 2023-10-15 是周日——'this Sunday' 有 today 歧义（AW 自身也限定
    目标日 ∈ 周一..周六，Oct 16..21，避开撞 today）。固定 'this Saturday'
    = 2023-10-21：2 个目标事件当天；噪声 = 周五 Birthday + 周日 Brunch +
    18 个其他日期事件（全部排除目标日 21，同 AW filter_fn）。"""
    cmds = [_calendar_ensure_db(), _calendar_clear()]
    for ev in [
        _calendar_day_event("Saturday Brunch", "Weekend brunch with friends",
                            "The Pancake House", 21, 10),
        _calendar_day_event("Weekend Market Trip", "Farmers market visit",
                            "Downtown Square", 21, 14),
    ]:
        cmds.append(_calendar_sqlite_insert(ev))
    noise = [ev for ev in _calendar_noise_events(24)
             if _calendar_ev_day(ev) != 21][:18]
    cmds.append(_calendar_sqlite_insert(data.CAL_EVENT_BIRTHDAY))  # Fri Oct 20，噪声
    cmds.append(_calendar_sqlite_insert(data.CAL_EVENT_SUNDAY))    # Sun Oct 22，噪声
    cmds.append(_calendar_sqlite_insert_many(noise))
    return cmds


def calendar_query_date_init() -> list[str]:
    """预置数据供查询。"""
    cmds = [_calendar_ensure_db(), _calendar_clear()]
    for ev in [data.CAL_EVENT_TEAM_MEETING, data.CAL_EVENT_LUNCH,
               data.CAL_EVENT_REVIEW, data.CAL_EVENT_DENTAL,
               data.CAL_EVENT_BIRTHDAY]:
        cmds.append(_calendar_sqlite_insert(ev))
    return cmds


def calendar_query_events_on_date_init() -> list[str]:
    return calendar_query_date_init()


def calendar_query_any_events_on_date_init() -> list[str]:
    """对齐 AW SimpleCalendarAnyEventsOnDate（3 个事件同在提问日期 + 噪声排除）：
    3 个事件都在提问日期 2023-10-15 + 60 个噪声事件在其他日期——回答有唯一正确答案。"""
    cmds = [_calendar_ensure_db(), _calendar_clear()]
    for ev in [
        _calendar_day_event("Test Meeting", "Automated test event",
                            "Conference Room A", 15, 9),
        _calendar_day_event("Team Lunch", "Monthly team lunch at Italian restaurant",
                            "Bella Italia", 15, 12),
        _calendar_day_event("Project Review", "Q3 project status review with stakeholders",
                            "Main Boardroom", 15, 16),
    ]:
        cmds.append(_calendar_sqlite_insert(ev))
    cmds.append(_calendar_sqlite_insert_many(_calendar_noise_events(60)))
    return cmds


def calendar_query_event_on_date_at_time_init() -> list[str]:
    return calendar_query_date_init()


def calendar_query_events_in_next_week_init() -> list[str]:
    """对齐 AW SimpleCalendarEventsInNextWeek（relevant_state 恰 2 个事件）：
    'next week'（Mon 10-16 ~ Sun 10-22，设备日期 10-15 周日不计入）内恰 2 个
    事件（Team Lunch 10-16 14:00 + Project Review 10-17 10:00），答案唯一。"""
    cmds = [_calendar_ensure_db(), _calendar_clear()]
    cmds.append(_calendar_sqlite_insert(data.CAL_EVENT_LUNCH))
    cmds.append(_calendar_sqlite_insert(data.CAL_EVENT_REVIEW))
    return cmds


def calendar_query_events_in_time_range_init() -> list[str]:
    return calendar_query_date_init()


def calendar_query_first_event_after_start_init() -> list[str]:
    return calendar_query_date_init()


def calendar_query_location_init() -> list[str]:
    return calendar_query_date_init()


def calendar_query_next_event_init() -> list[str]:
    return calendar_query_date_init()


def calendar_query_next_meeting_with_person_init() -> list[str]:
    """对齐 AW SimpleCalendarNextMeetingWithPerson：标题为 'Drinks with {person}'
    （AW tasks.textproto 原文）→ 'Drinks with Alice Smith' Oct 20 09:00；
    其余事件标题不含 Alice Smith（排除语义）。"""
    cmds = [_calendar_ensure_db(), _calendar_clear()]
    cmds.append(_calendar_sqlite_insert(data.CAL_EVENT_TEAM_MEETING))
    cmds.append(_calendar_sqlite_insert(data.CAL_EVENT_LUNCH))
    cmds.append(_calendar_sqlite_insert(
        _calendar_day_event("Drinks with Alice Smith", "Automated test event",
                            "Central Park", 20, 9)))
    return cmds


# ═══════════════════════════════════════════════════════════
# Retro Music — 4 cases
# ═══════════════════════════════════════════════════════════
# 对齐 AW RetroCreatePlaylist.initialize_task：
#   clear_internal_storage(≈rm Music/*.mp3) + _clear_playlist_dbs + 真实 MP3
#   （ID3 标题 + 精确时长，MediaStore 可索引）+ MEDIA_SCANNER_SCAN_FILE。
# 与 AW user_data_generation._create_test_mp3（pydub 静音段导出）等价——
# 无 pydub 依赖，纯字节构建静音 MP3（MPEG-1 Layer III 32kbps 44.1kHz CBR），
# Android MediaExtractor 按 (filesize-id3)*8/bitrate 估算时长，帧数反推保证
# MediaStore DURATION ≈ duration_ms（±1ms）。

_MP3_BITRATE = 32000
_MP3_SAMPLE_RATE = 44100
_MP3_FRAME_LEN = 144 * _MP3_BITRATE // _MP3_SAMPLE_RATE  # 104 B/帧，1152 采样/帧


def _mp3_silent_bytes(duration_ms: int, title: str, artist: str = "test_artist") -> bytes:
    """生成静音 MP3 + ID3v2.3 TIT2/TPE1 标签，帧数由 duration 反推。"""
    def _id3_frame(fid: str, text: str) -> bytes:
        payload = b"\x00" + text.encode("latin-1")  # encoding 0 = ISO-8859-1
        return fid.encode("latin-1") + len(payload).to_bytes(4, "big") + b"\x00\x00" + payload

    body = _id3_frame("TIT2", title) + _id3_frame("TPE1", artist)
    size = len(body)
    synchsafe = bytes(((size >> 21) & 0x7F, (size >> 14) & 0x7F,
                       (size >> 7) & 0x7F, size & 0x7F))
    id3 = b"ID3" + b"\x03\x00" + b"\x00" + synchsafe + body
    # 0xFF 0xFB 0x10 0x00: sync + MPEG1 + Layer III + 32kbps + 44.1kHz + stereo
    frame = b"\xff\xfb\x10\x00" + bytes(_MP3_FRAME_LEN - 4)
    # duration_ms × bitrate(bps) / 1000(ms→s) / 8(bit→byte)
    audio_bytes = duration_ms * _MP3_BITRATE // 8000
    n_frames = max(1, audio_bytes // _MP3_FRAME_LEN)
    return id3 + frame * n_frames


def _mp3_asset(title: str, duration_ms: int, local_name: str, device_path: str) -> str:
    """把真实 MP3 落到宿主 fastaget/meta/assets/，返回 host 侧 adb push 命令。"""
    from pathlib import Path
    local_dir = Path(__file__).resolve().parent.parent.parent / _ASSET_DIR
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / local_name).write_bytes(
        _mp3_silent_bytes(duration_ms, title))
    return f"adb push {_ASSET_DIR}/{local_name} \"{device_path}\""


def _retro_write_mp3(file_name: str, title: str = "", duration_ms: int = 1500,
                     local_prefix: str = "aw_retro_") -> str:
    """写入 1 首真实 MP3（ID3 title=文件名去扩展名），push 到 /sdcard/Music/。
    local 名按 title 确定性生成（hash() 每进程随机，禁止用于资产名）。
    local_prefix：host 侧资产名前缀——同歌不同时长的 case（如 PlaylistDuration
    与 CreatePlaylist 共用 _RETRO_SONG_FILES）必须用不同前缀，否则 yml 生成时
    后写的资产会覆盖先写的（push 路径相同但内容时长不同）。"""
    t = title or file_name.split(".")[0]
    local = local_prefix + t.replace(" ", "_").replace("/", "_") + ".mp3"
    return _mp3_asset(t, duration_ms, local, f"/sdcard/Music/{file_name}")


# 歌曲池（与 AW RetroCreatePlaylist 相同的 15 首；create/queue/save 共用）
_RETRO_SONG_FILES = [
    "Morning Vibes.mp3", "Summer Breeze.mp3", "Night Drive.mp3",
    "Rock Anthem.mp3", "Jazz Cafe.mp3", "Chill Beats.mp3",
    "Lost in Echo.mp3", "Dark Horse.mp3", "Piano Concerto.mp3",
    "City Lights.mp3", "Guitar Solo.mp3", "Electric Dreams.mp3",
    "Violin Duet.mp3", "Opera Highlights.mp3", "Wind Ensemble.mp3",
]

# RetroPlaylistDuration：10 首目标歌时长总和 = 2850000 ms（47.5 min，对齐 AW
# _generate_list_with_sum(int(47.5*60*1000), len(files))）——恰在 45-50 min 区间；
# 5 首噪声歌时长不同（3-5 min），保证"存在正确答案"
_RETRO_DURATION_TARGET_MS = [300000, 300000, 300000, 280000, 280000,
                             280000, 280000, 280000, 280000, 270000]
_RETRO_DURATION_NOISE_MS = [240000, 180000, 300000, 210000, 260000]


def _retro_scan_and_restart() -> list[str]:
    """对齐 AW _scan_music_directory：媒体扫描广播 + force-stop 让 app 重读 MediaStore。"""
    return [
        "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
        "-d file:///storage/emulated/0/Music 2>/dev/null || true",
        _retro_restart(),
    ]


def _retro_clear_playlist_dbs() -> list[str]:
    """对齐 AW _clear_playlist_dbs：清空 PlaylistEntity + SongEntity。"""
    db = data.DB_PATHS["retro_playlist"]
    return [
        f"sqlite3 {db} \"DELETE FROM PlaylistEntity;\" 2>/dev/null || true",
        f"sqlite3 {db} \"DELETE FROM SongEntity;\" 2>/dev/null || true",
    ]


def retro_create_playlist_init() -> list[str]:
    cmds = [
        _ensure_db_launched("code.name.monkey.retromusic", data.DB_PATHS["retro_playlist"]),
        "mkdir -p /sdcard/Music 2>/dev/null || true",
        "rm -f /sdcard/Music/*.mp3 2>/dev/null || true",
    ]
    cmds += _retro_clear_playlist_dbs()
    for f in _RETRO_SONG_FILES:
        cmds.append(_retro_write_mp3(f))
    cmds += _retro_scan_and_restart()
    return cmds


def retro_playing_queue_init() -> list[str]:
    """create playlist 同款 + 清空 playing_queue（对齐 AW RetroPlayingQueue 前提）。"""
    cmds = retro_create_playlist_init()
    cmds.insert(-1,  # 在 force-stop 前清空队列表
        f"sqlite3 {data.DB_PATHS['retro_playback']} "
        "\"DELETE FROM playing_queue;\" 2>/dev/null || true")
    return cmds


def retro_playlist_duration_init() -> list[str]:
    """对齐 AW RetroPlaylistDuration.initialize_task：10 首目标歌时长总和
    2850000 ms + 5 首噪声歌（3-5 min），全部真实 MP3。
    local_prefix='aw_retro_ped_'：与 create/queue/save 共用同一批歌名，但时长
    不同——独立 host 资产名防止 yml 生成时被 1500ms 版本覆盖（否则 push 内容
    错误、时长总和永远不达标）。"""
    cmds = [
        _ensure_db_launched("code.name.monkey.retromusic", data.DB_PATHS["retro_playlist"]),
        "mkdir -p /sdcard/Music 2>/dev/null || true",
        "rm -f /sdcard/Music/*.mp3 2>/dev/null || true",
    ]
    cmds += _retro_clear_playlist_dbs()
    for f, ms in zip(_RETRO_SONG_FILES[:10], _RETRO_DURATION_TARGET_MS):
        cmds.append(_retro_write_mp3(f, duration_ms=ms, local_prefix="aw_retro_ped_"))
    for f, ms in zip(_RETRO_SONG_FILES[10:], _RETRO_DURATION_NOISE_MS):
        cmds.append(_retro_write_mp3(f, duration_ms=ms, local_prefix="aw_retro_ped_"))
    cmds += _retro_scan_and_restart()
    return cmds


def retro_save_playlist_init() -> list[str]:
    """对齐 AW RetroSavePlaylist.initialize_task：先 force-stop app + 清空
    playlist DB（防上一轮残留 'Test Playlist fet' 假阳性）+ 清 m3u 导出残留，
    再走 create playlist 同款种子（真实 MP3 / 清空 PlaylistEntity+SongEntity /
    媒体扫描广播 / force-stop）。playlist 本身必须由 agent 创建。"""
    cmds = [_retro_restart()] + _retro_clear_playlist_dbs()
    cmds.append("rm -f /sdcard/Download/*.m3u 2>/dev/null || true")
    cmds += retro_create_playlist_init()
    return cmds


# ═══════════════════════════════════════════════════════════
# VLC — 2 cases
# ═══════════════════════════════════════════════════════════

def _vlc_write_video(file_name: str) -> str:
    """写入真实 MPEG-4 视频（对齐 AW write_video_file_to_device：cv2 mp4v 生成、
    帧上显示文件名文本），adb push 到 /sdcard/VLCVideos/。urandom 假 .mp4 可能
    不被 MediaStore 识别为 video，VLC 媒体库无法索引——agent 在 VLC 里看不到文件。"""
    title = file_name.split(".")[0]
    return _video_mp4_asset([title], f"aw_vlc_{file_name}",
                            f"/sdcard/VLCVideos/{file_name}")


def _vlc_clear_playlist_dbs() -> list[str]:
    """对齐 AW _clear_playlist_dbs：rm 整个 vlc_media.db（设备端 sqlite3 3.32 无法
    解析 VLC 新版 SQLite 生成的 UPDATE...FROM 触发器——DELETE 语句必然失败，
    只能整库删除；VLC 下次启动自动重建空库），保证目标 playlist 必然 ABSENT。"""
    return [
        _vlc_restart(),
        f"rm -f {data.DB_PATHS['vlc']} 2>/dev/null || true",
    ]


def _vlc_scan() -> str:
    """媒体扫描广播（对齐 retro _scan_music_directory）：让 MediaStore 索引
    /sdcard/VLCVideos 下新 push 的真实视频。"""
    return (
        "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
        "-d file:///storage/emulated/0/VLCVideos 2>/dev/null || true"
    )


def vlc_create_playlist_init() -> list[str]:
    """对齐 AW VlcCreatePlaylist.initialize_task：先 force-stop + 清空 playlist
    DB（防残留假阳性）+ 清旧视频，再写 3 个目标 + 2 个噪声真实视频，媒体扫描 +
    force-stop 让 VLC 重扫。playlist 本身必须由 agent 创建。"""
    cmds = _vlc_clear_playlist_dbs()
    cmds.append("mkdir -p /sdcard/VLCVideos 2>/dev/null || true")
    cmds.append("rm -f /sdcard/VLCVideos/*.mp4 2>/dev/null || true")
    for f in data.VLC_PLAYLIST["videos"] + ["other_video_1.mp4", "other_video_2.mp4"]:
        cmds.append(_vlc_write_video(f))
    cmds.append(_vlc_scan())
    cmds.append(_vlc_restart())
    return cmds


def vlc_create_two_playlists_init() -> list[str]:
    """对齐 AW VlcCreateTwoPlaylists.initialize_task：force-stop + 清空 playlist
    DB + 写 demo_1..4 目标视频 + 每 playlist 配 2 个噪声视频（对齐 AW
    noise_files per playlist），媒体扫描 + force-stop。playlist 必须由 agent 创建。"""
    cmds = _vlc_clear_playlist_dbs()
    cmds.append("mkdir -p /sdcard/VLCVideos 2>/dev/null || true")
    cmds.append("rm -f /sdcard/VLCVideos/*.mp4 2>/dev/null || true")
    for f in (data.VLC_PLAYLIST_ALPHA["videos"] + data.VLC_PLAYLIST_BETA["videos"]):
        cmds.append(_vlc_write_video(f))
    for f in ["noise_video_1.mp4", "noise_video_2.mp4",
              "noise_video_3.mp4", "noise_video_4.mp4"]:
        cmds.append(_vlc_write_video(f))
    cmds.append(_vlc_scan())
    cmds.append(_vlc_restart())
    return cmds


# ═══════════════════════════════════════════════════════════
# Tasks app — 7 cases
# ═══════════════════════════════════════════════════════════

DB_TASKS = data.DB_PATHS["tasks"]

_TASK_FORCE_STOP = "am force-stop org.tasks 2>/dev/null || true"

# 噪声任务标题池（对齐 AW 随机任务标题池；与各 case 固定目标标题互斥）
_TASK_NOISE = [
    ("Prepare presentation for meeting", 1), ("Call client for follow-up", 3),
    ("Research market trends", 2), ("Follow up on support tickets", 1),
    ("Prepare agenda for weekly meeting", 3), ("Book flights for conference", 2),
    ("Plan team outing", 1), ("Participate in brainstorming session", 3),
    ("Review performance metrics", 2), ("Attend training session", 1),
    ("Send report to manager", 3), ("Dinner with friends", 2),
    ("Organize movie night", 1), ("Exercise session with coach", 3),
    ("Read book for book club", 2), ("Plan family reunion", 1),
    ("Complete survey", 3), ("Check handwritten notes", 2),
    ("Confirm meeting location", 1), ("Schedule follow-up meeting", 3),
]


def _task_sqlite_insert(t: dict) -> str:
    """tasks 表 INSERT（对齐 AW create_task_from_proto 字段集：title/importance/
    dueDate/hideUntil/completed/created/modified/notes + NOT NULL 全列 deleted/
    estimatedSeconds/elapsedSeconds/timerStart/notificationFlags/lastNotified/
    collapsed/parent——缺 deleted 等列会 NOT NULL 约束失败，静默空库=init 假成功；
    created=dueDate-7h；时间戳均为 epoch 毫秒）。未提供的列取 0/默认。"""
    title = t["title"].replace("'", "")
    importance = t.get("importance", 2)
    notes = t.get("notes", "test notes").replace("'", "")
    due_ms = t.get("due_ms", 0)
    hide_ms = t.get("hide_ms", 0)
    completed_ms = t.get("completed_ms", 0)
    created_ms = due_ms - 7 * 3600 * 1000 if due_ms else 0
    return (
        f"sqlite3 {DB_TASKS} \"INSERT INTO tasks(title,importance,notes,dueDate,"
        f"hideUntil,completed,created,modified,deleted,estimatedSeconds,"
        f"elapsedSeconds,timerStart,notificationFlags,lastNotified,collapsed,parent) "
        f"VALUES('{title}',{importance},'{notes}',{due_ms},{hide_ms},{completed_ms},"
        f"{created_ms},{created_ms},0,0,0,0,0,0,0,0);\" "
        f"2>/dev/null || echo 'task_inserted'"
    )


def _task_clear() -> list[str]:
    """清空 tasks 表（对齐 AW clear_task_db）+ 确保 DB 存在（启动一次 app）。

    DELETE 不做 2>/dev/null 掩蔽——init 失败（DB 缺失/权限错）必须显式暴露，
    否则上一轮残留数据会导致假阳性。"""
    return [
        _ensure_db_launched("org.tasks", data.DB_PATHS["tasks"]),
        f"sqlite3 {DB_TASKS} \"DELETE FROM tasks;\"",
    ]


def tasks_due_on_date_init() -> list[str]:
    """对齐 AW TasksDueOnDate：3 个固定任务 due 2026-07-17（答案=3 标题）+ 20 个
    噪声任务（due 偏离 ±1..10 天），force-stop 让 app 重读库。"""
    cmds = _task_clear()
    for t in data.TASKS_DUE_ON_DATE:
        cmds.append(_task_sqlite_insert(
            {**t, "due_ms": data.TASK_DUE_2026_07_17_MS}))
    for i, (title, importance) in enumerate(_TASK_NOISE):
        day_off = i - 10 if i < 10 else i - 9  # -10..-1, +1..+10，避开目标日
        cmds.append(_task_sqlite_insert({
            "title": title, "importance": importance,
            "due_ms": data.TASK_DUE_2026_07_17_MS + day_off * 86400000,
            "notes": "noise task",
        }))
    cmds.append(_TASK_FORCE_STOP)
    return cmds


def tasks_completed_for_date_init() -> list[str]:
    """对齐 AW TasksCompletedTasksForDate：3 个固定任务 due 2026-07-17 且
    completed=2026-07-17 12:00 UTC（答案=3 标题）；噪声：due 同日未完成 5 条
    + 他日完成 5 条 + 他日未完成 10 条——均不污染 completed-07-17 视图。"""
    cmds = _task_clear()
    base = data.TASK_DUE_2026_07_17_MS
    completed_ms = base + 12 * 3600 * 1000  # 2026-07-17 12:00 UTC
    for t in data.TASKS_DUE_ON_DATE:
        cmds.append(_task_sqlite_insert(
            {**t, "due_ms": base, "completed_ms": completed_ms}))
    for i, (title, importance) in enumerate(_TASK_NOISE):
        if i < 5:
            row = {"title": title, "importance": importance,
                   "due_ms": base, "completed_ms": 0}
        elif i < 10:
            day_off = -(i - 4)  # -5..-1 天，完成日=其他日期（非 07-17）
            other = base + day_off * 86400000
            row = {"title": title, "importance": importance, "due_ms": other,
                   "completed_ms": other + 9 * 3600 * 1000}
        else:
            day_off = i - 9  # +1..+10 天
            row = {"title": title, "importance": importance,
                   "due_ms": base + day_off * 86400000, "completed_ms": 0}
        cmds.append(_task_sqlite_insert({**row, "notes": "noise task"}))
    cmds.append(_TASK_FORCE_STOP)
    return cmds


def tasks_due_next_week_init() -> list[str]:
    """对齐 AW TasksDueNextWeek：6 个固定任务 due 下一周（2023-10-16..21，
    答案=6）；噪声：本周（10-06..15）与再下周（10-23..11-01）各 10 条。"""
    cmds = _task_clear()
    for i, t in enumerate(data.TASKS_DUE_NEXT_WEEK):
        cmds.append(_task_sqlite_insert(
            {**t, "due_ms": data.TASK_NEXT_WEEK_START_MS + i * 86400000}))
    for i, (title, importance) in enumerate(_TASK_NOISE):
        if i < 10:
            due_ms = data.TASK_NEXT_WEEK_START_MS - (10 - i) * 86400000  # 10-06..10-15
        else:
            due_ms = data.TASK_NEXT_WEEK_START_MS + (7 + (i - 10)) * 86400000  # 10-23..11-01
        cmds.append(_task_sqlite_insert({
            "title": title, "importance": importance,
            "due_ms": due_ms, "notes": "noise task",
        }))
    cmds.append(_TASK_FORCE_STOP)
    return cmds


def tasks_high_priority_init() -> list[str]:
    """对齐 AW TasksHighPriorityTasks：3 个固定 importance=0 任务（答案=3 标题）
    + 20 个噪声任务（importance 1-3，AW 范围 0-3），force-stop 让 app 重读库。"""
    cmds = _task_clear()
    for t in data.TASKS_HIGH_PRIORITY:
        cmds.append(_task_sqlite_insert(
            {**t, "due_ms": data.TASK_NEXT_WEEK_START_MS + 86400000}))
    for i, (title, _imp) in enumerate(_TASK_NOISE):
        cmds.append(_task_sqlite_insert({
            "title": title, "importance": 1 + i % 3,
            "due_ms": data.TASK_DUE_2026_07_17_MS - (i + 1) * 86400000,
            "notes": "noise task",
        }))
    cmds.append(_TASK_FORCE_STOP)
    return cmds


def tasks_high_priority_due_on_date_init() -> list[str]:
    """对齐 AW TasksHighPriorityTasksDueOnDate：1 个固定 importance=0 任务
    due 2023-10-17 12:00 UTC（AW possible_values 日期，对齐 device 冻结时钟
    10-15；created=due-7h，答案=标题）+ 20 个噪声任务（due 偏离 ±1..10 天、
    importance 0-3——排除语义：不得同时满足 due==10-17 AND importance==0），
    force-stop 让 app 重读库。"""
    cmds = _task_clear()
    cmds.append(_task_sqlite_insert({
        **data.TASK_FINISH_REPORT,
        "due_ms": data.TASK_OCT17_2023_MS + 12 * 3600 * 1000}))  # 12:00pm（AW time 池）
    for i, (title, _imp) in enumerate(_TASK_NOISE):
        day_off = i - 10 if i < 10 else i - 9  # -10..-1, +1..+10，避开目标日
        cmds.append(_task_sqlite_insert({
            "title": title, "importance": i % 4,  # 0-3 随机池，对齐 AW
            "due_ms": data.TASK_OCT17_2023_MS + day_off * 86400000,
            "notes": "noise task",
        }))
    cmds.append(_TASK_FORCE_STOP)
    return cmds


def tasks_incomplete_tasks_on_date_init() -> list[str]:
    """对齐 AW TasksIncompleteTasksOnDate：3 个固定任务 due 2023-10-17
    （importance 1/2/0 各异，hideUntil 取 AW proto 原值 Oct 9/10/11 2023——
    早于 due 且早于 device 冻结时间 10-15，任务可见；notes 固定，均未完成，
    答案=3 标题）+ 20 个噪声任务（10 条晚于 10-17 未完成 + 10 条早于 10-17
    已完成——排除语义：due<=date AND completed=0 不同时满足），force-stop。"""
    cmds = _task_clear()
    base = data.TASK_OCT17_2023_MS
    # AW proto hide_until（"October 10 2023 8:00" / "October 9 2023 10:00" /
    # "October 11 2023 9:00"，device 冻结于 2023-10-15，均在过去→任务可见）
    hide_ms = [1696924800000, 1696845600000, 1697014800000]  # Oct 10 08:00 / Oct 9 10:00 / Oct 11 09:00 UTC
    for t, h in zip(data.TASKS_DUE_ON_DATE, hide_ms):
        cmds.append(_task_sqlite_insert({
            **t, "due_ms": base, "hide_ms": h}))
    for i, (title, importance) in enumerate(_TASK_NOISE):
        if i < 10:
            due_ms = base + (i + 1) * 86400000  # 晚于 2023-10-17，未完成
            row = {"title": title, "importance": importance,
                   "due_ms": due_ms, "completed_ms": 0}
        else:
            due_ms = base - (i - 9) * 86400000  # 早于 2023-10-17，已完成
            row = {"title": title, "importance": importance,
                   "due_ms": due_ms,
                   "completed_ms": due_ms + 3 * 3600 * 1000}
        cmds.append(_task_sqlite_insert({**row, "notes": "noise task"}))
    cmds.append(_TASK_FORCE_STOP)
    return cmds


# ═══════════════════════════════════════════════════════════
# OpenTracks — 7 cases
# ═══════════════════════════════════════════════════════════

DB_OPENTRACKS = data.DB_PATHS["opentracks"]


def opentracks_activities_init() -> list[str]:
    return [
        _ensure_db_launched("de.dennisguse.opentracks", data.DB_PATHS["opentracks"]),
        f"sqlite3 {DB_OPENTRACKS} \"DELETE FROM tracks;\" 2>/dev/null || echo 'db_cleared'",
    ]


# OpenTracks 固定种子（2023-10-09 ~ 10-15 周，对齐 AW exclusion 的 week 语义；
# 时间戳 = 毫秒，device 冻结于 2023-10-15 15:34 UTC）
_OT_DAY_EPOCH_MS = 1697328000 * 1000  # 2023-10-15 00:00 UTC


def _ot_day_ms(day: int) -> int:
    return _OT_DAY_EPOCH_MS + (day - 15) * 86400 * 1000


def _ot_insert(name: str, category: str, description: str,
               start_ms: int, duration_min: int, distance_m: int) -> str:
    """tracks 表 INSERT（对齐 AW SportsActivity 字段集：name/description/category/
    activity_type/totaldistance/starttime/stoptime/totaltime/movingtime/avgspeed/
    avgmovingspeed/elevationgain/elevationloss；avgspeed 由距离/时长推算）。"""
    stop_ms = start_ms + duration_min * 60000
    total_ms = stop_ms - start_ms
    avg_speed = round(distance_m / (total_ms / 1000.0), 6)
    return (
        f"sqlite3 {DB_OPENTRACKS} \"INSERT INTO tracks(name,description,category,"
        f"activity_type,starttime,stoptime,totaltime,movingtime,totaldistance,"
        f"avgspeed,avgmovingspeed,elevationgain,elevationloss) "
        f"VALUES('{name}','{description}','{category}','{category}',"
        f"{start_ms},{stop_ms},{total_ms},{total_ms},{distance_m},"
        f"{avg_speed},{avg_speed},0,0);\" "
        f"2>/dev/null || echo 'ot_insert_failed'"
    )


def _ot_restart() -> str:
    return "am force-stop de.dennisguse.opentracks 2>/dev/null || true"


def opentracks_activities_count_for_week_init() -> list[str]:
    """对齐 AW SportsTrackerActivitiesCountForWeek：week Mon 10-09 ~ Sun 10-15，
    2 条 Running（答案=2）；噪声：周内 Biking（错类）、周外 Running（错周）。"""
    cmds = opentracks_activities_init()
    cmds.append(_ot_insert("Morning Run", "Running", "5K run around the park",
                           _ot_day_ms(12) + 8 * 3600 * 1000, 30, 5000))
    cmds.append(_ot_insert("Evening Run", "Running", "Quick 3K jog after work",
                           _ot_day_ms(14) + 17 * 3600 * 1000, 20, 3000))
    cmds.append(_ot_insert("Bike Commute", "Biking", "Commute to office",
                           _ot_day_ms(11) + 9 * 3600 * 1000, 45, 12000))
    cmds.append(_ot_insert("Weekend Run", "Running", "Long run on the weekend",
                           _ot_day_ms(20) + 9 * 3600 * 1000, 60, 10000))
    cmds.append(_ot_restart())
    return cmds


def opentracks_activities_on_date_init() -> list[str]:
    """对齐 AW SportsTrackerActivitiesOnDate：2 条同日（10-12）不同类目
    （答案='Running, Biking'）；噪声在其他日期（AW exclusion：同日活动为 0）。"""
    cmds = opentracks_activities_init()
    cmds.append(_ot_insert("Morning Run", "Running", "5K run around the park",
                           _ot_day_ms(12) + 8 * 3600 * 1000, 30, 5000))
    cmds.append(_ot_insert("Bike Commute", "Biking", "Commute to office",
                           _ot_day_ms(12) + 17 * 3600 * 1000, 45, 12000))
    cmds.append(_ot_insert("Evening Run", "Running", "Quick 3K jog after work",
                           _ot_day_ms(14) + 17 * 3600 * 1000, 20, 3000))
    cmds.append(_ot_restart())
    return cmds


def opentracks_activity_duration_init() -> list[str]:
    """对齐 AW SportsTrackerActivityDuration：1 条 Running 在目标日期 10-12，
    时长 30 min（stoptime=starttime+30*60*1000，答案=30）；噪声：同日他类 +
    异日同类。"""
    cmds = opentracks_activities_init()
    cmds.append(_ot_insert("Morning Run", "Running", "5K run around the park",
                           _ot_day_ms(12) + 8 * 3600 * 1000, 30, 5000))
    cmds.append(_ot_insert("Bike Commute", "Biking", "Commute to office",
                           _ot_day_ms(12) + 17 * 3600 * 1000, 45, 12000))
    cmds.append(_ot_insert("Evening Run", "Running", "Quick 3K jog after work",
                           _ot_day_ms(14) + 17 * 3600 * 1000, 20, 3000))
    cmds.append(_ot_restart())
    return cmds


def opentracks_longest_distance_init() -> list[str]:
    """对齐 AW SportsTrackerLongestDistanceActivity：周内唯一较长 Running 距离
    X=5000（答案=5000）；噪声：周内 Biking 更长（错类）、周内 Running 更短
    （距离<X 允许）、周外 Running（错周）。"""
    cmds = opentracks_activities_init()
    cmds.append(_ot_insert("Morning Run", "Running", "5K run around the park",
                           _ot_day_ms(12) + 8 * 3600 * 1000, 30, 5000))
    cmds.append(_ot_insert("Bike Commute", "Biking", "Commute to office",
                           _ot_day_ms(11) + 9 * 3600 * 1000, 45, 12000))
    cmds.append(_ot_insert("Short Run", "Running", "Quick recovery jog",
                           _ot_day_ms(13) + 7 * 3600 * 1000, 15, 2000))
    cmds.append(_ot_insert("Weekend Run", "Running", "Long run on the weekend",
                           _ot_day_ms(20) + 9 * 3600 * 1000, 60, 10000))
    cmds.append(_ot_restart())
    return cmds


def opentracks_total_distance_init() -> list[str]:
    """对齐 AW SportsTrackerTotalDistanceForCategoryOverInterval：区间
    Oct 9 ~ Oct 15 内 2 条 Running（5000+3000=8000，答案=8000）；噪声：
    区间内 Biking（错类）、区间外 Running（错区间）。"""
    cmds = opentracks_activities_init()
    cmds.append(_ot_insert("Morning Run", "Running", "5K run around the park",
                           _ot_day_ms(12) + 8 * 3600 * 1000, 30, 5000))
    cmds.append(_ot_insert("Evening Run", "Running", "Quick 3K jog after work",
                           _ot_day_ms(14) + 17 * 3600 * 1000, 20, 3000))
    cmds.append(_ot_insert("Bike Commute", "Biking", "Commute to office",
                           _ot_day_ms(13) + 9 * 3600 * 1000, 45, 12000))
    cmds.append(_ot_insert("Weekend Run", "Running", "Long run on the weekend",
                           _ot_day_ms(20) + 9 * 3600 * 1000, 60, 10000))
    cmds.append(_ot_restart())
    return cmds


def opentracks_total_duration_init() -> list[str]:
    """对齐 AW SportsTrackerTotalDurationForCategoryThisWeek：week Mon 10-09 ~
    Sun 10-15 内 2 条 Running（30+20=50 min，stoptime=starttime+duration*60*1000，
    答案=50）；噪声：周内 Biking（错类）、周外 Running（错周）。"""
    cmds = opentracks_activities_init()
    cmds.append(_ot_insert("Morning Run", "Running", "5K run around the park",
                           _ot_day_ms(12) + 8 * 3600 * 1000, 30, 5000))
    cmds.append(_ot_insert("Evening Run", "Running", "Quick 3K jog after work",
                           _ot_day_ms(14) + 17 * 3600 * 1000, 20, 3000))
    cmds.append(_ot_insert("Bike Commute", "Biking", "Commute to office",
                           _ot_day_ms(11) + 9 * 3600 * 1000, 45, 12000))
    cmds.append(_ot_insert("Weekend Run", "Running", "Long run on the weekend",
                           _ot_day_ms(20) + 9 * 3600 * 1000, 60, 10000))
    cmds.append(_ot_restart())
    return cmds


# ═══════════════════════════════════════════════════════════
# Joplin Notes — 4 cases
# ═══════════════════════════════════════════════════════════

DB_JOPLIN = data.DB_PATHS["joplin"]


def joplin_clear_init() -> list[str]:
    """清空 joplin.sqlite 的 notes + notes_normalized（对齐 AW clear_dbs），
    然后 force-stop 让 Joplin 重新读库。"""
    return [
        _ensure_db_launched("net.cozic.joplin", data.DB_PATHS["joplin"]),
        "pm grant net.cozic.joplin android.permission.ACCESS_COARSE_LOCATION 2>/dev/null || true",
        "pm grant net.cozic.joplin android.permission.ACCESS_FINE_LOCATION 2>/dev/null || true",
        f"sqlite3 {DB_JOPLIN} \"DELETE FROM notes;\" 2>/dev/null || echo 'joplin_db_cleared'",
        f"sqlite3 {DB_JOPLIN} \"DELETE FROM notes_normalized;\" 2>/dev/null || echo 'joplin_db_cleared'",
        "am force-stop net.cozic.joplin 2>/dev/null || true",
    ]


def _joplin_clear() -> list[str]:
    """对齐 AW clear_dbs：清空 folders + notes + notes_normalized 三张表。"""
    return [
        _ensure_db_launched("net.cozic.joplin", data.DB_PATHS["joplin"]),
        "pm grant net.cozic.joplin android.permission.ACCESS_COARSE_LOCATION 2>/dev/null || true",
        "pm grant net.cozic.joplin android.permission.ACCESS_FINE_LOCATION 2>/dev/null || true",
        f"sqlite3 {DB_JOPLIN} \"DELETE FROM folders;\" 2>/dev/null || echo 'joplin_db_cleared'",
        f"sqlite3 {DB_JOPLIN} \"DELETE FROM notes;\" 2>/dev/null || echo 'joplin_db_cleared'",
        f"sqlite3 {DB_JOPLIN} \"DELETE FROM notes_normalized;\" 2>/dev/null || echo 'joplin_db_cleared'",
    ]


def _sql_literal(s: str) -> str:
    """SQLite 单引号字符串字面量：转义 ' 与换行（shell 双引号内 \\n 原样传给 sqlite3）。"""
    return s.replace("'", "''").replace("\n", "\\n")


def _joplin_insert_folder(fid: str, title: str) -> str:
    """对齐 AW _add_folders：插入 folders 行（固定 id/时间戳保证可重复）。"""
    ts = 1697385600000  # 2023-10-15，固定
    return (
        f"sqlite3 {DB_JOPLIN} \"INSERT INTO folders(id,title,created_time,updated_time,"
        f"user_created_time,user_updated_time,encryption_cipher_text,encryption_applied,"
        f"parent_id,is_shared,share_id,master_key_id,icon,user_data,deleted_time) "
        f"VALUES('{fid}','{_sql_literal(title)}',{ts},{ts},{ts},{ts},'',0,'',0,'','','','',0);\" "
        f"2>/dev/null || echo 'joplin_folder_inserted'"
    )


def _joplin_insert_note(note: dict, folder_id: str) -> list[str]:
    """对齐 AW create_note + add_notes：插入 notes + notes_normalized 两表。"""
    ts = 1697385600000  # 2023-10-15，固定
    nid = note["id"]
    title = _sql_literal(note["title"])
    body = _sql_literal(note["body"])
    is_todo = int(note.get("is_todo", 0))
    note_sql = (
        f"sqlite3 {DB_JOPLIN} \"INSERT INTO notes(id,parent_id,title,body,"
        f"created_time,updated_time,is_conflict,latitude,longitude,altitude,"
        f"author,source_url,is_todo,todo_due,todo_completed,source,"
        f"source_application,application_data,[order],user_created_time,"
        f"user_updated_time,encryption_cipher_text,encryption_applied,"
        f"markup_language,is_shared,share_id,conflict_original_id,"
        f"master_key_id,user_data,deleted_time) "
        f"VALUES('{nid}','{folder_id}','{title}','{body}',"
        f"{ts},{ts},0,0,0,0,'','',{is_todo},0,0,'','','',0,{ts},{ts},'',0,1,0,'','','','',0);\" "
        f"2>/dev/null || echo 'joplin_note_inserted'"
    )
    norm_sql = (
        f"sqlite3 {DB_JOPLIN} \"INSERT INTO notes_normalized(id,parent_id,title,body,"
        f"user_created_time,user_updated_time,is_todo,todo_completed,"
        f"latitude,longitude,altitude,source_url,todo_due) "
        f"VALUES('{nid}','{folder_id}','{title}','{body}',"
        f"{ts},{ts},{is_todo},0,0,0,0,'',0);\" "
        f"2>/dev/null || echo 'joplin_note_normalized_inserted'"
    )
    return [note_sql, norm_sql]


# 固定 id（hex 风格，跨 case 唯一）——数据固化原则，保证可重复
_JOPLIN_NOTE_ID_KAM = "f0000000000000000000000000000002"
_JOPLIN_NOTE_ID_DYT = "f0000000000000000000000000000004"
_JOPLIN_NOTE_ID_GAE = "f0000000000000000000000000000005"
_JOPLIN_NOTE_ID_TODO1 = "f0000000000000000000000000000006"
_JOPLIN_NOTE_ID_TODO2 = "f0000000000000000000000000000007"
_JOPLIN_NOTE_ID_TODO3 = "f0000000000000000000000000000008"

_JOPLIN_FOLDER_IDS: dict[str, str] = {
    "Recipes": "f0000000000000000000000000000001",
    "Meeting Notes": "f0000000000000000000000000000003",
    "Personal": "f0000000000000000000000000000100",
    "Work": "f0000000000000000000000000000101",
    "Projects": "f0000000000000000000000000000102",
    "School": "f0000000000000000000000000000103",
    "Travel": "f0000000000000000000000000000104",
    "Finance": "f0000000000000000000000000000105",
    "Health": "f0000000000000000000000000000106",
}


# Joplin 噪声笔记池（确定性；标题/正文取自 AW tasks proto 的 possible_values 池；
# is_todo 混合，但排除 (is_todo=1 AND folder=Personal)——对齐 AW exclusion_conditions，
# 不会干扰 NotesTodoItemCount 的计数）
_JOPLIN_NOISE_NOTES = [
    {"id": "f0000000000000000000000000000010", "title": "Grocery List",
     "folder": "Personal", "is_todo": 0,
     "body": "Buy milk, eggs, bread, and cereal from the grocery store."},
    {"id": "f0000000000000000000000000000011", "title": "Meeting Agenda",
     "folder": "Work", "is_todo": 0,
     "body": "Meeting with client at 2 PM to discuss project requirements."},
    {"id": "f0000000000000000000000000000012", "title": "Project Proposal",
     "folder": "Projects", "is_todo": 0,
     "body": "Finish presentation slides for the team meeting tomorrow."},
    {"id": "f0000000000000000000000000000013", "title": "Daily Journal",
     "folder": "Personal", "is_todo": 0,
     "body": "Write thank you cards for colleagues who helped with the project."},
    {"id": "f0000000000000000000000000000014", "title": "To-Do List",
     "folder": "Work", "is_todo": 1,
     "body": "Pick up dry cleaning from the tailor on Main Street."},
    {"id": "f0000000000000000000000000000015", "title": "Research Notes",
     "folder": "School", "is_todo": 0,
     "body": "Review chapter 5 for the upcoming history exam."},
    {"id": "f0000000000000000000000000000016", "title": "Travel Itinerary",
     "folder": "Travel", "is_todo": 0,
     "body": "Book flight tickets for vacation next month."},
    {"id": "f0000000000000000000000000000017", "title": "Recipe Collection",
     "folder": "Recipes", "is_todo": 0,
     "body": "Try a new pasta recipe with homemade sauce and garlic bread."},
    {"id": "f0000000000000000000000000000018", "title": "Budget Spreadsheet",
     "folder": "Finance", "is_todo": 0,
     "body": "Create a monthly budget, track expenses, and set savings goals."},
    {"id": "f0000000000000000000000000000019", "title": "Training Manual",
     "folder": "Health", "is_todo": 0,
     "body": "Go for a 30-minute run, do yoga for flexibility, and meditate for relaxation."},
]


def _joplin_seed_notes(notes: list[dict]) -> list[str]:
    """插入 folders（去重）+ notes/notes_normalized 两表，返回命令列表。"""
    cmds = []
    for folder in dict.fromkeys(n["folder"] for n in notes):
        cmds.append(_joplin_insert_folder(_JOPLIN_FOLDER_IDS[folder], folder))
    for n in notes:
        cmds += _joplin_insert_note(n, _JOPLIN_FOLDER_IDS[n["folder"]])
    return cmds


def notes_is_todo_init() -> list[str]:
    """对齐 AW setup_task_state：清空 + 目标笔记（'Test Recipe kam', is_todo=0）
    + 10 条噪声笔记，然后 force-stop 让 Joplin 重新读取 DB。"""
    cmds = _joplin_clear()
    cmds += _joplin_seed_notes(
        [dict(data.JOPLIN_RECIPE_NOTE, id=_JOPLIN_NOTE_ID_KAM)] + _JOPLIN_NOISE_NOTES)
    cmds.append("am force-stop net.cozic.joplin 2>/dev/null || true")
    return cmds


def notes_meeting_attendee_count_init() -> list[str]:
    """对齐 AW setup_task_state：清空 + 会议笔记（'Test Recipe dyt', body 含
    5 attendees）+ 10 条噪声笔记，然后 force-stop。"""
    cmds = _joplin_clear()
    cmds += _joplin_seed_notes(
        [dict(data.JOPLIN_MEETING_NOTE, id=_JOPLIN_NOTE_ID_DYT)] + _JOPLIN_NOISE_NOTES)
    cmds.append("am force-stop net.cozic.joplin 2>/dev/null || true")
    return cmds


def notes_recipe_ingredient_count_init() -> list[str]:
    """对齐 AW setup_task_state：清空 + 食谱笔记（'Test Recipe gae', body 含
    '3 tablespoons salt'）+ 10 条噪声笔记，然后 force-stop。"""
    cmds = _joplin_clear()
    cmds += _joplin_seed_notes(
        [dict(data.JOPLIN_RECIPE_GAE, id=_JOPLIN_NOTE_ID_GAE)] + _JOPLIN_NOISE_NOTES)
    cmds.append("am force-stop net.cozic.joplin 2>/dev/null || true")
    return cmds


def notes_todo_item_count_init() -> list[str]:
    """对齐 AW NotesTodoItemCount relevant_state：清空 + 'Personal' 文件夹 +
    3 个 is_todo=1 笔记 + 10 条噪声笔记（Personal 中无其他 to-do），然后 force-stop。"""
    cmds = _joplin_clear()
    todo_notes = [dict(data.JOPLIN_TODO_NOTE, id=_JOPLIN_NOTE_ID_TODO1),
                  dict(data.JOPLIN_TODO_NOTE_2, id=_JOPLIN_NOTE_ID_TODO2),
                  dict(data.JOPLIN_TODO_NOTE_3, id=_JOPLIN_NOTE_ID_TODO3)]
    cmds += _joplin_seed_notes(todo_notes + _JOPLIN_NOISE_NOTES)
    cmds.append("am force-stop net.cozic.joplin 2>/dev/null || true")
    return cmds


# ═══════════════════════════════════════════════════════════
# OsmAnd — 3 cases
# ═══════════════════════════════════════════════════════════

DB_OSMAND = data.DB_PATHS["osmand_markers"]


# OsmAnd init — 对齐 AW: favorite→GPX, marker→SQLite, track→GPX
OSMAND_FILES = "/storage/emulated/0/Android/data/net.osmand/files"


def osmand_favorite_init() -> list[str]:
    """清理 favorites.gpx 中所有 waypoint（对齐 AW _clear_favorites）。"""
    return [
        # 删除 favorites.gpx 中的 waypoint（简化：直接删除文件让 OsmAnd 重建）
        f"rm -f {OSMAND_FILES}/favorites/favorites.gpx 2>/dev/null || true",
    ]


def osmand_marker_init() -> list[str]:
    """清空 map_markers 表（对齐 AW SQLiteApp.initialize_task）+ force-stop 重载。"""
    return [
        f"sqlite3 {DB_OSMAND} \"DELETE FROM map_markers;\" 2>/dev/null || echo 'osmand_cleared'",
        "am force-stop net.osmand 2>/dev/null || true",
    ]


def osmand_track_init() -> list[str]:
    """清除 track 文件（对齐 AW _clear_tracks: rm -rf tracks/*）。"""
    return [
        f"rm -rf {OSMAND_FILES}/tracks/* 2>/dev/null || true",
    ]


# ═══════════════════════════════════════════════════════════
# Markor — complete all remaining 12 cases
# ═══════════════════════════════════════════════════════════

def _markor_grant() -> str:
    return "pm grant net.gsantner.markor android.permission.WRITE_EXTERNAL_STORAGE 2>/dev/null || true"


def markor_add_note_header_init() -> list[str]:
    return [
        _markor_grant(),
        "mkdir -p /sdcard/Documents/Markor",
        # 防止上一次运行残留的同名新文件干扰验证
        f"rm -f /sdcard/Documents/Markor/{data.MARKOR_NOTE_HEADER['new_name']} 2>/dev/null || true",
        f"echo '{data.MARKOR_NOTE_HEADER['text']}' > /sdcard/Documents/Markor/{data.MARKOR_NOTE_HEADER['file_name']}",
    ]


def markor_change_note_content_init() -> list[str]:
    return [
        _markor_grant(),
        "mkdir -p /sdcard/Documents/Markor",
        f"rm -f /sdcard/Documents/Markor/{data.MARKOR_NOTE_CHANGE['new_name']} 2>/dev/null || true",
        f"echo '{data.MARKOR_NOTE_CHANGE['text']}' > /sdcard/Documents/Markor/{data.MARKOR_NOTE_CHANGE['file_name']}",
    ]


def markor_create_folder_init() -> list[str]:
    return [
        _markor_grant(),
        "mkdir -p /sdcard/Documents/Markor",
        "rm -rf /sdcard/Documents/Markor/folder_dip 2>/dev/null || true",
    ]


def markor_create_note_and_sms_init() -> list[str]:
    return [
        _markor_grant(),
        "mkdir -p /sdcard/Documents/Markor",
        f"rm -f /sdcard/Documents/Markor/{data.MARKOR_NOTE_AND_SMS['file_name']} 2>/dev/null || true",
        "content delete --uri content://sms 2>/dev/null || true",
    ]


def markor_create_note_from_clipboard_init() -> list[str]:
    """预置剪贴板内容（对齐 AW adb_utils.set_clipboard_contents：clipper.set 广播）。"""
    return [
        _markor_grant(),
        "mkdir -p /sdcard/Documents/Markor",
        "pm grant ca.zgrs.clipper android.permission.READ_EXTERNAL_STORAGE 2>/dev/null || true",
        f"rm -f /sdcard/Documents/Markor/{data.MARKOR_CLIPBOARD['file_name']} 2>/dev/null || true",
        f"am broadcast -a clipper.set -e text '{data.MARKOR_CLIPBOARD['text']}' 2>/dev/null || true",
    ]


def markor_delete_all_notes_init() -> list[str]:
    """创建几个噪声文件供全部删除。"""
    cmds = [_markor_grant(), "mkdir -p /sdcard/Documents/Markor"]
    for i in range(5):
        cmds.append(
            f"echo 'noise content {i}' > /sdcard/Documents/Markor/noise_note_{i}.md"
        )
    return cmds


def markor_delete_newest_note_init() -> list[str]:
    cmds = [_markor_grant(), "mkdir -p /sdcard/Documents/Markor",
            "rm -rf /sdcard/Documents/Markor/* 2>/dev/null || true"]  # 对齐 AW clear_directory
    for i in range(4):
        cmds.append(
            f"echo 'random content {i}' > /sdcard/Documents/Markor/old_note_{i}.md"
        )
        cmds.append("sleep 0.2")  # 确保时间戳不同
    return cmds


def markor_delete_note_init() -> list[str]:
    return [
        _markor_grant(),
        "mkdir -p /sdcard/Documents/Markor",
        f"echo 'content to delete' > /sdcard/Documents/Markor/{data.MARKOR_NOTE_DELETE['file_name']}",
    ]


def markor_edit_note_init() -> list[str]:
    e = data.MARKOR_NOTE_EDIT
    return [
        _markor_grant(),
        "mkdir -p /sdcard/Documents/Markor",
        f"echo '{e['text']}' > /sdcard/Documents/Markor/{e['file_name']}",
    ]


def markor_merge_notes_init() -> list[str]:
    return [
        _markor_grant(),
        "mkdir -p /sdcard/Documents/Markor",
        # 防止上一次运行残留 merged_notes.md（对齐 AW clear_directory）
        "rm -rf /sdcard/Documents/Markor/* 2>/dev/null || true",
        f"echo '{data.MARKOR_NOTE_MERGE_1['text']}' > /sdcard/Documents/Markor/{data.MARKOR_NOTE_MERGE_1['file_name']}",
        f"echo '{data.MARKOR_NOTE_MERGE_2['text']}' > /sdcard/Documents/Markor/{data.MARKOR_NOTE_MERGE_2['file_name']}",
        f"echo '{data.MARKOR_NOTE_MERGE_3['text']}' > /sdcard/Documents/Markor/{data.MARKOR_NOTE_MERGE_3['file_name']}",
    ]


def markor_move_note_init() -> list[str]:
    """对齐 AW MoveFile：源文件写在 /sdcard/Documents/{file_name}（goal 的
    source_folder='Documents' 即 /sdcard/Documents），Markor 数据目录
    /sdcard/Documents/Markor 不含该文件（目标为空）。"""
    m = data.MARKOR_NOTE_MOVE
    return [
        _markor_grant(),
        "mkdir -p /sdcard/Documents",
        f"rm -f /sdcard/Documents/Markor/{m['file_name']} 2>/dev/null || true",
        f"echo '{m['text']}' > /sdcard/Documents/{m['file_name']}",
    ]


def markor_transcribe_receipt_init() -> list[str]:
    """生成真实固定小票 PNG（对齐 AW receipt_generator：公司名/表头/交易行），
    落到宿主 fastaget/meta/assets/，adb push 到 /sdcard/DCIM/receipt.png。"""
    rows = [f"{d}, {item}, {amt}" for d, item, amt in data.RECEIPT["transactions"]]
    text = "\n".join(["Tech Gadgets Inc.", "Innovating the Future",
                      data.RECEIPT["header"]] + rows)
    return [
        _markor_grant(),
        "mkdir -p /sdcard/Documents/Markor /sdcard/DCIM 2>/dev/null || true",
        "rm -f /sdcard/DCIM/receipt.png 2>/dev/null || true",
        _render_image_asset(text, "aw_receipt.png", f"/sdcard/DCIM/{data.RECEIPT['img_file']}"),
    ]


def _video_mp4_asset(messages: list[str], local_name: str, device_path: str) -> str:
    """用 OpenCV 生成真实 mp4（每段文字显示 5 秒，对齐 AW write_video_file_to_device），
    落到宿主 fastaget/meta/assets/，返回 host 侧 adb push 命令。"""
    from pathlib import Path
    import cv2
    import numpy as np
    local_dir = Path(__file__).resolve().parent.parent.parent / _ASSET_DIR
    local_dir.mkdir(parents=True, exist_ok=True)
    out_path = local_dir / local_name
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(out_path), fourcc, 10, (320, 240))
    frames_per_message = 10 * 5  # 10fps * 5s
    for message in messages:
        for _ in range(frames_per_message):
            frame = np.full((240, 320, 3), 25, dtype=np.uint8)  # 深色底，文字醒目
            cv2.putText(frame, message, (60, 120), cv2.FONT_HERSHEY_SIMPLEX,
                        1.2, (0, 255, 255), 2, cv2.LINE_AA)
            out.write(frame)
    out.release()
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(
            "Video generation failed — is opencv-python (cv2) installed on the host?"
        )
    return f"adb push {_ASSET_DIR}/{local_name} {device_path}"


def markor_transcribe_video_init() -> list[str]:
    """生成真实固定 mp4（帧上显示 3 个已知字符串），push 到 /sdcard/Download/。"""
    v = data.MARKOR_VIDEO
    return [
        _markor_grant(),
        "mkdir -p /sdcard/Documents/Markor /sdcard/Download 2>/dev/null || true",
        f"rm -f /sdcard/Download/{v['video_name']} 2>/dev/null || true",
        # 防止上一次运行残留目标笔记（对齐 AW clear_directory）
        f"rm -f /sdcard/Documents/Markor/{v['file_name']} 2>/dev/null || true",
        _video_mp4_asset(v["messages"], v["video_name"],
                         f"/sdcard/Download/{v['video_name']}"),
    ]


# ═══════════════════════════════════════════════════════════
# Browser — 3 cases
# ═══════════════════════════════════════════════════════════
# 对齐 AW BrowserTask.initialize_task：task.html 必须是 AW 原版完整 HTML
# （含任务 JS 逻辑），占位 HTML 无法产出 'Success!' 结果。
# 写入路径：宿主 assets → adb push（run_eval 对 `adb ` 前缀走 host 侧执行）

_ASSET_DIR = "fastaget/meta/assets"


def _write_text_asset(text: str, local_name: str, device_path: str) -> str:
    """把文本写到宿主 fastaget/meta/assets/，返回 host 侧 adb push 命令。"""
    from pathlib import Path
    local_dir = Path(__file__).resolve().parent.parent.parent / _ASSET_DIR
    local_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / local_name).write_text(text, encoding="utf-8")
    return f"adb push {_ASSET_DIR}/{local_name} {device_path}"


def _browser_html_init(html: str, local_name: str) -> list[str]:
    """把 AW 原版 HTML（%%SEED%% → data.BROWSER_SEED）推送到 /sdcard/Download/task.html。"""
    html = html.replace("%%SEED%%", str(data.BROWSER_SEED))
    return [
        "mkdir -p /sdcard/Download 2>/dev/null || true",
        _write_text_asset(html, local_name, f"/sdcard/Download/{data.BROWSER_HTML_FILE}"),
    ]


def browser_draw_init() -> list[str]:
    return _browser_html_init(data.BROWSER_HTML_DRAW, "aw_browser_draw.html")


def browser_maze_init() -> list[str]:
    return _browser_html_init(data.BROWSER_HTML_MAZE, "aw_browser_maze.html")


def browser_multiply_init() -> list[str]:
    return _browser_html_init(data.BROWSER_HTML_MULTIPLY, "aw_browser_multiply.html")


# ═══════════════════════════════════════════════════════════
# Audio Recorder — 2 cases
# ═══════════════════════════════════════════════════════════


def audio_recorder_record_init() -> list[str]:
    return [
        f"rm -rf {data.AUDIO_RECORDING['dir']}/* 2>/dev/null || true",
        f"mkdir -p {data.AUDIO_RECORDING['dir']}",
    ]


def audio_recorder_record_with_name_init() -> list[str]:
    return audio_recorder_record_init()


# ═══════════════════════════════════════════════════════════
# Simple Draw / Simple Gallery — 2 cases
# ═══════════════════════════════════════════════════════════


def simple_draw_create_drawing_init() -> list[str]:
    return [
        "mkdir -p /sdcard/Pictures",
        "rm -f /sdcard/Pictures/*.png 2>/dev/null || true",
    ]


def _receipt_image_text() -> str:
    """收据样式的固定文本（渲染成真实 JPEG 后 Simple Gallery Pro 可显示）。"""
    return (
        "Corner Market\n"
        "123 Main Street\n"
        "----------------------------\n"
        "Item          Qty    Price\n"
        "Milk            1   $3.50\n"
        "Bread           1   $2.25\n"
        "Eggs (dozen)    1   $4.00\n"
        "Coffee beans    1   $9.75\n"
        "----------------------------\n"
        "Subtotal            $19.50\n"
        "Tax                 $1.56\n"
        "TOTAL               $21.06\n"
        "Thank you for shopping!"
    )


def save_copy_init() -> list[str]:
    """对齐 AW SaveCopyOfReceiptTaskEval.initialize_task：先清 Download 残留
    （防上一轮 agent 复制产物满足 verify 的假阳性），再在 DCIM 放真实收据图片
    （.jpg，Simple Gallery Pro 可显示）。原 seed 是 .md 文本——图片 App 无法
    显示，任务经 UI 不可达。"""
    fname = data.SIMPLE_GALLERY_COPY["file_name"]
    return [
        "mkdir -p /sdcard/DCIM /sdcard/Download",
        f"rm -f /sdcard/Download/{fname} 2>/dev/null || true",
        _render_image_asset(
            _receipt_image_text(), "aw_receipt_ewvv.jpg",
            f"/sdcard/DCIM/{fname}"),
    ]


def save_copy_of_receipt_init() -> list[str]:
    return save_copy_init()


# ═══════════════════════════════════════════════════════════
# SMS — remaining cases
# ═══════════════════════════════════════════════════════════


def sms_reply_most_recent_init() -> list[str]:
    """对齐 AW SimpleSmsReplyMostRecent.initialize_task：收件箱只有非目标正文的
    消息，最后一条来自 5550100 且正文 ≠ goal message（agent 的回复目标）；
    'Hello from automated test' 只作为 agent 要发送的回复正文，绝不出现在 inbox。"""
    return [
        "cmd connectivity airplane-mode disable 2>/dev/null || true",
        _sms_clear(),
        "adb emu sms send 5550100 'Previous test message 1' 2>/dev/null || true",
        # AW sms.py:85-87：短信不保证按发送顺序入箱——每条之间 sleep 5 确保
        # 最后一条（5550100）稳定成为 most recent，否则 agent 会回复错对象
        "sleep 5",
        "adb emu sms send 7770200 'Another message' 2>/dev/null || true",
        "sleep 5",
        "adb emu sms send 5550100 'Another message' 2>/dev/null || true",
        "sleep 5",
    ]


def sms_send_clipboard_content_init() -> list[str]:
    """对齐 AW SimpleSmsSendClipboardContent.initialize_task（set_clipboard_contents
    走 Clipper：launch + clipper.set 广播，与 markor_create_note_from_clipboard_init 同机制）。"""
    return [
        "cmd connectivity airplane-mode disable 2>/dev/null || true",
        _sms_clear(),
        "pm grant ca.zgrs.clipper android.permission.READ_EXTERNAL_STORAGE 2>/dev/null || true",
        f"am broadcast -a clipper.set -e text '{data.SMS_HELLO['message']}' 2>/dev/null || true",
    ]


def sms_send_received_address_init() -> list[str]:
    """对齐 AW SimpleSmsSendReceivedAddress.initialize_task：Alice Smith->555-0100、
    Bob Jones->555-0200 两个联系人 + Bob（555-0200）发来的地址短信。"""
    return [
        "cmd connectivity airplane-mode disable 2>/dev/null || true",
        _sms_clear(),
        *_contact_inserts([data.CONTACT_ALICE, data.CONTACT_BOB]),
        f"adb emu sms send 5550200 '{data.SMS_RECEIVED_ADDRESS}' 2>/dev/null || true",
        "sleep 0.5",
    ]


_MMS_DB = "/data/data/com.android.providers.telephony/databases/mmssms.db"
# 固定 thread_id（2023-10-15 18:00 UTC 毫秒，device 冻结时间之后），保证可重复
_SMS_THREAD_ID = 1697392800000


def _sms_clear() -> str:
    """对齐 AW clear_sms_and_threads：sqlite 直清 sms/threads/canonical_addresses 三表。
    （content delete 本镜像对 sms/sent 的 insert 静默失败，seed 必须走 sqlite。）"""
    return (
        f"sqlite3 {_MMS_DB} \"DELETE FROM sms; DELETE FROM threads; "
        f"DELETE FROM canonical_addresses;\" 2>/dev/null || true"
    )


def _sms_sent_insert(address: str, body: str) -> str:
    """向 mmssms.db 插入一条已发送消息（type=2，等价 content://sms/sent 写入）：
    canonical_addresses(_id=1) + threads + sms 三行，App 可见（AW 文档明确
    Simple SMS Messenger 对 sqlite 直写即时同步）。"""
    body_esc = body.replace("'", "''")
    return (
        f"sqlite3 {_MMS_DB} \"INSERT OR REPLACE INTO canonical_addresses(_id,address) "
        f"VALUES(1,'{address}'); "
        f"INSERT INTO threads(_id,date,message_count,recipient_ids,snippet,snippet_cs,"
        f"read,archived,type,error,has_attachment) "
        f"VALUES({_SMS_THREAD_ID},{_SMS_THREAD_ID},1,1,'{body_esc}',1,1,0,1,0,0); "
        f"INSERT INTO sms(thread_id,address,date,date_sent,protocol,read,status,type,"
        f"reply_path_present,subject,body,service_center,locked,error_code,sub_id) "
        f"VALUES({_SMS_THREAD_ID},'{address}',{_SMS_THREAD_ID},{_SMS_THREAD_ID},"
        f"0,1,-1,2,0,NULL,'{body_esc}',NULL,0,0,1);\" "
        f"2>/dev/null || echo 'sms_seed_failed'"
    )


def sms_resend_init() -> list[str]:
    """对齐 AW SimpleSmsResend.initialize_task：已发出的 'init test message' 在
    content://sms/sent（sqlite 直写）+ Alice Smith->555-0100 联系人 +
    对方请求重发的提示短信（inbox，同线程）。agent 重发后 SENT 中应有 2 条。"""
    return [
        "cmd connectivity airplane-mode disable 2>/dev/null || true",
        _sms_clear(),
        _sms_sent_insert(data.CONTACT_ALICE["number"].replace("-", ""), data.SMS_RESEND_MESSAGE),
        *_contact_inserts([data.CONTACT_ALICE]),
        f"adb emu sms send 5550100 '{data.SMS_RESEND_PROMPT}' 2>/dev/null || true",
        "sleep 0.5",
    ]


# ═══════════════════════════════════════════════════════════
# Clock — 2 remaining cases
# ═══════════════════════════════════════════════════════════


def clock_stopwatch_running_init() -> list[str]:
    return ["pm clear com.google.android.deskclock 2>/dev/null || true"]


def clock_timer_entry_init() -> list[str]:
    return ["pm clear com.google.android.deskclock 2>/dev/null || true"]


# ═══════════════════════════════════════════════════════════
# Composite tasks
# ═══════════════════════════════════════════════════════════


def turn_off_wifi_turn_on_bluetooth_init() -> list[str]:
    return [
        "svc wifi enable",
        "svc bluetooth disable",
    ]


def turn_on_wifi_and_open_app_init() -> list[str]:
    return ["svc wifi disable"]


# ═══════════════════════════════════════════════════════════
# OpenApp
# ═══════════════════════════════════════════════════════════


def open_app_init() -> list[str]:
    return [
        "pm grant com.android.settings android.permission.ACCESS_COARSE_LOCATION 2>/dev/null || true",
    ]


# ═══════════════════════════════════════════════════════════
# Simple Calendar — add remaining query/info retrieval inits
# ═══════════════════════════════════════════════════════════
# (already covered above in calendar_* functions)
