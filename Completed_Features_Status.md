# CUTM AI Chatbot — Completed Features Status Report

This document provides a comprehensive review of all implemented features, technical design, backend endpoints, and database models currently working in the **Centurion University (CUTM) AI Chatbot** repository.

---

## 1. System Architecture & Tech Stack
*   **Backend**: Python 3 standard library `http.server` running a threaded, connection-reusing TCP server (`socketserver.ThreadingMixIn`).
*   **Frontend**: Vanilla HTML5, CSS3 (curated Crystal Indigo palette, responsive animations, custom scrollbars), and modern JavaScript (ES6+).
*   **Database**: MongoDB Atlas (`pymongo`) with built-in connection pooling.
*   **AI Integration**: Anthropic Claude API (messages endpoint) with round-robin multi-key load balancing.
*   **Document Parsers**: `pdfminer.six` (PDFs), `mammoth` / `python-docx` (Word documents), `BeautifulSoup4` (HTML webpages), `gdown` (Google Drive downloads).
*   **Client Libraries**: `marked.js` (Markdown parsing), `highlight.js` (syntax highlighting), `Chart.js` (graph visualization), `pdf.js` (client-side PDF parsing), `mammoth.js` (client-side docx parsing), `html2pdf.js` (PDF exports).

---

## 2. Implemented Backend Endpoints

### 🔐 Authentication & Session APIs
*   `POST /api/auth/register`
    *   Creates a new user account with `is_approved = False`.
    *   Passwords deterministically converted to alphanumeric hashes before hashing using standard PBKDF2 with salt.
    *   **Security check**: RESTRICTS registration strictly to institutional domains (`@cutmap.ac.in` and `@cutm.ac.in`). All other registration attempts log suspicious events and return `403 Forbidden`.
*   `POST /api/auth/login`
    *   Validates credentials and updates `last_login` timestamp.
    *   Generates a cryptographically secure 32-character session token.
    *   Terminates early if the user's lifetime token usage exceeds their set limit.
*   `POST /api/auth/google`
    *   Server-side Google JWT token validation using `google-auth` library transport.
    *   Extracts verified name, email, profile picture, and Google ID (sub).
    *   Automatically creates accounts for new institutional users (pending admin approval).
*   `POST /api/auth/verify`
    *   Validates active session tokens and returns current user meta, token balance, and credits consumed.
*   `POST /api/auth/logout`
    *   Terminates sessions by deleting the token from MongoDB.

### 💬 Claude AI Integration
*   `POST /api/claude/stream` (SSE - Server-Sent Events)
    *   Streams replies word-by-word via readable streams (`content_block_delta` event processing).
    *   Enforces user token limit checks.
    *   Automatically creates a new conversation doc if none is provided.
    *   Rotates API keys on every request (using round-robin `KeyRotator`).
    *   Trims message history context (keeps last 6 messages) and utilizes a cheap model summarizing older messages once history exceeds 12 entries to optimize token consumption.
    *   Automatically scans user prompts for URLs and Google Drive links, fetches their plaintext content, and prepends it to the Claude context.
*   `POST /api/claude/vision`
    *   Accepts a Base64-encoded image and media type (`image/jpeg`, `image/png`, etc.).
    *   Forwards the image directly to Claude's vision APIs alongside user instructions.
*   `POST /api/claude` (Standard JSON response fallback)
    *   Performs non-streaming completions for backward compatibility.

### 🗂️ Conversation Management
*   `POST /api/conversations/new`: Creates a new chat session.
*   `POST /api/conversations/list`: Retrieves all conversations owned by the user, sorted by modification date.
*   `POST /api/conversations/messages`: Fetches chronological messages for a conversation after validating ownership.
*   `POST /api/conversations/delete`: Cascade deletes a conversation and all its associated messages.
*   `POST /api/conversations/rename`: Updates the conversation title.

### 🛡️ Admin & Monitoring APIs
*   `POST /api/admin/stats`
    *   Aggregates system counts (total users, conversations, messages, sessions).
    *   Calculates lifetime credit costs consumed by each user based on Anthropic model pricing.
    *   Returns recent token usage logs and active session listings.
*   `POST /api/admin/approve_user`
    *   Allows approving, revoking, or rejecting (deleting) users.
    *   Kicks out revoked users instantly by deleting all active sessions.
*   `POST /api/admin/set_limit`
    *   Dynamically sets a custom token limit for a specific user.
*   `POST /api/admin/send_monitoring_report`
    *   Generates the latest production status report and sends it immediately to administrators in a background thread.

---

## 3. Database Schema (MongoDB Atlas)

