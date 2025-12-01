#!/usr/bin/env python3
"""
Inspect Zoho CRM Fields
Run this script to see exactly what fields and values Zoho returns for Leads.

Usage:
    python scripts/inspect_zoho_fields.py
"""
import os
import sys
import httpx
from pathlib import Path

# Load .env file
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

# Get credentials from environment
CLIENT_ID = os.getenv("ZOHO_CLIENT_ID")
CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN")
ACCOUNTS_DOMAIN = os.getenv("ZOHO_ACCOUNTS_DOMAIN", "https://accounts.zoho.com")
API_DOMAIN = os.getenv("ZOHO_API_DOMAIN", "https://www.zohoapis.com")

def get_access_token():
    """Get access token using refresh token"""
    print("🔑 Getting access token...")

    response = httpx.post(
        f"{ACCOUNTS_DOMAIN}/oauth/v2/token",
        params={
            "refresh_token": REFRESH_TOKEN,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "refresh_token",
        },
    )

    if response.status_code != 200:
        print(f"❌ Auth failed: {response.text}")
        sys.exit(1)

    data = response.json()
    print("✅ Got access token")
    return data["access_token"]

def get_leads(token, count=5):
    """Fetch a few leads to inspect their fields"""
    print(f"\n📥 Fetching {count} leads from Zoho CRM...")

    headers = {"Authorization": f"Zoho-oauthtoken {token}"}

    response = httpx.get(
        f"{API_DOMAIN}/crm/v2/Leads",
        headers=headers,
        params={"per_page": count}
    )

    if response.status_code != 200:
        print(f"❌ Failed to fetch leads: {response.text}")
        sys.exit(1)

    return response.json()

def main():
    print("=" * 60)
    print("ZOHO CRM FIELD INSPECTOR")
    print("=" * 60)

    # Check credentials
    if not all([CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN]):
        print("❌ Missing Zoho credentials in .env file")
        print(f"   Looking for .env at: {env_path}")
        sys.exit(1)

    # Get token and fetch leads
    token = get_access_token()
    data = get_leads(token, count=5)

    records = data.get("data", [])
    print(f"✅ Got {len(records)} leads\n")

    if not records:
        print("No records found!")
        return

    # Show all unique field names across all records
    all_fields = set()
    for record in records:
        all_fields.update(record.keys())

    print("=" * 60)
    print(f"ALL FIELDS RETURNED ({len(all_fields)} fields):")
    print("=" * 60)
    for field in sorted(all_fields):
        print(f"  - {field}")

    # Look for status-related fields
    print("\n" + "=" * 60)
    print("STATUS-RELATED FIELDS:")
    print("=" * 60)
    status_keywords = ["status", "stage", "state", "candidate"]
    for field in sorted(all_fields):
        if any(kw in field.lower() for kw in status_keywords):
            print(f"  ⭐ {field}")

    # Show detailed info for first 3 leads
    print("\n" + "=" * 60)
    print("SAMPLE LEAD DATA (first 3 records):")
    print("=" * 60)

    for i, record in enumerate(records[:3], 1):
        print(f"\n--- Lead {i} ---")
        print(f"  ID: {record.get('id')}")
        print(f"  Name: {record.get('First_Name', '')} {record.get('Last_Name', '')}")
        print(f"  Email: {record.get('Email')}")

        # Show all status-related fields with their values
        for field in sorted(record.keys()):
            if any(kw in field.lower() for kw in status_keywords):
                value = record.get(field)
                print(f"  {field}: {value}")

    # Show unique values for Candidate_Status if it exists
    print("\n" + "=" * 60)
    print("CANDIDATE_STATUS VALUES IN SAMPLE:")
    print("=" * 60)

    status_field = None
    for field in all_fields:
        if "candidate" in field.lower() and "status" in field.lower():
            status_field = field
            break

    if status_field:
        values = set(record.get(status_field) for record in records if record.get(status_field))
        print(f"  Field name: {status_field}")
        print(f"  Unique values: {values}")
    else:
        print("  ⚠️  No 'Candidate_Status' field found!")
        print("  Looking for alternatives...")
        for field in sorted(all_fields):
            if "status" in field.lower():
                values = set(record.get(field) for record in records if record.get(field))
                print(f"  {field}: {values}")

if __name__ == "__main__":
    main()
