# 🏛️ Centurion CUTM AI Portal

A premium, fully whitelabeled academic AI assistant portal designed for the students, faculty, and researchers of **Centurion University of Technology and Management (CUTM)**. 

This platform provides an elegant, zero-friction interface powered by **Anthropic Claude API**, optimized for speed, cost, and high concurrent load.

---

## ✨ Features

* **🛡️ Domain Restriction:** Registrations are strictly restricted to official `@cutmap.ac.in` and `@cutm.ac.in` email addresses.
* **🔄 Round-Robin Load Balancing:** Thread-safe key rotator that balances user traffic across up to 4+ Claude API keys simultaneously to prevent rate limiting.
* **⚡ Token Optimization System:**
  * Context capping at the last 20 messages to keep request weights minimal.
  * Ultra-compressed system instruction set saving ~50 tokens per turn.
  * Smart summarization of history for long chats (>30 messages) using the cost-efficient **Claude Haiku** model.
  * Live frontend session token tracking indicator.
* **🎨 Premium UI/UX:** Whitelabeled with Centurion CUTM brand styles, clean dark mode layout, hidden advanced clutter (no projects/artifacts sidebar, hidden design mode, and pruned toolbar).
* **📦 Auto-Deployment Ready:** Single automated script (`setup_ubuntu.sh`) for installing Nginx, Python, MongoDB, firewall rules, SSL Certbot, and daemonizing the server on Ubuntu 22.04 LTS.

---

## 📂 Project Structure

```
d:/BOT AI/
├── BOT AI/                     # Main Web Application Folder
│   ├── index.html              # Chat Monolith & Main Dashboard
│   ├── login.html              # Login & Google One Tap Sign-In Page
│   ├── signup.html             # Email Registration Page
│   ├── admin.html              # Administration Panel for monitoring stats
│   ├── simple_server.py        # Connection-pooled, load-balanced Python Backend
│   ├── database_setup.py       # MongoDB database index & admin seeding script
│   ├── requirements.txt        # Backend dependencies list
│   └── .env.example            # Environment variables template
├── setup_ubuntu.sh             # Production Bare-Metal Ubuntu Setup Script
├── README.md                   # Project Documentation (This File)
└── .gitignore                  # Production Git ignore rules
```

---

## 🛠️ Quick Start (Local Development)

### 1. Prerequisites
Ensure you have the following installed locally:
* **Python 3.10+**
* **MongoDB Community Server** (running locally or a MongoDB Atlas URI)

### 2. Configuration
1. Copy `.env.example` inside the `BOT AI/` folder to `.env`:
   ```bash
   cp "BOT AI/.env.example" "BOT AI/.env"
   ```
2. Open `BOT AI/.env` and configure your credentials:
   * `MONGO_URI`: Your MongoDB Atlas or local connection string.
   * `CLAUDE_API_KEYS`: A comma-separated list of your Claude API keys (e.g. `sk-ant-..., sk-ant-...`).
   * `GOOGLE_CLIENT_ID`: Your Google OAuth 2.0 Web Client ID.

### 3. Initialize the Database
Run the setup script to seed databases, set unique validation indexes, and create the default admin user:
```bash
python "BOT AI/database_setup.py"
```

### 4. Run the Server
Launch the backend server locally:
```bash
python "BOT AI/simple_server.py"
```
The application will be live at: **`http://localhost:3000`**

---

## 🚀 Bare-Metal Ubuntu 22.04 LTS Production Deployment

For deploying to your production server in one step, upload the files and run the included bash script:

```bash
sudo chmod +x setup_ubuntu.sh
sudo ./setup_ubuntu.sh /var/www/cutm-ai
```

The script automatically performs:
1. System package upgrades & installs core tools.
2. Setup of **Python 3.10+**, pip, and virtual environments.
3. Installation, startup, and enabling of **MongoDB v7.0**.
4. Installation and reverse-proxy routing configuration of **Nginx** (Redirecting Port 80 to backend).
5. Daemonization of the server using **Systemd** (autostart on crash or system boot).
6. Setup of **UFW firewall rules** (allowing SSH, HTTP, HTTPS).
7. Setup of **Let's Encrypt Certbot** for zero-friction SSL certificates.

---

## 🔒 Security & Git Best Practices

* **NEVER upload real `.env` files or API Keys to GitHub.**
* The root `.gitignore` is pre-configured to block:
  * `.env` files
  * `client_secret_*.json` (Google Developer credentials)
  * `.venv/` virtual environment folders
  * `__pycache__/` and Python system logs
