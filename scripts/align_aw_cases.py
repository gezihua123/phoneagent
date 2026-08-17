#!/usr/bin/env python3
"""从现有 eval_cases_aw_filled.yml 生成 AndroidWorld 对齐版本。

为每个 case 从 scripts/aw 模块获取正确的 init/verify 命令，
替换弱校验，保证与 AndroidWorld 100% 对齐。
"""
from __future__ import annotations

import sys, yaml
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

from scripts.aw import init, verify, data


# case name → init generator + verify generator + goal update
ALIGN_MAP: dict[str, tuple] = {}


def _reg(name: str, init_fn, verify_fn, goal: str = ""):
    ALIGN_MAP[name] = (init_fn, verify_fn, goal)


# ── Recipe (13 cases) ──
_reg("AW-RecipeAddMultipleRecipes", init.recipe_add_multiple_init,
     verify.recipe_add_multiple_verify,
     "Add the following recipes into the Broccoli app:\n" + init._recipe_csv(
         [data.RECIPE_CHOCOLATE_CAKE, data.RECIPE_CHICKEN_SOUP,
          data.RECIPE_PASTA_PRIMAVERA]))

_reg("AW-RecipeAddMultipleRecipesFromImage", init.recipe_add_from_image_init,
     verify.recipe_add_from_image_verify,
     "Add the recipes from recipes.jpg in Simple Gallery Pro to the Broccoli recipe app.")

_reg("AW-RecipeAddMultipleRecipesFromMarkor", init.recipe_add_from_markor_init,
     verify.recipe_add_from_markor_verify,
     "Add the recipes from recipes.txt in Markor to the Broccoli recipe app.")

_reg("AW-RecipeAddMultipleRecipesFromMarkor2", init.recipe_add_from_markor2_init,
     verify.recipe_add_from_markor2_verify,
     "Add the recipes from recipes.txt in Markor that take 30 mins to prepare into the Broccoli recipe app.")

_reg("AW-RecipeAddSingleRecipe", init.recipe_add_single_init,
     verify.recipe_add_single_verify,
     "Add the following recipes into the Broccoli app:\n" + init._recipe_csv(
         [data.RECIPE_SPICY_TUNA]))

_reg("AW-RecipeDeleteDuplicateRecipes", init.recipe_delete_duplicates_init,
     verify.recipe_delete_duplicates_verify,
     "Delete all but one of any recipes in the Broccoli app that are exact duplicates, "
     "ensuring at least one instance of each unique recipe remains")

_reg("AW-RecipeDeleteDuplicateRecipes2", init.recipe_delete_duplicates2_init,
     verify.recipe_delete_duplicates2_verify,
     "Delete all but one of any recipes in the Broccoli app that are exact duplicates, "
     "ensuring at least one instance of each unique recipe remains")

_reg("AW-RecipeDeleteDuplicateRecipes3", init.recipe_delete_duplicates3_init,
     verify.recipe_delete_duplicates3_verify,
     "Delete all but one of any recipes in the Broccoli app that are exact duplicates, "
     "ensuring at least one instance of each unique recipe remains")

_reg("AW-RecipeDeleteMultipleRecipes", init.recipe_delete_multiple_init,
     verify.recipe_delete_multiple_verify,
     f"Delete the following recipes from Broccoli app: "
     f"{data.RECIPE_SPICY_TUNA['title']}, {data.RECIPE_AVOCADO_TOAST['title']}, "
     f"{data.RECIPE_GREEK_SALAD['title']}.")

_reg("AW-RecipeDeleteMultipleRecipesWithConstraint", init.recipe_delete_with_constraint_init,
     verify.recipe_delete_with_constraint_verify,
     "Delete the recipes from Broccoli app that use salt in the directions.")

_reg("AW-RecipeDeleteMultipleRecipesWithNoise", init.recipe_delete_multiple_with_noise_init,
     verify.recipe_delete_multiple_with_noise_verify,
     f"Delete the following recipes from Broccoli app: "
     f"{data.RECIPE_SPICY_TUNA['title']}, {data.RECIPE_AVOCADO_TOAST['title']}, "
     f"{data.RECIPE_GREEK_SALAD['title']}.")

_reg("AW-RecipeDeleteSingleRecipe", init.recipe_delete_single_init,
     verify.recipe_delete_single_verify,
     f"Delete the following recipes from Broccoli app: {data.RECIPE_SPICY_TUNA['title']}.")

