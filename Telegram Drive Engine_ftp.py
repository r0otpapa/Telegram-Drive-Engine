import os
import time
import json
import zipfile
import asyncio
import threading
from ftplib import FTP
from datetime import datetime
import customtkinter as ctk
from tkinter import filedialog
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

def get_past_credentials():
    config = load_config()
    tokens = set()
    chat_ids = set()
    ftp_servers = set()
    for folder in config.values():
        if folder.get("token"): tokens.add(folder.get("token").strip())
        if folder.get("chat_id"): chat_ids.add(folder.get("chat_id").strip())
        if folder.get("ftp_server"): ftp_servers.add(folder.get("ftp_server").strip())
    return list(tokens), list(chat_ids), list(ftp_servers)


# ================= BACKGROUND BACKUP ENGINE =================

def safe_log(msg):
    """Safely updates UI components across threads using CustomTkinter's after event scheduler."""
    if 'app' in globals() and app and app.winfo_exists():
        app.after(0, lambda: app.log(msg))

async def upload_pipeline(files_to_upload, token, chat_id, folder_id, should_auto_delete, use_zip):
    """Handles the entire Telegram upload sequence cleanly inside a single async session."""
    bot = Bot(token.strip())
    async with bot:
        for file in files_to_upload:
            try:
                safe_log(f"📤 [{folder_id}] Uploading to Telegram: {os.path.basename(file)}...")
                with open(file, "rb") as f:
                    await bot.send_document(chat_id=chat_id.strip(), document=f)
                safe_log(f"✅ [{folder_id}] Uploaded to Telegram successfully.")

                if should_auto_delete and use_zip:
                    if os.path.exists(file):
                        os.remove(file)
                        safe_log(f"🧹 [Auto-Delete] Purged local archive: {os.path.basename(file)}")
            except Exception as upload_err:
                safe_log(f"❌ [{folder_id}] Telegram upload failed for {os.path.basename(file)}: {str(upload_err)}")

def upload_to_ftp(files_to_upload, server, user, passwd, remote_dir, folder_id, should_auto_delete, use_zip):
    """Handles file transfer to FTP server (Router Storage / NAS / Local Cloud)."""
    try:
        safe_log(f"⚡ [{folder_id}] Connecting to FTP Server: {server}...")
        ftp = FTP(server.strip())
        ftp.login(user=user.strip(), passwd=passwd.strip())
        
        # Change directory if specified
        if remote_dir.strip():
            try:
                ftp.cwd(remote_dir.strip())
            except Exception:
                # Try to create directory if it doesn't exist
                try:
                    ftp.mkd(remote_dir.strip())
                    ftp.cwd(remote_dir.strip())
                except Exception:
                    safe_log(f"⚠️ [{folder_id}] Could not navigate/create remote FTP directory. Saving in root.")

        for file in files_to_upload:
            filename = os.path.basename(file)
            safe_log(f"📤 [{folder_id}] Transferring to FTP Storage: {filename}...")
            with open(file, "rb") as f:
                ftp.storbinary(f"STOR {filename}", f)
            safe_log(f"✅ [{folder_id}] FTP Transfer Success: {filename}")

            if should_auto_delete and use_zip:
                if os.path.exists(file):
                    os.remove(file)
                    safe_log(f"🧹 [Auto-Delete] Purged local archive: {filename}")

        ftp.quit()
    except Exception as ftp_err:
        safe_log(f"❌ [{folder_id}] FTP Transmission Error: {str(ftp_err)}")

