import sys
import os
import shutil
from pathlib import Path

# Setup Path
BACKEND_DIR = Path("c:/Users/e629/Desktop/faceattendance/backend_face")
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    from auth.companies import create_company, delete_company, get_companies
    from auth.users import create_user, get_users, delete_user
    from auth.storage import get_tokens, save_tokens, AUTH_DATA_DIR
    DATA_DIR = Path("data")
    print("Imports successful!")
except Exception as e:
    print(f"IMPORT ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

def test_cascading_deletion():
    print("Starting Cascading Deletion Test...")
    company_id = "test_cleanup_comp"
    admin_uname = "test_cleanup_admin"
    
    try:
        # Create company
        print(f"Creating company {company_id}...")
        create_company("Test Cleanup Company", company_id=company_id)
        
        # Create user
        print(f"Creating user {admin_uname}...")
        create_user(admin_uname, "password", "Admin", "system", company_id=company_id)
        
        # Simulate active token
        print("Creating dummy token...")
        tokens = get_tokens()
        dummy_token = "dummy_token_123"
        tokens[dummy_token] = {"username": admin_uname, "company_id": company_id}
        save_tokens(tokens)
        
        # Create dummy settings file
        settings_file = AUTH_DATA_DIR / f"settings_{company_id}.json"
        settings_file.write_text("{}")
        
        # Create dummy data folder
        comp_dir = DATA_DIR / company_id
        comp_dir.mkdir(parents=True, exist_ok=True)
        (comp_dir / "dummy.txt").write_text("dummy")
        
        print("Setup complete. Verifying deletion...")
        
        # 2. Delete Company
        print(f"Deleting company {company_id} (Triggering Cascading Cleanup)...")
        delete_company(company_id)
        
        # 3. Assertions
        companies = get_companies()
        users = get_users()
        tokens = get_tokens()
        
        errors = []
        if company_id in companies: errors.append("Company still exists in companies.json")
        if admin_uname in users: errors.append("User still exists in users.json")
        if dummy_token in tokens: errors.append("Token still exists in tokens.json")
        if settings_file.exists(): errors.append("Settings file still exists")
        if comp_dir.exists(): errors.append("Data directory still exists")
        
        if not errors:
            print("SUCCESS: All data cleaned up correctly!")
        else:
            print("FAILURE: Some data remains:")
            for e in errors:
                print(f"  - {e}")
                
    except Exception as e:
        print(f"EXCEPTION during test: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup any mess left by the test itself
        try:
            if company_id in get_companies():
                delete_company(company_id)
        except: pass

if __name__ == "__main__":
    test_cascading_deletion()