_reg("AW-RecipeDeleteSingleWithRecipeWithNoise", init.recipe_delete_single_with_noise_init,
     verify.recipe_delete_single_with_noise_verify,
     f"Delete the following recipes from Broccoli app: {data.RECIPE_SPICY_TUNA['title']}.")

# ── Expense (9 cases) ──
_reg("AW-ExpenseAddMultiple", init.expense_add_multiple_init,
     verify.expense_add_multiple_verify,
     # 对齐 AW goal 的 text_block 格式：含 category_name 与 note（amount 单位美元）
     "Add the following expenses into the arduia pro expense:\n"
     f"{init._expense_text_block([data.EXPENSE_LUNCH, data.EXPENSE_COFFEE, data.EXPENSE_TAXI])}")

_reg("AW-ExpenseAddMultipleFromGallery", init.expense_add_from_gallery_init,
     verify.expense_add_from_gallery_verify,
     "Add the expenses from expenses.jpg in Simple Gallery Pro to pro expense.")

_reg("AW-ExpenseAddMultipleFromMarkor", init.expense_add_from_markor_init,
     verify.expense_add_from_markor_verify,
     "Go through the transactions in my_expenses.txt in Markor. Log the reimbursable "
     "transactions in the arduia pro expense.")

_reg("AW-ExpenseAddSingle", init.expense_add_single_init,
     verify.expense_add_single_verify,
     # 对齐 AW goal 的 text_block 格式：含 category_name 与 note（amount 单位美元）
     "Add the following expenses into the arduia pro expense:\n"
     f"{init._expense_text_block([data.EXPENSE_LUNCH])}")

_reg("AW-ExpenseDeleteDuplicates", init.expense_delete_duplicates_init,
     verify.expense_delete_duplicates_verify,
     "Delete all but one of any expenses in arduia pro expense that are exact duplicates, "
     "ensuring at least one instance of each unique expense remains.")

_reg("AW-ExpenseDeleteDuplicates2", init.expense_delete_duplicates2_init,
     verify.expense_delete_duplicates2_verify,
     "Delete all but one of any expenses in arduia pro expense that are exact duplicates, "
     "ensuring at least one instance of each unique expense remains.")

_reg("AW-ExpenseDeleteMultiple", init.expense_delete_multiple_init,
     verify.expense_delete_multiple_verify,
     f"Delete the following expenses from arduia pro expense: "
     f"{data.EXPENSE_LUNCH['name']} {data.EXPENSE_LUNCH['amount']/100:.2f}, "
     f"{data.EXPENSE_COFFEE['name']} {data.EXPENSE_COFFEE['amount']/100:.2f}, "
     f"{data.EXPENSE_TAXI['name']} {data.EXPENSE_TAXI['amount']/100:.2f}.")

_reg("AW-ExpenseDeleteMultiple2", init.expense_delete_multiple2_init,
     verify.expense_delete_multiple2_verify,
     f"Delete the following expenses from arduia pro expense: "
     f"{data.EXPENSE_LUNCH['name']} {data.EXPENSE_LUNCH['amount']/100:.2f}, "
     f"{data.EXPENSE_COFFEE['name']} {data.EXPENSE_COFFEE['amount']/100:.2f}, "
     f"{data.EXPENSE_TAXI['name']} {data.EXPENSE_TAXI['amount']/100:.2f}.")

_reg("AW-ExpenseDeleteSingle", init.expense_delete_single_init,
     verify.expense_delete_single_verify,
     f"Delete the following expenses from arduia pro expense: "
     f"{data.EXPENSE_LUNCH['name']} {data.EXPENSE_LUNCH['amount']/100:.2f}.")

# ── Calendar (17 cases) ──
_reg("AW-SimpleCalendarAddOneEvent", init.calendar_add_one_event_init,
     verify.calendar_add_one_event_verify,
     "In Simple Calendar Pro, create a calendar event on 2023-10-15 at 14h with the "
     "title 'Test Meeting' and the description 'Automated test event'. The event should last for 60 mins.")

_reg("AW-SimpleCalendarAddOneEventInTwoWeeks", init.calendar_add_one_event_in_two_weeks_init,
     verify.calendar_add_one_event_in_two_weeks_verify,
     "In Simple Calendar Pro, create a calendar event in two weeks from today at 14h with "
     "the title 'Test Meeting' and the description 'Automated test event'. The event should last for 60 mins.")

_reg("AW-SimpleCalendarAddOneEventRelativeDay", init.calendar_add_one_event_relative_day_init,
     verify.calendar_add_one_event_relative_day_verify,
     "In Simple Calendar Pro, create a calendar event for this Thursday at 14h with the "
     "title 'Test Meeting' and the description 'Automated test event'. The event should last for 60 mins.")

