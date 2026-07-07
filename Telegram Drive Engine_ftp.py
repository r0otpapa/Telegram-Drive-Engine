import os
import time
import json
import zipfile
import asyncio
import threading
from ftplib import FTP
from datetime import datetime, timedelta
import customtkinter as ctk
from tkinter import filedialog
from telegram import Bot
from telegram.ext import Application, CommandHandler

CONFIG_FILE = "backup_config.json"
BACKUP_DIR = "Backups"
HISTORY_FILE = "backup_history.json"

if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR, exist_ok=True)

ACTIVE_WORKERS = {}
BOT_APP_INSTANCE = None
BOT_THREAD_LOOP = None
HISTORY_LOCK = threading.Lock()

# ================= DATA STORAGE MANAGEMENT LAYER =================

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f: 
                raw_data = json.load(f)
                return {k: v for k, v in raw_data.items() if isinstance(v, dict)}
        except Exception: return {}
    return {}

def save_config(config_data):
    with open(CONFIG_FILE, "w") as f: 
        json.dump(config_data, f, indent=4)

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f: return json.load(f)
        except Exception: return []
    return []

def save_history(history_data):
    with open(HISTORY_FILE, "w") as f: json.dump(history_data, f, indent=4)

def add_to_history(fingerprints):
    with HISTORY_LOCK:
        current_history = load_history()
        updated = False
        for fp in fingerprints:
            if fp not in current_history:
                current_history.append(fp)
                updated = True
        if updated:
            save_history(current_history)

def get_file_fingerprint(folder_id, filepath):
    try:
        stat = os.stat(filepath)
        return f"{folder_id}_{os.path.basename(filepath)}_{int(stat.st_size)}_{int(stat.st_mtime)}"
    except Exception:
        return f"{folder_id}_{os.path.basename(filepath)}"

def get_past_credentials():
    config = load_config()
    tokens, chat_ids, ftp_servers, ftp_users, ftp_passes, ftp_dirs = set(), set(), set(), set(), set(), set()
    for folder in config.values():
        if isinstance(folder, dict):
            if folder.get("token"): tokens.add(folder.get("token").strip())
            if folder.get("chat_id"): chat_ids.add(folder.get("chat_id").strip())
            if folder.get("ftp_server"): ftp_servers.add(folder.get("ftp_server").strip())
            if folder.get("ftp_user"): ftp_users.add(folder.get("ftp_user").strip())
            if folder.get("ftp_pass"): ftp_passes.add(folder.get("ftp_pass").strip())
            if folder.get("ftp_dir"): ftp_dirs.add(folder.get("ftp_dir").strip())
    return list(tokens), list(chat_ids), list(ftp_servers), list(ftp_users), list(ftp_passes), list(ftp_dirs)


# ================= DATA PACKAGING AND TRANSFER PIPELINES =================

def create_standard_zip(source_dir, output_zip, target_files):
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        for full_path in target_files:
            if os.path.exists(full_path):
                zipf.write(full_path, os.path.relpath(full_path, source_dir))

async def upload_pipeline(files_to_upload, token, chat_id, folder_id, should_auto_delete, use_zip, fingerprints_to_save):
    bot = Bot(token.strip())
    async with bot:
        for file in files_to_upload:
            if folder_id in ACTIVE_WORKERS and not ACTIVE_WORKERS[folder_id]["active"]:
                break
            filename = os.path.basename(file)
            try:
                safe_log(f"📤 [{folder_id}] Uploading to Telegram: {filename}...")
                with open(file, "rb") as f:
                    await bot.send_document(chat_id=chat_id.strip(), document=f)
                safe_log(f"✅ [{folder_id}] Uploaded successfully.")
                
                # Always save individual file fingerprints to avoid re-zipping unchanged files later
                add_to_history(fingerprints_to_save)

                if should_auto_delete and use_zip and os.path.exists(file):
                    os.remove(file)
                    safe_log(f"🧹 [Auto-Delete] Purged local archive: {filename}")
            except Exception as upload_err:
                safe_log(f"❌ [{folder_id}] Upload failed: {str(upload_err)}")

