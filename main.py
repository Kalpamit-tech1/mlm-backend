from pydantic import BaseModel, EmailStr, ConfigDict
from fastapi import FastAPI, HTTPException, Request
from typing import Optional, List, Dict, Literal
import os
from pymongo import MongoClient
from dotenv import load_doten

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

    name: str
    email: EmailStr
    password: str
    referral_code: str  # ✅ Required now

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
        if not user_data_collection.find_one({"referral_code": code}):
            return code
    
app = FastAPI()


# POST endpoint to insert user data
# --- Endpoint ---
@app.post("/user_data")
async def create_or_update_user(data: UserData):
    existing_user = user_data_collection.find_one({"firebase_uid": data.firebase_uid})

    update_fields = data.dict()

    if not existing_user:
        # New user → generate referral code
        referral_code = generate_unique_referral_code()
        update_fields["referral_code"] = referral_code
    else:
        # Use the existing referral code if updating
        referral_code = existing_user.get("referral_code", data.referral_code)
        update_fields["referral_code"] = referral_code  # Ensure it's preserved

    # Perform the upsert
    user_data_collection.update_one(
        {"firebase_uid": data.firebase_uid},
        {"$set": update_fields, "$setOnInsert": {"referral_code": referral_code}},
        upsert=True
    )

    return {
        "message": "User created" if not existing_user else "User updated",
        "referral_code": referral_code
    }

@app.get("/items/{item_id}")
def read_item(item_id: int, q: Optional[str] = None):
    return {"item_id": item_id, "q": q}
