import os
import time
import json
import zipfile
import asyncio
import threading
import schedule
import customtkinter as ctk
from tkinter import filedialog
from datetime import datetime
from telegram import Bot

CONFIG_FILE = "backup_config.json"
BACKUP_DIR = "Backups"

# Ensure global data structures
if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR, exist_ok=True)

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_config(config_data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_data, f, indent=4)

# Helper to get unique past credentials for the dropdown selection list
def get_past_credentials():
    config = load_config()
    tokens = set()
    chat_ids = set()
    for folder in config.values():
        if folder.get("token"): tokens.add(folder.get("token").strip())
        if folder.get("chat_id"): chat_ids.add(folder.get("chat_id").strip())
    return list(tokens), list(chat_ids)


# ================= BACKGROUND BACKUP ENGINE =================

def safe_log(msg):
    """Safely updates UI components across threads using CustomTkinter's after event scheduler."""
    if 'app' in globals() and app.winfo_exists():
        app.after(0, lambda: app.log(msg))

async def upload_file(file_path, token, chat_id):
    bot = Bot(token.strip())
    with open(file_path, "rb") as f:
        await bot.send_document(chat_id=chat_id.strip(), document=f)

def run_folder_backup(folder_id, folder_data):
    try:
        path = folder_data.get("path")
        token = folder_data.get("token")
        chat_id = folder_data.get("chat_id")
        use_zip = folder_data.get("zip", True)
        should_auto_delete = folder_data.get("auto_delete", False)
        
        if not path or not os.path.exists(path):
            safe_log(f"❌ [{folder_id}] Path does not exist: {path}")
            return
        if not token or not chat_id:
            safe_log(f"❌ [{folder_id}] Missing Bot Token or Chat ID.")
            return

        safe_log(f"⏳ [{folder_id}] Starting backup...")
        files_to_upload = []

        if use_zip:
            folder_name = os.path.basename(path.rstrip(os.sep)) or "backup"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_name = f"{folder_name}_{timestamp}.zip"
            zip_path = os.path.join(BACKUP_DIR, zip_name)

            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(path):
                    for file in files:
                        full_path = os.path.join(root, file)
                        zipf.write(full_path, os.path.relpath(full_path, path))
            files_to_upload.append(zip_path)
        else:
            for root, _, files in os.walk(path):
                for file in files:
                    files_to_upload.append(os.path.join(root, file))

        safe_log(f"📤 [{folder_id}] Uploading {len(files_to_upload)} asset(s) to Telegram...")
        
        for file in files_to_upload:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(upload_file(file, token, chat_id))
            loop.close()
            safe_log(f"✅ [{folder_id}] Uploaded: {os.path.basename(file)}")

            # IMMEDIATE AUTO DELETE: Remove file right after successful transfer if enabled
            if should_auto_delete and use_zip:
                try:
                    if os.path.exists(file):
                        os.remove(file)
                        safe_log(f"🧹 [Auto-Delete] Instantly purged temporary local archive: {os.path.basename(file)}")
                except Exception as del_err:
                    safe_log(f"⚠️ [Auto-Delete] Failed immediate purge of {os.path.basename(file)}: {str(del_err)}")

        # Handle Retention Days Cleanup
        if should_auto_delete:
            days = int(folder_data.get("delete_days", 7))
            now = time.time()
            safe_log(f"🧹 [{folder_id}] Checking historical retention local copies...")
            for root, _, files in os.walk(BACKUP_DIR):
                for f in files:
                    f_path = os.path.join(root, f)
                    if now - os.path.getmtime(f_path) > (days * 86400):
                        try:
                            os.remove(f_path)
                            safe_log(f"🗑️ Deleted expired local file: {f}")
                        except Exception as delete_err:
                            pass

        safe_log(f"🎉 [{folder_id}] Full process complete!")
    except Exception as e:
        safe_log(f"❌ [{folder_id}] Critical Error: {str(e)}")

def start_threaded_backup(folder_id, folder_data):
    threading.Thread(target=run_folder_backup, args=(folder_id, folder_data), daemon=True).start()

def run_all_backups():
    config = load_config()
    if not config:
        safe_log("⚠️ No folders managed in the database configuration.")
        return
    for fid, fdata in config.items():
        start_threaded_backup(fid, fdata)

# ================= CRON SCHEDULER ENGINE =================
def global_scheduler():
    schedule.every(1).minute.do(check_scheduled_backups)
    while True:
        schedule.run_pending()
        time.sleep(10)

def check_scheduled_backups():
    config = load_config()
    current_time = datetime.now().strftime("%H:%M")
    for fid, fdata in config.items():
        if fdata.get("auto_backup", False) and fdata.get("backup_time", "02:00") == current_time:
            start_threaded_backup(fid, fdata)

threading.Thread(target=global_scheduler, daemon=True).start()


# ================= UI SUBWINDOWS (MODAL CONFIG) =================