def upload_to_ftp(files_to_upload, server, user, passwd, remote_dir, folder_id, should_auto_delete, use_zip, fingerprints_to_save):
    try:
        safe_log(f"⚡ [{folder_id}] Connecting to FTP: {server}...")
        ftp = FTP(server.strip())
        ftp.login(user=user.strip(), passwd=passwd.strip())
        
        if remote_dir.strip():
            try: ftp.cwd(remote_dir.strip())
            except Exception:
                try:
                    ftp.mkd(remote_dir.strip())
                    ftp.cwd(remote_dir.strip())
                except Exception: pass

        uploaded_successfully = False
        for file in files_to_upload:
            if folder_id in ACTIVE_WORKERS and not ACTIVE_WORKERS[folder_id]["active"]:
                break
            filename = os.path.basename(file)
            safe_log(f"📤 [{folder_id}] Uploading to FTP: {filename}...")
            with open(file, "rb") as f:
                ftp.storbinary(f"STOR {filename}", f)
            safe_log(f"✅ [{folder_id}] FTP Transfer Success: {filename}")
            uploaded_successfully = True

            if should_auto_delete and use_zip and os.path.exists(file): 
                os.remove(file)

        if uploaded_successfully:
            add_to_history(fingerprints_to_save)
            
        ftp.quit()
    except Exception as ftp_err:
        safe_log(f"❌ [{folder_id}] FTP Transfer Error: {str(ftp_err)}")


# ================= THREADED BACKGROUND ENGINES =================

def safe_log(msg):
    if 'app' in globals() and app and app.winfo_exists():
        app.after(0, lambda: app.log(msg))

def run_folder_backup(folder_id, folder_data):
    try:
        path = folder_data.get("path")
        dest_type = folder_data.get("dest_type", "Telegram")
        use_zip = folder_data.get("zip", True)
        should_auto_delete = folder_data.get("auto_delete", False)
        backup_all = folder_data.get("backup_all", True)
        
        if not path or not os.path.exists(path):
            safe_log(f"❌ [{folder_id}] Directory path does not exist.")
            return

        safe_log(f"⏳ [{folder_id}] Indexing assets...")
        
        with HISTORY_LOCK:
            history = load_history()
            
        raw_files = []
        fingerprints_to_save = []

        for root, _, files in os.walk(path):
            for file in files:
                full_path = os.path.join(root, file)
                fp_key = get_file_fingerprint(folder_id, full_path)
                
                # Dynamic filter works perfectly for both Zip and Raw File selections
                if not backup_all and fp_key in history:
                    continue
                
                raw_files.append(full_path)
                fingerprints_to_save.append(fp_key)

        if not raw_files:
            safe_log(f"⚠️ [{folder_id}] No new or modified assets to process.")
            if folder_id in ACTIVE_WORKERS:
                del ACTIVE_WORKERS[folder_id]
            if 'app' in globals(): app.after(0, app.refresh_dashboard)
            return

        files_to_upload = []
        if use_zip:
            folder_name = os.path.basename(path.rstrip(os.sep)) or "backup"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_path = os.path.join(BACKUP_DIR, f"{folder_name}_{timestamp}.zip")
            
            # Packages ONLY new/updated files into the zip file matrix
            create_standard_zip(path, zip_path, raw_files)
            files_to_upload.append(zip_path)
        else:
            files_to_upload = raw_files

        if dest_type == "FTP (Router Storage)":
            upload_to_ftp(files_to_upload, folder_data.get("ftp_server"), folder_data.get("ftp_user", ""), folder_data.get("ftp_pass", ""), folder_data.get("ftp_dir", ""), folder_id, should_auto_delete, use_zip, fingerprints_to_save)
        else:
            token, chat_id = folder_data.get("token"), folder_data.get("chat_id")
            if token and chat_id:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try: loop.run_until_complete(upload_pipeline(files_to_upload, token, chat_id, folder_id, should_auto_delete, use_zip, fingerprints_to_save))
                finally: loop.close()

        safe_log(f"🎉 [{folder_id}] Pipeline completed successfully.")
    except Exception as e:
        safe_log(f"❌ [{folder_id}] Execution error: {str(e)}")
    finally:
        if folder_id in ACTIVE_WORKERS: del ACTIVE_WORKERS[folder_id]
        if 'app' in globals(): app.after(0, app.refresh_dashboard)