def run_folder_backup(folder_id, folder_data):
    try:
        path = folder_data.get("path")
        dest_type = folder_data.get("dest_type", "Telegram")
        use_zip = folder_data.get("zip", True)
        should_auto_delete = folder_data.get("auto_delete", False)
        
        if not path or not os.path.exists(path):
            safe_log(f"❌ [{folder_id}] Source path does not exist: {path}")
            return

        safe_log(f"⏳ [{folder_id}] Analyzing target folder data...")
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

        if not files_to_upload:
            safe_log(f"⚠️ [{folder_id}] No assets found to process.")
            return

        # Core Routing based on Destination Choice
        if dest_type == "FTP (Router Storage)":
            server = folder_data.get("ftp_server")
            user = folder_data.get("ftp_user", "")
            passwd = folder_data.get("ftp_pass", "")
            remote_dir = folder_data.get("ftp_dir", "")
            
            if not server:
                safe_log(f"❌ [{folder_id}] Missing FTP Server configuration link.")
                return
                
            upload_to_ftp(files_to_upload, server, user, passwd, remote_dir, folder_id, should_auto_delete, use_zip)
        else:
            token = folder_data.get("token")
            chat_id = folder_data.get("chat_id")
            if not token or not chat_id:
                safe_log(f"❌ [{folder_id}] Missing Bot Token or Chat ID.")
                return
                
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(upload_pipeline(files_to_upload, token, chat_id, folder_id, should_auto_delete, use_zip))
            finally:
                loop.close()

        # Handle Retention Days Cleanup
        if should_auto_delete:
            days = int(folder_data.get("delete_days", 7))
            now = time.time()
            safe_log(f"🧹 [{folder_id}] Evaluating historical local archives retention limit...")
            for root, _, files in os.walk(BACKUP_DIR):
                for f in files:
                    f_path = os.path.join(root, f)
                    if now - os.path.getmtime(f_path) > (days * 86400):
                        try:
                            os.remove(f_path)
                            safe_log(f"🗑️ Expired local file deleted: {f}")
                        except Exception:
                            pass

        safe_log(f"🎉 [{folder_id}] Full backup pipeline complete!")
    except Exception as e:
        safe_log(f"❌ [{folder_id}] Critical Engine Failure: {str(e)}")

def start_threaded_backup(folder_id, folder_data):
    threading.Thread(target=run_folder_backup, args=(folder_id, folder_data), daemon=True).start()

def run_all_backups():
    config = load_config()
    if not config:
        safe_log("⚠️ No active managed configurations found.")
        return
    for fid, fdata in config.items():
        start_threaded_backup(fid, fdata)


# ================= CRON SCHEDULER ENGINE =================

LAST_FIRED_BACKUPS = {}

def global_scheduler():
    while True:
        check_scheduled_backups()
        time.sleep(30)