_reg("AW-SimpleCalendarAddOneEventTomorrow", init.calendar_add_one_event_tomorrow_init,
     verify.calendar_add_one_event_tomorrow_verify,
     "In Simple Calendar Pro, create a calendar event for tomorrow at 14h with the "
     "title 'Test Meeting' and the description 'Automated test event'. The event should last for 60 mins.")

_reg("AW-SimpleCalendarAddRepeatingEvent", init.calendar_add_repeating_event_init,
     verify.calendar_add_repeating_event_verify,
     "In Simple Calendar Pro, create a recurring calendar event titled 'Test Meeting' "
     "starting on 2023-10-15 at 14h. The event recurs daily, forever, and lasts for 60 "
     "minutes each occurrence. The event description should be 'Automated test event'.")

_reg("AW-SimpleCalendarDeleteEvents", init.calendar_delete_events_init,
     verify.calendar_delete_events_verify,
     "In Simple Calendar Pro, delete all the calendar events on 2023-10-15")

_reg("AW-SimpleCalendarDeleteEventsOnRelativeDay", init.calendar_delete_events_on_relative_day_init,
     verify.calendar_delete_events_on_relative_day_verify,
     # 设备日期 2023-10-15 是周日——'this Sunday' 歧义（today vs Oct 22），
     # AW 目标日限定 周一..周六；固定 'this Saturday' = 2023-10-21
     "In Simple Calendar Pro, delete all events scheduled for this Saturday.")

_reg("AW-SimpleCalendarDeleteOneEvent", init.calendar_delete_one_event_init,
     verify.calendar_delete_one_event_verify,
     "In Simple Calendar Pro, delete the calendar event on 2023-10-15 at 18h with the title 'Test Meeting'")

# Query tasks (V5 verification)
_reg("AW-SimpleCalendarAnyEventsOnDate", init.calendar_query_any_events_on_date_init,
     verify.calendar_query_any_events_on_date_verify,
     "Do I have any events 2023-10-15 in Simple Calendar Pro? Answer with the titles only. "
     "If there are multiples titles, format your answer in a comma separated list.")

_reg("AW-SimpleCalendarEventOnDateAtTime", init.calendar_query_event_on_date_at_time_init,
     verify.calendar_query_event_on_date_at_time_verify,
     "What is on my schedule for October 15 2023 at 18:00 in Simple Calendar Pro? Answer with "
     "the titles only. If there are multiples titles, format your answer in a comma separated list.")

_reg("AW-SimpleCalendarEventsInNextWeek", init.calendar_query_events_in_next_week_init,
     verify.calendar_query_events_in_next_week_verify,
     "What events do I have in the next week in Simple Calendar Pro? Assume the week starts "
     "from Monday. Answer with the titles only. If there are multiples titles, format your "
     "answer in a comma separated list.")

_reg("AW-SimpleCalendarEventsInTimeRange", init.calendar_query_events_in_time_range_init,
     verify.calendar_query_events_in_time_range_verify,
     "Do I have any events between 10:00 and 8pm October 16 2023 in Simple Calendar Pro? "
     "Answer with the titles only. If there are multiples titles, format your answer in a "
     "comma separated list.")

_reg("AW-SimpleCalendarEventsOnDate", init.calendar_query_events_on_date_init,
     verify.calendar_query_events_on_date_verify,
     "What events do I have October 15 2023 in Simple Calendar Pro? Answer with the titles "
     "only. If there are multiple titles, format your answer as a comma separated list.")

_reg("AW-SimpleCalendarFirstEventAfterStartTime", init.calendar_query_first_event_after_start_init,
     verify.calendar_query_first_event_after_start_verify,
     "What is my first event after 14:00 October 15 2023 in Simple Calendar Pro? Answer with "
     "the titles only. If there are multiples titles, format your answer in a comma separated list.")

_reg("AW-SimpleCalendarLocationOfEvent", init.calendar_query_location_init,
     verify.calendar_query_location_verify,
     "What is the location of my Test Meeting event in Simple Calendar Pro? Answer with the location only.")

_reg("AW-SimpleCalendarNextEvent", init.calendar_query_next_event_init,
     verify.calendar_query_next_event_verify,
     "What is my next upcoming event in Simple Calendar Pro? Answer with the title only. "
     "If there are multiples titles, format your answer in a comma separated list.")

_reg("AW-SimpleCalendarNextMeetingWithPerson", init.calendar_query_next_meeting_with_person_init,
     verify.calendar_query_next_meeting_with_person_verify,
     "When is my next meeting with Alice Smith in Simple Calendar Pro? Express your answer "
     "in the format <month name> <day> <year> <hour in 24-hour format>:<minutes>.")

