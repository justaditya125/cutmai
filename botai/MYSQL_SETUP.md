# MySQL Database Setup Guide

This guide will help you set up MySQL database for the Claude AI Chatbot.

## Step 1: Install MySQL

### Option A: MySQL Installer (Recommended)
1. Download MySQL Installer from [MySQL Official Website](https://dev.mysql.com/downloads/installer/)
2. Run the installer and choose "Developer Default"
3. Follow the installation wizard
4. Set a root password (remember this!)

### Option B: MySQL Workbench Only
1. Download MySQL Workbench from [MySQL Workbench](https://dev.mysql.com/downloads/workbench/)
2. Install MySQL Server separately if needed

## Step 2: Install Python MySQL Connector

```bash
pip install mysql-connector-python
```

## Step 3: Configure Database Connection

1. Open `database_setup.py`
2. Update the database configuration:

```python
DB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',  # Your MySQL username
    'password': 'your_mysql_password',  # Your MySQL password
    'database': 'claude_chatbot'
}
```

## Step 4: Setup Database

Run the database setup script:

```bash
python database_setup.py
```

This will:
- ✅ Create the `claude_chatbot` database
- ✅ Create all necessary tables
- ✅ Create a test user account

## Step 5: Verify Setup

### Using MySQL Workbench:
1. Open MySQL Workbench
2. Connect to your local MySQL server
3. You should see the `claude_chatbot` database
4. Check the tables: `users`, `user_sessions`, `conversations`, `messages`

### Using Command Line:
```sql
mysql -u root -p
USE claude_chatbot;
SHOW TABLES;
DESCRIBE users;
```

## Database Schema

### Users Table
```sql
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255),
    name VARCHAR(255),
    profile_picture TEXT,
    login_method ENUM('email', 'google') DEFAULT 'email',
    google_id VARCHAR(255) UNIQUE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login TIMESTAMP NULL
);
```

### User Sessions Table
```sql
CREATE TABLE user_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    session_token VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR(45),
    user_agent TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

### Conversations Table
```sql
CREATE TABLE conversations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    title VARCHAR(255) DEFAULT 'New Conversation',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

### Messages Table
```sql
CREATE TABLE messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    conversation_id INT NOT NULL,
    user_id INT NOT NULL,
    role ENUM('user', 'assistant') NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

## Features

### ✅ User Management
- Email/password registration and login
- Google OAuth integration
- Password hashing with salt
- User profile management

### ✅ Session Management
- Secure session tokens
- Session expiration (30 days)
- IP address and user agent tracking
- Automatic session cleanup

### ✅ Chat History
- Conversation management
- Message storage
- User-specific chat history
- Conversation titles

### ✅ Security Features
- Password hashing with PBKDF2
- Secure session tokens
- SQL injection protection
- Input validation

## Testing

### Test User Account
The setup script creates a test user:
- **Email:** test@example.com
- **Password:** test123

### Manual Testing
1. Start the server: `python proxy_server.py`
2. Go to: `http://localhost:3000`
3. Try logging in with the test account
4. Register a new account
5. Test Google Sign-In (if configured)

## Troubleshooting

### Common Issues:

1. **"Access denied for user 'root'"**
   - Check your MySQL password in `database_setup.py`
   - Ensure MySQL server is running

2. **"Can't connect to MySQL server"**
   - Start MySQL service
   - Check if MySQL is running on port 3306

3. **"Database 'claude_chatbot' doesn't exist"**
   - Run `python database_setup.py` again
   - Check MySQL permissions

4. **"Module 'mysql.connector' not found"**
   - Install: `pip install mysql-connector-python`

### MySQL Service Commands:

**Windows:**
```bash
# Start MySQL
net start mysql80

# Stop MySQL
net stop mysql80
```

**Linux/Mac:**
```bash
# Start MySQL
sudo systemctl start mysql

# Stop MySQL
sudo systemctl stop mysql
```

## Production Considerations

### Security:
- Use environment variables for database credentials
- Enable SSL connections
- Regular database backups
- Monitor for suspicious activity

### Performance:
- Add database indexes for frequently queried fields
- Implement connection pooling
- Regular database maintenance
- Monitor query performance

### Backup:
```bash
# Create backup
mysqldump -u root -p claude_chatbot > backup.sql

# Restore backup
mysql -u root -p claude_chatbot < backup.sql
```