def check_scheduled_backups():
    config = load_config()
    now_dt = datetime.now()
    current_time = now_dt.strftime("%H:%M")
    current_date = now_dt.strftime("%Y-%m-%d")

    for fid, fdata in config.items():
        if fdata.get("auto_backup", False) and fdata.get("backup_time", "02:00") == current_time:
            if LAST_FIRED_BACKUPS.get(fid) != f"{current_date}_{current_time}":
                LAST_FIRED_BACKUPS[fid] = f"{current_date}_{current_time}"
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
        self.geometry("580x720")
        self.resizable(False, False)
        
        if os.path.exists("icon.ico"):
            self.iconbitmap("icon.ico")
            
        self.transient(parent)
        self.grab_set()

        past_tokens, past_chats, past_ftps = get_past_credentials()
        self.path_var = ctk.StringVar(value=self.folder_data.get("path", ""))
        
        ctk.CTkLabel(self, text="Folder Profile Configuration", font=("Arial", 18, "bold")).pack(pady=15)
        
        # 1. Path Selector Frame
        p_frame = ctk.CTkFrame(self, fg_color="transparent")
        p_frame.pack(fill="x", padx=30, pady=5)
        self.path_entry = ctk.CTkEntry(p_frame, placeholder_text="Select target system backup path...", textvariable=self.path_var, width=390)
        self.path_entry.pack(side="left", padx=(0, 10))
        ctk.CTkButton(p_frame, text="Browse", width=80, command=self.browse_folder).pack(side="right")

        # 2. Destination Engine Toggle
        ctk.CTkLabel(self, text="Backup Target Destination Platform:", anchor="w").pack(fill="x", padx=30, pady=(10,0))
        self.dest_var = ctk.StringVar(value=self.folder_data.get("dest_type", "Telegram"))
        self.dest_selector = ctk.CTkSegmentedButton(self, values=["Telegram", "FTP (Router Storage)"], variable=self.dest_var, command=self.toggle_destination_fields, width=490)
        self.dest_selector.pack(padx=30, pady=5)

        # Container Frame for Dynamic Fields
        self.dynamic_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.dynamic_frame.pack(fill="x", padx=30, pady=5)

        # 3. Automation & Schedule Settings
        self.auto_var = ctk.BooleanVar(value=self.folder_data.get("auto_backup", False))
        ctk.CTkSwitch(self, text="Enable Automated Schedule Cycle", variable=self.auto_var).pack(anchor="w", padx=30, pady=10)
        
        t_frame = ctk.CTkFrame(self, fg_color="transparent")
        t_frame.pack(fill="x", padx=30, pady=5)
        ctk.CTkLabel(t_frame, text="Daily Time execution format (HH:MM):").pack(side="left")
        self.time_entry = ctk.CTkEntry(t_frame, width=80, placeholder_text="02:00")
        self.time_entry.insert(0, self.folder_data.get("backup_time", "02:00"))
        self.time_entry.pack(side="right")

        # 4. Compression & Cleanup Switches
        self.zip_var = ctk.BooleanVar(value=self.folder_data.get("zip", True))
        ctk.CTkSwitch(self, text="Compress Folder into single (.zip) archive", variable=self.zip_var).pack(anchor="w", padx=30, pady=10)

        self.del_var = ctk.BooleanVar(value=self.folder_data.get("auto_delete", False))
        ctk.CTkSwitch(self, text="Auto-Delete local copies instantly after sending", variable=self.del_var).pack(anchor="w", padx=30, pady=10)
        
        d_frame = ctk.CTkFrame(self, fg_color="transparent")
        d_frame.pack(fill="x", padx=30, pady=5)
        ctk.CTkLabel(d_frame, text="Keep Local Archives Retention (Days Limit):").pack(side="left")
        self.days_entry = ctk.CTkEntry(d_frame, width=80, placeholder_text="7")
        self.days_entry.insert(0, str(self.folder_data.get("delete_days", 7)))
        self.days_entry.pack(side="right")

        # Save Button
        ctk.CTkButton(self, text="Save Profile Configuration", fg_color="#1f538d", height=40, command=self.save_profile).pack(fill="x", padx=30, pady=20)

        # Initial render of dynamic target fields
        self.toggle_destination_fields(self.dest_var.get(), past_tokens, past_chats, past_ftps)

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.path_var.set(folder)

    def toggle_destination_fields(self, selection, past_tokens=[], past_chats=[], past_ftps=[]):
        """Clears and re-builds necessary credentials rows dynamically to keep UI lightweight."""
        for widget in self.dynamic_frame.winfo_children():
            widget.destroy()

        if not past_tokens: # Fetch if triggered via toggle event
            past_tokens, past_chats, past_ftps = get_past_credentials()

        if selection == "FTP (Router Storage)":
            ctk.CTkLabel(self.dynamic_frame, text="FTP Server Host / Router IP Address:", anchor="w").pack(fill="x", pady=(5,0))
            self.ftp_srv_entry = ctk.CTkComboBox(self.dynamic_frame, width=490, values=past_ftps)
            self.ftp_srv_entry.set(self.folder_data.get("ftp_server", ""))
            self.ftp_srv_entry.pack(pady=2)

            # Grid for dual inputs (User / Pass)
            up_frame = ctk.CTkFrame(self.dynamic_frame, fg_color="transparent")
            up_frame.pack(fill="x", pady=5)
            up_frame.columnconfigure(0, weight=1)
            up_frame.columnconfigure(1, weight=1)

            ctk.CTkLabel(up_frame, text="FTP Username:", anchor="w").grid(row=0, column=0, padx=(0,5), sticky="w")
            ctk.CTkLabel(up_frame, text="FTP Password:", anchor="w").grid(row=0, column=1, padx=(5,0), sticky="w")

            self.ftp_user_entry = ctk.CTkEntry(up_frame, placeholder_text="anonymous")
            self.ftp_user_entry.insert(0, self.folder_data.get("ftp_user", ""))
            self.ftp_user_entry.grid(row=1, column=0, padx=(0,5), sticky="ew")

            self.ftp_pass_entry = ctk.CTkEntry(up_frame, placeholder_text="", show="*")
            self.ftp_pass_entry.insert(0, self.folder_data.get("ftp_pass", ""))
            self.ftp_pass_entry.grid(row=1, column=1, padx=(5,0), sticky="ew")

            ctk.CTkLabel(self.dynamic_frame, text="Target Directory path on Storage (Optional):", anchor="w").pack(fill="x", pady=(5,0))
            self.ftp_dir_entry = ctk.CTkEntry(self.dynamic_frame, placeholder_text="/Backups")
            self.ftp_dir_entry.insert(0, self.folder_data.get("ftp_dir", ""))
            self.ftp_dir_entry.pack(fill="x", pady=2)
        else:
            ctk.CTkLabel(self.dynamic_frame, text="Telegram Bot Token:", anchor="w").pack(fill="x", pady=(5,0))
            self.token_entry = ctk.CTkComboBox(self.dynamic_frame, width=490, values=past_tokens)
            self.token_entry.set(self.folder_data.get("token", ""))
            self.token_entry.pack(pady=2)

            ctk.CTkLabel(self.dynamic_frame, text="Telegram Chat ID:", anchor="w").pack(fill="x", pady=(5,0))
            self.chat_entry = ctk.CTkComboBox(self.dynamic_frame, width=490, values=past_chats)
            self.chat_entry.set(self.folder_data.get("chat_id", ""))
            self.chat_entry.pack(pady=2)

    def save_profile(self):
        path = self.path_entry.get().strip()
        dest = self.dest_var.get()
        
        if not path:
            return 
            
        config = load_config()
        fid = self.folder_id if self.folder_id else os.path.basename(path.rstrip(os.sep)) or "Profile"
        
        profile_entry = {
            "path": path,
            "dest_type": dest,
            "zip": self.zip_var.get(),
            "auto_backup": self.auto_var.get(),
            "backup_time": self.time_entry.get().strip() or "02:00",
            "auto_delete": self.del_var.get(),
            "delete_days": int(self.days_entry.get() or 7)
        }

        # Dynamic assignments based on configuration choice
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


