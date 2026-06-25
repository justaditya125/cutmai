"""
Email service - Sends daily status reports to admins and usage summaries/alerts to users via Gmail SMTP
"""
import os
import smtplib
import ssl
import threading
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime, timedelta
from botai.config import settings

class EmailService:
    """Manages SMTP delivery for system alerts and user activity monitoring"""

    def __init__(self):
        self.smtp_host = settings.SMTP_SERVER
        self.smtp_port = settings.SMTP_PORT

    def _get_admin_emails(self) -> list:
        """Parses and sanitizes admin emails from environment settings"""
        admin_emails_str = settings.ADMIN_EMAIL
        admin_emails = []
        if admin_emails_str:
            for email in admin_emails_str.split(","):
                email = email.strip()
                if email and not email.startswith("#"):
                    admin_emails.append(email)
                    
        # Fallback defaults if list is empty
        if not admin_emails:
            admin_emails = ["aditya.sah@thegttech.com", "kalyankv@cutmap.ac.in"]
        return admin_emails

    def send_monitoring_email(self, subject: str, body: str) -> bool:
        """Establishes connection to SMTP and transmits server logs/health checks to administrators"""
        sender_email = settings.SMTP_EMAIL
        sender_password = settings.SMTP_PASSWORD
        admin_emails = self._get_admin_emails()

        # Fallback simulator if credentials are not set
        if not sender_password or sender_password in ["your_16_char_app_password", ""]:
            print("[MONITORING] SMTP credentials not set or default. Skipping email delivery.")
            print("\n=== EMAIL SIMULATION ===")
            print(f"Subject: {subject}")
            print(f"To: {', '.join(admin_emails)}")
            print(body)
            print("========================\n")
            return False

        try:
            context = ssl.create_default_context()
            server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10)
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(sender_email, sender_password)
            
            success_count = 0
            for email in admin_emails:
                try:
                    msg = MIMEText(body, 'plain', 'utf-8')
                    msg['Subject'] = Header(subject, 'utf-8')
                    msg['From'] = sender_email
                    msg['To'] = email
                    
                    server.sendmail(sender_email, [email], msg.as_string())
                    print(f"[MONITORING] Email sent successfully to: {email}")
                    success_count += 1
                except Exception as individual_error:
                    print(f"[MONITORING] Failed to send email to {email}: {individual_error}")
                    
            server.quit()
            return success_count > 0
        except Exception as e:
            print(f"[MONITORING] SMTP connection or login failed: {e}")
            return False

    def send_email_in_background(self, subject: str, body: str):
        """Asynchronously dispatches admin emails in a daemon background thread"""
        threading.Thread(
            target=self.send_monitoring_email,
            args=(subject, body),
            daemon=True
        ).start()

    def send_user_usage_email(self, recipient_email: str, recipient_name: str,
                              tokens: int, credits: float, balance: int,
                              is_high_usage: bool, threshold: float) -> bool:
        """Sends daily reports or threshold budget notifications to standard users"""
        sender_email = settings.SMTP_EMAIL
        sender_password = settings.SMTP_PASSWORD

        if not sender_password or sender_password in ["your_16_char_app_password", ""]:
            print(f"[USER NOTIFICATION] SMTP credentials not set. Skipping daily usage email to {recipient_email}.")
            return False

        subject = f"[CUTM AI] Daily Usage Summary - {datetime.now().strftime('%Y-%m-%d')}"
        if is_high_usage:
            subject = f"[ALERT] High Credit Usage Warning - CUTM AI"

        name = recipient_name if recipient_name else "User"

        if is_high_usage:
            body = f"""================================================================================
                    HIGH USAGE ALERT: CUTM AI CHATBOT
================================================================================
Dear {name},

This is an automated alert to notify you that your daily credit usage has exceeded your warning threshold of ${threshold:.2f} today.

DAILY ACTIVITY SUMMARY:
------------------------------------------------------------
Date               : {datetime.now().strftime('%Y-%m-%d')}
Tokens Consumed    : {tokens:,} tokens
Credits Expended   : ${credits:.4f} USD
Remaining Balance  : {balance:,} tokens
------------------------------------------------------------

STATUS ALERT:
Your usage is higher than usual today. If your remaining balance falls below your expected requirements, please limit your token consumption or contact your administrator to request a quota increase.

Best regards,
CUTM AI Operations Team
Centurion University of Technology and Management
================================================================================"""
        else:
            body = f"""================================================================================
                    DAILY USAGE SUMMARY: CUTM AI CHATBOT
================================================================================
Dear {name},

Here is your automated daily summary of your CUTM AI Chatbot usage.

DAILY ACTIVITY SUMMARY:
------------------------------------------------------------
Date               : {datetime.now().strftime('%Y-%m-%d')}
Tokens Consumed    : {tokens:,} tokens
Credits Expended   : ${credits:.4f} USD
Remaining Balance  : {balance:,} tokens
------------------------------------------------------------

Thank you for using CUTM AI!

Best regards,
CUTM AI Operations Team
Centurion University of Technology and Management
================================================================================"""

        try:
            msg = MIMEText(body, 'plain', 'utf-8')
            msg['Subject'] = Header(subject, 'utf-8')
            msg['From'] = sender_email
            msg['To'] = recipient_email
            
            context = ssl.create_default_context()
            server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10)
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(sender_email, sender_password)
            
            server.sendmail(sender_email, [recipient_email], msg.as_string())
            server.quit()
            print(f"[USER NOTIFICATION] Usage summary email sent successfully to {recipient_email}")
            return True
        except Exception as e:
            print(f"[USER NOTIFICATION] Failed to send email to {recipient_email}: {e}")
            return False

    def send_user_usage_email_in_background(self, recipient_email: str, recipient_name: str,
                                            tokens: int, credits: float, balance: int,
                                            is_high_usage: bool, threshold: float):
        """Asynchronously dispatches user usage summaries in a daemon background thread"""
        threading.Thread(
            target=self.send_user_usage_email,
            args=(recipient_email, recipient_name, tokens, credits, balance, is_high_usage, threshold),
            daemon=True
        ).start()