class FolderConfigWindow(ctk.CTkToplevel):
    def __init__(self, parent, folder_id=None, folder_data=None):
        super().__init__(parent)
        self.parent = parent
        self.folder_id = folder_id
        self.folder_data = folder_data or {}
        
        self.title("Folder Settings Manager" if folder_id else "Add Backup Profile")
        self.geometry("550x640")
        self.resizable(False, False)
        
        # Icon Support
        if os.path.exists("icon.ico"):
            self.iconbitmap("icon.ico")
            
        self.transient(parent)
        self.grab_set()

        # Load credential memory lists
        past_tokens, past_chats = get_past_credentials()

        # Target Path Selection
        self.path_var = ctk.StringVar(value=self.folder_data.get("path", ""))
        
        ctk.CTkLabel(self, text="Folder Profile Configuration", font=("Arial", 18, "bold")).pack(pady=15)
        
        # Path Selector Frame
        p_frame = ctk.CTkFrame(self, fg_color="transparent")
        p_frame.pack(fill="x", padx=30, pady=5)
        self.path_entry = ctk.CTkEntry(p_frame, placeholder_text="Select target system backup path...", textvariable=self.path_var, width=360)
        self.path_entry.pack(side="left", padx=(0, 10))
        ctk.CTkButton(p_frame, text="Browse", width=80, command=self.browse_folder).pack(side="right")

        # Telegram Bot Token Selection (Memory Dropdown)
        ctk.CTkLabel(self, text="Telegram Bot Token (Select existing or type new):", anchor="w").pack(fill="x", padx=30, pady=(10,0))
        self.token_entry = ctk.CTkComboBox(self, width=460, values=past_tokens)
        self.token_entry.set(self.folder_data.get("token", ""))
        self.token_entry.pack(padx=30, pady=2)

        # Telegram Chat ID Selection (Memory Dropdown)
        ctk.CTkLabel(self, text="Telegram Chat ID (Select existing or type new):", anchor="w").pack(fill="x", padx=30, pady=(10,0))
        self.chat_entry = ctk.CTkComboBox(self, width=460, values=past_chats)
        self.chat_entry.set(self.folder_data.get("chat_id", ""))
        self.chat_entry.pack(padx=30, pady=2)

        # ZIP settings switches
        self.zip_var = ctk.BooleanVar(value=self.folder_data.get("zip", True))
        ctk.CTkSwitch(self, text="Compress Folder into single (.zip) archive", variable=self.zip_var).pack(anchor="w", padx=30, pady=15)

        # Scheduler Settings
        self.auto_var = ctk.BooleanVar(value=self.folder_data.get("auto_backup", False))
        ctk.CTkSwitch(self, text="Enable Automated Schedule Cycle", variable=self.auto_var).pack(anchor="w", padx=30, pady=5)
        
        t_frame = ctk.CTkFrame(self, fg_color="transparent")
        t_frame.pack(fill="x", padx=30, pady=5)
        ctk.CTkLabel(t_frame, text="Daily Time execution format (HH:MM):").pack(side="left")
        self.time_entry = ctk.CTkEntry(t_frame, width=80, placeholder_text="02:00")
        self.time_entry.insert(0, self.folder_data.get("backup_time", "02:00"))
        self.time_entry.pack(side="right")

        # Purge Local Files Settings
        self.del_var = ctk.BooleanVar(value=self.folder_data.get("auto_delete", False))
        ctk.CTkSwitch(self, text="Auto-Delete local copies instantly after sending", variable=self.del_var).pack(anchor="w", padx=30, pady=10)
        
        d_frame = ctk.CTkFrame(self, fg_color="transparent")
        d_frame.pack(fill="x", padx=30, pady=5)
        ctk.CTkLabel(d_frame, text="Keep Local Archives Retention (Days Limit):").pack(side="left")
        self.days_entry = ctk.CTkEntry(d_frame, width=80, placeholder_text="7")
        self.days_entry.insert(0, str(self.folder_data.get("delete_days", 7)))
        self.days_entry.pack(side="right")

        # Action Buttons
        ctk.CTkButton(self, text="Save Profile Configuration", fg_color="#1f538d", height=40, command=self.save_profile).pack(fill="x", padx=30, pady=25)

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.path_var.set(folder)

    def save_profile(self):
        path = self.path_entry.get().strip()
        token = self.token_entry.get().strip()
        chat = self.chat_entry.get().strip()
        
        if not path or not token or not chat:
            return 
            
        config = load_config()
        fid = self.folder_id if self.folder_id else os.path.basename(path.rstrip(os.sep)) or "Profile"
        
        config[fid] = {
            "path": path,
            "token": token,
            "chat_id": chat,
            "zip": self.zip_var.get(),
            "auto_backup": self.auto_var.get(),
            "backup_time": self.time_entry.get().strip() or "02:00",
            "auto_delete": self.del_var.get(),
            "delete_days": int(self.days_entry.get() or 7)
        }
        
        save_config(config)
        self.parent.refresh_dashboard()
        self.destroy()