# ── Contacts ──
_reg("AW-ContactsAddContact", init.contacts_add_init,
     verify.contacts_add_verify,
     f"Open the Contacts app (com.google.android.contacts), create a new contact for "
     f"{data.CONTACT_ALICE['name']}. Their number is {data.CONTACT_ALICE['number']}.")
_reg("AW-ContactsNewContactDraft", init.contacts_draft_init,
     verify.contacts_draft_verify,
     f"Open the Contacts app (com.google.android.contacts), go to the new contact screen "
     f"and enter: First Name: Alice, Last Name: Smith, Phone: 555-0100, Phone Label: Home. Do NOT hit save.")

# ── SMS (6 cases) ──
_reg("AW-SimpleSmsSend", init.sms_send_init,
     verify.sms_send_verify,
     f"Send a text message using Simple SMS Messenger to {data.SMS_HELLO['number']} "
     f"with message: {data.SMS_HELLO['message']}")
_reg("AW-SimpleSmsReply", init.sms_reply_init,
     verify.sms_reply_verify,
     f"Reply to 555-0100 with message: Hello from automated test in Simple SMS Messenger")
_reg("AW-SimpleSmsReplyMostRecent", init.sms_reply_most_recent_init,
     verify.sms_reply_most_recent_verify,
     "Reply to the most recent text message using Simple SMS Messenger with message: Hello from automated test")
_reg("AW-SimpleSmsSendClipboardContent", init.sms_send_clipboard_content_init,
     verify.sms_send_clipboard_content_verify,
     "Send a message to 555-0100 with the clipboard content in Simple SMS Messenger")
_reg("AW-SimpleSmsSendReceivedAddress", init.sms_send_received_address_init,
     verify.sms_send_received_address_verify,
     "Text the address of the event to Alice Smith that Bob Jones just sent me in Simple SMS Messenger")
_reg("AW-SimpleSmsResend", init.sms_resend_init,
     verify.sms_resend_verify,
     "Resend the message I just sent to Alice Smith in Simple SMS Messenger")

# ── File ──
_reg("AW-FilesDeleteFile", init.file_delete_init,
     verify.file_delete_verify,
     f"Open the Files app (com.google.android.documentsui), go to {data.FILE_DELETE['subfolder']} folder, "
     f"and delete the file {data.FILE_DELETE['file_name']}.")
_reg("AW-FilesMoveFile", init.file_move_init,
     verify.file_move_verify,
     f"Open the Files app (com.google.android.documentsui), go to {data.FILE_MOVE['source_folder']} folder, "
     f"move the file {data.FILE_MOVE['file_name']} to the {data.FILE_MOVE['destination_folder']} folder.")

# ── System (14 cases) ──
_reg("AW-SystemBluetoothTurnOff", init.sys_bluetooth_off_init, verify.sys_bluetooth_off_verify, "")
_reg("AW-SystemBluetoothTurnOn", init.sys_bluetooth_on_init, verify.sys_bluetooth_on_verify, "")
_reg("AW-SystemBluetoothTurnOffVerify", init.sys_bluetooth_off_verify_init,
     verify.sys_bluetooth_off_verify, "")
_reg("AW-SystemBluetoothTurnOnVerify", init.sys_bluetooth_on_verify_init,
     verify.sys_bluetooth_on_verify, "")
_reg("AW-SystemWifiTurnOff", init.sys_wifi_off_init, verify.sys_wifi_off_verify, "")
_reg("AW-SystemWifiTurnOn", init.sys_wifi_on_init, verify.sys_wifi_on_verify, "")
_reg("AW-SystemWifiTurnOffVerify", None, verify.sys_wifi_off_verify, "")
_reg("AW-SystemWifiTurnOnVerify", None, verify.sys_wifi_on_verify, "")
_reg("AW-SystemBrightnessMax", init.sys_brightness_max_init, verify.sys_brightness_max_verify, "")
_reg("AW-SystemBrightnessMin", init.sys_brightness_min_init, verify.sys_brightness_min_verify, "")
_reg("AW-SystemBrightnessMaxVerify", init.sys_brightness_max_verify_init,
     verify.sys_brightness_max_verify, "")
_reg("AW-SystemBrightnessMinVerify", init.sys_brightness_min_verify_init,
     verify.sys_brightness_min_verify, "")
