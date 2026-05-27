import sys
sys.path.insert(0, '.')
import csv
from src.writer.email_writer import draft_email

with open('data/processed/partners_classified.csv') as f:
    partners = list(csv.DictReader(f))

# Grab 5 that aren't ignored
test = [p for p in partners if p['classification'] != 'ignore'][:5]

for partner in test:
    print(f"\n--- {partner['name']} ({partner['classification']}) ---")
    email = draft_email(partner)
    print(f"TO:      {email['email_to']}")
    print(f"SUBJECT: {email['subject']}")
    print(f"\n{email['body']}")
    print("-" * 60)