# ProtonMail Scraper Setup Guide

This scraper uses browser automation to extract emails from ProtonMail, just like your Roundcube scraper.

## Installation

1. **Install Python dependencies:**
\`\`\`bash
pip install -r requirements.txt
\`\`\`

2. **Install Playwright browsers:**
\`\`\`bash
playwright install chromium
\`\`\`

## Configuration

Edit the `protonmail_scraper.py` file and update the accounts list:

\`\`\`python
accounts = [
    {
        'email': 'your-email@proton.me',
        'password': 'your-password'
    },
    {
        'email': 'another-email@proton.me',
        'password': 'another-password'
    },
]
\`\`\`

## Usage

Run the scraper:
\`\`\`bash
python protonmail_scraper.py
\`\`\`

## Features (Same as Roundcube)

✓ **Multiple accounts** - Process multiple ProtonMail accounts
✓ **Date filtering** - Only emails from last N days (default: 30)
✓ **All folders** - Inbox, Sent, Drafts, Archive, Spam, Trash, Labels
✓ **Progress tracking** - Resume from where you left off
✓ **Completed accounts** - Skip already processed accounts
✓ **.eml format** - Standard email format
✓ **Attachment download** - Extracts all attachments
✓ **Organized storage** - `protonmail_data/email_at_domain/folder/emails.eml`

## Important Notes

### 2FA / CAPTCHA Handling
- The browser will open in **non-headless mode** (you can see it)
- If ProtonMail shows 2FA or CAPTCHA, **complete it manually** in the browser
- The script will wait 60 seconds for you to complete 2FA
- After completion, the script continues automatically

### Rate Limiting
- ProtonMail may rate limit if you scrape too fast
- The script includes delays between actions
- If you get blocked, wait a few hours and try again

### Free Account Limitations
- Works with **free ProtonMail accounts**
- No subscription needed
- May be slower than Bridge method but works the same way

## Output Structure

\`\`\`
protonmail_data/
├── your-email_at_proton.me/
│   ├── Inbox/
│   │   ├── 0_Email_Subject.eml
│   │   ├── 0_attachments/
│   │   │   └── document.pdf
│   │   └── 1_Another_Email.eml
│   ├── Sent/
│   └── Archive/
├── progress.json
└── completed_accounts.json
\`\`\`

## Troubleshooting

**Login fails:**
- Check credentials
- Complete CAPTCHA/2FA manually
- ProtonMail may require email verification for new locations

**Emails not loading:**
- Increase wait times in the script
- Check your internet connection
- ProtonMail may be slow to load

**Attachments not downloading:**
- Some attachment types may require special handling
- Check browser download settings
- Ensure sufficient disk space

## Comparison with Roundcube Script

| Feature | Roundcube | ProtonMail |
|---------|-----------|------------|
| Method | HTTP requests | Browser automation |
| Speed | Fast | Moderate |
| 2FA | Automatic | Manual intervention |
| Reliability | High | High |
| Free account | ✓ | ✓ |
| Attachments | ✓ | ✓ |
| Date filtering | ✓ | ✓ |
| Progress tracking | ✓ | ✓ |

## Advanced Configuration

Change date range:
\`\`\`python
scraper = ProtonMailScraper(
    base_dir="protonmail_data",
    days_back=60  # Last 60 days
)
\`\`\`

Run in headless mode (no browser window):
\`\`\`python
browser = p.chromium.launch(headless=True)  # Line 287
\`\`\`
Note: Headless mode may trigger more CAPTCHAs
