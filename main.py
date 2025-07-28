import os
import random
import string
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, ConfigDict
from pymongo import MongoClient
from dotenv import load_dotenv

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
    
app = FastAPI()

# Allow frontend domain (replace with your actual Vercel frontend URL)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# POST endpoint to insert user data
# --- Endpoint ---
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

    # Clean up fields that shouldn't be overwritten
    update_fields.pop("referral_code", None)
    update_fields.pop("reference_code", None)

    # Upsert the user
    user_data.update_one(
        {"firebase_uid": data.firebase_uid},
        {
            "$set": update_fields,
            "$setOnInsert": {
                "referral_code": referral_code,
                "payment_status": payment_status,
                "referred_by": referred_by_name
            }
        },
        upsert=True
    )

    return {
        "message": "User created" if not existing_user else "User updated",
        "referral_code": referral_code,
        "referred_by": referred_by_name
    }

# --- GET: Fetch User by UID ---
@app.get("/user_data/{firebase_uid}")
async def get_user(firebase_uid: str):
    user = user_data.find_one({"firebase_uid": firebase_uid}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

# Run FastAPI server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