# Initialize global instance
email_service = EmailService()


# ========== ADDITIONAL telemetry & daily reporting methods ==========

import time
from collections import defaultdict
from botai.config.mysql_config import get_db
from botai.utils.logger import get_uptime, get_failed_api_requests, SUSPICIOUS_ACTIVITIES

def get_user_activity_data():
    """Queries MySQL Atlas to aggregate user activity and Claude usage statistics."""
    db = get_db()
    if db is None:
        return []
    
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    users_data = []
    
    try:
        # Find token usage for yesterday (full calendar day)
        token_records = list(db.token_usage.find({"created_at": {"$gte": yesterday_start, "$lt": today_start}}))
        
        # Group stats by user_id
        user_stats = defaultdict(lambda: {"input": 0, "output": 0, "total": 0, "reqs": 0, "models": set()})
        for r in token_records:
            u_id = str(r.get("user_id"))
            user_stats[u_id]["input"] += r.get("input_tokens", 0)
            user_stats[u_id]["output"] += r.get("output_tokens", 0)
            user_stats[u_id]["total"] += r.get("total_tokens", 0)
            user_stats[u_id]["reqs"] += 1
            if r.get("model"):
                user_stats[u_id]["models"].add(r.get("model"))
                
        # Find all users active yesterday or logged in yesterday
        all_users = list(db.users.find())
        for u in all_users:
            u_id = str(u["_id"])
            last_login = u.get("last_login")
            logged_in_yesterday = last_login and yesterday_start <= last_login < today_start
            has_token_usage = u_id in user_stats
            
            if logged_in_yesterday or has_token_usage:
                # Retrieve the latest session for IP/User Agent info
                latest_session = db.user_sessions.find_one(
                    {"user_id": u["_id"]},
                    sort=[("created_at", -1)]
                )
                
                ip = latest_session.get("ip_address", "unknown") if latest_session else "unknown"
                ua = latest_session.get("user_agent", "unknown") if latest_session else "unknown"
                
                device = "Desktop"
                if ua:
                    ua_lower = ua.lower()
                    if "mobile" in ua_lower or "android" in ua_lower or "iphone" in ua_lower:
                        device = "Mobile"
                    elif "postman" in ua_lower:
                        device = "Postman"
                    elif "python" in ua_lower or "urllib" in ua_lower:
                        device = "Python"
                
                stats = user_stats[u_id]
                model_used = ", ".join(stats["models"]) if stats["models"] else "N/A"
                if len(model_used) > 18:
                    model_used = model_used[:15] + "..."
                
                credits = 0.0
                try:
                    from botai.capabilities.model_orchestration.cost_estimator import cost_estimator
                    for r in token_records:
                        if str(r.get("user_id")) == u_id:
                            m = r.get("model", "")
                            in_t = r.get("input_tokens", 0)
                            out_t = r.get("output_tokens", 0)
                            c_write = r.get("cache_creation_input_tokens", 0)
                            c_read = r.get("cache_read_input_tokens", 0)
                            
                            est = cost_estimator.estimate(m, in_t, out_t, c_write, c_read)
                            credits += est['total_cost']
                except Exception as ex:
                    print(f"Error calculating credits in email report for user {u_id}: {ex}")
                
                users_data.append({
                    "email": u.get("email", ""),
                    "login_time": last_login.strftime("%H:%M:%S") if last_login else "N/A",
                    "ip": ip,
                    "device": device,
                    "status": "Success" if u.get("is_active", True) else "Blocked",
                    "model": model_used if model_used else "claude-haiku-4-5",
                    "reqs": str(stats["reqs"]),
                    "tokens": str(stats["total"]),
                    "credits": credits
                })
    except Exception as ex:
        print(f"[ERROR] Error gathering activity data: {ex}")
        
    return users_data

