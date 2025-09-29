import os
import json
import time
import re
from datetime import datetime, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import base64
import email
from email import policy
from email.parser import BytesParser

class ProtonMailScraper:
    def __init__(self, base_dir="protonmail_data", days_back=30):
        self.base_dir = Path(base_dir)
        self.days_back = days_back
        self.cutoff_date = datetime.now() - timedelta(days=days_back)
        self.progress_file = self.base_dir / "progress.json"
        self.completed_file = self.base_dir / "completed_accounts.json"
        self.base_dir.mkdir(exist_ok=True)
        
    def load_progress(self):
        """Load scraping progress"""
        if self.progress_file.exists():
            with open(self.progress_file, 'r') as f:
                return json.load(f)
        return {}
    
    def save_progress(self, progress):
        """Save scraping progress"""
        with open(self.progress_file, 'w') as f:
            json.dump(progress, f, indent=2)
    
    def load_completed_accounts(self):
        """Load list of completed accounts"""
        if self.completed_file.exists():
            with open(self.completed_file, 'r') as f:
                return json.load(f)
        return []
    
    def save_completed_account(self, email):
        """Mark account as completed"""
        completed = self.load_completed_accounts()
        if email not in completed:
            completed.append(email)
            with open(self.completed_file, 'w') as f:
                json.dump(completed, f, indent=2)
    
    def login(self, page, email, password):
        """Login to ProtonMail"""
        print(f"[{datetime.now()}] Logging in as {email}...")
        
        # Navigate to ProtonMail
        page.goto("https://account.proton.me/login", wait_until="networkidle")
        time.sleep(2)
        
        # Enter username
        page.fill('input[name="username"]', email)
        page.fill('input[name="password"]', password)
        
        # Click login button
        page.click('button[type="submit"]')
        
        # Wait for potential 2FA or CAPTCHA
        print("Waiting for login to complete (handle 2FA/CAPTCHA if needed)...")
        time.sleep(5)
        
        # Check if we need to handle 2FA
        if "two-factor" in page.url.lower() or page.locator('input[type="text"][placeholder*="code"]').count() > 0:
            print("\n⚠️  2FA REQUIRED - Please enter your 2FA code in the browser")
            print("Waiting 60 seconds for you to complete 2FA...")
            time.sleep(60)
        
        # Wait for mail interface to load
        try:
            page.wait_for_url("**/mail/**", timeout=30000)
            print(f"[{datetime.now()}] Login successful!")
            time.sleep(3)
            return True
        except PlaywrightTimeout:
            # Try alternative: check if we're already in mail
            if "/mail" in page.url or page.locator('[data-testid="navigation-link:inbox"]').count() > 0:
                print(f"[{datetime.now()}] Login successful!")
                return True
            print(f"[{datetime.now()}] Login failed or timed out")
            return False
    
    def get_folders(self, page):
        """Get list of mail folders"""
        print(f"[{datetime.now()}] Fetching folders...")
        
        folders = []
        
        # Wait for navigation to be visible
        page.wait_for_selector('[data-testid="navigation-link:inbox"]', timeout=10000)
        
        # Get all folder links
        folder_selectors = [
            ('[data-testid="navigation-link:inbox"]', 'Inbox'),
            ('[data-testid="navigation-link:sent"]', 'Sent'),
            ('[data-testid="navigation-link:drafts"]', 'Drafts'),
            ('[data-testid="navigation-link:starred"]', 'Starred'),
            ('[data-testid="navigation-link:archive"]', 'Archive'),
            ('[data-testid="navigation-link:spam"]', 'Spam'),
            ('[data-testid="navigation-link:trash"]', 'Trash'),
        ]
        
        for selector, name in folder_selectors:
            if page.locator(selector).count() > 0:
                folders.append({'name': name, 'selector': selector})
        
        # Try to get custom folders/labels
        try:
            label_elements = page.locator('[data-testid^="navigation-link:label-"]').all()
            for elem in label_elements:
                label_name = elem.inner_text().strip()
                if label_name:
                    folders.append({
                        'name': f'Label: {label_name}',
                        'selector': f'text="{label_name}"'
                    })
        except:
            pass
        
        print(f"[{datetime.now()}] Found {len(folders)} folders")
        return folders
    
    def navigate_to_folder(self, page, folder):
        """Navigate to a specific folder"""
        print(f"[{datetime.now()}] Opening folder: {folder['name']}")
        
        try:
            page.click(folder['selector'])
            time.sleep(2)
            
            # Wait for email list to load
            page.wait_for_selector('[data-testid="message-item"]', timeout=10000)
            return True
        except PlaywrightTimeout:
            print(f"[{datetime.now()}] No emails in folder or timeout")
            return False
    
    def parse_date(self, date_str):
        """Parse date from various formats"""
        try:
            # Try common formats
            for fmt in ["%b %d, %Y", "%d %b %Y", "%Y-%m-%d", "%m/%d/%Y"]:
                try:
                    return datetime.strptime(date_str, fmt)
                except:
                    continue
            
            # Handle relative dates like "Today", "Yesterday"
            if "today" in date_str.lower():
                return datetime.now()
            elif "yesterday" in date_str.lower():
                return datetime.now() - timedelta(days=1)
            
            return None
        except:
            return None
    
    def get_emails_in_folder(self, page, folder, account_email):
        """Get all emails in a folder"""
        print(f"[{datetime.now()}] Fetching emails from {folder['name']}...")
        
        emails = []
        processed_ids = set()
        
        # Scroll to load all emails
        last_count = 0
        scroll_attempts = 0
        max_scrolls = 50
        
        while scroll_attempts < max_scrolls:
            # Get current email items
            email_items = page.locator('[data-testid="message-item"]').all()
            current_count = len(email_items)
            
            if current_count == last_count:
                scroll_attempts += 1
                if scroll_attempts >= 3:
                    break
            else:
                scroll_attempts = 0
            
            last_count = current_count
            
            # Scroll down
            if email_items:
                email_items[-1].scroll_into_view_if_needed()
                time.sleep(1)
        
        print(f"[{datetime.now()}] Found {current_count} emails, processing...")
        
        # Process each email
        email_items = page.locator('[data-testid="message-item"]').all()
        
        for idx, item in enumerate(email_items):
            try:
                # Get email ID (use index as fallback)
                email_id = f"{folder['name']}_{idx}"
                
                if email_id in processed_ids:
                    continue
                
                # Click to open email
                item.click()
                time.sleep(1.5)
                
                # Wait for email content to load
                page.wait_for_selector('[data-testid="message-content"]', timeout=5000)
                
                # Extract email details
                subject = "No Subject"
                try:
                    subject_elem = page.locator('[data-testid="message-header-subject"]').first
                    if subject_elem.count() > 0:
                        subject = subject_elem.inner_text().strip()
                except:
                    pass
                
                # Get sender
                sender = "Unknown"
                try:
                    sender_elem = page.locator('[data-testid="message-header-from"]').first
                    if sender_elem.count() > 0:
                        sender = sender_elem.inner_text().strip()
                except:
                    pass
                
                # Get date
                date_str = ""
                email_date = None
                try:
                    date_elem = page.locator('[data-testid="message-header-date"]').first
                    if date_elem.count() > 0:
                        date_str = date_elem.inner_text().strip()
                        email_date = self.parse_date(date_str)
                except:
                    pass
                
                # Check if email is within date range
                if email_date and email_date < self.cutoff_date:
                    print(f"[{datetime.now()}] Email too old, stopping: {subject[:50]}")
                    break
                
                # Get email body
                body_html = ""
                body_text = ""
                try:
                    body_elem = page.locator('[data-testid="message-content"]').first
                    if body_elem.count() > 0:
                        body_html = body_elem.inner_html()
                        body_text = body_elem.inner_text()
                except:
                    pass
                
                # Get attachments
                attachments = []
                try:
                    attachment_elems = page.locator('[data-testid^="attachment-"]').all()
                    for att_elem in attachment_elems:
                        att_name = att_elem.inner_text().strip()
                        if att_name:
                            attachments.append(att_name)
                except:
                    pass
                
                email_data = {
                    'id': email_id,
                    'subject': subject,
                    'from': sender,
                    'date': date_str,
                    'date_parsed': email_date.isoformat() if email_date else None,
                    'body_html': body_html,
                    'body_text': body_text,
                    'attachments': attachments,
                    'folder': folder['name']
                }
                
                emails.append(email_data)
                processed_ids.add(email_id)
                
                print(f"[{datetime.now()}] [{idx+1}/{current_count}] {subject[:50]}")
                
                # Go back to list
                page.go_back()
                time.sleep(1)
                
            except Exception as e:
                print(f"[{datetime.now()}] Error processing email {idx}: {e}")
                # Try to go back to list
                try:
                    page.go_back()
                    time.sleep(1)
                except:
                    pass
                continue
        
        return emails
    
    def save_email_as_eml(self, email_data, account_email):
        """Save email as .eml file"""
        # Create directory structure
        account_dir = self.base_dir / account_email.replace('@', '_at_')
        folder_dir = account_dir / email_data['folder'].replace('/', '_')
        folder_dir.mkdir(parents=True, exist_ok=True)
        
        # Create .eml file
        safe_subject = re.sub(r'[<>:"/\\|?*]', '_', email_data['subject'][:100])
        filename = f"{email_data['id']}_{safe_subject}.eml"
        filepath = folder_dir / filename
        
        # Build email message
        msg = email.message.EmailMessage()
        msg['Subject'] = email_data['subject']
        msg['From'] = email_data['from']
        msg['Date'] = email_data['date']
        
        # Set body
        if email_data['body_html']:
            msg.set_content(email_data['body_text'])
            msg.add_alternative(email_data['body_html'], subtype='html')
        else:
            msg.set_content(email_data['body_text'])
        
        # Save to file
        with open(filepath, 'wb') as f:
            f.write(msg.as_bytes())
        
        return filepath
    
    def download_attachments(self, page, email_data, account_email):
        """Download email attachments"""
        if not email_data['attachments']:
            return []
        
        # Create attachments directory
        account_dir = self.base_dir / account_email.replace('@', '_at_')
        folder_dir = account_dir / email_data['folder'].replace('/', '_')
        attachments_dir = folder_dir / f"{email_data['id']}_attachments"
        attachments_dir.mkdir(parents=True, exist_ok=True)
        
        downloaded = []
        
        print(f"[{datetime.now()}] Downloading {len(email_data['attachments'])} attachments...")
        
        # Note: Actual attachment download requires clicking download buttons
        # This is a simplified version - full implementation would need to handle
        # the download dialog and file system operations
        
        try:
            attachment_elems = page.locator('[data-testid^="attachment-"]').all()
            
            for idx, att_elem in enumerate(attachment_elems):
                try:
                    # Get attachment name
                    att_name = email_data['attachments'][idx] if idx < len(email_data['attachments']) else f"attachment_{idx}"
                    
                    # Setup download handler
                    with page.expect_download() as download_info:
                        # Click download button
                        download_btn = att_elem.locator('button[title*="Download"]').first
                        if download_btn.count() > 0:
                            download_btn.click()
                    
                    download = download_info.value
                    
                    # Save file
                    filepath = attachments_dir / att_name
                    download.save_as(filepath)
                    downloaded.append(str(filepath))
                    
                    print(f"[{datetime.now()}] Downloaded: {att_name}")
                    
                except Exception as e:
                    print(f"[{datetime.now()}] Failed to download attachment: {e}")
                    continue
        
        except Exception as e:
            print(f"[{datetime.now()}] Error downloading attachments: {e}")
        
        return downloaded
    
    def scrape_account(self, email, password):
        """Scrape all emails from an account"""
        print(f"\n{'='*60}")
        print(f"Starting scrape for: {email}")
        print(f"{'='*60}\n")
        
        # Check if already completed
        completed = self.load_completed_accounts()
        if email in completed:
            print(f"Account {email} already completed. Skipping...")
            return
        
        # Load progress
        progress = self.load_progress()
        account_progress = progress.get(email, {
            'current_folder': 0,
            'completed_folders': []
        })
        
        with sync_playwright() as p:
            # Launch browser (headless=False so you can see and handle 2FA/CAPTCHA)
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = context.new_page()
            
            try:
                # Login
                if not self.login(page, email, password):
                    print(f"Failed to login to {email}")
                    return
                
                # Get folders
                folders = self.get_folders(page)
                
                # Process each folder
                for idx, folder in enumerate(folders):
                    if folder['name'] in account_progress['completed_folders']:
                        print(f"Folder {folder['name']} already completed. Skipping...")
                        continue
                    
                    print(f"\n--- Processing folder {idx+1}/{len(folders)}: {folder['name']} ---")
                    
                    # Navigate to folder
                    if not self.navigate_to_folder(page, folder):
                        continue
                    
                    # Get emails
                    emails = self.get_emails_in_folder(page, folder, email)
                    
                    # Save emails
                    for email_data in emails:
                        # Save as .eml
                        eml_path = self.save_email_as_eml(email_data, email)
                        print(f"[{datetime.now()}] Saved: {eml_path}")
                        
                        # Download attachments if any
                        if email_data['attachments']:
                            # Navigate back to email to download attachments
                            self.navigate_to_folder(page, folder)
                            time.sleep(1)
                            
                            # Find and click the email again
                            email_items = page.locator('[data-testid="message-item"]').all()
                            for item in email_items:
                                if email_data['subject'] in item.inner_text():
                                    item.click()
                                    time.sleep(1.5)
                                    break
                            
                            self.download_attachments(page, email_data, email)
                            
                            # Go back to folder
                            page.go_back()
                            time.sleep(1)
                    
                    # Mark folder as completed
                    account_progress['completed_folders'].append(folder['name'])
                    account_progress['current_folder'] = idx + 1
                    progress[email] = account_progress
                    self.save_progress(progress)
                    
                    print(f"[{datetime.now()}] Completed folder: {folder['name']}")
                
                # Mark account as completed
                self.save_completed_account(email)
                
                # Clean up progress for this account
                if email in progress:
                    del progress[email]
                    self.save_progress(progress)
                
                print(f"\n{'='*60}")
                print(f"✓ Completed scraping for: {email}")
                print(f"{'='*60}\n")
                
            except Exception as e:
                print(f"Error scraping account {email}: {e}")
                import traceback
                traceback.print_exc()
            
            finally:
                browser.close()
    
    def scrape_multiple_accounts(self, accounts):
        """Scrape multiple accounts"""
        print(f"Starting scrape for {len(accounts)} accounts")
        print(f"Date range: Last {self.days_back} days")
        print(f"Cutoff date: {self.cutoff_date.strftime('%Y-%m-%d')}\n")
        
        for idx, account in enumerate(accounts):
            print(f"\n[Account {idx+1}/{len(accounts)}]")
            self.scrape_account(account['email'], account['password'])
            
            # Wait between accounts
            if idx < len(accounts) - 1:
                print("\nWaiting 10 seconds before next account...")
                time.sleep(10)
        
        print("\n" + "="*60)
        print("✓ ALL ACCOUNTS COMPLETED")
        print("="*60)


# Example usage
if __name__ == "__main__":
    # Configuration
    accounts = [
        {
            'email': 'your-email@proton.me',
            'password': 'your-password'
        },
        # Add more accounts as needed
    ]
    
    # Create scraper (last 30 days)
    scraper = ProtonMailScraper(
        base_dir="protonmail_data",
        days_back=30
    )
    
    # Scrape all accounts
    scraper.scrape_multiple_accounts(accounts)
