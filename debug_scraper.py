import sys
sys.path.insert(0, '.')
import csv
from src.classifier.job_classifier import load_profile, classify_company

profile = load_profile()

with open('data/raw/partners_raw.csv') as f:
    partners = list(csv.DictReader(f))

# Test on first 5
for partner in partners[:5]:
    print(f"\n--- {partner['name']} ---")
    try:
        result = classify_company(partner, profile)
        print(f"  Classification: {result['classification']}")
        print(f"  Reasoning:      {result['reasoning']}")
        print(f"  Email:          {result['contact_email']}")
    except Exception as e:
        print(f"  ERROR: {e}")
