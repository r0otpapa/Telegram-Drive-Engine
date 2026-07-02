# 🗄️ Telegram Drive Engine & FTP Backup Automator

A powerful, resizable desktop application built with Python and
CustomTkinter that automates your data backups. It allows you to monitor
multiple folders simultaneously and back up your assets directly to a
**Telegram Private Chat** or an **FTP Server (Router Storage)**. It also
features a built-in Telegram Bot for remote file retrieval without
needing file extensions!

------------------------------------------------------------------------

## 🚀 Key Features

-   **Dual Storage Pipelines:** Seamlessly backup your files either to
    **Telegram Channels/Chats** or **FTP Servers** (like local Router
    Storage).
-   **Intelligent Duplicate & Update Tracking:** Fingerprint tracking
    based on `File Path + Size + Modification Timestamp`. If a file is
    modified or present in multiple folders, the system intelligently
    updates and captures it as a new version.
-   **Extensionless Remote Bot Commands (`/sent`):** Retrieve files
    remotely via Telegram! Just type `/sent filename` without worrying
    about extensions.
-   **Multi-Profile Search Support:** If the same file exists across
    multiple monitored backup profiles, the bot streams all copies
    separately and clearly tags the source profile name.
-   **Fully Resizable Responsive UI:** Built using modern
    `CustomTkinter` with dynamic scaling.
-   **Smart Automation Engine:**
    -   Cron Scheduling
    -   Auto Compression
    -   Retention Policy
    -   Local cleanup after successful transfer

------------------------------------------------------------------------

## 🛠️ Tech Stack & Prerequisites

-   **Language:** Python 3.10+
-   **GUI Framework:** CustomTkinter
-   **Asynchronous Engine:** Asyncio & Threading
-   **API Wrapper:** Python-Telegram-Bot v20+

## 📦 Installation

``` bash
pip install customtkinter python-telegram-bot
```

------------------------------------------------------------------------

## 📂 Project Structure

    backup_config.json
        Stores folder paths, execution times, tokens, and target profiles.

    backup_history.json
        Stores file fingerprints and backup tracking data.

    Backups/
        Temporary compressed backup storage.

------------------------------------------------------------------------

## 🤖 Remote Telegram Bot Commands

  Command     Syntax               Description
  ----------- -------------------- -----------------------------------
  Help        `/help`              Displays available commands
  Send File   `/sent <filename>`   Searches and sends matching files

### Example

Typing:

    /sent invoice

will search for:

    invoice.pdf
    invoice.xlsx
    invoice.png

and return available copies with their source profile names.

------------------------------------------------------------------------

## ⚡ How to Run

1.  Clone or download the repository.
2.  Run:

``` bash
python Telegram Drive Engine.py
python Telegram Drive Engine_ftp.py
```

3.  Click **Add Profile**.
4.  Select folders to monitor.
5.  Configure Telegram Bot Token / Chat ID or FTP details.
6.  Start the Bot Listener.

------------------------------------------------------------------------

## 🤝 Contribution & License

Created with ❤️ by **Tarun Sharma**.

Feel free to fork this repository, submit issues, or create pull
requests to improve the backup pipeline.