def start_threaded_backup(folder_id, folder_data):
    if folder_id in ACTIVE_WORKERS:
        ACTIVE_WORKERS[folder_id]["active"] = False
        safe_log(f"🛑 [{folder_id}] Stopping backup worker sequence...")
        return
    ACTIVE_WORKERS[folder_id] = {"active": True}
    threading.Thread(target=run_folder_backup, args=(folder_id, folder_data), daemon=True).start()
    if 'app' in globals(): app.refresh_dashboard()

def toggle_all_backups():
    config = load_config()
    any_active = any(worker["active"] for worker in ACTIVE_WORKERS.values())
    if any_active:
        for fid in list(ACTIVE_WORKERS.keys()):
            ACTIVE_WORKERS[fid]["active"] = False
        safe_log("🛑 Broadcast Triggered: Stopping all system backup sequences.")
    else:
        for fid, fdata in config.items():
            if isinstance(fdata, dict) and fid not in ACTIVE_WORKERS:
                ACTIVE_WORKERS[fid] = {"active": True}
                threading.Thread(target=run_folder_backup, args=(fid, fdata), daemon=True).start()
        safe_log("⚡ Broadcast Triggered: Threading all automated backup workers.")
    if 'app' in globals(): app.refresh_dashboard()


# ================= TELEGRAM LIVE BACKEND PROCESSING =================

async def tg_help_command(update, context):
    await update.message.reply_text("🤖 *Operational Commands Matrix*\n\n🔸 `/sent <filename>` - Extract asset path without needing file format/extension", parse_mode="Markdown")

async def tg_sent_command(update, context):
    if not context.args:
        await update.message.reply_text("⚠️ Syntax: `/sent filename` (Extension/format write karna zaroori nahi h)")
        return
    
    user_query = " ".join(context.args).strip().lower()
    config = load_config()
    matched_files = [] 
    
    for fid, fdata in config.items():
        if not isinstance(fdata, dict) or not fdata.get("bot_requests_enabled", True): 
            continue
            
        path = fdata.get("path")
        if path and os.path.exists(path):
            for root, _, files in os.walk(path):
                for f in files:
                    f_name_only, f_ext = os.path.splitext(f)
                    if f.lower() == user_query or f_name_only.lower() == user_query:
                        full_path = os.path.join(root, f)
                        matched_files.append((fid, full_path))

    if matched_files:
        await update.message.reply_text(f"🔍 Found {len(matched_files)} matching asset(s). Dispatching files...")
        for folder_id, found_file_path in matched_files:
            if os.path.exists(found_file_path):
                try:
                    caption_msg = f"📂 *Source Profile:* `{folder_id}`\n📍 *File Name:* `{os.path.basename(found_file_path)}`"
                    with open(found_file_path, "rb") as document:
                        await update.message.reply_document(
                            document=document,
                            caption=caption_msg,
                            parse_mode="Markdown"
                        )
                except Exception as send_err:
                    await update.message.reply_text(f"❌ Telegram API failed to stream data packet from [{folder_id}]: {str(send_err)}")
    else:
        await update.message.reply_text("❌ Target file could not be located inside any of the active profile directory folders.")

