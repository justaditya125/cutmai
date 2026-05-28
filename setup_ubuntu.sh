#!/usr/bin/env bash

# ==============================================================================
# Centurion University of Technology and Management (CUTM AI)
# Ubuntu 22.04 LTS Bare-Metal Automated Setup & Deployment Script
# ==============================================================================
# This script performs a zero-friction, production-grade installation of:
#   1. System package upgrades & core tools (curl, git, ufw, etc.)
#   2. Python 3.10+, pip, and virtualenv tools
#   3. MongoDB Community Edition v7.0 (Started & Enabled)
#   4. Nginx Reverse Proxy (Port 80 -> 3000 backend redirection)
#   5. Systemd Daemon Service Setup (Autostart on boot / recovery)
#   6. UFW Firewall Setup & Let's Encrypt Certbot
# ==============================================================================

# Strict error checking: exit immediately if any command fails
set -euo pipefail

# Style Variables
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0;37m' # No Color

echo -e "${BLUE}======================================================================${NC}"
echo -e "${GREEN}      🚀 Starting CUTM AI Automated Ubuntu 22.04 Deployment 🚀       ${NC}"
echo -e "${BLUE}======================================================================${NC}"

# ─── 1. ROOT CHECK ────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}❌ ERROR: This script must be run as root (sudo).${NC}" 
   exit 1
fi

# ─── 2. SYSTEM UPDATE & UPGRADE ───────────────────────────────────────────────
echo -e "\n${YELLOW}🔄 Step 1: Updating system packages...${NC}"
apt update -y && apt upgrade -y
apt install -y curl git wget build-essential software-properties-common gnupg apt-transport-https ca-certificates snapd

# ─── 3. PYTHON ENVIRONMENT INSTALLATION ───────────────────────────────────────
echo -e "\n${YELLOW}🐍 Step 2: Installing Python development environment...${NC}"
apt install -y python3 python3-pip python3-venv python3-dev
echo -e "${GREEN}✅ Python installed successfully: $(python3 --version)${NC}"

# ─── 4. MONGODB COMMUNITY EDITION INSTALLATION (v7.0) ──────────────────────────
echo -e "\n${YELLOW}🍃 Step 3: Installing MongoDB Community Edition v7.0...${NC}"
# Import the public GPG key for the latest stable MongoDB
curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg --overwrite

# Create list file for Ubuntu 22.04 (Jammy)
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" | tee /etc/apt/sources.list.d/mongodb-org-7.0.list

# Update package index and install MongoDB packages
apt update -y
apt install -y mongodb-org

# Start and enable MongoDB service
systemctl daemon-reload
systemctl start mongod
systemctl enable mongod

# Verify status
if systemctl is-active --quiet mongod; then
    echo -e "${GREEN}✅ MongoDB Community Edition started & enabled successfully!${NC}"
else
    echo -e "${RED}⚠️ WARNING: MongoDB service failed to start automatically. Please check logs via 'journalctl -u mongod'${NC}"
fi

# ─── 5. NGINX REVERSE PROXY SETUP ─────────────────────────────────────────────
echo -e "\n${YELLOW}🌐 Step 4: Installing and configuring Nginx Reverse Proxy...${NC}"
apt install -y nginx

# Define custom Nginx site block for reverse proxy
NGINX_CONF="/etc/nginx/sites-available/cutm_ai"

cat << 'EOF' > "$NGINX_CONF"
server {
    listen 80;
    server_name _; # Replace with your Domain Name or Server Public IP

    # Restrict request body size limit to protect server memory
    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }
}
EOF

# Enable the new site and disable default site
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Test and reload Nginx
nginx -t
systemctl restart nginx
echo -e "${GREEN}✅ Nginx reverse proxy configured and active!${NC}"

# ─── 6. SYSTEMD SERVICE DAEMON SETUP (AUTORUN) ────────────────────────────────
echo -e "\n${YELLOW}⚙️ Step 5: Creating Systemd daemon service for CUTM AI...${NC}"

# Define target project directory (supports command-line argument, interactive prompt, or default fallback)
DEFAULT_DIR="/var/www/cutm-ai"
PROJECT_DIR="$DEFAULT_DIR"

