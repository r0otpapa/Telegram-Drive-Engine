🤖 How to Get Your Telegram Bot Token & Chat ID
If you are routing your backups to Telegram, follow these sequential steps to set up your target pipeline:

Step 1: Generate a Bot Token via BotFather
Open Telegram and launch the official account here: Telegram BotFather.

Send the command /newbot to start the creation process.

Choose a friendly name for your bot (e.g., My Backup System Engine).

Choose a unique username that ends in "bot" (e.g., TarunDriveBackup_bot).

BotFather will reply with an API Access Token. It looks something like this:
123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
Copy this string securely; this is your Bot Token.

Step 2: Retrieve Your Telegram Chat ID
Your backup tool needs to know exactly where to deliver your archives. You can send backups to a Private Chat, a Group, or a Channel.

Option A: Sending to your Personal Private Chat
Click your new bot's link provided by BotFather and tap Start (or send any text message).

Open the following bot utility: Telegram User Info Bot.

Tap Start or send any message to that helper bot, and it will instantly return your unique numeric Chat ID (e.g., 987654321).

Option B: Sending to a Telegram Channel or Group (Recommended for Storage)
Create a new Channel or Group inside your Telegram client application.

Open your Channel/Group details view, go to Administrators, tap Add Admin, and find your custom Bot by typing its username. Grant it standard document/file posting permissions.

Open a web browser window and visit the following web address API tool link (Make sure to replace <YOUR_BOT_TOKEN> with your exact string from Step 1):
https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates

Look through the plain-text system code block response data for the "chat" parent entry string to locate your unique targeting ID.

Note: Target public or private Channel IDs always start with a minus sign and a '100' prefix block (e.g., -100123456789). Ensure you copy the entire numeric value including the negative indicator symbol.

🏗️ Quick Start Implementation
Clone the Repository:

Bash
git clone [https://github.com/your-username/telegram-drive-engine.git](https://github.com/your-username/telegram-drive-engine.git)
cd telegram-drive-engine
Execute the Code Deck:

Bash
python main.py
Establish an Engine Mapping Profile:

Click ➕ Add Folder Profile.

Locate the target directory you want to securely map.

Pick your pipeline strategy (Telegram or FTP (Router Storage)).

Key in your specific Bot API token strings, Chat ID, or local network IP credentials, and toggle auto-run scheduling variables if needed.

📂 Configuration Mapping Scheme
When customized through the GUI dashboard management panel, your setup definitions auto-save locally to backup_config.json:

JSON
{
    "Project_Backup": {
        "path": "C:/Users/Tarun/Documents/Projects",
        "dest_type": "Telegram",
        "zip": true,
        "auto_backup": true,
        "backup_time": "02:00",
        "auto_delete": true,
        "delete_days": 7,
        "token": "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ",
        "chat_id": "-100123456789"
    }
}
📝 Contributor Core Mapping
Lead Engineer: Tarun Sharma

Licensing: Distributed under the MIT Open Source standard format guidelines. Feel free to clone, edit, or adjust as needed!
"""

with open("README.md", "w", encoding="utf-8") as f:
f.write(readme_content)

print("README.md created successfully.")

Your Markdown file is ready
[file-tag: code-generated-file-0-1782692316838738160]

The `README.md` file has been fully compiled and generated with all changes included:
* **Perfect Image Scaling:** Fixed both layout screenshot dimensions using HTML alignment containers set to `width="650"`.
* **Interactive Bot Setup links:** Embedded clickable direct URLs pointing to [Telegram BotFather](https://t.me/BotFather) and the [Telegram User Info Bot](https://t.me/userinfobot) directly. 
* **Complete Documentation Deck:** Retained features list, configuration structure mappings, deployment command lines, prerequisites, and contributor credits.

You can now drop this file directly into the root directory of your GitHub repository.
