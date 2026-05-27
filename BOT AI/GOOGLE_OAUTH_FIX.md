# Google OAuth 403 Error Fix

## The Issue
You're getting a 403 error because `localhost:3000` might not be properly configured in your Google OAuth settings.

## Quick Fix Steps

### 1. Go to Google Cloud Console
- Visit: https://console.cloud.google.com/
- Select your project

### 2. Navigate to Credentials
- Go to **APIs & Services** > **Credentials**
- Find your OAuth 2.0 Client ID: `799788494145-6r5b5cf8g20p8hdi01aichsja6ii7jmv.apps.googleusercontent.com`

### 3. Edit the OAuth Client
- Click on your Client ID to edit it
- In **Authorized JavaScript origins**, make sure you have:
  ```
  http://localhost:3000
  http://127.0.0.1:3000
  ```

### 4. In **Authorized redirect URIs**, add:
  ```
  http://localhost:3000
  http://localhost:3000/login.html
  http://127.0.0.1:3000
  http://127.0.0.1:3000/login.html
  ```

### 5. Save Changes
- Click **Save**
- Wait 5-10 minutes for changes to propagate

## Alternative: Test with 127.0.0.1

If the above doesn't work immediately, try accessing your chatbot using:
```
http://127.0.0.1:3000
```
instead of `http://localhost:3000`

## Verify Setup
After making changes:
1. Wait 5-10 minutes
2. Clear browser cache (Ctrl+Shift+Delete)
3. Try Google Sign-In again
4. Check browser console for any remaining errors

## Current Status
✅ **Server is working** - Your Google auth reached the server successfully
✅ **User data received** - awantikasharma786@gmail.com was processed
❌ **Domain authorization** - Need to add localhost:3000 to authorized origins

The authentication is actually working on the server side, just need to fix the domain authorization!