### 👤 `users` collection
```json
{
  "_id": ObjectId("..."),
  "email": "student@cutmap.ac.in",
  "name": "Jane Doe",
  "password_hash": "salt:pbkdf2_hash",
  "google_id": "google-sub-id-if-google-login",
  "profile_picture": "https://...",
  "login_method": "google",
  "is_approved": true,
  "is_active": true,
  "is_admin": false,
  "token_limit": 1000000,
  "total_tokens_used": 15200,
  "total_messages": 12,
  "created_at": ISODate("2026-06-01T00:00:00Z"),
  "updated_at": ISODate("2026-06-04T12:00:00Z"),
  "last_login": ISODate("2026-06-04T12:00:00Z")
}
```

### 🔑 `user_sessions` collection
```json
{
  "_id": ObjectId("..."),
  "user_id": ObjectId("..."),
  "session_token": "secure-random-token",
  "ip_address": "127.0.0.1",
  "user_agent": "Mozilla/5.0...",
  "created_at": ISODate("..."),
  "expires_at": ISODate("...")
}
```

### 📂 `conversations` collection
```json
{
  "_id": ObjectId("..."),
  "user_id": ObjectId("..."),
  "title": "Python lists sorting",
  "created_at": ISODate("..."),
  "updated_at": ISODate("...")
}
```

### 💬 `messages` collection
```json
{
  "_id": ObjectId("..."),
  "conversation_id": ObjectId("..."),
  "user_id": ObjectId("..."),
  "role": "user", // "user" or "assistant"
  "content": "How do I sort a list?",
  "created_at": ISODate("...")
}
```

### 📊 `token_usage` collection
```json
{
  "_id": ObjectId("..."),
  "user_id": ObjectId("..."),
  "input_tokens": 412,
  "output_tokens": 204,
  "total_tokens": 616,
  "model": "claude-haiku-4-5",
  "created_at": ISODate("...")
}
```

---

## 4. Frontend & User Interface Features

### 🌟 Premium Aesthetics
*   Modern, high-contrast, clean layout utilizing the Google Font **Inter** and an elegant **Georgia** serif style for headers.
*   Interactive hovering effects, custom scrollbars, animated loading skeletons, and soft indigo brand accents.
*   Responsive collapsible sidebar and responsive content paneling.

### ⚡ Real-time Stream Rendering
*   Decodes readable stream bytes in real-time, parsing and rendering markdown headings, lists, tables, bold text, and code syntax highlighting (`highlight.js`).
*   Implements a client-side **Stop Generation** button (`AbortController`) to halt responses immediately, and a **Regenerate** button for assistant messages.

### 📑 File Integration & Web Scrapers
*   **Web Browsing via URL**: Automatically detects web links in messages, downloads their content using spoofed headers, parses clean text via BeautifulSoup, and feeds it to Claude.
*   **Google Drive Scraper**: Downloads public files and folders via `gdown`. Supports extracting text from PDFs (`pdfminer`), Word docs (`mammoth`), text files, and CSVs.
*   **Local File Uploads**: Allows drag-and-drop or browsing to upload images, PDFs, Word docs, and plain text. Image uploads are sent via the Vision API, while text extraction for local PDFs and Word documents is executed entirely client-side using `pdf.js` and `mammoth.js` to preserve server resources.

### 📊 Interactive Artifacts & Graphs
*   **Artifacts Side Panel**: Displays responsive HTML pages, SVGs, scripts, markdown documents, and stylesheets generated by Claude.
*   **Chart rendering**: Intercepts ```chart JSON payloads and displays responsive, animated graphs using **Chart.js** (supports bar, line, pie, doughnut, radar charts).
*   **Visualize Tables**: Adds a "📊 Visualize as Chart" button directly below any markdown table in bot messages, dynamically mapping row data to a new chart artifact.
*   **Document Exports**: Exports bot responses or artifacts to downloadable **PDF** and **Microsoft Word (.doc)** documents with single-click buttons.
*   **AI Art Studio**: Modal interface to generate custom AI artwork through a Pollinations AI image generator proxy, featuring styled presets (Cinematic, Anime, Minimalist, etc.) and aspect-ratio templates (1:1, 16:9, 9:16).

---

## 5. Security, Monitoring & Automation

### 🛑 Security Guardrails
*   **IP Rate Limiting**: Limit-checks client IPs for logins (10/min), registrations (5/10min), Google authentication (10/min), and Claude API requests (30/min) using an in-memory window store to prevent brute-force attacks and abuse.
*   **Suspicious Activity Logs**: Tracks events such as unauthorized admin attempts, registrations from disallowed domains, or hitting rate limits. Suspicious logs are displayed on the admin interface.

### 📧 SMTP Alert System
*   **Startup Alert**: Triggers a background email notification containing port details and database status upon starting the server.
*   **Daily Status Report**: A background scheduler running 24/7 triggers every day at 3:00 AM local time, compiling server uptime, MongoDB status, user credit costs, lifetime active tokens, security threat counts, and sending a clean text report to system administrators.

---