def bot_polling_thread(token):
    global BOT_APP_INSTANCE, BOT_THREAD_LOOP
    try:
        BOT_THREAD_LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(BOT_THREAD_LOOP)
        BOT_APP_INSTANCE = Application.builder().token(token).build()
        BOT_APP_INSTANCE.add_handler(CommandHandler("help", tg_help_command))
        BOT_APP_INSTANCE.add_handler(CommandHandler("sent", tg_sent_command))
        safe_log("🤖 Telegram Control Link active: Polling incoming command chains...")
        BOT_APP_INSTANCE.run_polling(close_loop=False)
    except Exception as e:
        safe_log(f"❌ Hook link unestablished: {str(e)}")

def toggle_bot_listener():
    global BOT_APP_INSTANCE, BOT_THREAD_LOOP
    if BOT_APP_INSTANCE is not None:
        safe_log("🛑 Request sent: Terminating active backend polling hooks...")
        try:
            if BOT_THREAD_LOOP and BOT_THREAD_LOOP.is_running():
                BOT_THREAD_LOOP.call_soon_threadsafe(lambda: asyncio.ensure_future(BOT_APP_INSTANCE.updater.stop()))
                BOT_THREAD_LOOP.call_soon_threadsafe(lambda: asyncio.ensure_future(BOT_APP_INSTANCE.stop()))
                BOT_THREAD_LOOP.call_soon_threadsafe(lambda: asyncio.ensure_future(BOT_APP_INSTANCE.shutdown()))
            BOT_APP_INSTANCE = None
            safe_log("🛑 Telegram Bot Service successfully stopped.")
        except Exception as err:
            safe_log(f"⚠️ Service cleanup response: {str(err)}")
            BOT_APP_INSTANCE = None
    else:
        config = load_config()
        token = next((f.get("token").strip() for f in config.values() if isinstance(f, dict) and f.get("token")), "")
        if not token:
            safe_log("❌ Error initializing bot: Missing Telegram Token configuration array mapping.")
            return
        threading.Thread(target=bot_polling_thread, args=(token,), daemon=True).start()
    if 'app' in globals(): app.refresh_dashboard()


# ================= SCHEDULER ENGINE =================

LAST_FIRED_BACKUPS = {}

def global_scheduler():
    while True:
        config = load_config()
        now_dt = datetime.now()
        
        current_time_12h = now_dt.strftime("%I:%M %p") 
        current_date = now_dt.strftime("%Y-%m-%d")
        current_day_int = now_dt.day

        for fid, fdata in config.items():
            if not isinstance(fdata, dict): continue
            if fdata.get("auto_backup", False):
                target_time = fdata.get("backup_time", "02:00 PM").strip()
                frequency = fdata.get("backup_frequency", "Daily")
                
                if target_time == current_time_12h:
                    unique_fire_key = f"{fid}_{current_date}_{target_time}"
                    
                    if LAST_FIRED_BACKUPS.get(fid) != unique_fire_key:
                        should_trigger = False
                        
                        if frequency == "Daily":
                            should_trigger = True
                        elif frequency == "Monthly" and current_day_int == 1:
                            should_trigger = True
                        
                        if should_trigger:
                            LAST_FIRED_BACKUPS[fid] = unique_fire_key
                            safe_log(f"⏰ [Scheduler] Auto-Trigger activated for profile: {fid} ({frequency} Cycle)")
                            start_threaded_backup(fid, fdata)
                            
        time.sleep(30)

threading.Thread(target=global_scheduler, daemon=True).start()


# ================= POPUP PROFILE WINDOW MODAL =================

