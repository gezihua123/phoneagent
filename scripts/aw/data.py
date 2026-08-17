"""固定测试数据——从 AndroidWorld schema 提取，用固定种子保证可重复。

AndroidWorld 每次 run 用 random.seed(params.seed) 随机生成数据。
fastaget 改用预先确定的固定值，写入 YAML goal/init/verify——零运行时随机。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

# ═══════════════════════════════════════════════════════════
# SQLite 数据库路径常量
# ═══════════════════════════════════════════════════════════

DB_PATHS: dict[str, str] = {
    "broccoli": "/data/data/com.flauschcode.broccoli/databases/broccoli",
    "expense": "/data/data/com.arduia.expense/databases/accounting.db",
    "calendar": "/data/data/com.simplemobiletools.calendar.pro/databases/events.db",  # SimpleCalendar
    "tasks": "/data/data/org.tasks/databases/database",
    "opentracks": "/data/data/de.dennisguse.opentracks/databases/database.db",
    "joplin": "/data/data/net.cozic.joplin/databases/joplin.sqlite",
    "retro_playlist": "/data/data/code.name.monkey.retromusic/databases/playlist.db",
    "retro_playback": "/data/data/code.name.monkey.retromusic/databases/music_playback_state.db",
    "vlc": "/data/data/org.videolan.vlc/app_db/vlc_media.db",
    "osmand_markers": "/data/data/net.osmand/databases/map_markers_db",
}


# ═══════════════════════════════════════════════════════════
# Recipe (Broccoli) — fixed recipes from AndroidWorld _RECIPES
# ═══════════════════════════════════════════════════════════

RECIPE_SPICY_TUNA = {
    "title": "Spicy Tuna Wraps",
    "description": "A quick and easy meal, perfect for busy weekdays.",
    "servings": "2 servings",
    "preparationTime": "20 mins",
    "source": "",
    "ingredients": "varies",
    "directions": (
        "Mix canned tuna with mayo and sriracha. Spread on tortillas, add "
        "lettuce and cucumber slices, roll up. "
        "Try adding a pinch of your favorite spices for extra flavor."
    ),
    "favorite": 0,
}

RECIPE_AVOCADO_TOAST = {
    "title": "Avocado Toast with Egg",
    "description": "A delicious and healthy choice for any time of the day.",
    "servings": "1 serving",
    "preparationTime": "10 mins",
    "source": "",
    "ingredients": "as per recipe",
    "directions": (
        "Toast bread, top with mashed avocado, a fried egg, salt, pepper, "
        "and chili flakes. "
        "Garnish with fresh herbs for a more vibrant taste."
    ),
    "favorite": 0,
}

RECIPE_GREEK_SALAD = {
    "title": "Greek Salad Pita Pockets",
    "description": "An ideal recipe for experimenting with different flavors and ingredients.",
    "servings": "3-4 servings",
    "preparationTime": "30 mins",
    "source": "",
    "ingredients": "to preference",
    "directions": (
        "Fill pita pockets with lettuce, cucumber, tomato, feta, olives, "
        "and Greek dressing. "
        "Feel free to substitute with ingredients you have on hand."
    ),
    "favorite": 0,
}


# ═══════════════════════════════════════════════════════════
# Expense (Pro Expense) — fixed expenses
# ═══════════════════════════════════════════════════════════

EXPENSE_LUNCH = {
    "name": "Lunch",
    "amount": 1550,       # $15.50 in cents
    "category": 3,        # Food
    "note": "Team lunch",
}

EXPENSE_COFFEE = {
    "name": "Coffee",
    "amount": 400,        # $4.00 in cents
    "category": 3,        # Food (AW category_id_to_name: 3=Food)
    "note": "Morning coffee",
}

EXPENSE_TAXI = {
    "name": "Taxi Ride",
    "amount": 2500,       # $25.00 in cents
    "category": 7,        # Transportation
    "note": "Airport transfer",
}

# ExpenseDeleteDuplicates2 目标变体扰动金额（cents）——对齐 AW
# random.sample(range(50, 1000), 3)：同 name=Lunch，amount=1550+扰动，独立时间戳
EXPENSE_DUP_PERTURBATIONS = [50, 500, 950]


# ═══════════════════════════════════════════════════════════
# Contact — fixed contact details
# ═══════════════════════════════════════════════════════════

CONTACT_ALICE = {"name": "Alice Smith", "number": "555-0100"}
CONTACT_BOB = {"name": "Bob Jones", "number": "555-0200"}


# ═══════════════════════════════════════════════════════════
# SMS — fixed message
# ═══════════════════════════════════════════════════════════

SMS_HELLO = {"number": "555-0100", "message": "Hello from automated test"}

# SimpleSmsSendReceivedAddress：AW addresses[0]（Bob Jones 发来的地址，
# agent 须转发给 Alice Smith）
SMS_RECEIVED_ADDRESS = "123 Main St Girdwood, AK, 99587"

# SimpleSmsResend：init 预置在 content://sms/sent 的"我刚刚发出的消息"
# （agent 重发后 SENT 中恰有 2 条），以及对方请求重发的提示消息（AW 原文）
SMS_RESEND_MESSAGE = "init test message"
SMS_RESEND_PROMPT = "Sorry, there was a glitch, what was the last message you sent me?"


# ═══════════════════════════════════════════════════════════
# Calendar Event — using AndroidWorld DT = Oct 15 2023 15:34 UTC
# ═══════════════════════════════════════════════════════════

CALENDAR_EVENT_MEETING = {
    "title": "Test Meeting",
    "description": "Automated test event",
    "location": "Conference Room A",
    "start_ts": 1697385600,   # 2023-10-15 16:00 UTC
    "end_ts": 1697389200,     # 2023-10-15 17:00 UTC (1 hour)
}


# ═══════════════════════════════════════════════════════════
# Task (Tasks app)
# ═══════════════════════════════════════════════════════════

TASK_BUY_GROCERIES = {
    "title": "Buy groceries",
    "importance": 0,  # high priority
    "notes": "Milk, eggs, bread, butter",
}


# ═══════════════════════════════════════════════════════════
# Markor notes
# ═══════════════════════════════════════════════════════════

MARKOR_NOTE = {
    "file_name": "test_note.md",
    "text": "hello world automated test",
}


# ═══════════════════════════════════════════════════════════
# File operations
# ═══════════════════════════════════════════════════════════

FILE_DELETE = {
    "file_name": "test_note_opit.md",
    "subfolder": "Download",
}

FILE_MOVE = {
    "file_name": "test_note_vjcs.md",
    "source_folder": "Documents",
    "destination_folder": "Markor",
}


# ═══════════════════════════════════════════════════════════
# System settings
# ═══════════════════════════════════════════════════════════

SYS_BLUETOOTH_ON = {"desired": "1"}       # bluetooth_on=1
SYS_BLUETOOTH_OFF = {"desired": "0"}
SYS_WIFI_ON = {"desired": "1|2"}          # wifi_on=1 or 2
SYS_WIFI_OFF = {"desired": "0"}
SYS_BRIGHTNESS_MAX = {"desired": "255"}
SYS_BRIGHTNESS_MIN = {"desired": "1"}

# SystemCopyToClipboard：固定剪贴板文本（对齐 AW clipboard_content 池取值；
# goal 与 verify 共用，init 把剪贴板重置为哨兵值）
SYS_CLIPBOARD_CONTENT = "test clipboard content"


# ═══════════════════════════════════════════════════════════
# Recipe variants (noise rows for delete tasks)
# ═══════════════════════════════════════════════════════════

RECIPE_CHOCOLATE_CAKE = {
    "title": "Chocolate Cake",
    "description": "A rich and moist chocolate cake for special occasions.",
    "servings": "8 servings",
    "preparationTime": "45 mins",
    "source": "",
    "ingredients": "flour, cocoa, sugar, eggs, butter",
    "directions": "Mix dry ingredients. Add wet ingredients. Bake at 350F for 30 mins.",
    "favorite": 0,
}

RECIPE_CHICKEN_SOUP = {
    "title": "Chicken Soup",
    "description": "A hearty soup perfect for cold winter days.",
    "servings": "6 servings",
    "preparationTime": "60 mins",
    "source": "",
    "ingredients": "chicken, carrots, celery, onion, broth",
    "directions": "Boil chicken, add vegetables, simmer for 45 mins. Add salt to taste.",
    "favorite": 0,
}

RECIPE_PASTA_PRIMAVERA = {
    "title": "Pasta Primavera",
    "description": "A light pasta dish loaded with fresh seasonal vegetables.",
    "servings": "4 servings",
    "preparationTime": "25 mins",
    "source": "",
    "ingredients": "pasta, bell peppers, zucchini, cherry tomatoes, olive oil",
    "directions": "Cook pasta. Sauté vegetables. Toss together with olive oil and Parmesan.",
    "favorite": 0,
}

RECIPE_BANANA_BREAD = {
    "title": "Banana Bread",
    "description": "A classic quick bread made with ripe bananas.",
    "servings": "8 servings",
    "preparationTime": "50 mins",
    "source": "",
    "ingredients": "bananas, flour, sugar, eggs, baking soda",
    "directions": "Mash bananas. Mix all ingredients. Bake at 350F for 45 mins.",
    "favorite": 0,
}

# RecipeAddMultipleRecipesFromMarkor2 目标（preparationTime='30 mins'）——
# AW prep_time 选项中的 '30 mins'；与 GREEK_SALAD（也 30 mins）组成 3 个目标
RECIPE_QUINOA_BOWL = {
    "title": "Quinoa Veggie Bowl",
    "description": "A light and fresh bowl with quinoa and roasted vegetables.",
    "servings": "3-4 servings",
    "preparationTime": "30 mins",
    "source": "",
    "ingredients": "as needed",
    "directions": "Cook quinoa, roast vegetables, and toss together with a lemon vinaigrette.",
    "favorite": 0,
}

RECIPE_TERIYAKI_SALMON = {
    "title": "Teriyaki Salmon",
    "description": "A quick and easy meal, perfect for busy weekdays.",
    "servings": "2 servings",
    "preparationTime": "30 mins",
    "source": "",
    "ingredients": "varies",
    "directions": "Pan-sear salmon fillets, brush with teriyaki sauce, and serve with steamed rice.",
    "favorite": 0,
}

# RecipeDeleteMultipleRecipesWithConstraint 的第 3 个目标（directions 含 'salt'）——
# 标题/正文取自 AW _RECIPES 池的 'Tomato Basil Bruschetta'（salt, and pepper）
RECIPE_TOMATO_BASIL_BRUSCHETTA = {
    "title": "Tomato Basil Bruschetta",
    "description": "A light and fresh appetizer with ripe tomatoes and basil.",
    "servings": "6 servings",
    "preparationTime": "15 mins",
    "source": "",
    "ingredients": "as needed",
    "directions": (
        "Top sliced baguette with a mix of chopped tomatoes, basil, garlic, "
        "olive oil, salt, and pepper."
    ),
    "favorite": 0,
}

ALL_RECIPES = [RECIPE_SPICY_TUNA, RECIPE_AVOCADO_TOAST, RECIPE_GREEK_SALAD,
               RECIPE_CHOCOLATE_CAKE, RECIPE_CHICKEN_SOUP, RECIPE_PASTA_PRIMAVERA,
               RECIPE_BANANA_BREAD, RECIPE_QUINOA_BOWL, RECIPE_TERIYAKI_SALMON]


# ═══════════════════════════════════════════════════════════
# Expense variants (noise rows)
# ═══════════════════════════════════════════════════════════

EXPENSE_DINNER = {
    "name": "Dinner Out",
    "amount": 4200,        # $42.00
    "category": 3,         # Food
    "note": "Date night",
}

EXPENSE_GROCERIES = {
    "name": "Groceries",
    "amount": 8950,        # $89.50
    "category": 3,         # Food
    "note": "Weekly shopping",
}

EXPENSE_GAS = {
    "name": "Gas Station",
    "amount": 5500,        # $55.00
    "category": 7,         # Transportation
    "note": "Fill up tank",
}

EXPENSE_CONCERT = {
    "name": "Concert Tickets",
    "amount": 15000,       # $150.00
    "category": 5,         # Entertainment
    "note": "Birthday gift",
}

EXPENSE_RENT = {
    "name": "Monthly Rent",
    "amount": 150000,      # $1500.00
    "category": 4,         # Housing
    "note": "Due on 1st",
}

EXPENSE_DOCTOR = {
    "name": "Doctor Visit",
    "amount": 3000,        # $30.00
    "category": 9,         # Health Care
    "note": "Annual checkup",
}

EXPENSE_BOOK = {
    "name": "Programming Book",
    "amount": 4999,        # $49.99
    "category": 10,        # Education
    "note": "Python reference",
}

ALL_EXPENSES = [EXPENSE_LUNCH, EXPENSE_COFFEE, EXPENSE_TAXI,
                EXPENSE_DINNER, EXPENSE_GROCERIES, EXPENSE_GAS,
                EXPENSE_CONCERT, EXPENSE_RENT, EXPENSE_DOCTOR, EXPENSE_BOOK]


# ═══════════════════════════════════════════════════════════
# Calendar events — Oct 2023 timestamped events
# ═══════════════════════════════════════════════════════════

# Base timestamps in milliseconds (device 冻结于 2023-10-15 15:34 UTC，
# Simple Calendar 按设备时区 UTC 显示，故常量必须与注释的 UTC 时刻严格一致)
_OCT15_T1800 = 1697392800000   # 2023-10-15 18:00 UTC
_OCT15_T1900 = 1697396400000   # 2023-10-15 19:00 UTC
_OCT15_T2000 = 1697400000000   # 2023-10-15 20:00 UTC
_OCT16_T1400 = 1697464800000   # 2023-10-16 14:00 UTC
_OCT16_T1500 = 1697468400000   # 2023-10-16 15:00 UTC
_OCT17_T1000 = 1697536800000   # 2023-10-17 10:00 UTC
_OCT17_T1200 = 1697544000000   # 2023-10-17 12:00 UTC
_OCT18_T1600 = 1697644800000   # 2023-10-18 16:00 UTC
_OCT20_T0900 = 1697792400000   # 2023-10-20 09:00 UTC
_OCT22_T1400 = 1697983200000   # 2023-10-22 14:00 UTC

CAL_EVENT_TEAM_MEETING = {
    "title": "Test Meeting",
    "description": "Automated test event",
    "location": "Conference Room A",
    "dtstart": str(_OCT15_T1800),
    "dtend": str(_OCT15_T1900),
    "calendar_id": "1",
}

CAL_EVENT_LUNCH = {
    "title": "Team Lunch",
    "description": "Monthly team lunch at Italian restaurant",
    "location": "Bella Italia",
    "dtstart": str(_OCT16_T1400),
    "dtend": str(_OCT16_T1500),
    "calendar_id": "1",
}

CAL_EVENT_REVIEW = {
    "title": "Project Review",
    "description": "Q3 project status review with stakeholders",
    "location": "Main Boardroom",
    "dtstart": str(_OCT17_T1000),
    "dtend": str(_OCT17_T1200),
    "calendar_id": "1",
}

CAL_EVENT_DENTAL = {
    "title": "Dental Appointment",
    "description": "Regular dental checkup",
    "location": "Smile Clinic",
    "dtstart": str(_OCT18_T1600),
    "dtend": str(_OCT18_T1600 + 3600000),  # +1 hour
    "calendar_id": "1",
}

CAL_EVENT_BIRTHDAY = {
    "title": "Alice Smith Birthday",
    "description": "Alice's birthday party",
    "location": "Central Park",
    "dtstart": str(_OCT20_T0900),
    "dtend": str(_OCT20_T0900 + 7200000),   # +2 hours
    "calendar_id": "1",
}

CAL_EVENT_SUNDAY = {
    "title": "Sunday Brunch",
    "description": "Weekend brunch with friends",
    "location": "The Pancake House",
    "dtstart": str(_OCT22_T1400),
    "dtend": str(_OCT22_T1400 + 3600000),   # +1 hour
    "calendar_id": "1",
}

ALL_CAL_EVENTS = [CAL_EVENT_TEAM_MEETING, CAL_EVENT_LUNCH, CAL_EVENT_REVIEW,
                  CAL_EVENT_DENTAL, CAL_EVENT_BIRTHDAY, CAL_EVENT_SUNDAY]


# ═══════════════════════════════════════════════════════════
# Tasks (Tasks app)
# ═══════════════════════════════════════════════════════════

TASK_BUY_GROCERIES = {
    "title": "Buy groceries",
    "importance": 0,  # high priority
    "notes": "Milk, eggs, bread, butter",
}

TASK_CALL_DENTIST = {
    "title": "Call dentist",
    "importance": 1,  # medium
    "notes": "Schedule appointment for next week",
}

TASK_FINISH_REPORT = {
    "title": "Finish quarterly report",
    "importance": 0,  # high priority
    "notes": "Due by Friday, needs charts from marketing",
}

TASK_BOOK_FLIGHT = {
    "title": "Book flight tickets",
    "importance": 2,  # low
    "notes": "NYC to SF, Nov 5-10",
}

TASK_FIX_LEAK = {
    "title": "Fix kitchen sink leak",
    "importance": 0,  # high priority
    "notes": "Call plumber: 555-0150",
}

ALL_TASKS = [TASK_BUY_GROCERIES, TASK_CALL_DENTIST, TASK_FINISH_REPORT,
             TASK_BOOK_FLIGHT, TASK_FIX_LEAK]

# ── Tasks IR 固定日期（epoch 毫秒，UTC；device 冻结于 2023-10-15 15:34 UTC）──

TASK_DUE_2026_07_17_MS = 1784246400000    # 2026-07-17 00:00 UTC（TasksDueOnDate 等固定日期）
TASK_NEXT_WEEK_START_MS = 1697414400000   # 2023-10-16 00:00 UTC（device 下一周的 Mon 起点）
TASK_OCT17_2023_MS = 1697500800000        # 2023-10-17 00:00 UTC（TasksHighPriorityTasksDueOnDate / TasksIncompleteTasksOnDate 固定日期——AW possible_values 且对齐 device 冻结时钟 10-15）

# TasksDueOnDate / TasksCompletedTasksForDate：3 个固定任务 due 2026-07-17
# （标题取自 AW title 池，importance 0-3 范围）
TASKS_DUE_ON_DATE = [
    {"title": "Complete project proposal", "importance": 1,
     "notes": "Remember to complete this task."},
    {"title": "Review code changes", "importance": 2,
     "notes": "This task is important."},
    {"title": "Schedule team meeting", "importance": 0,
     "notes": "Don't forget to follow up on this task."},
]

# TasksDueNextWeek：6 个固定任务 due 下一周（2023-10-16 ~ 10-21，
# 对齐 AW exclusion 的 Oct 16..22 窗口；due_ms 由 init 按周起点 + 天偏移生成）
TASKS_DUE_NEXT_WEEK = [
    {"title": "Submit expense report", "importance": 2, "notes": "Double-check details."},
    {"title": "Update website content", "importance": 1, "notes": "Send an update."},
    {"title": "Review quarterly goals", "importance": 0, "notes": "This is high priority."},
    {"title": "Organize files and folders", "importance": 3, "notes": "Follow up with others."},
    {"title": "Draft marketing email", "importance": 1, "notes": "Remember to review ahead of time."},
    {"title": "Attend networking event", "importance": 2, "notes": "Schedule follow-up tasks."},
]

# TasksHighPriorityTasks：3 个固定 importance=0 任务（复用上方高优先级常量）
TASKS_HIGH_PRIORITY = [TASK_FINISH_REPORT, TASK_FIX_LEAK, TASK_BUY_GROCERIES]


# ═══════════════════════════════════════════════════════════
# OpenTracks activities
# ═══════════════════════════════════════════════════════════

OPENTRACKS_RUN_1 = {
    "name": "Morning Run",
    "category": "Running",
    "description": "5K run around the park",
    "start_time": str(_OCT15_T1800),       # Oct 15
    "end_time": str(_OCT15_T1800 + 1800000),  # 30min
    "total_distance": "5000",
}

OPENTRACKS_RUN_2 = {
    "name": "Evening Jog",
    "category": "Running",
    "description": "Quick 3K jog after work",
    "start_time": str(_OCT16_T1400),       # Oct 16
    "end_time": str(_OCT16_T1400 + 1200000),  # 20min
    "total_distance": "3000",
}

OPENTRACKS_BIKE = {
    "name": "Bike Commute",
    "category": "Biking",
    "description": "Commute to office",
    "start_time": str(_OCT17_T1000),       # Oct 17
    "end_time": str(_OCT17_T1000 + 2700000),  # 45min
    "total_distance": "12000",
}

ALL_OPENTRACKS_ACTIVITIES = [OPENTRACKS_RUN_1, OPENTRACKS_RUN_2, OPENTRACKS_BIKE]


# ═══════════════════════════════════════════════════════════
# Joplin notes
# ═══════════════════════════════════════════════════════════

JOPLIN_RECIPE_NOTE = {
    "title": "Test Recipe kam",
    "folder": "Recipes",
    "is_todo": 0,
    "body": "## Test Recipe kam\n\nIngredients:\n- 2 tbsp salt\n- 1 cup flour",
}

JOPLIN_MEETING_NOTE = {
    "title": "Test Recipe dyt",
    "folder": "Meeting Notes",   # 对齐 AW NotesMeetingAttendeeCount 的 folder 取值
    "is_todo": 0,
    # 对齐 AW 的 body 模板（{attendee_count}=5）："Attended by 5 participants"
    "body": ("Meeting Notes:\n"
             "- Discussed project milestones\n"
             "- Assigned action items to team members\n"
             "- Reviewed budget allocation\n"
             "- Decided on next meeting date\n"
             "- Attended by 5 participants"),
}

JOPLIN_RECIPE_GAE = {
    "title": "Test Recipe gae",
    "folder": "Recipes",
    "is_todo": 0,
    "body": "## Ingredients\n- 3 tablespoons salt\n- 2 cups sugar",
}

JOPLIN_TODO_NOTE = {
    "title": "Personal Tasks",
    "folder": "Personal",
    "is_todo": 1,
    "body": "- [ ] Buy groceries\n- [x] Call mom\n- [ ] Fix sink",
}

# NotesTodoItemCount 需要 Personal 文件夹中恰 3 个 to-do 笔记（对齐 AW 3 个
# is_todo="True" 的 notes 条目）——与 JOPLIN_TODO_NOTE 合计 3 个
JOPLIN_TODO_NOTE_2 = {
    "title": "Work Tasks",
    "folder": "Personal",
    "is_todo": 1,
    "body": "- [ ] Complete quarterly report\n- [x] Schedule team meeting\n- [ ] Follow up with clients",
}

JOPLIN_TODO_NOTE_3 = {
    "title": "Health Routine",
    "folder": "Personal",
    "is_todo": 1,
    "body": "- [ ] Go for a 30-minute run\n- [ ] Do yoga for flexibility\n- [x] Meditate for relaxation",
}

ALL_JOPLIN_NOTES = [JOPLIN_RECIPE_NOTE, JOPLIN_MEETING_NOTE, JOPLIN_RECIPE_GAE,
                    JOPLIN_TODO_NOTE, JOPLIN_TODO_NOTE_2, JOPLIN_TODO_NOTE_3]


# ═══════════════════════════════════════════════════════════
# Retro Music / VLC data
# ═══════════════════════════════════════════════════════════

RETRO_PLAYLIST = {
    "name": "Test Playlist jwt",
    "songs": ["Morning Vibes", "Summer Breeze", "Night Drive"],
}

RETRO_PLAYLIST_SAVE = {
    "name": "Test Playlist fet",
    "songs": ["Rock Anthem", "Jazz Cafe", "Chill Beats"],
}

RETRO_PLAYLIST_PED = {
    "name": "Test Playlist ped",
}

VLC_PLAYLIST = {
    "name": "Test Playlist wjj",
    "videos": ["test_video_1.mp4", "test_video_2.mp4", "test_video_3.mp4"],
}

VLC_PLAYLIST_ALPHA = {
    "name": "Playlist Alpha mor",
    "videos": ["demo_1.mp4", "demo_2.mp4"],
}

VLC_PLAYLIST_BETA = {
    "name": "Playlist Beta vnx",
    "videos": ["demo_3.mp4", "demo_4.mp4"],
}


# ═══════════════════════════════════════════════════════════
# Markor note variants
# ═══════════════════════════════════════════════════════════

MARKOR_NOTE_HEADER = {
    "file_name": "test_note_xddc.md",
    "new_name": "test_note_vqbs.md",
    "text": "original content for header test",
    "header": "# Test Header",
}

MARKOR_NOTE_CHANGE = {
    "file_name": "test_note_pczi.md",
    "new_name": "test_note_ftmn.md",
    "text": "original content xyz",
    "updated_content": "updated content zklw",
}

MARKOR_NOTE_CREATE = {
    "file_name": "test_note_hsxn.md",
    "text": "hello world automated test",
}

# MarkorCreateNoteAndSms（composite）：笔记文本 = SMS 正文
MARKOR_NOTE_AND_SMS = {
    "file_name": "test_note_eonp.md",
    "text": "hello world automated test",
    "number": "555-0100",
}

# MarkorCreateNoteFromClipboard：init 预置剪贴板（clipper.set 广播），
# agent 粘贴后保存的笔记必须包含该文本
MARKOR_CLIPBOARD = {
    "file_name": "test_note_glzb.md",
    "text": "q3v9xw2kpm",
}

# MarkorEditNote：edit_type=header，文件内容 = header + "\n" + text
MARKOR_NOTE_EDIT = {
    "file_name": "test_note_wxut.md",
    "text": "original content here",
    "header": "# Test Header",
}

MARKOR_NOTE_DELETE = {
    "file_name": "test_note_llxx.md",
    "text": "content to delete",
}

MARKOR_NOTE_MOVE = {
    "file_name": "test_note_xbdw.md",
    "text": "content to move",
    "source_folder": "Documents",
    "destination_folder": "Markor",
}

MARKOR_NOTE_MERGE_1 = {"file_name": "note_alpha.md", "text": "Alpha content line one"}
MARKOR_NOTE_MERGE_2 = {"file_name": "note_beta.md", "text": "Beta content here"}
MARKOR_NOTE_MERGE_3 = {"file_name": "note_gamma.md", "text": "Gamma notes"}
MARKOR_NOTE_MERGE_NEW = {"file_name": "merged_notes.md"}

MARKOR_FOLDER = {"folder_name": "folder_dip"}


# ═══════════════════════════════════════════════════════════
# Receipt / Video transcription (Markor)
# ═══════════════════════════════════════════════════════════

# MarkorTranscribeReceipt：init 生成固定小票 PNG（PIL 绘制，push 到
# /sdcard/DCIM/receipt.png）；receipt.md 必须含表头 + 全部交易行
RECEIPT = {
    "img_file": "receipt.png",
    "md_file": "receipt.md",
    "header": "Date, Item, Amount",
    "transactions": [
        ("2023-10-01", "USB-C Cable", "$15.99"),
        ("2023-10-08", "Wireless Mouse", "$29.50"),
        ("2023-10-15", "Bluetooth Keyboard", "$45.00"),
    ],
}

# MarkorTranscribeVideo：init 生成固定 mp4（每帧显示一个字符串，
# 对齐 AW write_video_file_to_device）；test_note_ozfg.md 须为
# messages 按 ', ' 连接的序列
MARKOR_VIDEO = {
    "video_name": "test_video.mp4",
    "file_name": "test_note_ozfg.md",
    "messages": ["Alice", "Emma", "David"],
}


# ═══════════════════════════════════════════════════════════
# Audio Recorder
# ═══════════════════════════════════════════════════════════

AUDIO_RECORDING = {
    # AW 的 AudioRecorderRecordAudioWithFileName 用 generate_modified_file_name
    # 生成 <word>_<suffix>.m4a——音频扩展名必须保留（校验 file_name + '.m4a' 存在）
    "name": "test_note_plxw.m4a",
    "dir": "/storage/emulated/0/Android/data/com.dimowner.audiorecorder/files/Music/records",
}


# ═══════════════════════════════════════════════════════════
# Simple Draw / Simple Gallery
# ═══════════════════════════════════════════════════════════

SIMPLE_DRAW = {
    "file_name": "test_note_ufvu.png",
}


# ═══════════════════════════════════════════════════════════
# Browser task HTML (AndroidWorld 原版，%%SEED%% 由 init 替换为固定种子)
# ═══════════════════════════════════════════════════════════

BROWSER_HTML_FILE = "task.html"
# AW BrowserTask.generate_random_params 用 random.randint(0, 2**32-1)；
# 这里固定种子保证可重复（同 AW 的 seed 语义）
BROWSER_SEED = 123456789

BROWSER_HTML_DRAW = """\
<!DOCTYPE html>
<html>
<head>
  <title>Color Challenge</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {
      text-align: center;
      font-size: 14px;
    }
    canvas {
      border: 1px solid black;
      touch-action: none;
    }
    .color-button {
      width: 30px;
      height: 30px;
      margin: 3px;
      border: none;
      cursor: pointer;
    }
    #colorPalette {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      max-width: 300px;
      margin: 0 auto;
    }
    #canvasContainer {
      display: flex;
      justify-content: center;
    }
    #taskColors div {
      width: 30px;
      height: 30px;
      margin: 3px;
      display: inline-block;
    }
    button {
      margin: 5px;
      padding: 5px 10px;
      font-size: 14px;
    }
  </style>
