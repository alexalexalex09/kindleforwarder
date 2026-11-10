import sys
import os
import time
import threading
import tempfile
import uuid
import smtplib
import email
from email.utils import parseaddr
from email.message import EmailMessage
import logging
import re
from dotenv import load_dotenv

# Ensure background apps don't crash when drawing progress bars
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

from docx2pdf import convert
import pystray
from PIL import Image, ImageDraw
from imapclient import IMAPClient
import pythoncom
from plyer import notification
import requests
from bs4 import BeautifulSoup

# --- Configuration (Loaded securely from .env) ---
# Explicitly find the .env file next to this script
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, '.env')
load_dotenv(dotenv_path=env_path)

GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
KINDLE_EMAIL = os.getenv("KINDLE_EMAIL")
TO_EMAIL = os.getenv("TO_EMAIL")

# Fail-safe check to ensure the .env file loaded correctly
if not all([GMAIL_USER, GMAIL_APP_PASSWORD, KINDLE_EMAIL, TO_EMAIL]):
    notification.notify(
        title="KindleBot Error",
        message="Missing configuration in .env file. Bot shutting down.",
        app_name="KindleBot",
        timeout=10
    )
    sys.exit()

is_running = True

# Set up the background log file
log_path = os.path.join(os.path.expanduser('~'), 'Documents', 'kindlebot_log.txt')
logging.basicConfig(
    filename=log_path,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logging.info("KindleBot started successfully with environment variables.")

def process_inbox(server):
    """Processes unread emails and routes them based on sender and content."""
    messages = server.search(['UNSEEN'])
    if not messages:
        return

    for uid, message_data in server.fetch(messages, 'RFC822').items():
        msg = email.message_from_bytes(message_data[b'RFC822'])
        
        sender_name, sender_addr = parseaddr(msg.get('From', ''))
        sender_addr = sender_addr.lower()

        amazon_pdf_url = None
        amazon_subject = "Scribe Export"  # Default fallback subject

        for part in msg.walk():
            content_type = part.get_content_type()
            
            # --- ROUTE A: Amazon Scribe Export ---
            if sender_addr == 'do-not-reply@amazon.com' and content_type == 'text/html':
                body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                
                if "You sent a file" in body:
                    soup = BeautifulSoup(body, 'html.parser')
                    
                    # 1. Extract the document name for the subject line
                    plain_text = soup.get_text(separator=' ')
                    match = re.search(r'You sent a file[^"“”]*["“”]([^"“”]+)["“”]', plain_text, re.IGNORECASE)
                    if match:
                        amazon_subject = match.group(1).strip()
                    
                    # 2. Extract the download URL
                    link = soup.find('a', string=lambda text: text and 'Download PDF' in text.strip())
                    
                    if link and link.get('href'):
                        amazon_pdf_url = link['href']
                        break 

            # --- ROUTE B: Standard Word Document Conversion ---
            elif part.get_content_maintype() != 'multipart' and part.get('Content-Disposition') is not None:
                original_filename = part.get_filename()
                
                if original_filename and (original_filename.lower().endswith('.doc') or original_filename.lower().endswith('.docx')):
                    temp_dir = tempfile.gettempdir()
                    safe_base = str(uuid.uuid4())
                    docx_path = os.path.join(temp_dir, f"{safe_base}.docx")
                    pdf_path = os.path.join(temp_dir, f"{safe_base}.pdf")
                    pdf_display_filename = original_filename.rsplit('.', 1)[0] + '.pdf'
                    
                    try:
                        with open(docx_path, 'wb') as f:
                            f.write(part.get_payload(decode=True))
                        
                        logging.info(f"Converting {original_filename}...")
                        convert(docx_path, pdf_path)
                        send_to_kindle(pdf_path, pdf_display_filename)
                    
                    except Exception as e:
                        error_msg = f"Failed to convert {original_filename}. Error: {e}"
                        logging.error(error_msg)
                        notification.notify(
                            title="KindleBot Error",
                            message="Failed to convert document. Check the log file.",
                            app_name="KindleBot",
                            timeout=5
                        )
                    finally:
                        if os.path.exists(docx_path):
                            os.remove(docx_path)
                        if os.path.exists(pdf_path):
                            os.remove(pdf_path)

        # --- EXECUTE ROUTE A (If URL was found) ---
        if amazon_pdf_url:
            download_and_forward_amazon_pdf(amazon_pdf_url, amazon_subject)

        # Mark email as deleted so we don't process it again
        server.add_flags(uid, [b'\\Deleted'])
    
    server.expunge()


def download_and_forward_amazon_pdf(url, subject_line):
    """Downloads the PDF from the Amazon link and emails it to the Covenant address."""
    temp_dir = tempfile.gettempdir()
    safe_base = str(uuid.uuid4())
    pdf_path = os.path.join(temp_dir, f"{safe_base}.pdf")
    
    # Strip illegal filename characters from the subject line
    safe_filename = re.sub(r'[\\/*?:"<>|]', "", subject_line).strip()
    
    # Fallback just in case the subject was entirely illegal characters
    if not safe_filename:
        safe_filename = "Scribe_Export"
        
    attachment_name = f"{safe_filename}.pdf"
    
    try:
        logging.info(f"Downloading Amazon Scribe link: {subject_line}")
        r = requests.get(url, stream=True)
        r.raise_for_status()
        
        with open(pdf_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                
        logging.info(f"Sending Amazon PDF as '{attachment_name}' to Covenant email...")
        send_to_covenant(pdf_path, attachment_name, subject_line)
        
    except Exception as e:
        error_msg = f"Failed to download or send Amazon PDF. Error: {e}"
        logging.error(error_msg)
        notification.notify(
            title="KindleBot Error",
            message="Failed to process Amazon Scribe export. Check log.",
            app_name="KindleBot",
            timeout=5
        )
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

def send_to_covenant(file_path, filename, subject_line):
    """Emails the extracted PDF to the Covenant email address."""
    msg = EmailMessage()
    msg['Subject'] = subject_line
    msg['From'] = GMAIL_USER
    msg['To'] = TO_EMAIL

    with open(file_path, 'rb') as f:
        pdf_data = f.read()
    
    msg.add_attachment(pdf_data, maintype='application', subtype='pdf', filename=filename)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.send_message(msg)
        
    logging.info(f"Successfully sent {filename} to {TO_EMAIL}.")
    notification.notify(
        title="KindleBot Success",
        message=f"Forwarded '{subject_line}' to Covenant email!",
        app_name="KindleBot",
        timeout=5
    )

def send_to_kindle(file_path, filename):
    """Emails the converted PDF to the Kindle address."""
    msg = EmailMessage()
    msg['Subject'] = 'Scribe Document'
    msg['From'] = GMAIL_USER
    msg['To'] = KINDLE_EMAIL

    with open(file_path, 'rb') as f:
        pdf_data = f.read()
    
    msg.add_attachment(pdf_data, maintype='application', subtype='pdf', filename=filename)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.send_message(msg)
        
    logging.info(f"Successfully sent {filename} to Kindle.")
    notification.notify(
        title="KindleBot Success",
        message=f"Converted and sent {filename} to your Kindle!",
        app_name="KindleBot",
        timeout=5
    )

def background_task():
    global is_running
    pythoncom.CoInitialize()
    
    while is_running:
        try:
            with IMAPClient('imap.gmail.com') as server:
                server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
                server.select_folder('INBOX')
                
                while is_running:
                    process_inbox(server)
                    server.idle()
                    
                    idle_timeout = 900 
                    start_time = time.time()
                    
                    while is_running and (time.time() - start_time) < idle_timeout:
                        responses = server.idle_check(timeout=1.0)
                        if responses:
                            break
                    
                    server.idle_done()
                    
        except Exception as e:
            if is_running:
                time.sleep(10)
                
    pythoncom.CoUninitialize()

def create_tray_icon():
    image = Image.new('RGB', (64, 64), color=(0, 120, 215))
    d = ImageDraw.Draw(image)
    d.rectangle([16, 16, 48, 48], fill='white')
    return image

def on_quit(icon, item):
    global is_running
    is_running = False
    icon.stop()

def setup(icon):
    icon.visible = True
    threading.Thread(target=background_task, daemon=True).start()

if __name__ == "__main__":
    menu = pystray.Menu(
        pystray.MenuItem('Quit', on_quit)
    )
    
    icon = pystray.Icon("KindleBot", create_tray_icon(), "Kindle Forwarder", menu)
    icon.run(setup)