class FolderConfigWindow(ctk.CTkToplevel):
    def __init__(self, parent, folder_id=None, folder_data=None):
        super().__init__(parent)
        self.parent = parent
        self.folder_id = folder_id
        self.folder_data = folder_data or {}
        
        self.title("Folder Settings Manager" if folder_id else "Add Backup Profile")
        self.geometry("580x750")
        
        self.resizable(True, True) 
        self.minsize(500, 720) 
        
        self.transient(parent)
        self.grab_set()

        self.past_tk, self.past_ch, self.past_srv, self.past_us, self.past_ps, self.past_dr = get_past_credentials()
        self.path_var = ctk.StringVar(value=self.folder_data.get("path", ""))
        
        ctk.CTkLabel(self, text="Folder Profile Configuration", font=("Arial", 18, "bold")).pack(pady=10)
        
        main_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        main_scroll.pack(fill="both", expand=True, padx=10, pady=5)
        
        p_frame = ctk.CTkFrame(main_scroll, fg_color="transparent")
        p_frame.pack(fill="x", padx=20, pady=5)
        self.path_entry = ctk.CTkEntry(p_frame, placeholder_text="Select target system backup path...", textvariable=self.path_var)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(p_frame, text="Browse", width=80, command=self.browse_folder).pack(side="right")

        self.dest_var = ctk.StringVar(value=self.folder_data.get("dest_type", "Telegram"))
        self.dest_selector = ctk.CTkSegmentedButton(main_scroll, values=["Telegram", "FTP (Router Storage)"], variable=self.dest_var, command=self.refresh_fields)
        self.dest_selector.pack(fill="x", padx=20, pady=5)

        self.dynamic_frame = ctk.CTkFrame(main_scroll, fg_color="transparent")
        self.dynamic_frame.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(main_scroll, text="Backup Strategy Filter Mode:", anchor="w").pack(fill="x", padx=20, pady=(5,0))
        self.mode_var = ctk.StringVar(value="All Files" if self.folder_data.get("backup_all", True) else "New/Updated Files")
        self.mode_selector = ctk.CTkSegmentedButton(main_scroll, values=["All Files", "New/Updated Files"], variable=self.mode_var)
        self.mode_selector.pack(fill="x", padx=20, pady=5)

        self.bot_req_var = ctk.BooleanVar(value=self.folder_data.get("bot_requests_enabled", True))
        self.bot_req_switch = ctk.CTkSwitch(main_scroll, text="Enable Remote Bot Commands (/sent, /help)", variable=self.bot_req_var)
        self.bot_req_switch.pack(anchor="w", padx=20, pady=10)

        self.auto_var = ctk.BooleanVar(value=self.folder_data.get("auto_backup", False))
        ctk.CTkSwitch(main_scroll, text="Enable Automated Schedule Cycle", variable=self.auto_var).pack(anchor="w", padx=20, pady=5)
        
        freq_frame = ctk.CTkFrame(main_scroll, fg_color="transparent")
        freq_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(freq_frame, text="Execution Interval (Frequency Cycle):").pack(side="left")
        self.freq_selector = ctk.CTkComboBox(freq_frame, values=["Daily", "Monthly"], width=120)
        self.freq_selector.set(self.folder_data.get("backup_frequency", "Daily"))
        self.freq_selector.pack(side="right")
        
        t_frame = ctk.CTkFrame(main_scroll, fg_color="transparent")
        t_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(t_frame, text="Execution Clock Target Time (HH:MM):").pack(side="left")
        
        self.ampm_selector = ctk.CTkComboBox(t_frame, values=["AM", "PM"], width=70)
        raw_saved_time = self.folder_data.get("backup_time", "02:00 PM")
        
        if " " in raw_saved_time:
            time_digits, ampm_part = raw_saved_time.split(" ")
            ampm_part = ampm_part.strip().upper()
        else:
            time_digits, ampm_part = raw_saved_time, "PM"
            
        self.ampm_selector.set(ampm_part if ampm_part in ["AM", "PM"] else "PM")
        self.ampm_selector.pack(side="right", padx=(5, 0))
        
        self.time_entry = ctk.CTkEntry(t_frame, width=80, placeholder_text="02:00")
        self.time_entry.insert(0, time_digits)
        self.time_entry.pack(side="right")

        self.zip_var = ctk.BooleanVar(value=self.folder_data.get("zip", True))
        ctk.CTkSwitch(main_scroll, text="Compress Folder into single (.zip) archive", variable=self.zip_var).pack(anchor="w", padx=20, pady=5)

        self.del_var = ctk.BooleanVar(value=self.folder_data.get("auto_delete", False))
        ctk.CTkSwitch(main_scroll, text="Auto-Delete local copies instantly after sending", variable=self.del_var).pack(anchor="w", padx=20, pady=5)
        
        d_frame = ctk.CTkFrame(main_scroll, fg_color="transparent")
        d_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(d_frame, text="Keep Local Archives Retention (Days Limit):").pack(side="left")
        self.days_entry = ctk.CTkEntry(d_frame, width=80, placeholder_text="7")
        self.days_entry.insert(0, str(self.folder_data.get("delete_days", 7)))
        self.days_entry.pack(side="right")

        ctk.CTkButton(self, text="Save Profile Configuration", fg_color="#1f538d", height=40, command=self.save_profile).pack(fill="x", padx=30, pady=10)
        
        footer_frame = ctk.CTkFrame(self, height=25, fg_color="transparent")
        footer_frame.pack(fill="x", side="bottom", pady=5)
        ctk.CTkLabel(footer_frame, text="Created by Tarun Sharma (r0tpapa)", font=("Arial", 11, "italic"), text_color="#7f8c8d").pack(side="bottom")

        self.refresh_fields(self.dest_var.get())

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder: self.path_var.set(folder)

    def refresh_fields(self, selection):
        for widget in self.dynamic_frame.winfo_children(): widget.destroy()
        if selection == "FTP (Router Storage)":
            self.bot_req_switch.configure(state="disabled")
            ctk.CTkLabel(self.dynamic_frame, text="FTP Server Host / Router IP Address:", anchor="w").pack(fill="x", pady=(2,0))
            self.ftp_srv_entry = ctk.CTkComboBox(self.dynamic_frame, values=self.past_srv)
            self.ftp_srv_entry.set(self.folder_data.get("ftp_server", ""))
            self.ftp_srv_entry.pack(fill="x", pady=2)

            up_frame = ctk.CTkFrame(self.dynamic_frame, fg_color="transparent")
            up_frame.pack(fill="x", pady=2)
            up_frame.columnconfigure(0, weight=1)
            up_frame.columnconfigure(1, weight=1)
            
            ctk.CTkLabel(up_frame, text="FTP Server Username:", anchor="w").grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(up_frame, text="FTP Server Password:", anchor="w").grid(row=0, column=1, sticky="w", padx=(10,0))

            self.ftp_user_entry = ctk.CTkComboBox(up_frame, values=self.past_us)
            self.ftp_user_entry.set(self.folder_data.get("ftp_user", ""))
            self.ftp_user_entry.grid(row=1, column=0, padx=(0,5), sticky="ew")
            
            self.ftp_pass_entry = ctk.CTkComboBox(up_frame, values=self.past_ps)
            self.ftp_pass_entry.set(self.folder_data.get("ftp_pass", ""))
            self.ftp_pass_entry.grid(row=1, column=1, padx=(5,0), sticky="ew")

            ctk.CTkLabel(self.dynamic_frame, text="Remote Store Folder Directory Path:", anchor="w").pack(fill="x", pady=(4,0))
            self.ftp_dir_entry = ctk.CTkComboBox(self.dynamic_frame, values=self.past_dr)
            self.ftp_dir_entry.set(self.folder_data.get("ftp_dir", ""))
            self.ftp_dir_entry.pack(fill="x", pady=2)
        else:
            self.bot_req_switch.configure(state="normal")
            ctk.CTkLabel(self.dynamic_frame, text="Telegram Bot Token API Key Reference:", anchor="w").pack(fill="x", pady=(2,0))
            self.token_entry = ctk.CTkComboBox(self.dynamic_frame, values=self.past_tk)
            self.token_entry.set(self.folder_data.get("token", ""))
            self.token_entry.pack(fill="x", pady=4)
            
            ctk.CTkLabel(self.dynamic_frame, text="Telegram Private target Chat ID String:", anchor="w").pack(fill="x", pady=(2,0))
            self.chat_entry = ctk.CTkComboBox(self.dynamic_frame, values=self.past_ch)
            self.chat_entry.set(self.folder_data.get("chat_id", ""))
            self.chat_entry.pack(fill="x", pady=4)

    def save_profile(self):
        path = self.path_entry.get().strip()
        dest = self.dest_var.get()
        if not path: return 
            
        config = load_config()
        fid = self.folder_id if self.folder_id else os.path.basename(path.rstrip(os.sep)) or "Profile"
        
        time_text = self.time_entry.get().strip() or "02:00"
        ampm_text = self.ampm_selector.get()
        combined_12h_time = f"{time_text} {ampm_text}"
        
        profile_entry = {
            "path": path,
            "dest_type": dest,
            "zip": self.zip_var.get(),
            "backup_all": True if self.mode_selector.get() == "All Files" else False,
            "bot_requests_enabled": self.bot_req_var.get(),
            "auto_backup": self.auto_var.get(),
            "backup_frequency": self.freq_selector.get(),
            "backup_time": combined_12h_time,
            "auto_delete": self.del_var.get(),
            "delete_days": int(self.days_entry.get() or 7)
        }

        if dest == "FTP (Router Storage)":
            profile_entry["ftp_server"] = self.ftp_srv_entry.get().strip()
            profile_entry["ftp_user"] = self.ftp_user_entry.get().strip() or "anonymous"
            profile_entry["ftp_pass"] = self.ftp_pass_entry.get().strip()
            profile_entry["ftp_dir"] = self.ftp_dir_entry.get().strip()
            if not profile_entry["ftp_server"]: return
        else:
            profile_entry["token"] = self.token_entry.get().strip()
            profile_entry["chat_id"] = self.chat_entry.get().strip()
            if not profile_entry["token"] or not profile_entry["chat_id"]: return
        
        config[fid] = profile_entry
        save_config(config)
        self.parent.refresh_dashboard()
        self.destroy()