# ================= MAIN DASHBOARD UI =================

class DashboardApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Telegram Drive Engine — Dashboard")
        self.geometry("950x675")
        ctk.set_appearance_mode("dark")
        
        if os.path.exists("icon.ico"):
            self.iconbitmap("icon.ico")
        
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, height=70, fg_color="#1a1a1a", corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(header, text="🗄️ Backup Control Deck", font=("Arial", 22, "bold")).pack(side="left", padx=25, pady=15)
        
        actions_frame = ctk.CTkFrame(header, fg_color="transparent")
        actions_frame.pack(side="right", padx=20)
        
        ctk.CTkButton(actions_frame, text="⚡ Run All Backups", fg_color="#2b7337", hover_color="#1e5226", command=run_all_backups).pack(side="left", padx=5)
        ctk.CTkButton(actions_frame, text="➕ Add Folder Profile", fg_color="#1f538d", hover_color="#153b66", command=self.open_add_window).pack(side="left", padx=5)

        main_pane = ctk.CTkFrame(self, fg_color="transparent")
        main_pane.grid(row=1, column=0, sticky="nsew", padx=20, pady=15)
        main_pane.grid_rowconfigure(0, weight=1)
        main_pane.grid_columnconfigure(0, weight=3) 
        main_pane.grid_columnconfigure(1, weight=2) 

        self.scroll_deck = ctk.CTkScrollableFrame(main_pane, label_text="Active Folder Profiles")
        self.scroll_deck.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        log_frame = ctk.CTkFrame(main_pane)
        log_frame.grid(row=0, column=1, sticky="nsew")
        log_frame.grid_rowconfigure(1, weight=1)
        log_frame.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(log_frame, text="📋 Engine Console Logs", font=("Arial", 14, "bold"), anchor="w").grid(row=0, column=0, padx=15, pady=10, sticky="ew")
        self.log_box = ctk.CTkTextbox(log_frame, font=("Courier New", 12), text_color="#a6a6a6")
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0,10))

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
            
            disp_path = fdata.get('path', '')
            if len(disp_path) > 40:
                disp_path = f"...{disp_path[-37:]}"

            # Append the protocol destination into dashboard profile card
            dtype = "🌐 FTP" if fdata.get("dest_type") == "FTP (Router Storage)" else "🤖 TG"
            lbl_text = f"📂 {fid} [{dtype}]\n📍 Path: {disp_path}"
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
    app.mainloop()