_reg("AW-SystemCopyToClipboard", init.sys_clipboard_init, verify.sys_clipboard_verify,
     f"Copy the following text to the clipboard: {data.SYS_CLIPBOARD_CONTENT}")

# ── Camera ──
_reg("AW-CameraTakePhoto", init.camera_photo_init, verify.camera_photo_verify,
     "Open the Camera app (com.android.camera2) and take one photo.")
_reg("AW-CameraTakeVideo", init.camera_video_init, verify.camera_video_verify,
     "Open the Camera app (com.android.camera2), switch to video mode, and take one video.")

# ── Markor (14 cases) ──
_reg("AW-MarkorAddNoteHeader", init.markor_add_note_header_init,
     verify.markor_add_note_header_verify,
     f"Update the Markor note {data.MARKOR_NOTE_HEADER['file_name']} by adding the following text, "
     f"along with a new blank line before the existing content: \"{data.MARKOR_NOTE_HEADER['header']}\", "
     f"and rename it to {data.MARKOR_NOTE_HEADER['new_name']}.")
_reg("AW-MarkorChangeNoteContent", init.markor_change_note_content_init,
     verify.markor_change_note_content_verify,
     f"Update the content of {data.MARKOR_NOTE_CHANGE['file_name']} to "
     f"\"{data.MARKOR_NOTE_CHANGE['updated_content']}\" in Markor and change its name to "
     f"{data.MARKOR_NOTE_CHANGE['new_name']}.")
_reg("AW-MarkorCreateFolder", init.markor_create_folder_init,
     verify.markor_create_folder_verify,
     f"Create a new folder in Markor named {data.MARKOR_FOLDER['folder_name']}.")
_reg("AW-MarkorCreateNote", init.markor_create_note_init,
     verify.markor_create_note_verify,
     f"Create a new note in Markor named {data.MARKOR_NOTE_CREATE['file_name']} "
     f"with the following text: {data.MARKOR_NOTE_CREATE['text']}")
_reg("AW-MarkorCreateNoteAndSms", init.markor_create_note_and_sms_init,
     verify.markor_create_note_and_sms_verify,
     f"Create a new note in Markor named {data.MARKOR_NOTE_AND_SMS['file_name']} "
     f"with the following text: {data.MARKOR_NOTE_AND_SMS['text']}. Share the entire content "
     f"of the note with the phone number {data.MARKOR_NOTE_AND_SMS['number']} via SMS using "
     f"Simple SMS Messenger")
_reg("AW-MarkorCreateNoteFromClipboard", init.markor_create_note_from_clipboard_init,
     verify.markor_create_note_from_clipboard_verify,
     f"Create a note in Markor named {data.MARKOR_CLIPBOARD['file_name']}. Perform a paste "
     f"operation in the note and save the note.")
_reg("AW-MarkorDeleteAllNotes", init.markor_delete_all_notes_init,
     verify.markor_delete_all_notes_verify,
     "Delete all my notes in Markor.")
_reg("AW-MarkorDeleteNewestNote", init.markor_delete_newest_note_init,
     verify.markor_delete_newest_note_verify,
     "Delete the newest note in Markor.")
_reg("AW-MarkorDeleteNote", init.markor_delete_note_init,
     verify.markor_delete_note_verify,
     f"Delete the note in Markor named {data.MARKOR_NOTE_DELETE['file_name']}.")
_reg("AW-MarkorEditNote", init.markor_edit_note_init,
     verify.markor_edit_note_verify,
     f"Edit {data.MARKOR_NOTE_EDIT['file_name']} in Markor. Add to the top of the note "
     f"{data.MARKOR_NOTE_EDIT['header']}")
_reg("AW-MarkorMergeNotes", init.markor_merge_notes_init,
     verify.markor_merge_notes_verify,
     "Merge the contents of Markor notes note_alpha.md, note_beta.md and note_gamma.md "
     "(in the same order) into a new Markor note named merged_notes.md and save it. "
     "Add a new line between the content of each note.")
_reg("AW-MarkorMoveNote", init.markor_move_note_init,
     verify.markor_move_note_verify,
     f"In Markor, move the note {data.MARKOR_NOTE_MOVE['file_name']} from "
     f"{data.MARKOR_NOTE_MOVE['source_folder']} to {data.MARKOR_NOTE_MOVE['destination_folder']}.")
_reg("AW-MarkorTranscribeReceipt", init.markor_transcribe_receipt_init,
     verify.markor_transcribe_receipt_verify,
     "Create a file in Markor, called receipt.md with the transactions from the receipt.png. "
     "Use Simple Gallery to view the receipt. Please enter transactions in csv format including "
     "the header \"Date, Item, Amount\".")
