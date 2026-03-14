import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
import uuid
from datetime import datetime
from .storage import load_json, atomic_write_json

COMPANIES_FILE = Path("data/auth/companies.json")

def ensure_companies_file():
    COMPANIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not COMPANIES_FILE.exists():
        atomic_write_json(COMPANIES_FILE, {})

def get_companies() -> Dict[str, Any]:
    ensure_companies_file()
    return load_json(COMPANIES_FILE, {})

def save_companies(companies: Dict[str, Any]):
    atomic_write_json(COMPANIES_FILE, companies)

def create_company(name: str, company_id: Optional[str] = None) -> Dict[str, Any]:
    companies = get_companies()
    
    # If no ID provided, we could still generate one, but plan says slug is provided
    # or auto-generated in frontend. Let's ensure it's unique.
    cid = company_id if company_id else str(uuid.uuid4())
    
    if cid in companies:
        raise ValueError(f"Company ID {cid} already exists")
    
    company_data = {
        "id": cid,
        "name": name,
        "created_at": datetime.now().isoformat()
    }
    companies[cid] = company_data
    save_companies(companies)
    return company_data

def get_company(company_id: str) -> Optional[Dict[str, Any]]:
    companies = get_companies()
    return companies.get(company_id)

def list_companies() -> List[Dict[str, Any]]:
    return list(get_companies().values())

def update_company(company_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    companies = get_companies()
    if company_id not in companies:
        return None
    
    company = companies[company_id]
    allowed_updates = ["name", "address"]
    for key, value in updates.items():
        if key in allowed_updates:
            company[key] = value
            
    save_companies(companies)
    return company

def delete_company(company_id: str) -> bool:
    companies = get_companies()
    if company_id not in companies:
        return False
    
    del companies[company_id]
    save_companies(companies)
    return True
