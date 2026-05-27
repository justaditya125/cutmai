# Google OAuth Setup Guide

To enable real Google Sign-In functionality, you need to set up Google OAuth credentials.

## Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Google+ API (if not already enabled)

## Step 2: Configure OAuth Consent Screen

1. Go to **APIs & Services** > **OAuth consent screen**
2. Choose **External** user type
3. Fill in the required information:
   - App name: "Claude AI Chatbot"
   - User support email: Your email
   - Developer contact information: Your email
4. Add scopes: `email`, `profile`, `openid`
5. Save and continue

## Step 3: Create OAuth 2.0 Credentials

1. Go to **APIs & Services** > **Credentials**
2. Click **Create Credentials** > **OAuth 2.0 Client IDs**
3. Choose **Web application**
4. Add authorized JavaScript origins:
   - `http://localhost:3000`
   - `http://127.0.0.1:3000`
5. Add authorized redirect URIs:
   - `http://localhost:3000`
   - `http://localhost:3000/login.html`
6. Click **Create**

## Step 4: Update Your Code

1. Copy the **Client ID** from the credentials page
2. Open `login.html`
3. Replace this line:
   ```javascript
   const GOOGLE_CLIENT_ID = '1234567890-abcdefghijklmnopqrstuvwxyz123456.apps.googleusercontent.com';
   ```
   With your actual Client ID:
   ```javascript
   const GOOGLE_CLIENT_ID = 'YOUR_ACTUAL_CLIENT_ID_HERE.apps.googleusercontent.com';
   ```

## Step 5: Test the Integration

1. Restart your server
2. Go to `http://localhost:3000`
3. Click "Continue with Google"
4. You should see the real Google account selection popup

## Important Notes

- The Client ID is public and safe to include in frontend code
- Never include the Client Secret in frontend code
- For production, add your actual domain to authorized origins
- Test with different Google accounts to ensure it works properly

## Troubleshooting

### Common Issues:

1. **"This app isn't verified"** - Normal for development, click "Advanced" > "Go to app"
2. **"redirect_uri_mismatch"** - Check your authorized redirect URIs
3. **"origin_mismatch"** - Check your authorized JavaScript origins
4. **Popup blocked** - Enable popups for localhost in browser settings

### Testing Tips:

- Test in incognito mode to simulate new users
- Test with multiple Google accounts
- Check browser console for detailed error messages
- Ensure your server is running on the correct port (3000)

## Security Best Practices

- Only add necessary scopes (`email`, `profile`)
- Regularly rotate credentials if compromised
- Monitor usage in Google Cloud Console
- Use HTTPS in production environments