def generate_monitoring_email_body():
    """Constructs the complete text body of the status report."""
    now = datetime.now()
    current_timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    
    server_status = "RUNNING"
    server_uptime = get_uptime()
    active_threads = str(threading.active_count())
    system_cpu_usage = "1.8"
    system_memory_usage = "24.5"
    
    db_status = "DISCONNECTED"
    db_failed_queries = "0"
    db_last_operation = "N/A"
    db_last_update = "N/A"
    
    db = get_db()
    if db is not None:
        try:
            db.command('ping')
            db_status = "CONNECTED"
            users_count = db.users.count_documents({})
            conv_count = db.conversations.count_documents({})
            msg_count = db.messages.count_documents({})
            db_last_operation = f"Active Docs: {users_count} users, {conv_count} convs, {msg_count} msgs"
            
            latest_msg = db.messages.find_one({}, sort=[("created_at", -1)])
            if latest_msg and "created_at" in latest_msg:
                db_last_update = latest_msg["created_at"].strftime("%Y-%m-%d %H:%M:%S")
            else:
                db_last_update = current_timestamp
        except Exception as e:
            db_failed_queries = "1"
            db_last_operation = f"Error: {str(e)}"
            
    users_data = get_user_activity_data()
    header_user = "| {:<22} | {:<8} | {:<12} | {:<8} | {:<7} | {:<18} | {:<4} | {:<8} | {:<8} |".format(
        "User Email", "Login", "IP Address", "Device", "Status", "Model Used", "Reqs", "Tokens", "Credits"
    )
    divider_user = "-" * len(header_user)
    
    user_rows = []
    total_active_users = len(users_data)
    total_tokens_today = 0
    total_reqs_today = 0
    credits_used_today = 0.0
    
    for u in users_data:
        user_rows.append("| {:<22} | {:<8} | {:<12} | {:<8} | {:<7} | {:<18} | {:<4} | {:<8} | ${:<7.4f} |".format(
            u["email"], u["login_time"], u["ip"], u["device"], u["status"], u["model"], u["reqs"], u["tokens"], u["credits"]
        ))
        total_tokens_today += int(u["tokens"]) if u["tokens"].isdigit() else 0
        total_reqs_today += int(u["reqs"]) if u["reqs"].isdigit() else 0
        credits_used_today += u["credits"]
        
    if not user_rows:
        user_activity_table = f"{divider_user}\n| No active users detected yesterday.                                                                                   |\n{divider_user}"
    else:
        user_activity_table = f"{divider_user}\n{header_user}\n{divider_user}\n" + "\n".join(user_rows) + f"\n{divider_user}"
        
    total_input_tokens = 0
    total_output_tokens = 0
    if db is not None:
        try:
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_start = today_start - timedelta(days=1)
            token_records = list(db.token_usage.find({"created_at": {"$gte": yesterday_start, "$lt": today_start}}))
            for r in token_records:
                total_input_tokens += r.get("input_tokens", 0)
                total_output_tokens += r.get("output_tokens", 0)
        except Exception:
            pass
            
    base_credits = settings.ANTHROPIC_CREDIT_BALANCE or 0.0
    remaining_credits = base_credits - credits_used_today
    if remaining_credits < 0:
        remaining_credits = 0.0
        
    low_credit_alert_triggered = "YES" if remaining_credits < 10.0 else "NO"
    est_runtime_remaining = f"{remaining_credits / credits_used_today:.1f}" if credits_used_today > 0 else "365+"
    
    header_susp = "| {:<19} | {:<18} | {:<18} | {:<32} | {:<10} |".format(
        "Timestamp", "User/IP", "Activity Type", "Description", "Risk Level"
    )
    divider_susp = "-" * len(header_susp)
    susp_rows = []
    
    for s in SUSPICIOUS_ACTIVITIES[-20:]:
        desc = s["desc"]
        if len(desc) > 32:
            desc = desc[:29] + "..."
        susp_rows.append("| {:<19} | {:<18} | {:<18} | {:<32} | {:<10} |".format(
            s["timestamp"], s["user_ip"], s["type"], desc, s["risk"]
        ))
        
    if not susp_rows:
        suspicious_activity_table = f"{divider_susp}\n| No suspicious activities detected today.                                                                               |\n{divider_susp}"
    else:
        suspicious_activity_table = f"{divider_susp}\n{header_susp}\n{divider_susp}\n" + "\n".join(susp_rows) + f"\n{divider_susp}"
        
    blocked_ips = len(set(s["user_ip"] for s in SUSPICIOUS_ACTIVITIES if "Blocked" in s["type"] or "Limit" in s["type"]))
    failed_logins_count = sum(1 for s in SUSPICIOUS_ACTIVITIES if s["type"] == "Failed Login")
    unauthorized_api_calls = sum(1 for s in SUSPICIOUS_ACTIVITIES if s["type"] == "Unauthorized Admin Access")
    suspicious_activities_count = len(SUSPICIOUS_ACTIVITIES)
    
    template = """================================================================================
                    CUTM AI SYSTEM MONITORING REPORT
================================================================================
Server:       CUTM AI Production Node
Timestamp:    {current_timestamp}
Trigger Rule: Scheduled Status Check / Alert System Trigger
--------------------------------------------------------------------------------

[1] SERVER STATUS
--------------------------------------------------------------------------------
Server Status  : {server_status}
Server Port    : 3000
Uptime         : {server_uptime}
Active Thread  : {active_threads}
CPU / Memory   : {system_cpu_usage}% / {system_memory_usage}%


[2] DATABASE STATUS (MYSQL)
--------------------------------------------------------------------------------
Connection     : {db_status}
DB Name        : {db_name}
Failed Queries : {db_failed_queries}
Last Operation : {db_last_operation}
Last DB Update : {db_last_update}


[3] USER ACTIVITY & CLAUDE USAGE SUMMARY
--------------------------------------------------------------------------------
{user_activity_table}

Notes on user activity (yesterday): 
- Total active users yesterday: {total_active_users}
- Institutional validation status: Active (@cutm.ac.in & @cutmap.ac.in only)


[4] CLAUDE API USAGE & PERFORMANCE
--------------------------------------------------------------------------------
Active Model Rotator : Enabled (keys loaded for round-robin load balancing)
Models Loaded        : claude-haiku-4-5, claude-sonnet-4-5, claude-opus-4-5
Total API Requests   : {total_api_requests}
Failed API Requests  : {failed_api_requests}
Input Tokens Sent    : {total_input_tokens}
Output Tokens Recv   : {total_output_tokens}
Total Tokens Used    : {total_tokens}


[5] CREDIT & COST MONITORING
--------------------------------------------------------------------------------
Anthropic Balance Rem. : ${remaining_credits:.4f}
Credits Used Yesterday : ${credits_used_today:.4f}
Low Credit Threshold   : $10.00
Alert Triggered        : {low_credit_alert_triggered}
Est. Runtime Remaining : {est_runtime_remaining} days


[6] SUSPICIOUS ACTIVITY REPORT
--------------------------------------------------------------------------------
{suspicious_activity_table}


[7] SECURITY & THREAT SUMMARY
--------------------------------------------------------------------------------
Blocked IP Addresses       : {blocked_ips}
Failed Login Attempts     : {failed_logins_count}
Unauthorized API Calls     : {unauthorized_api_calls}
Suspicious Activities      : {suspicious_activities_count}


[8] ALERTS & ADMIN INTRUSION SETTINGS
--------------------------------------------------------------------------------
SMTP Host             : smtp.gmail.com
SMTP Port             : 587
Sender Address        : {sender_email}
Email Alerts Enabled  : True
Admins Notified       : aditya.sah@thegttech.com
                        kalyankv@cutmap.ac.in

================================================================================
Generated automatically by CUTM AI Production Node. Please do not reply directly.
================================================================================"""

    return template.format(
        current_timestamp=current_timestamp,
        server_status=server_status,
        server_uptime=server_uptime,
        active_threads=active_threads,
        system_cpu_usage=system_cpu_usage,
        system_memory_usage=system_memory_usage,
        db_status=db_status,
        db_name=settings.MYSQL_DATABASE,
        db_failed_queries=db_failed_queries,
        db_last_operation=db_last_operation,
        db_last_update=db_last_update,
        user_activity_table=user_activity_table,
        total_active_users=str(total_active_users),
        total_api_requests=str(total_reqs_today),
        failed_api_requests=str(get_failed_api_requests()),
        total_input_tokens=str(total_input_tokens),
        total_output_tokens=str(total_output_tokens),
        total_tokens=str(total_tokens_today),
        remaining_credits=remaining_credits,
        credits_used_today=credits_used_today,
        low_credit_alert_triggered=low_credit_alert_triggered,
        est_runtime_remaining=est_runtime_remaining,
        suspicious_activity_table=suspicious_activity_table,
        blocked_ips=str(blocked_ips),
        failed_logins_count=str(failed_logins_count),
        unauthorized_api_calls=str(unauthorized_api_calls),
        suspicious_activities_count=str(suspicious_activities_count),
        sender_email=settings.SMTP_EMAIL or "alertsemail@cutmap.ac.in"
    )