</head>
<body>
  <div id="taskColors"></div>
  <div id="canvasContainer">
    <canvas id="canvas" width="300" height="300"></canvas>
  </div>
  <br>
  <p>Available Colors:</p>
  <div id="colorPalette"></div>
  <br>
  <button id="clearButton">Clear</button>
  <button id="submitButton">Submit</button>
  <p id="result"></p>
  <script>
    class SeededRNG {
      constructor(seed) {
        this.seed = seed;
      }

      random() {
        const a = 1664525;
        const c = 1013904223;
        const m = 2 ** 32;
        this.seed = (a * this.seed + c) % m;
        return this.seed / m;
      }
    }

    const rng = new SeededRNG(%%SEED%%);

    const canvas = document.getElementById('canvas');
    const ctx = canvas.getContext('2d');
    const taskColorsElement = document.getElementById('taskColors');
    const colorPalette = document.getElementById('colorPalette');
    const clearButton = document.getElementById('clearButton');
    const submitButton = document.getElementById('submitButton');
    const resultElement = document.getElementById('result');

    let taskColors = [];

    const availableColors = [
      '#ff0000', '#00ff00', '#0000ff', '#ffff00', '#ff00ff', '#00ffff',
      '#800000', '#008000', '#000080', '#808000', '#800080', '#008080',
      '#ffa500', '#ff1493', '#9932cc', '#20b2aa', '#4b0082', '#00ff7f',
      '#ff6347', '#00ced1', '#9400d3', '#f0e68c', '#ff8c00', '#228b22',
    ];

    function clearCanvas() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }

    function generateRandomColors(count) {
      const colors = [];
      const remainingColors = [...availableColors];

      for (let i = 0; i < count; i++) {
        if (remainingColors.length === 0) {
          break;
        }

        const randomIndex = Math.floor(rng.random() * remainingColors.length);
        const selectedColor = remainingColors[randomIndex];
        colors.push(selectedColor);
        remainingColors.splice(randomIndex, 1);
      }

      return colors;
    }

    function displayTaskColors() {
      taskColorsElement.innerHTML = '';
      taskColors.forEach(color => {
        const div = document.createElement('div');
        div.style.backgroundColor = color;
        div.style.width = '50px';
        div.style.height = '50px';
        div.style.display = 'inline-block';
        div.style.margin = '5px';
        taskColorsElement.appendChild(div);
      });
    }

    function createColorPalette() {
      colorPalette.innerHTML = '';
      availableColors.forEach(color => {
        const button = document.createElement('button');
        button.style.backgroundColor = color;
        button.classList.add('color-button');
        button.addEventListener('click', () => {
          ctx.strokeStyle = color;
        });
        colorPalette.appendChild(button);
      });
    }

    function submitTask() {
      submitButton.disabled = true;
      evaluateTask();
      submitButton.disabled = false;
    }

    function evaluateTask() {
      const pixelData = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      const usedColors = new Set();
      for (let i = 0; i < pixelData.length; i += 4) {
        const r = pixelData[i];
        const g = pixelData[i + 1];
        const b = pixelData[i + 2];
        const color = rgbToHex(r, g, b);
        usedColors.add(color);
      }
      const success = taskColors.every(color => usedColors.has(color));
      showResult(success);
    }

    function rgbToHex(r, g, b) {
      const componentToHex = (c) => {
        const hex = c.toString(16);
        return hex.length === 1 ? '0' + hex : hex;
      };
      return '#' + componentToHex(r) + componentToHex(g) + componentToHex(b);
    }

    function showResult(success) {
      if (success) {
        resultElement.textContent = 'Success!';
      } else {
        resultElement.textContent = '';
      }
    }

    function init() {
      taskColors = generateRandomColors(3);
      displayTaskColors();
      createColorPalette();
    }

    canvas.addEventListener('mousedown', startDrawing);
    canvas.addEventListener('mousemove', draw);
    canvas.addEventListener('mouseup', stopDrawing);
    canvas.addEventListener('mouseout', stopDrawing);

    canvas.addEventListener('touchstart', startDrawing);
    canvas.addEventListener('touchmove', draw);
    canvas.addEventListener('touchend', stopDrawing);

    let isDrawing = false;
    let lastX = 0;
    let lastY = 0;

    function startDrawing(e) {
      isDrawing = true;
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      const x = (e.clientX || e.touches[0].clientX) - rect.left;
      const y = (e.clientY || e.touches[0].clientY) - rect.top;
      lastX = x * scaleX;
      lastY = y * scaleY;
    }

    function draw(e) {
      if (!isDrawing) return;
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      const x = (e.clientX || e.touches[0].clientX) - rect.left;
      const y = (e.clientY || e.touches[0].clientY) - rect.top;
      const currentX = x * scaleX;
      const currentY = y * scaleY;
      ctx.beginPath();
      ctx.moveTo(lastX, lastY);
      ctx.lineTo(currentX, currentY);
      ctx.stroke();
      [lastX, lastY] = [currentX, currentY];
    }
    function stopDrawing() {
      isDrawing = false;
    }

    init();
    clearButton.addEventListener('click', clearCanvas);
    submitButton.addEventListener('click', submitTask);
  </script>