# ================= MAIN RUNTIME APPLICATION INTERFACE =================

class DashboardApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Drive Engine — Dashboard")
        self.geometry("1020x750")
        ctk.set_appearance_mode("dark")
        
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, height=75, fg_color="#1a1a1a", corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(header, text="🗄️ Backup Control Deck", font=("Arial", 22, "bold")).pack(side="left", padx=25, pady=15)
        
        self.actions_frame = ctk.CTkFrame(header, fg_color="transparent")
        self.actions_frame.pack(side="right", padx=20)

        self.bot_toggle_btn = ctk.CTkButton(self.actions_frame, text="🤖 Start Bot Listener", fg_color="#8e44ad", width=150, command=toggle_bot_listener)
        self.bot_toggle_btn.pack(side="left", padx=5)

        self.run_all_btn = ctk.CTkButton(self.actions_frame, text="⚡ Run All", fg_color="#2b7337", width=100, command=toggle_all_backups)
        self.run_all_btn.pack(side="left", padx=5)

        ctk.CTkButton(self.actions_frame, text="➕ Add Profile", fg_color="#1f538d", width=100, command=lambda: FolderConfigWindow(self)).pack(side="left", padx=5)

        main_pane = ctk.CTkFrame(self, fg_color="transparent")
        main_pane.grid(row=1, column=0, sticky="nsew", padx=20, pady=15)
        main_pane.grid_rowconfigure(0, weight=1)
        main_pane.grid_columnconfigure(0, weight=3) 
        main_pane.grid_columnconfigure(1, weight=2) 

        self.scroll_deck = ctk.CTkScrollableFrame(main_pane, label_text="Active Managed Folder Profiles")
        self.scroll_deck.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        log_frame = ctk.CTkFrame(main_pane)
        log_frame.grid(row=0, column=1, sticky="nsew")
        log_frame.grid_rowconfigure(1, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(log_frame, text="📋 Engine Console Logs", font=("Arial", 14, "bold"), anchor="w").grid(row=0, column=0, padx=15, pady=10, sticky="ew")
        self.log_box = ctk.CTkTextbox(log_frame, font=("Courier New", 12), text_color="#a6a6a6")
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0,10))

        footer_frame = ctk.CTkFrame(self, height=25, fg_color="transparent")
        footer_frame.grid(row=2, column=0, sticky="ew", pady=(0, 5))
        ctk.CTkLabel(footer_frame, text="Created by Tarun Sharma (r0tpapa)", font=("Arial", 11, "italic"), text_color="#7f8c8d").pack(side="bottom")

        self.refresh_dashboard()

    def log(self, msg):
        self.log_box.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log_box.see("end")

    def refresh_dashboard(self):
        if BOT_APP_INSTANCE is not None:
            self.bot_toggle_btn.configure(text="🛑 Stop Bot Listener", fg_color="#c0392b")
        else:
            self.bot_toggle_btn.configure(text="🤖 Start Bot Listener", fg_color="#8e44ad")

        any_active = any(worker["active"] for worker in ACTIVE_WORKERS.values())
        if any_active:
            self.run_all_btn.configure(text="🟥 Stop All", fg_color="#d35400")
        else:
            self.run_all_btn.configure(text="⚡ Run All", fg_color="#2b7337")

        for child in self.scroll_deck.winfo_children(): child.destroy()
        config = load_config()
        
        has_profiles = False
        for fid, fdata in config.items():
            if not isinstance(fdata, dict): continue
            has_profiles = True
            row = ctk.CTkFrame(self.scroll_deck, height=85)
            row.pack(fill="x", pady=6, padx=5)
            
            disp_path = fdata.get('path', '')
            if len(disp_path) > 30: disp_path = f"...{disp_path[-27:]}"

            dtype = "🌐 FTP" if fdata.get("dest_type") == "FTP (Router Storage)" else "🤖 TG"
            mode = "🔄 All" if fdata.get("backup_all", True) else "🆕 New/Mod"
            bot_stat = "📡 Bot On" if fdata.get("bot_requests_enabled", True) else "🔒 Bot Off"
            
            lbl_text = f"📂 {fid} [{dtype} | {mode} | {bot_stat}]\n📍 Path: {disp_path}"
            ctk.CTkLabel(row, text=lbl_text, justify="left", font=("Arial", 12)).pack(side="left", padx=15, pady=10)
            
            btn_container = ctk.CTkFrame(row, fg_color="transparent")
            btn_container.pack(side="right", padx=10)

            if fid in ACTIVE_WORKERS and ACTIVE_WORKERS[fid]["active"]:
                run_txt, run_col = "🟥 Stop", "#d35400"
            else:
                run_txt, run_col = "▶ Run", "#2b7337"

            ctk.CTkButton(btn_container, text=run_txt, width=55, fg_color=run_col, command=lambda f=fid, d=fdata: start_threaded_backup(f, d)).pack(side="left", padx=2)
            ctk.CTkButton(btn_container, text="⚙ Edit", width=50, fg_color="#e67e22", command=lambda f=fid, d=fdata: FolderConfigWindow(self, f, d)).pack(side="left", padx=2)
            ctk.CTkButton(btn_container, text="🗑", width=35, fg_color="#c0392b", command=lambda f=fid: self.delete_profile(f)).pack(side="left", padx=2)

        if not has_profiles:
            ctk.CTkLabel(self.scroll_deck, text="No managed configurations setup. Add one above!").pack(pady=40)

    def delete_profile(self, folder_id):
        config = load_config()
        if folder_id in config:
            del config[folder_id]
            save_config(config)
            self.log(f"Removed profile mapping: {folder_id}")
            self.refresh_dashboard()

if __name__ == "__main__":
    app = DashboardApp()
    app.mainloop()