# ================= MAIN DASHBOARD UI =================

class DashboardApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Drive Engine — Dashboard")
        self.geometry("950x675")
        ctk.set_appearance_mode("dark")
        
        # Taskbar and Window Icon Setup
        if os.path.exists("icon.ico"):
            self.iconbitmap("icon.ico")
        
        # Grid layout allocation
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0) # Row allocated for footer elements
        self.grid_columnconfigure(0, weight=1)

        # Header Title Deck
        header = ctk.CTkFrame(self, height=70, fg_color="#1a1a1a", corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(header, text="🗄️ Backup Control Deck", font=("Arial", 22, "bold")).pack(side="left", padx=25, pady=15)
        
        # Batch Controller Buttons
        actions_frame = ctk.CTkFrame(header, fg_color="transparent")
        actions_frame.pack(side="right", padx=20)
        
        ctk.CTkButton(actions_frame, text="⚡ Run All Backups", fg_color="#2b7337", hover_color="#1e5226", command=run_all_backups).pack(side="left", padx=5)
        ctk.CTkButton(actions_frame, text="➕ Add Folder Profile", fg_color="#1f538d", hover_color="#153b66", command=self.open_add_window).pack(side="left", padx=5)

        # Main Dynamic Dashboard Area
        main_pane = ctk.CTkFrame(self, fg_color="transparent")
        main_pane.grid(row=1, column=0, sticky="nsew", padx=20, pady=15)
        main_pane.grid_rowconfigure(0, weight=1)
        main_pane.grid_columnconfigure(0, weight=3) 
        main_pane.grid_columnconfigure(1, weight=2) 

        # Left Column: Managed Profiles
        self.scroll_deck = ctk.CTkScrollableFrame(main_pane, label_text="Active Folder Profiles")
        self.scroll_deck.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        # Right Column: UI Console Logging Output
        log_frame = ctk.CTkFrame(main_pane)
        log_frame.grid(row=0, column=1, sticky="nsew")
        log_frame.grid_rowconfigure(1, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(log_frame, text="📋 Engine Console Logs", font=("Arial", 14, "bold"), anchor="w").grid(row=0, column=0, padx=15, pady=10, sticky="ew")
        self.log_box = ctk.CTkTextbox(log_frame, font=("Courier New", 12), text_color="#a6a6a6")
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0,10))

        # ================= FOOTER APP BRAND DECK =================
        footer_frame = ctk.CTkFrame(self, height=30, fg_color="#141414", corner_radius=0)
        footer_frame.grid(row=2, column=0, sticky="ew")
        
        ctk.CTkLabel(
            footer_frame, 
            text="Created by Tarun Sharma", 
            font=("Arial", 11, "italic"), 
            text_color="#6e6e6e"
        ).pack(pady=4)

        self.refresh_dashboard()

    def log(self, msg):
        self.log_box.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log_box.see("end")

    def open_add_window(self):
        FolderConfigWindow(self)

    def refresh_dashboard(self):
        for child in self.scroll_deck.winfo_children():
            child.destroy()

        config = load_config()
        if not config:
            ctk.CTkLabel(self.scroll_deck, text="No managed configurations setup. Add one above!").pack(pady=40)
            return

        for fid, fdata in config.items():
            row = ctk.CTkFrame(self.scroll_deck, height=80)
            row.pack(fill="x", pady=6, padx=5)
            
            disp_path = fdata.get('path')
            if len(disp_path) > 40:
                disp_path = f"...{disp_path[-37:]}"

            lbl_text = f"📂 {fid}\n📍 Path: {disp_path}"
            if fdata.get("auto_backup"):
                lbl_text += f"  |  ⏰ Time: {fdata.get('backup_time')}"
                
            ctk.CTkLabel(row, text=lbl_text, justify="left", font=("Arial", 12)).pack(side="left", padx=15, pady=10)
            
            btn_container = ctk.CTkFrame(row, fg_color="transparent")
            btn_container.pack(side="right", padx=10)

            ctk.CTkButton(btn_container, text="▶ Run", width=55, fg_color="#2b7337", command=lambda f=fid, d=fdata: start_threaded_backup(f, d)).pack(side="left", padx=2)
            ctk.CTkButton(btn_container, text="⚙ Edit", width=55, fg_color="#e67e22", command=lambda f=fid, d=fdata: FolderConfigWindow(self, f, d)).pack(side="left", padx=2)
            ctk.CTkButton(btn_container, text="🗑 Delete", width=65, fg_color="#c0392b", command=lambda f=fid: self.delete_profile(f)).pack(side="left", padx=2)

    def delete_profile(self, folder_id):
        config = load_config()
        if folder_id in config:
            del config[folder_id]
            save_config(config)
            self.log(f"Removed system profile entry mapping: {folder_id}")
            self.refresh_dashboard()

if __name__ == "__main__":
    app = DashboardApp()
    main_instance = app  # Map standard initialization
    app.mainloop()