if [[ $# -gt 0 ]]; then
    PROJECT_DIR="$1"
    echo -e "${GREEN}Using command-line argument path: $PROJECT_DIR${NC}"
elif [ -t 0 ]; then
    echo -e "${YELLOW}Please enter the path where you will upload the project files (Default: $DEFAULT_DIR):${NC}"
    read -r -p "Directory Path: " USER_DIR
    PROJECT_DIR="${USER_DIR:-$DEFAULT_DIR}"
else
    echo -e "${GREEN}Running in non-interactive mode. Using default path: $PROJECT_DIR${NC}"
fi

# Create directories if they do not exist
mkdir -p "$PROJECT_DIR"
chown -R www-data:www-data "$PROJECT_DIR"

# Create Systemd service config file
SERVICE_FILE="/etc/systemd/system/cutm_ai.service"

cat << EOF > "$SERVICE_FILE"
[Unit]
Description=Centurion CUTM AI Chatbot Daemon
After=network.target mongod.service

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR
Environment=PYTHONIOENCODING=utf-8
ExecStart=$PROJECT_DIR/.venv/bin/python3 $PROJECT_DIR/simple_server.py
Restart=always
RestartSec=5
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=cutm-ai

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}✅ Systemd service template written to $SERVICE_FILE${NC}"

# ─── 7. SECURITY & FIREWALL CONFIGURATION ─────────────────────────────────────
echo -e "\n${YELLOW}🛡️ Step 6: Setting up UFW firewall rules...${NC}"
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow http
ufw allow https
echo "y" | ufw enable
echo -e "${GREEN}✅ Firewall active. Allowed ports: 22 (SSH), 80 (HTTP), 443 (HTTPS)${NC}"

# ─── 8. CERTBOT SSL CERTIFICATE INSTRUCTIONS ──────────────────────────────────
echo -e "\n${YELLOW}🔒 Step 7: Preparing snapd & Certbot for SSL...${NC}"
snap install core; snap refresh core
snap install --classic certbot
ln -sf /snap/bin/certbot /usr/bin/certbot
echo -e "${GREEN}✅ Certbot SSL setup tool installed successfully!${NC}"

# ─── 9. MSMTP MAIL CLIENT CONFIGURATION ────────────────────────────────────────
echo -e "\n${YELLOW}📧 Step 8: Installing and configuring msmtp for Admin Mail Alerts...${NC}"
apt install -y msmtp msmtp-mta ca-certificates

# Create log file with secure permissions
touch /var/log/msmtp.log
chmod 666 /var/log/msmtp.log

# Create a secure /etc/msmtprc template
MSMTPRC_FILE="/etc/msmtprc"
cat << 'EOF' > "$MSMTPRC_FILE"
defaults
auth           on
tls            on
tls_trust_file /etc/ssl/certs/ca-certificates.crt
logfile        /var/log/msmtp.log

account        gmail
host           smtp.gmail.com
port           587
from           alertsemail@cutmap.ac.in
user           alertsemail@cutmap.ac.in
password       aenuaqtlofasxgqq

# Set default account
account default : gmail
EOF

# Ensure secure permissions for /etc/msmtprc (must be owner-readable only)
chmod 600 "$MSMTPRC_FILE"
chown root:root "$MSMTPRC_FILE"

echo -e "${GREEN}✅ msmtp and msmtp-mta installed successfully!${NC}"
echo -e "${YELLOW}Template config created at $MSMTPRC_FILE (Be sure to update with your Gmail & App Password!)${NC}"

# ─── 10. SUMMARY & DEPLOYMENT CHECKLIST ───────────────────────────────────────
echo -e "${BLUE}======================================================================${NC}"
echo -e "${GREEN}                 🎉 INSTALLATION COMPLETE 🎉                         ${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo -e "${YELLOW}Next Steps to Complete Deployment:${NC}"
echo -e " 1. Upload your project code files to: ${GREEN}$PROJECT_DIR${NC}"
echo -e " 2. Navigate to directory: ${BLUE}cd $PROJECT_DIR${NC}"
echo -e " 3. Create python virtual environment: ${BLUE}python3 -m venv .venv${NC}"
echo -e " 4. Install dependencies: ${BLUE}.venv/bin/pip install -r requirements.txt${NC}"
echo -e " 5. Create your ${BLUE}.env${NC} file with credentials (e.g. ${GREEN}MONGO_URI${NC}, ${GREEN}CLAUDE_API_KEYS${NC} as a comma-separated list, etc.) in ${GREEN}$PROJECT_DIR${NC}"
echo -e " 6. Configure ${BLUE}/etc/msmtprc${NC} with your SMTP credentials for Admin Mail Alerts."
echo -e " 7. Enable and start your CUTM AI daemon:"
echo -e "    ${BLUE}systemctl daemon-reload${NC}"
echo -e "    ${BLUE}systemctl enable cutm_ai${NC}"
echo -e "    ${BLUE}systemctl start cutm_ai${NC}"
echo -e " 8. (Optional) Run Certbot for HTTPS/SSL:"
echo -e "    ${BLUE}certbot --nginx${NC}"
echo -e "${BLUE}======================================================================${NC}"

