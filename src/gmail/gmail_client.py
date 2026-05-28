# gmail_client.py — Handles Gmail auth, sending, and inbox monitoring
# Think of this as the post office:
# it authenticates you at the counter, sends your mail,
# and checks your inbox for replies.

import os
import base64
import json
import pickle
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from config import DATA_PROCESSED_DIR

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify"
]

TOKEN_FILE = "gmail_token.pickle"
RESUME_PATH = os.path.join("profile", "Resume.pdf")


def get_gmail_service():
    """
    Authenticates with Gmail via OAuth and returns a service object.
    On first run opens a browser for Google sign-in.
    Token is cached in gmail_token.pickle for subsequent runs.
    """
    creds = None

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            client_config = {
                "installed": {
                    "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                    "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                    "redirect_uris": ["http://localhost:5000/auth/callback"],
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token"
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=8080)

        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    return build("gmail", "v1", credentials=creds)


def build_email(to: str, subject: str, body: str, attach_resume: bool = True) -> str:
    """
    Builds a MIME email with optional resume attachment.
    Returns base64-encoded raw email string ready for Gmail API.
    """
    msg = MIMEMultipart()
    msg["To"] = to
    msg["From"] = "russo.sebastian@gmail.com"
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    if attach_resume and os.path.exists(RESUME_PATH):
        with open(RESUME_PATH, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f'attachment; filename="Sebastian_Russo_Resume.pdf"'
        )
        msg.attach(part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return raw


def send_email(service, to: str, subject: str, body: str) -> dict:
    """
    Sends an email via Gmail API. Returns the sent message metadata.
    """
    raw = build_email(to, subject, body)
    result = service.users().messages().send(
        userId="me",
        body={"raw": raw}
    ).execute()
    return result


def check_replies(service, companies: list[dict]) -> list[dict]:
    """
    Scans inbox for replies from any company on our list.
    Matches by sender domain against company websites.
    Returns list of matches with company + message details.
    """
    from urllib.parse import urlparse

    # Build domain -> company map
    domain_map = {}
    for c in companies:
        website = c.get("website", "")
        if website:
            domain = urlparse(website).netloc.replace("www.", "")
            if domain:
                domain_map[domain] = c

    matches = []

    # Fetch unread messages
    results = service.users().messages().list(
        userId="me",
        q="is:unread in:inbox",
        maxResults=100
    ).execute()

    messages = results.get("messages", [])

    for msg in messages:
        full = service.users().messages().get(
            userId="me",
            id=msg["id"],
            format="metadata",
            metadataHeaders=["From", "Subject", "Date"]
        ).execute()

        headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}
        sender = headers.get("From", "")
        subject = headers.get("Subject", "")
        date = headers.get("Date", "")

        # Extract domain from sender email
        sender_email = sender.split("<")[-1].replace(">", "").strip()
        sender_domain = sender_email.split("@")[-1].lower() if "@" in sender_email else ""

        if sender_domain in domain_map:
            company = domain_map[sender_domain]
            matches.append({
                "message_id": msg["id"],
                "company_name": company["name"],
                "sender": sender,
                "subject": subject,
                "date": date,
                "company": company
            })

    return matches
