import os
import random
import string
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, ConfigDict
from pymongo import MongoClient
from dotenv import load_dotenv
from fastapi import Query
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

# Retrieve credentials from .env
username = os.getenv("MONGO_USER")
password = os.getenv("MONGO_PASS")

# Build the MongoDB connection string
connection_string = (
    f"mongodb+srv://{username}:{password}@kalpamit-mlm.u7ppluu.mongodb.net/"
    "?retryWrites=true&w=majority&appName=kalpamit-mlm"
)

# Connect to MongoDB Atlas
client = MongoClient(connection_string)

# --- Access Databases and Collections ---

# Database: kalpamit_admin
kalpamit_admin = client["kalpamit_admin"]
admin_payments = kalpamit_admin["admin_payments"]
withdrawal_requests = kalpamit_admin["admin_withdrawal_requests"]

# Database: kalpamit_mlm_users
kalpamit_mlm_users = client["kalpamit_mlm_users"]
user_data = kalpamit_mlm_users["user_data"]
user_payments = kalpamit_mlm_users["user_payments"]


# --- Bank Details (optional) ---
class BankDetails(BaseModel):
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    ifsc_code: Optional[str] = None
    branch_name: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


# --- Main Sign-Up Input Model ---
class UserData(BaseModel):
    firebase_uid: str 

    name: Optional[str] = None
    email: Optional[EmailStr] = None
    reference_code: Optional[str] = None  

    sex: Optional[str] = None
    state: Optional[str] = None
    district: Optional[str] = None
    pin_code: Optional[str] = None

    bank_details: Optional[BankDetails] = None

    model_config = ConfigDict(extra="forbid")

# Helper: Generate unique referral code
def generate_unique_referral_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        if not user_data.find_one({"referral_code": code}):
            return code

class WithdrawalRequest(BaseModel):
    firebase_uid: str
    amount: float  # you can change this to int if needed
    
app = FastAPI()

# Allow frontend domain (replace with your actual Vercel frontend URL)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# POST endpoint to insert user data
@app.post("/user_data")
async def create_or_update_user(data: UserData):
    existing_user = user_data.find_one({"firebase_uid": data.firebase_uid})
    update_fields = data.dict()

    if not existing_user:
        # New user → generate referral code and default values
        referral_code = generate_unique_referral_code()
        payment_status = False

        # Handle reference code lookup
        referred_by_name = None
        reference_code = update_fields.get("reference_code")

        if reference_code:
            referrer = user_data.find_one({"referral_code": reference_code})
            if referrer:
                referred_by_name = referrer.get("name")
            else:
                raise HTTPException(status_code=400, detail="Invalid reference code")
    else:
        # Existing user → preserve previous values
        referral_code = existing_user.get("referral_code")
        payment_status = existing_user.get("payment_status", False)
        referred_by_name = existing_user.get("referred_by")
        reference_code = existing_user.get("reference_code_used")  # Preserve if already set

    # Clean up fields that shouldn't be overwritten directly
    update_fields.pop("referral_code", None)

    # Upsert the user
    user_data.update_one(
        {"firebase_uid": data.firebase_uid},
        {
            "$set": update_fields,
            "$setOnInsert": {
                "referral_code": referral_code,
                "payment_status": payment_status,
                "referred_by": referred_by_name,
                "reference_code_used": reference_code  # <-- Preserve input reference code
            }
        },
        upsert=True
    )

    return {
        "message": "User created" if not existing_user else "User updated",
        "referral_code": referral_code,
        "referred_by": referred_by_name,
        "reference_code_used": reference_code
    }


# --- GET: Fetch User by UID ---
@app.get("/user_data/{firebase_uid}")
async def get_user(firebase_uid: str):
    user = user_data.find_one({"firebase_uid": firebase_uid}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

# --- GET: Fetch User's Team upto 3 levels ---
@app.get("/team")
async def get_team(firebase_uid: str = Query(...)):
    # Step 1: Get referral code for the user
    user = user_data.find_one({"firebase_uid": firebase_uid})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    root_referral_code = user.get("referral_code")
    if not root_referral_code:
        raise HTTPException(status_code=400, detail="Referral code not found for this user")

    # Helper function to fetch users referred by given referral codes
    def find_users_by_referral(ref_codes):
        referred_users = list(user_data.find(
            {"reference_code": {"$in": ref_codes}},
            {"_id": 0, "name": 1, "referral_code": 1}
        ))
        return referred_users

    # Step 2: Build the 3-level team
    team = {}

    # Level 1
    level_1_users = find_users_by_referral([root_referral_code])
    team["level_1"] = level_1_users

    # Level 2
    level_1_codes = [user["referral_code"] for user in level_1_users]
    level_2_users = find_users_by_referral(level_1_codes)
    team["level_2"] = level_2_users

    # Level 3
    level_2_codes = [user["referral_code"] for user in level_2_users]
    level_3_users = find_users_by_referral(level_2_codes)
    team["level_3"] = level_3_users

    return team

# --- GET: Fetch User's Transactions ---
@app.get("/payments")
async def get_or_create_payment(firebase_uid: str = Query(...)):
    # Step 1: Check if payment document exists
    payment_doc = user_payments.find_one({"firebase_uid": firebase_uid}, {"_id": 0})
    if payment_doc:
        return payment_doc

    # Step 2: Check if user exists
    user_exists = user_data.find_one({"firebase_uid": firebase_uid})
    if not user_exists:
        raise HTTPException(status_code=404, detail="User not found")

    # Step 3: Create and insert an empty payment document
    empty_doc = {
        "firebase_uid": firebase_uid,
        "transactions": [],
        "last_updated": datetime.utcnow()
    }

    user_payments.insert_one(empty_doc)

    return empty_doc


# --- POST: post withdrawal request ---
@app.post("/withdrawal_request")
async def raise_withdrawal_request(data: WithdrawalRequest):
    # Step 1: Find user
    user = user_data.find_one({"firebase_uid": data.firebase_uid})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    name = user.get("name", "Unknown")

    # Step 2: Insert request
    request_doc = {
        "firebase_uid": data.firebase_uid,
        "name": name,
        "amount": data.amount,
        "requested_at": datetime.utcnow()
    }

    withdrawal_requests.insert_one(request_doc)

    return {"message": "Withdrawal request submitted", "request": request_doc}


# Run FastAPI server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