_reg("AW-MarkorTranscribeVideo", init.markor_transcribe_video_init,
     verify.markor_transcribe_video_verify,
     f"Transcribe the contents of video {data.MARKOR_VIDEO['video_name']} by watching it in VLC "
     f"player (located in Download) and writing the sequence of strings shown on each frame to "
     f"the text file {data.MARKOR_VIDEO['file_name']} in Markor as a comma separated list. "
     f"For example, if the first frame shows the text \"edna\" and the second frame shows the "
     f"text \"pineapple\", then the text file should contain only the following text: "
     f"\"edna, pineapple\".")

# ── Clock (3 cases) ──
_reg("AW-ClockStopWatchPausedVerify", init.clock_timer_entry_init,
     verify.clock_stopwatch_paused_verify,
     "Open the Clock app (com.google.android.deskclock), go to Stopwatch tab, and pause the stopwatch.")
_reg("AW-ClockStopWatchRunning", init.clock_stopwatch_running_init,
     verify.clock_stopwatch_running_verify,
     "Open the Clock app (com.google.android.deskclock), go to Stopwatch tab, and run the stopwatch.")
_reg("AW-ClockTimerEntry", init.clock_timer_entry_init,
     verify.clock_timer_entry_verify,
     "Open the Clock app (com.google.android.deskclock), go to Timer tab, create a timer with 0 hours, 5 minutes, and 0 seconds. Do not start the timer.")

# ── Retro Music (4 cases) ──
_reg("AW-RetroCreatePlaylist", init.retro_create_playlist_init,
     verify.retro_playlist_verify,
     f"Create a playlist in Retro Music titled \"Test Playlist jwt\" with the "
     "following songs, in order: Morning Vibes, Summer Breeze, Night Drive")
_reg("AW-RetroPlayingQueue", init.retro_playing_queue_init,
     verify.retro_playing_queue_verify,
     "Add the following songs, in order, Morning Vibes, Summer Breeze, Night Drive "
     "to my playing queue in Retro music.")
_reg("AW-RetroPlaylistDuration", init.retro_playlist_duration_init,
     verify.retro_playlist_duration_verify,
     "Create a playlist in Retro Music titled \"Test Playlist ped\" with a duration "
     "between 45 and 50 minutes using the provided songs.")
_reg("AW-RetroSavePlaylist", init.retro_save_playlist_init,
     verify.retro_save_playlist_verify,
     "Create a playlist in Retro Music titled \"Test Playlist fet\" with the following songs, "
     "in order: Rock Anthem, Jazz Cafe, Chill Beats. Then export the playlist to the Downloads "
     "directory on the device.")

# ── VLC (2 cases) ──
_reg("AW-VlcCreatePlaylist", init.vlc_create_playlist_init,
     verify.vlc_create_playlist_verify,
     f"Create a playlist titled \"{data.VLC_PLAYLIST['name']}\" with the following files "
     f"in VLC (located in Internal Memory/VLCVideos), in order: "
     f"{', '.join(data.VLC_PLAYLIST['videos'])}")
_reg("AW-VlcCreateTwoPlaylists", init.vlc_create_two_playlists_init,
     verify.vlc_create_two_playlists_verify,
     f"Create a playlist titled \"{data.VLC_PLAYLIST_ALPHA['name']}\" with the following "
     f"files in VLC (located in Internal Memory/VLCVideos), in order: "
     f"{', '.join(data.VLC_PLAYLIST_ALPHA['videos'])}. And then, create a playlist titled "
     f"\"{data.VLC_PLAYLIST_BETA['name']}\" with the following files in VLC, in order: "
     f"{', '.join(data.VLC_PLAYLIST_BETA['videos'])}")

# ── Browser (3 cases) ──
_reg("AW-BrowserDraw", init.browser_draw_init,
     verify.browser_activity_verify,
     "Open the file task.html in Downloads in the file manager; when prompted open it with Chrome. "
     "Then create a drawing using the three colors shown at the top and hit submit.")
_reg("AW-BrowserMaze", init.browser_maze_init,
     verify.browser_activity_verify,
     "Open the file task.html in Downloads in the file manager; when prompted open it with Chrome. "
     "Then navigate the X to the bottom-right cell, by using the direction buttons.")
_reg("AW-BrowserMultiply", init.browser_multiply_init,
     verify.browser_activity_verify,
     "Open the file task.html in Downloads in the file manager; when prompted open it with Chrome. "
     "Then click the button 5 times, remember the numbers displayed, and enter their product in the form.")