</body>
</html>
"""

BROWSER_HTML_MAZE = """\
<!DOCTYPE html>
<html>
<head>
  <title>Maze Puzzle</title>
  <style>
    .row {
      display: flex;
    }

    .cell {
      width: 110px;
      height: 110px;
      border: 1px solid black;
      display: flex;
      justify-content: center;
      align-items: center;
      font-size: 56px;
    }

    .wall {
      background-color: black;
    }

    .character {
      color: black;
    }

    .goal {
      background-color: green;
    }

    .controls {
      margin-top: 10px;
    }

    .controls button {
      margin-right: 5px;
      padding: 15px 28px;
      font-size: 30px;
    }
  </style>
</head>
<body>

  <div id="maze"></div>

  <div class="controls">
    <button onclick="moveCharacter('up')">Up</button>
    <button onclick="moveCharacter('down')">Down</button>
    <button onclick="moveCharacter('left')">Left</button>
    <button onclick="moveCharacter('right')">Right</button>
  </div>

  <script>
    const mazeSize = 4;
    let mazeLayout = [];
    let characterPosition = { row: 0, col: 0 };

    class SeededRNG {
    constructor(seed) {
        this.seed = seed;
    }

    random() {
        const a = 1664525;
        const c = 1013904223;
        const m = 2 ** 32;

        this.seed = (a * this.seed + c) % m;
        return this.seed / m;
    }
    }

    rng = new SeededRNG(%%SEED%%)
    function generateMaze() {
      mazeLayout = [];
      for (let row = 0; row < mazeSize; row++) {
        const currentRow = [];
        for (let col = 0; col < mazeSize; col++) {
          currentRow.push('#');
        }
        mazeLayout.push(currentRow);
      }

      // Create a path from start to goal
      const stack = [{ row: 0, col: 0 }];
      const directions = [[-1, 0], [1, 0], [0, -1], [0, 1]];

      while (stack.length > 0) {
        const { row, col } = stack.pop();
        mazeLayout[row][col] = ' ';

        if (row === mazeSize - 1 && col === mazeSize - 1) {
          break;
        }

        // Shuffle the order of directions
        for (let i = directions.length - 1; i > 0; i--) {
          const j = Math.floor(rng.random() * (i + 1));
          [directions[i], directions[j]] = [directions[j], directions[i]];
        }

        for (const [dx, dy] of directions) {
          const newRow = row + dx;
          const newCol = col + dy;
          if (
            newRow >= 0 &&
            newRow < mazeSize &&
            newCol >= 0 &&
            newCol < mazeSize &&
            mazeLayout[newRow][newCol] === '#'
          ) {
            stack.push({ row: newRow, col: newCol });
          }
        }
      }

      mazeLayout[0][0] = ' ';
      mazeLayout[mazeSize - 1][mazeSize - 1] = '$';
      characterPosition = { row: 0, col: 0 };
    }

    function renderMaze() {
      const mazeElement = document.getElementById('maze');
      mazeElement.innerHTML = '';

      for (let row = 0; row < mazeLayout.length; row++) {
        const rowElement = document.createElement('div');
        rowElement.className = 'row';

        for (let col = 0; col < mazeLayout[row].length; col++) {
          const cellElement = document.createElement('div');
          cellElement.className = 'cell';

          if (mazeLayout[row][col] === '#') {
            cellElement.classList.add('wall');
          } else if (row === characterPosition.row && col === characterPosition.col) {
            cellElement.classList.add('character');
            cellElement.innerHTML = 'X';
          } else if (mazeLayout[row][col] === '$') {
            cellElement.classList.add('goal');
          }

          rowElement.appendChild(cellElement);
        }

        mazeElement.appendChild(rowElement);
      }
    }

    function moveCharacter(direction) {
      const newPosition = { ...characterPosition };

      switch (direction) {
        case 'up':
          newPosition.row--;
          break;
        case 'down':
          newPosition.row++;
          break;
        case 'left':
          newPosition.col--;
          break;
        case 'right':
          newPosition.col++;
          break;
      }

      if (isValidMove(newPosition)) {
        characterPosition = newPosition;
        renderMaze();
        checkGoalReached();
      }
    }

    function isValidMove(position) {
      const { row, col } = position;
      if (
        row < 0 ||
        row >= mazeLayout.length ||
        col < 0 ||
        col >= mazeLayout[row].length ||
        mazeLayout[row][col] === '#'
      ) {
        return false;
      }
      return true;
    }

    function checkGoalReached() {
      const { row, col } = characterPosition;
      if (mazeLayout[row][col] === '$') {
        document.body.innerHTML = '<h1>Success!</h1>';
      }
    }

    generateMaze();
    renderMaze();
  </script>