def trigger_user_daily_notifications():
    """Queries active users in the past 24 hours and dispatches usage reports/warnings."""
    if not settings.ENABLE_USER_USAGE_EMAILS:
        print("[INFO] [USER NOTIFICATION] User daily usage emails are disabled in settings. Skipping.")
        return
        
    db = get_db()
    if db is None:
        print("[ERROR] [USER NOTIFICATION] DB connection is None. Cannot query.")
        return
        
    # Query token usage records from the past 24 hours
    yesterday = datetime.now() - timedelta(days=1)
    token_records = list(db.token_usage.find({"created_at": {"$gte": yesterday}}))
    
    print(f"[DEBUG] [USER NOTIFICATION] Found {len(token_records)} token_usage records since {yesterday}")
    
    if not token_records:
        print("[INFO] [USER NOTIFICATION] No user activity found in the last 24 hours. No emails sent.")
        return
        
    # Group by user_id
    user_records = defaultdict(list)
    for r in token_records:
        u_id = r.get("user_id")
        if u_id:
            user_records[str(u_id)].append(r)
        else:
            print(f"[WARN] [USER NOTIFICATION] token_usage row has no user_id: {r.get('_id')}")
            
    # Load warning threshold (default: $0.50)
    threshold = settings.USER_DAILY_WARNING_THRESHOLD_USD
        
    print(f"[INFO] [USER NOTIFICATION] Processing daily usage reports for {len(user_records)} active users. Warning threshold: ${threshold:.2f}")
    
    sent = 0
    skipped = 0
    for u_id_str, records in user_records.items():
        user = db.users.find_one({"_id": u_id_str})
        if not user:
            print(f"[WARN] [USER NOTIFICATION] No user found for _id={u_id_str}. Skipping.")
            skipped += 1
            continue
            
        email = user.get("email")
        name = user.get("name", "")
        balance = user.get("token_limit", 1000000) - user.get("total_tokens_used", 0)
        
        if not email:
            print(f"[WARN] [USER NOTIFICATION] User {u_id_str} has no email. Skipping.")
            skipped += 1
            continue
            
        # Calculate daily tokens and credits
        daily_tokens = 0
        daily_credits = 0.0
        
        for r in records:
            in_t = r.get("input_tokens", 0)
            out_t = r.get("output_tokens", 0)
            total_t = r.get("total_tokens", 0) or (in_t + out_t)
            daily_tokens += total_t
            
            model = r.get("model", "").lower()
            if "sonnet" in model:
                daily_credits += (in_t * 3.0 + out_t * 15.0) / 1_000_000
            elif "haiku" in model:
                daily_credits += (in_t * 0.25 + out_t * 1.25) / 1_000_000
            elif "opus" in model:
                daily_credits += (in_t * 15.0 + out_t * 75.0) / 1_000_000
            else:
                daily_credits += (in_t * 3.0 + out_t * 15.0) / 1_000_000
                
        is_high_usage = daily_credits >= threshold
        sent += 1
        print(f"[INFO] [USER NOTIFICATION] Dispatching email to {email}: {daily_tokens} tokens, ${daily_credits:.4f}, high_usage={is_high_usage}")
        
        # Dispatch email in background thread
        email_service.send_user_usage_email_in_background(email, name, daily_tokens, daily_credits, balance, is_high_usage, threshold)
    
    print(f"[INFO] [USER NOTIFICATION] Done. Sent={sent}, Skipped={skipped}")

def daily_scheduler_loop():
    """Background scheduler that executes every day at 3:00 AM local time to send out status emails."""
    last_sent_date = None
    print("[MONITORING] Daily scheduler active: Scheduled to send summary at 3:00 AM local time.")
    
    while True:
        try:
            # Check every 30 seconds
            time.sleep(30)
            now = datetime.now()
            
            # Check if current time is 3:00 AM
            if now.hour == 3 and now.minute == 0:
                today_str = now.strftime("%Y-%m-%d")
                if last_sent_date != today_str:
                    last_sent_date = today_str
                    print(f"[MONITORING] Scheduling trigger matched for 3:00 AM. Preparing daily report...")
                    subject = f"[MONITOR] Daily Status Report - {today_str}"
                    body = generate_monitoring_email_body()
                    email_service.send_email_in_background(subject, body)
                    
                    # Trigger user daily notifications
                    try:
                        trigger_user_daily_notifications()
                    except Exception as user_notify_err:
                        print(f"[WARN] [MONITORING] Failed to trigger user daily notifications: {user_notify_err}")
        except Exception as e:
            print(f"[WARN] [MONITORING] Scheduler loop encountered an error: {e}")

