# Telegram Drive Engine 🗄️

An automated, cross-platform backup router that packages target system folders into timestamped `.zip` archives (or ships raw data) and mirrors them to a **Telegram Chat/Channel (via Bot API)** or a local/remote **FTP Storage Unit (NAS, Local Cloud, Router Storage)**. Equipped with a modern, responsive interface built via CustomTkinter.

## Key Features 🚀

*   **Dual Storage Pipelines:** Toggle dynamically between Telegram Bot streams and standard FTP network connections.
*   **Asynchronous Engine:** Utilizes isolated thread routing so heavy compression or networking operations never freeze the application UI.
*   **Automated Cron Scheduler:** Built-in lightweight cron-loop checking for scheduled backups to execute precise daily routines seamlessly.
*   **Smart Cache Retention:** Optional rule configurations to instantly purge temporary local zip wrappers or clear historical local logs after a set threshold of days.
*   **Credential Memory:** Tracks past configurations to feed quick dropdown selection cards upon setup modifications.
*   **Console Tracking:** Includes a synchronized event logger for tracing transmission feedback, errors, and task statuses in real-time.

---

## 🛠️ System Prerequisites

Ensure you have Python 3.8 or higher installed on your target machine.

```bash
pip install customtkinter python-telegram-bot