# ── Audio Recorder (2 cases) ──
_reg("AW-AudioRecorderRecordAudio", init.audio_recorder_record_init,
     verify.audio_recorder_verify,
     "Record an audio clip using Audio Recorder app and save it.")
_reg("AW-AudioRecorderRecordAudioWithFileName", init.audio_recorder_record_with_name_init,
     verify.audio_recorder_with_name_verify,
     f"Record an audio clip and save it with name \"{data.AUDIO_RECORDING['name']}\" using Audio Recorder app.")

# ── OpenApp ──
_reg("AW-OpenAppTaskEval", init.open_app_init,
     verify.open_app_verify,
     "Open the Settings app (com.android.settings). Clear any pop-ups that may appear "
     "by granting all permissions that are required.")

# ── Save Copy of Receipt / Simple Draw ──
_reg("AW-SaveCopyOfReceiptTaskEval", init.save_copy_init,
     verify.save_copy_of_receipt_verify,
     data.SAVE_COPY_GOAL)

_reg("AW-SimpleDrawProCreateDrawing", init.simple_draw_create_drawing_init,
     verify.simple_draw_create_drawing_verify,
     "Create a new drawing in Simple Draw Pro. Name it test_note_ufvu.png. Save it in the "
     "Pictures folder within the sdk_gphone_x86_64 storage area.")

# ── OsmAnd (3 cases) ──
_reg("AW-OsmAndFavorite", init.osmand_favorite_init,
     verify.osmand_favorite_verify,
     f"Add a favorite location marker for {data.OSMAND_FAVORITE['name']} in the OsmAnd maps app.")
_reg("AW-OsmAndMarker", init.osmand_marker_init,
     verify.osmand_marker_verify,
     f"Add a location marker for {data.OSMAND_MARKER['name']} in the OsmAnd maps app.")
_reg("AW-OsmAndTrack", init.osmand_track_init,
     verify.osmand_track_verify,
     "Save a track with waypoints "
     f"{', '.join(w['name'] for w in data.OSMAND_WAYPOINTS)} in the "
     "OsmAnd maps app in the same order as listed.")

# ── Tasks app (7 cases) ──
_reg("AW-TasksCompletedTasksForDate", init.tasks_completed_for_date_init,
     verify.tasks_completed_for_date_verify,
     "Which tasks have I completed for 2026-07-17 in Tasks app? Answer with the titles only. "
     "If there are multiples titles, format your answer in a comma separated list.")
_reg("AW-TasksDueNextWeek", init.tasks_due_next_week_init,
     verify.tasks_due_next_week_verify,
     "How many tasks do I have due next week in Tasks app? Assume the week starts from Monday. "
     "Express your answer as a single integer.")
_reg("AW-TasksDueOnDate", init.tasks_due_on_date_init,
     verify.tasks_due_on_date_verify,
     "What tasks do I have due 2026-07-17 in Tasks app? Answer with the titles only. "
     "If there are multiples titles, format your answer in a comma separated list.")
_reg("AW-TasksHighPriorityTasks", init.tasks_high_priority_init,
     verify.tasks_high_priority_verify,
     "What are my high priority tasks in Tasks app? Answer with the titles only. "
     "If there are multiples titles, format your answer in a comma separated list.")
_reg("AW-TasksHighPriorityTasksDueOnDate", init.tasks_high_priority_due_on_date_init,
     verify.tasks_high_priority_due_on_date_verify,
     "Which tasks with high priority are due October 17 2023 in the Tasks app? Answer with the title only. "
     "If there are multiples titles, format your answer in a comma separated list.")
_reg("AW-TasksIncompleteTasksOnDate", init.tasks_incomplete_tasks_on_date_init,
     verify.tasks_incomplete_tasks_on_date_verify,
     "What incomplete tasks do I have still have to do by October 17 2023 in Tasks app? Answer with the titles only. "
     "If there are multiples titles, format your answer in a comma separated list.")

# ── OpenTracks (7 cases) ──
_reg("AW-SportsTrackerActivitiesCountForWeek", init.opentracks_activities_count_for_week_init,
     verify.opentracks_activities_count_for_week_verify,
     "How many Running activities did I do this week in the OpenTracks app? Assume the week "
     "starts from Monday. Express your answer as a single integer.")
_reg("AW-SportsTrackerActivitiesOnDate", init.opentracks_activities_on_date_init,
     verify.opentracks_activities_on_date_verify,
     "What activities did I do October 12 2023 in the OpenTracks app? Answer with the "
     "activity type only. If there are multiple types, format your answer in a comma "
     "separated list.")