</body>
</html>"""

BROWSER_HTML_MULTIPLY = """\
<!DOCTYPE html>
<html>
<head>
  <title>Memory Task</title>
  <style>
    .container {
      text-align: center;
      margin-top: 50px;
    }

    .number {
      font-size: 48px;
      margin-bottom: 20px;
    }

    .button {
      padding: 10px 20px;
      font-size: 24px;
      margin-bottom: 20px;
    }

    .form {
      margin-top: 20px;
    }

    .form input {
      padding: 5px;
      font-size: 18px;
    }

    .form button {
      padding: 5px 10px;
      font-size: 18px;
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="number" id="number"></div>
    <button class="button" id="button" onclick="handleButtonClick()">Click Me</button>
    <div class="form" id="form" style="display: none;">
      <input type="number" id="answer" placeholder="Enter the product">
      <button onclick="checkAnswer()">Submit</button>
    </div>
    <div id="result"></div>
  </div>

  <script>
    class SeededRNG {
      constructor(seed) {
        this.seed = seed;
      }

      random() {
        const a = 1664525;
        const c = 1013904223;
        const m = 2 ** 32;
        this.seed = (a * this.seed + c) % m;
        return this.seed / m;
      }
    }

    const rng = new SeededRNG(%%SEED%%);
    const numbers = [];
    let clickCount = 0;

    function generateNumber() {
      const number = Math.floor(rng.random() * 10) + 1;
      numbers.push(number);
      document.getElementById('number').textContent = number;
    }

    function handleButtonClick() {
      clickCount++;
      if (clickCount < 5) {
        generateNumber();
      } else {
        document.getElementById('button').style.display = 'none';
        document.getElementById('number').style.display = 'none';
        document.getElementById('form').style.display = 'block';
      }
    }

    function checkAnswer() {
      const answer = parseInt(document.getElementById('answer').value);
      const product = numbers.reduce((acc, num) => acc * num, 1);
      const result = document.getElementById('result');
      if (answer === product) {
        result.innerHTML = '<h2>Success!</h2>';
      } else {
        result.innerHTML = '<h2></h2>';
      }
    }

    generateNumber();
  </script>
</body>
</html>"""

# ═══════════════════════════════════════════════════════════
# Simple Gallery copy task
# ═══════════════════════════════════════════════════════════

SIMPLE_GALLERY_COPY = {"file_name": "receipt_ewvv.jpg"}
SAVE_COPY_GOAL = (
    "In Simple Gallery Pro, copy receipt_ewvv.jpg in DCIM and "
    "save a copy with the same name in Download"
)

# ═══════════════════════════════════════════════════════════
# OsmAnd markers
# ═══════════════════════════════════════════════════════════

# OsmAnd 预加载 Liechtenstein 地图中的固定地点（对齐 AW _PRELOADED_MAP_LOCATIONS 精确坐标）
OSMAND_FAVORITE = {"name": "Ruggell, Liechtenstein", "lat": 47.23976, "lon": 9.5262837}

OSMAND_MARKER = {"name": "Bendern, Liechtenstein", "lat": 47.2122151, "lon": 9.5062101}

OSMAND_WAYPOINTS = [
    {"name": "Ruggell, Liechtenstein", "lat": 47.23976, "lon": 9.5262837},
    {"name": "Bendern, Liechtenstein", "lat": 47.2122151, "lon": 9.5062101},
]
