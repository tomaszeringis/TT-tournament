# 📦 Packaging Streamlit for Microsoft Teams

This guide explains how to package the Tournament Platform Streamlit app as a Microsoft Teams Tab.

## 1. Prerequisites
- A hosted URL for your Streamlit app (must be **HTTPS**).
- Two icon files:
  - `color.png`: 192x192 pixels.
  - `outline.png`: 32x32 pixels (must be transparent with white/black outline).

## 2. Customize `manifest.json`
Open `teams/manifest.json` and update the following fields:
- `id`: Generate a unique GUID (use `[guid]::NewGuid()` in PowerShell).
- `contentUrl` & `websiteUrl`: Replace `https://your-streamlit-app.com` with your actual hosted URL.
- `validDomains`: Add your application's domain (e.g., `tournament.azurewebsites.net`).

## 3. Configure validDomains
The `validDomains` array is a security measure that tells Teams which domains are authorized to be loaded within the Teams Tab iframe.
- **Why?** It prevents unauthorized sites from being loaded and protects against clickjacking.
- **What to include?**
  - Your main app domain: `"tournament.example.com"`
  - Wildcard for subdomains (if applicable): `"*.tournament.example.com"`
  - Authentication providers (if they use redirects): e.g., `"login.microsoftonline.com"`

## 4. Packaging the .zip File
To create the Teams App package:
1. Go to the `teams/` directory.
2. Ensure it contains exactly three files:
   - `manifest.json`
   - `color.png`
   - `outline.png`
3. Select these three files and compress them into a `.zip` file.
   
**PowerShell Command:**
```powershell
Compress-Archive -Path "teams\manifest.json", "teams\color.png", "teams\outline.png" -DestinationPath "TournamentPlatform_TeamsApp.zip"
```

## 5. Uploading to Teams Admin Center
1. Navigate to [Microsoft Teams Admin Center](https://admin.teams.microsoft.com/).
2. Go to **Teams apps** > **Manage apps**.
3. Click **Upload new app** and select the `.zip` file you created.
4. Once uploaded, publish the app so it's available to your organization.

## 6. Important Streamlit Config (Frame Compatibility)
By default, Streamlit may block being embedded in iframes for security. You must ensure your hosting environment allows `teams.microsoft.com`.

If using Nginx as a reverse proxy, ensure headers are set:
```nginx
add_header Content-Security-Policy "frame-ancestors 'self' https://teams.microsoft.com https://*.teams.microsoft.com;";
```
Alternatively, in your Streamlit `config.toml`, you may need:
```toml
[server]
enableCORS = false
enableXsrfProtection = false
```
*Note: Disabling XSRF protection should be done with caution and ideally handled at the reverse proxy level.*