_reg("AW-SportsTrackerActivityDuration", init.opentracks_activity_duration_init,
     verify.opentracks_activity_duration_verify,
     "How long was my Running activity October 12 2023 in the OpenTracks app? Express your "
     "answer in minutes as a single integer.")
_reg("AW-SportsTrackerLongestDistanceActivity", init.opentracks_longest_distance_init,
     verify.opentracks_longest_distance_verify,
     "What was the longest distance covered in a Running activity in the OpenTracks app this "
     "week? Assume the week starts from Monday. Express your answer as a single number in "
     "meters rounded to the nearest integer.")
_reg("AW-SportsTrackerTotalDistanceForCategoryOverInterval", init.opentracks_total_distance_init,
     verify.opentracks_total_distance_verify,
     "What was the total distance covered for Running activities in the OpenTracks app from "
     "October 9 2023 to October 15 2023? Express your answer as a single number in meters "
     "rounded to the nearest integer.")
_reg("AW-SportsTrackerTotalDurationForCategoryThisWeek", init.opentracks_total_duration_init,
     verify.opentracks_total_duration_verify,
     "What was the total duration of Running activities in the OpenTracks app this week? "
     "Assume the week starts from Monday. Express your answer in minutes as a single integer.")

# ── Joplin Notes (4 cases) ──
_reg("AW-NotesIsTodo", init.notes_is_todo_init,
     verify.notes_is_todo_verify,
     "Is the note titled 'Test Recipe kam' in the Joplin app marked as a todo item? "
     "Respond with either 'True' if it is a todo or 'False' if not.")
_reg("AW-NotesMeetingAttendeeCount", init.notes_meeting_attendee_count_init,
     verify.notes_meeting_attendee_count_verify,
     "How many attendees were present in the meeting titled 'Test Recipe dyt' in the Joplin app? "
     "Express your answer as just a single number.")
_reg("AW-NotesRecipeIngredientCount", init.notes_recipe_ingredient_count_init,
     verify.notes_recipe_ingredient_count_verify,
     "What quantity of salt do I need for the recipe 'Test Recipe gae' in the Joplin app? "
     "Express your answer in the format <amount> <unit> where both the amount and unit "
     "exactly match the format in the recipe.")
_reg("AW-NotesTodoItemCount", init.notes_todo_item_count_init,
     verify.notes_todo_item_count_verify,
     "How many to-dos do I have in the 'Personal' folder in the Joplin app? "
     "Express your answer as just a single number.")

# ── Composite tasks (2 cases) ──
_reg("AW-TurnOffWifiAndTurnOnBluetooth", init.turn_off_wifi_turn_on_bluetooth_init,
     verify.turn_off_wifi_turn_on_bluetooth_verify,
     "Turn off WiFi, then enable bluetooth")
_reg("AW-TurnOnWifiAndOpenApp", init.turn_on_wifi_and_open_app_init,
     verify.turn_on_wifi_and_open_app_verify,
     "Turn on Wifi, then open the Settings app (com.android.settings). Clear any pop-ups that "
     "may appear by granting all permissions that are required.")


def align_case(case: dict) -> dict:
    """对齐单个 case——补全 init/verify，填充 goal 占位符。"""
    name = case.get("name", "")
    if name not in ALIGN_MAP:
        return case  # 暂不对齐的 case 保持原样

    init_fn, verify_fn, new_goal = ALIGN_MAP[name]

    # 更新 goal
    if new_goal:
        case["goal"] = new_goal

    # 更新 init
    if init_fn:
        case["initialize"] = [{"command": c} for c in init_fn()]

    # 更新 verify
    if verify_fn:
        case["verify"] = verify_fn()

    return case


def main():
    src = PROJ / "fastaget" / "meta" / "eval_cases_aw_filled.yml"
    dst = PROJ / "fastaget" / "meta" / "eval_cases_aw_aligned.yml"

    with open(src) as f:
        data = yaml.safe_load(f)

    cases = data.get("cases", data) if isinstance(data, dict) else data
    if isinstance(data, dict) and "cases" in data:
        cases = data["cases"]

    aligned = [align_case(c) for c in cases]
    n_aligned = sum(1 for c in aligned if c["name"] in ALIGN_MAP)

    out = {"cases": aligned} if isinstance(data, dict) else aligned
    with open(dst, "w") as f:
        yaml.dump(out, f, allow_unicode=True, default_flow_style=False, width=200)

    print(f"Aligned {n_aligned}/{len(aligned)} cases → {dst}")


if __name__ == "__main__":
    main()
