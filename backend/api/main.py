"""
FastAPI backend for Samruddhi AI
Handles all API routes with Clerk JWT authentication
"""

import os
import json
import logging
import re
import time
from typing import Optional, List, Dict, Any
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import uuid

from fastapi import FastAPI, HTTPException, Depends, Query, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
import boto3
from mangum import Mangum
from dotenv import load_dotenv
from fastapi_clerk_auth import ClerkConfig, ClerkHTTPBearer, HTTPAuthorizationCredentials

from src import Database
from src import deployment as explorer
from src import ledger, market_live, performance
from src.market_session import IST, session_state
from src.projection import ASSUMPTIONS as PROJECTION_ASSUMPTIONS
from src.returns import TXN_TYPES, Series, Txn
from src.schemas import (
    UserCreate,
    AccountCreate,
    PositionCreate,
    JobCreate, JobUpdate,
    JobType, JobStatus,
    HoldingAccountType,
)
from src.transactions_csv import TEMPLATE as TRANSACTIONS_TEMPLATE
from src.transactions_csv import parse as parse_transactions_csv

# Load environment variables
load_dotenv(override=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Samruddhi AI API",
    description="Backend API for AI-powered financial planning",
    version="1.0.0"
)

# CORS configuration
# Get origins from CORS_ORIGINS env var (comma-separated) or fall back to localhost
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom exception handlers for better error messages
@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    """Handle Pydantic validation errors with user-friendly messages"""
    return JSONResponse(
        status_code=422,
        content={"detail": "Invalid input data. Please check your request and try again."}
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with improved messages"""
    # Map technical errors to user-friendly messages
    user_friendly_messages = {
        401: "Your session has expired. Please sign in again.",
        403: "You don't have permission to access this resource.",
        404: "The requested resource was not found.",
        429: "Too many requests. Please slow down and try again later.",
        500: "An internal error occurred. Please try again later.",
        503: "The service is temporarily unavailable. Please try again later."
    }

    message = user_friendly_messages.get(exc.status_code, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": message}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected errors gracefully"""
    logger.error(f"Unexpected error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Our team has been notified."}
    )

# Initialize services
db = Database()

# SQS client for job queueing
sqs_client = boto3.client('sqs', region_name=os.getenv('DEFAULT_AWS_REGION', 'us-east-1'))
SQS_QUEUE_URL = os.getenv('SQS_QUEUE_URL', '')

# Clerk authentication setup (exactly like saas reference)
clerk_config = ClerkConfig(jwks_url=os.getenv("CLERK_JWKS_URL"))
clerk_guard = ClerkHTTPBearer(clerk_config)

async def get_current_user_id(creds: HTTPAuthorizationCredentials = Depends(clerk_guard)) -> str:
    """Extract user ID from validated Clerk token"""
    # The clerk_guard dependency already validated the token
    # creds.decoded contains the JWT payload
    user_id = creds.decoded["sub"]
    logger.info(f"Authenticated user: {user_id}")
    return user_id

# Request/Response models
class UserResponse(BaseModel):
    user: Dict[str, Any]
    created: bool

class UserUpdate(BaseModel):
    """Update user settings"""
    display_name: Optional[str] = None
    years_until_retirement: Optional[int] = Field(None, ge=0, le=60)
    target_retirement_income: Optional[float] = Field(None, ge=0)
    asset_class_targets: Optional[Dict[str, float]] = None
    region_targets: Optional[Dict[str, float]] = None
    # Personal inputs (migration 005)
    date_of_birth: Optional[date] = None
    monthly_contribution: Optional[float] = Field(None, ge=0, le=10_000_000)
    monthly_expenses: Optional[float] = Field(None, ge=0, le=10_000_000)
    emergency_fund_months: Optional[int] = Field(None, ge=0, le=36)
    horizon_years: Optional[int] = Field(None, ge=0, le=60)
    # The AI disclosure version the user just accepted (migration 006)
    ai_disclosure_version: Optional[str] = Field(None, max_length=20)

class AccountUpdate(BaseModel):
    """Update account"""
    account_name: Optional[str] = None
    account_purpose: Optional[str] = None
    cash_balance: Optional[float] = Field(None, ge=0)
    account_type: Optional[HoldingAccountType] = None

class PositionUpdate(BaseModel):
    """Update position"""
    quantity: Optional[float] = None

# Bump with the disclosure copy (frontend/components/Disclosure.tsx and
# AI_DISCLOSURE_VERSION in frontend/lib/ai.ts); users accept again before their next analysis
AI_DISCLOSURE_VERSION = "2026-09-28"
AI_FEEDBACK_PER_DAY = 20

class AiFeedbackIn(BaseModel):
    """"Report a problem" on AI-written text"""
    surface: str = Field(..., description="report, retirement, charts, market_narrative or other")
    category: str = Field(..., description="advice, wrong_number, outdated, unclear or other")
    message: Optional[str] = Field(None, max_length=2000)
    job_id: Optional[str] = None

class AnalyzeRequest(BaseModel):
    analysis_type: str = Field(default="portfolio", description="Type of analysis to perform")
    options: Dict[str, Any] = Field(default_factory=dict, description="Analysis options")

class AnalyzeResponse(BaseModel):
    job_id: str
    message: str


def _age(dob: date, today: date) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _owned_account(account_id: str, clerk_user_id: str) -> Dict:
    try:
        uuid.UUID(str(account_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Account not found")
    account = db.accounts.find_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.get('clerk_user_id') != clerk_user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return account


def _ensure_instrument(symbol: str) -> None:
    """Create a basic catalogue row for a symbol the app hasn't seen; the Tagger classifies it later."""
    if db.instruments.find_by_symbol(symbol):
        return
    from src.schemas import InstrumentCreate

    logger.info(f"Creating new instrument: {symbol}")
    instrument_type = "stock" if len(symbol) <= 5 and symbol.isalpha() else "etf"
    db.instruments.create_instrument(InstrumentCreate(
        symbol=symbol,
        name=f"{symbol} - User Added",
        instrument_type=instrument_type,
        allocation_regions={"india": 100.0},
        allocation_sectors={"other": 100.0},
        allocation_asset_class={"equity": 100.0} if instrument_type == "stock" else {"fixed_income": 100.0},
    ))

# API Routes

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/api/user", response_model=UserResponse)
async def get_or_create_user(
    clerk_user_id: str = Depends(get_current_user_id),
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard)
):
    """Get user or create if first time"""

    try:
        # Check if user exists
        user = db.users.find_by_clerk_id(clerk_user_id)

        if user:
            return UserResponse(user=user, created=False)

        # Create new user with defaults from JWT token
        token_data = creds.decoded
        display_name = token_data.get('name') or token_data.get('email', '').split('@')[0] or "New User"

        # Create user with ALL defaults in one operation
        user_data = {
            'clerk_user_id': clerk_user_id,
            'display_name': display_name,
            'years_until_retirement': 20,
            'target_retirement_income': 60000,
            'asset_class_targets': {"equity": 70, "fixed_income": 30},
            'region_targets': {"india": 70, "international": 30}
        }

        # Insert directly with all data
        created_clerk_id = db.users.db.insert('users', user_data, returning='clerk_user_id')

        # Fetch the created user
        created_user = db.users.find_by_clerk_id(clerk_user_id)
        logger.info(f"Created new user: {clerk_user_id}")

        return UserResponse(user=created_user, created=True)

    except Exception as e:
        logger.error(f"Error in get_or_create_user: {e}")
        raise HTTPException(status_code=500, detail="Failed to load user profile")

@app.put("/api/user")
async def update_user(user_update: UserUpdate, clerk_user_id: str = Depends(get_current_user_id)):
    """Update user settings"""

    try:
        # Get user
        user = db.users.find_by_clerk_id(clerk_user_id)

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Update user - users table uses clerk_user_id as primary key
        update_data = user_update.model_dump(exclude_unset=True)
        if "ai_disclosure_version" in update_data:
            if update_data["ai_disclosure_version"] != AI_DISCLOSURE_VERSION:
                raise HTTPException(status_code=400, detail="That disclosure version is out of date. Reload the page and try again.")
            update_data["ai_disclosure_accepted_at"] = datetime.now(timezone.utc)
        dob = update_data.get("date_of_birth")
        if dob is not None:
            age = _age(dob, datetime.now(IST).date())
            if not 18 <= age <= 100:
                raise HTTPException(status_code=400, detail="Enter a date of birth for someone aged 18 to 100.")

        # Use the database client directly since users table has clerk_user_id as PK
        db.users.db.update(
            'users',
            update_data,
            "clerk_user_id = :clerk_user_id",
            {'clerk_user_id': clerk_user_id}
        )

        # Return updated user
        updated_user = db.users.find_by_clerk_id(clerk_user_id)
        return updated_user

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/accounts")
async def list_accounts(clerk_user_id: str = Depends(get_current_user_id)):
    """List user's accounts"""

    try:
        # Get accounts for user
        accounts = db.accounts.find_by_user(clerk_user_id)
        return accounts

    except Exception as e:
        logger.error(f"Error listing accounts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/accounts")
async def create_account(account: AccountCreate, clerk_user_id: str = Depends(get_current_user_id)):
    """Create new account"""

    try:
        # Verify user exists
        user = db.users.find_by_clerk_id(clerk_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Create account
        account_id = db.accounts.create_account(
            clerk_user_id=clerk_user_id,
            account_name=account.account_name,
            account_purpose=account.account_purpose,
            cash_balance=getattr(account, 'cash_balance', Decimal('0')),
            account_type=account.account_type,
        )

        # Return created account
        created_account = db.accounts.find_by_id(account_id)
        return created_account

    except Exception as e:
        logger.error(f"Error creating account: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/accounts/{account_id}")
async def update_account(account_id: str, account_update: AccountUpdate, clerk_user_id: str = Depends(get_current_user_id)):
    """Update account"""

    try:
        # Verify account belongs to user
        account = db.accounts.find_by_id(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Verify ownership - accounts table stores clerk_user_id directly
        if account.get('clerk_user_id') != clerk_user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        # Update account
        update_data = account_update.model_dump(exclude_unset=True)
        db.accounts.update(account_id, update_data)

        # Return updated account
        updated_account = db.accounts.find_by_id(account_id)
        return updated_account

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating account: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str, clerk_user_id: str = Depends(get_current_user_id)):
    """Delete an account and all its positions"""

    try:
        # Verify account belongs to user
        account = db.accounts.find_by_id(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Verify ownership - accounts table stores clerk_user_id directly
        if account.get('clerk_user_id') != clerk_user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        # Delete all positions first (due to foreign key constraint)
        positions = db.positions.find_by_account(account_id)
        for position in positions:
            db.positions.delete(position['id'])

        # Delete the account
        db.accounts.delete(account_id)

        return {"message": "Account deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting account: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/accounts/{account_id}/positions")
async def list_positions(account_id: str, clerk_user_id: str = Depends(get_current_user_id)):
    """Get positions for account"""

    try:
        # Verify account belongs to user
        account = db.accounts.find_by_id(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Verify ownership - accounts table stores clerk_user_id directly
        if account.get('clerk_user_id') != clerk_user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        # One query: each position comes back with its full instrument row,
        # including price_as_of, price_source and price_status
        positions = db.positions.find_by_account_with_instruments(account_id)

        return {"positions": positions}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing positions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/positions")
async def create_position(position: PositionCreate, clerk_user_id: str = Depends(get_current_user_id)):
    """Create position"""

    try:
        # Verify account belongs to user
        account = db.accounts.find_by_id(position.account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Verify ownership - accounts table stores clerk_user_id directly
        if account.get('clerk_user_id') != clerk_user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        symbol = position.symbol.upper()
        _ensure_instrument(symbol)

        # The holding's quantity lives in the ledger as an opening balance
        ledger.set_quantity(db, position.account_id, symbol, float(position.quantity), datetime.now(IST).date())
        created = db.positions.find_holding(position.account_id, symbol)
        position_id = created["id"] if created else None

        # Return created position
        created_position = db.positions.find_by_id(position_id)
        return created_position

    except HTTPException:
        raise
    except ledger.LedgerConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating position: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/positions/{position_id}")
async def update_position(position_id: str, position_update: PositionUpdate, clerk_user_id: str = Depends(get_current_user_id)):
    """Update position"""

    try:
        # Get position and verify ownership
        position = db.positions.find_by_id(position_id)
        if not position:
            raise HTTPException(status_code=404, detail="Position not found")

        account = db.accounts.find_by_id(position['account_id'])
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Verify ownership - accounts table stores clerk_user_id directly
        if account.get('clerk_user_id') != clerk_user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        # Quantity changes go through the ledger (the holding's opening balance)
        update_data = position_update.model_dump(exclude_unset=True)
        if update_data.get("quantity") is not None:
            ledger.set_quantity(db, position['account_id'], position['symbol'], float(update_data["quantity"]))

        # Return updated position
        updated_position = db.positions.find_by_id(position_id)
        return updated_position

    except HTTPException:
        raise
    except ledger.LedgerConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating position: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/positions/{position_id}")
async def delete_position(position_id: str, clerk_user_id: str = Depends(get_current_user_id)):
    """Delete position"""

    try:
        # Get position and verify ownership
        position = db.positions.find_by_id(position_id)
        if not position:
            raise HTTPException(status_code=404, detail="Position not found")

        account = db.accounts.find_by_id(position['account_id'])
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Verify ownership - accounts table stores clerk_user_id directly
        if account.get('clerk_user_id') != clerk_user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        ledger.remove_holding(db, position['account_id'], position['symbol'])
        return {"message": "Position deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting position: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/instruments")
async def list_instruments(clerk_user_id: str = Depends(get_current_user_id)):
    """Get all available instruments for autocomplete"""

    try:
        instruments = db.instruments.find_all()
        # Return simplified list for autocomplete
        return [
            {
                "symbol": inst["symbol"],
                "name": inst["name"],
                "instrument_type": inst["instrument_type"],
                "current_price": float(inst["current_price"]) if inst.get("current_price") else None,
                "price_as_of": inst.get("price_as_of"),
                "price_source": inst.get("price_source"),
                "price_status": inst.get("price_status"),
            }
            for inst in instruments
        ]
    except Exception as e:
        logger.error(f"Error fetching instruments: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analyze", response_model=AnalyzeResponse)
async def trigger_analysis(request: AnalyzeRequest, clerk_user_id: str = Depends(get_current_user_id)):
    """Trigger portfolio analysis"""

    try:
        # Get user
        user = db.users.find_by_clerk_id(clerk_user_id)

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # The one-time AI disclosure comes before the first analysis (plan section 9)
        if user.get("ai_disclosure_version") != AI_DISCLOSURE_VERSION:
            raise HTTPException(
                status_code=428,
                detail="Read how AI is used in Samruddhi AI and accept it before running an analysis.",
            )

        # The Planner only calls the Reporter and Charter when there are
        # positions, so a cash-only run would finish with no report or charts
        if db.positions.count_by_user(clerk_user_id) == 0:
            raise HTTPException(
                status_code=400,
                detail="Add at least one holding before running an analysis. Cash balances on their own aren't reviewed.",
            )

        # Create job
        job_id = db.jobs.create_job(
            clerk_user_id=clerk_user_id,
            job_type="portfolio_analysis",
            request_payload=request.model_dump()
        )

        # Get the created job
        job = db.jobs.find_by_id(job_id)

        # Send to SQS
        if SQS_QUEUE_URL:
            message = {
                'job_id': str(job_id),
                'clerk_user_id': clerk_user_id,
                'analysis_type': request.analysis_type,
                'options': request.options
            }

            sqs_client.send_message(
                QueueUrl=SQS_QUEUE_URL,
                MessageBody=json.dumps(message)
            )
            logger.info(f"Sent analysis job to SQS: {job_id}")
        else:
            logger.warning("SQS_QUEUE_URL not configured, job created but not queued")

        return AnalyzeResponse(
            job_id=str(job_id),
            message="Analysis started. Check job status for results."
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error triggering analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/ai-feedback", status_code=201)
async def report_ai_problem(feedback: AiFeedbackIn, clerk_user_id: str = Depends(get_current_user_id)):
    """Record a problem a user found in AI-written text, for a person to review."""
    if feedback.surface not in db.ai_feedback.SURFACES:
        raise HTTPException(status_code=400, detail="Choose where the problem is.")
    if feedback.category not in db.ai_feedback.CATEGORIES:
        raise HTTPException(status_code=400, detail="Choose what kind of problem it is.")
    try:
        job_id = None
        if feedback.job_id:
            try:
                job_id = str(uuid.UUID(feedback.job_id))
            except ValueError:
                raise HTTPException(status_code=400, detail="Unknown analysis.")
            job = db.jobs.find_by_id(job_id)
            if not job or job.get("clerk_user_id") != clerk_user_id:
                raise HTTPException(status_code=404, detail="Analysis not found.")
        if db.ai_feedback.count_since(clerk_user_id, datetime.now(timezone.utc) - timedelta(days=1)) >= AI_FEEDBACK_PER_DAY:
            raise HTTPException(status_code=429, detail="You've sent a lot of reports today. Try again tomorrow.")
        message = (feedback.message or "").strip() or None
        feedback_id = db.ai_feedback.create(clerk_user_id, feedback.surface, feedback.category, message, job_id)
        logger.info(f"AI feedback {feedback_id}: {feedback.surface}/{feedback.category} job={job_id}")
        return {"id": feedback_id, "status": "open"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving AI feedback: {e}")
        raise HTTPException(status_code=500, detail="Couldn't save the report. Try again.")

@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str, clerk_user_id: str = Depends(get_current_user_id)):
    """Get job status and results"""

    try:
        # Get job
        job = db.jobs.find_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Verify job belongs to user - jobs table stores clerk_user_id directly
        if job.get('clerk_user_id') != clerk_user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        return job

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/jobs")
async def list_jobs(
    fields: str = "full",
    limit: int = 100,
    clerk_user_id: str = Depends(get_current_user_id),
):
    """List user's analysis jobs.

    fields=summary leaves out the JSONB payloads (flags, chart count and a
    report excerpt instead), which keeps long lists under the Data API's
    1 MiB response limit. Fetch one job's full results with /api/jobs/{id}.
    """

    try:
        limit = max(1, min(limit, 100))
        if fields == "summary":
            user_jobs = db.jobs.find_summaries_by_user(clerk_user_id, limit=limit)
        else:
            user_jobs = db.jobs.find_by_user(clerk_user_id, limit=limit)
        # Sort by created_at descending (most recent first)
        user_jobs.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return {"jobs": user_jobs}

    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Market context (index-level only; written daily by backend/market)
# ---------------------------------------------------------------------------

MARKET_METHOD_VERSION = os.getenv("MARKET_METHOD_VERSION", "v1-expanding")
MARKET_CHARTS = {"valuation", "turbulence", "perspective"}
MARKET_RANGES = {"1y": 1, "5y": 5, "10y": 10, "max": None}
MARKET_DISCLAIMER = (
    "Index statistics describe the past and do not predict future returns. "
    "Nifty 50 and India VIX closes are end of day from Yahoo Finance (demo data); "
    "valuation and total-return history is from NSE Indices. This is not investment advice."
)


@app.get("/api/market/context")
async def market_context(clerk_user_id: str = Depends(get_current_user_id)):
    """The latest market_signals row plus the NSE session state.

    Kept behind sign-in: serving it publicly would count as open-website
    display under the data licences (plan section 7.3).
    """
    try:
        now = datetime.now(timezone.utc)
        today = now.date()
        holidays = db.market.holidays(today - timedelta(days=7), today + timedelta(days=45))
        session = session_state(now, holidays)
        signal = db.market.latest_signal(MARKET_METHOD_VERSION)
        if not signal:
            return {"available": False, "session": session, "disclaimer": MARKET_DISCLAIMER}

        indicators = signal.get("indicators") or {}
        valuation = dict(indicators.get("valuation") or {})
        valuation["history"] = signal.get("history_stats")
        return {
            "available": True,
            "as_of": signal["as_of"],
            "computed_at": signal.get("created_at"),
            "method_version": signal["method_version"],
            "session": session,
            "index": indicators.get("index"),
            "valuation": valuation,
            "turbulence": indicators.get("turbulence"),
            "breaks": (indicators.get("breaks") or {}).get("registered", []),
            "coverage": indicators.get("coverage"),
            "narrative": signal.get("narrative"),
            "disclaimer": MARKET_DISCLAIMER,
        }
    except Exception as e:
        logger.error(f"Error loading market context: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Delayed intraday prices (Phase 5): DynamoDB only, written by backend/pricer
# ---------------------------------------------------------------------------

SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9&._-]{0,19}$")
SNAPSHOT_DISCLAIMER = (
    "Prices are delayed by at least 15 minutes and come from Yahoo Finance (demo data, not licensed "
    "for public display). Index levels describe the market, not any holding. This is not investment advice."
)


def _symbol_list(text: Optional[str], limit: int) -> List[str]:
    symbols = [s for s in dict.fromkeys(part.strip().upper() for part in (text or "").split(",")) if s]
    if len(symbols) > limit:
        raise HTTPException(status_code=400, detail=f"Ask for at most {limit} symbols at a time.")
    bad = [s for s in symbols if not SYMBOL_PATTERN.match(s)]
    if bad:
        raise HTTPException(status_code=400, detail=f"Not a symbol: {', '.join(bad[:3])}")
    return symbols


@app.get("/api/market/snapshot")
async def market_snapshot(
    symbols: Optional[str] = Query(None, description="Comma-separated symbols, at most 50"),
    intraday: Optional[str] = Query(None, description="Index ids for today's 5-minute points, e.g. NIFTY50"),
    clerk_user_id: str = Depends(get_current_user_id),
):
    """The latest delayed prices for the indices and the given symbols, plus the session state.

    Reads only DynamoDB (src/market_live.py), never Aurora, so open tabs can
    poll it every minute while NSE is open. Behind sign-in like the rest of
    /api/market/* (plan section 7.3).
    """
    started = time.perf_counter()
    wanted = _symbol_list(symbols, market_live.MAX_SYMBOLS)
    series = _symbol_list(intraday, len(market_live.INDICES))
    unknown = [s for s in series if s not in market_live.INDICES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"intraday must be one of {sorted(market_live.INDICES)}")
    try:
        body = market_live.read_snapshot(wanted, datetime.now(timezone.utc), series)
    except Exception as e:
        logger.error(f"Error reading the market snapshot: {e}")
        raise HTTPException(status_code=503, detail="Delayed prices are unavailable right now. Please try again shortly.")
    body["disclaimer"] = SNAPSHOT_DISCLAIMER
    response = JSONResponse(body)
    response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - started) * 1000:.1f}"
    response.headers["Cache-Control"] = "private, no-store"
    return response


BAR_RANGES = {"6m": 183, "1y": 366, "3y": 1096, "max": None}
BAR_SOURCES = {"yahoo": "Yahoo Finance (demo data)", "amfi": "AMFI"}


@app.get("/api/instruments/{symbol}/bars")
async def instrument_bars(
    symbol: str,
    range_: str = Query("1y", alias="range"),
    clerk_user_id: str = Depends(get_current_user_id),
):
    """Daily bars for the chart on a holding's detail: OHLC for exchange prices, closes for NAVs."""
    symbol = symbol.strip().upper()
    if not SYMBOL_PATTERN.match(symbol):
        raise HTTPException(status_code=400, detail="Not a symbol.")
    if range_ not in BAR_RANGES:
        raise HTTPException(status_code=400, detail=f"range must be one of {list(BAR_RANGES)}")
    days = BAR_RANGES[range_]
    start = date(1990, 1, 1) if days is None else datetime.now(IST).date() - timedelta(days=days)
    try:
        rows = db.prices.bars(symbol, start)
    except Exception as e:
        logger.error(f"Error loading bars for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    ohlc = bool(rows) and all(r["o"] is not None and r["h"] is not None and r["l"] is not None for r in rows)
    sources = sorted({r["source"] for r in rows})
    return {
        "symbol": symbol,
        "range": range_,
        "kind": "ohlc" if ohlc else "close",
        "fields": ["d", "o", "h", "l", "c"] if ohlc else ["d", "c"],
        "rows": [[r["d"], r["o"], r["h"], r["l"], r["c"]] if ohlc else [r["d"], r["c"]] for r in rows],
        "as_of": rows[-1]["d"] if rows else None,
        "source": ", ".join(BAR_SOURCES.get(s, s) for s in sources),
    }


def _rows_since(table: Optional[Dict], cutoff: str) -> Optional[Dict]:
    """Keep chart rows dated on or after cutoff (dates are ISO strings, first field)."""
    if not table or "rows" not in table:
        return table
    return {**table, "rows": [row for row in table["rows"] if row[0] >= cutoff]}


@app.get("/api/market/history")
async def market_history(
    chart: str,
    range_: str = Query("max", alias="range"),
    clerk_user_id: str = Depends(get_current_user_id),
):
    """One precomputed Market page chart, trimmed to the requested range."""
    if chart not in MARKET_CHARTS:
        raise HTTPException(status_code=400, detail=f"chart must be one of {sorted(MARKET_CHARTS)}")
    if range_ not in MARKET_RANGES:
        raise HTTPException(status_code=400, detail=f"range must be one of {list(MARKET_RANGES)}")
    try:
        row = db.market.chart(chart, MARKET_METHOD_VERSION)
        if not row:
            return {"chart": chart, "available": False}
        payload = row["payload"]
        years = MARKET_RANGES[range_]
        if years and payload.get("available"):
            as_of = datetime.fromisoformat(row["as_of"])
            cutoff = (as_of - timedelta(days=round(365.25 * years))).date().isoformat()
            payload = _rows_since(payload, cutoff)
            if "vix" in payload:
                payload["vix"] = _rows_since(payload["vix"], cutoff)
        return {"chart": chart, "range": range_, "as_of": row["as_of"], "method_version": MARKET_METHOD_VERSION, **payload}
    except Exception as e:
        logger.error(f"Error loading market chart {chart}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------------
# Transactions (Phase 3): the ledger behind each holding's quantity and cost
# ---------------------------------------------------------------------------

class TransactionIn(BaseModel):
    account_id: str
    txn_type: str
    trade_date: date
    symbol: Optional[str] = Field(None, max_length=20)
    quantity: Optional[float] = None
    price: Optional[float] = Field(None, ge=0)
    amount: Optional[float] = Field(None, ge=0)
    fees: float = Field(0, ge=0)
    note: Optional[str] = Field(None, max_length=500)
    update_cash: bool = False


class TransactionEdit(BaseModel):
    trade_date: Optional[date] = None
    quantity: Optional[float] = None
    price: Optional[float] = Field(None, ge=0)
    amount: Optional[float] = Field(None, ge=0)
    fees: Optional[float] = Field(None, ge=0)
    note: Optional[str] = Field(None, max_length=500)


class TransactionImport(BaseModel):
    account_id: str
    csv: str = Field(..., max_length=2_000_000)
    update_cash: bool = False
    dry_run: bool = True


def _not_in_future(day: Optional[date]) -> None:
    if day and day > datetime.now(IST).date():
        raise HTTPException(status_code=400, detail="The date can't be in the future.")


def _owned_transaction(txn_id: str, clerk_user_id: str) -> Dict:
    try:
        uuid.UUID(str(txn_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Transaction not found")
    row = db.transactions.get(txn_id)
    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if row.get("clerk_user_id") != clerk_user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return row


@app.get("/api/transactions")
async def list_transactions(
    account_id: Optional[str] = None,
    symbol: Optional[str] = None,
    clerk_user_id: str = Depends(get_current_user_id),
):
    """A user's ledger, newest first, optionally for one account or symbol."""
    if account_id:
        _owned_account(account_id, clerk_user_id)
    rows = db.transactions.for_user(clerk_user_id, account_id, symbol.upper() if symbol else None)
    return {"transactions": rows, "types": list(TXN_TYPES)}


@app.get("/api/transactions/template")
async def transactions_template(clerk_user_id: str = Depends(get_current_user_id)):
    """The CSV layout the importer reads, with three example rows."""
    return {"filename": "samruddhi-transactions-template.csv", "csv": TRANSACTIONS_TEMPLATE}


@app.post("/api/transactions")
async def create_transaction(body: TransactionIn, clerk_user_id: str = Depends(get_current_user_id)):
    _owned_account(body.account_id, clerk_user_id)
    _not_in_future(body.trade_date)
    symbol = body.symbol.strip().upper() if body.symbol and body.symbol.strip() else None
    try:
        if symbol:
            _ensure_instrument(symbol)
        txn = Txn(body.txn_type, body.trade_date, symbol, float(body.quantity or 0.0), body.price, body.amount, body.fees)
        txn_id = ledger.add(db, body.account_id, txn, update_cash=body.update_cash, note=body.note)
        return db.transactions.get(txn_id)
    except ledger.LedgerConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/transactions/{txn_id}")
async def update_transaction(txn_id: str, body: TransactionEdit, clerk_user_id: str = Depends(get_current_user_id)):
    row = _owned_transaction(txn_id, clerk_user_id)
    changes = body.model_dump(exclude_unset=True)
    _not_in_future(changes.get("trade_date"))
    try:
        ledger.edit(db, row, changes)
        return db.transactions.get(txn_id)
    except ledger.LedgerConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/transactions/{txn_id}")
async def delete_transaction(txn_id: str, clerk_user_id: str = Depends(get_current_user_id)):
    row = _owned_transaction(txn_id, clerk_user_id)
    try:
        ledger.remove(db, row)
        return {"message": "Transaction deleted"}
    except ledger.LedgerConflict as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/transactions/import")
async def import_transactions(body: TransactionImport, clerk_user_id: str = Depends(get_current_user_id)):
    """Preview (dry_run) or record a CSV of transactions into one account."""
    _owned_account(body.account_id, clerk_user_id)
    parsed = parse_transactions_csv(body.csv)
    symbols = sorted({r["txn"].symbol for r in parsed["rows"] if r["txn"].symbol})
    known = {i["symbol"] for i in db.instruments.find_all()}
    if body.dry_run:
        return {
            "dry_run": True,
            "columns": parsed["columns"],
            "rows": [
                {
                    "line": r["line"], "txn_type": r["txn"].txn_type, "trade_date": r["txn"].trade_date.isoformat(),
                    "symbol": r["txn"].symbol, "quantity": r["txn"].quantity if r["txn"].symbol else None,
                    "price": r["txn"].price, "amount": r["txn"].amount, "fees": r["txn"].fees, "note": r["note"],
                }
                for r in parsed["rows"]
            ],
            "errors": parsed["errors"],
            "new_symbols": [s for s in symbols if s not in known],
        }
    try:
        for symbol in symbols:
            if symbol not in known:
                _ensure_instrument(symbol)
        result = ledger.import_rows(db, body.account_id, parsed["rows"], update_cash=body.update_cash)
    except ledger.LedgerConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"dry_run": False, **result, "errors": sorted(parsed["errors"] + result["errors"], key=lambda e: e["line"])}


# ---------------------------------------------------------------------------
# Performance (Phase 3): XIRR, absolute return and the Nifty 50 on the same flows
# ---------------------------------------------------------------------------

PERFORMANCE_DISCLAIMER = (
    "Returns are worked out from the transactions and opening balances you recorded, at the latest prices "
    "in the app. They describe the past and do not predict future returns. The Nifty 50 comparison invests "
    "the same rupees on the same dates in the index; it is not a recommendation."
)


def _series(rows: List[Dict]) -> Series:
    return Series.of((date.fromisoformat(r["d"]), r["v"]) for r in rows)


@app.get("/api/portfolio/performance")
async def portfolio_performance(
    range_: str = Query("1y", alias="range"),
    clerk_user_id: str = Depends(get_current_user_id),
):
    if range_ not in performance.RANGES:
        raise HTTPException(status_code=400, detail=f"range must be one of {list(performance.RANGES)}")
    try:
        rows = db.transactions.for_user(clerk_user_id)
        txns = [ledger.to_txn(r) for r in rows]
        if not txns:
            return {"available": False, "reason": "no_transactions", "disclaimer": PERFORMANCE_DISCLAIMER}
        today = datetime.now(IST).date()
        first = min(t.trade_date for t in txns)
        symbols = sorted({t.symbol for t in txns if t.symbol})
        catalogue = {i["symbol"]: i for i in db.instruments.find_all()}

        def price(symbol: str) -> Optional[float]:
            value = (catalogue.get(symbol) or {}).get("current_price")
            return float(value) if value not in (None, "") and float(value) > 0 else None

        closes = {s: _series(db.prices.closes(s, first - timedelta(days=10))) for s in symbols}
        indices = {sid: _series(db.prices.series(sid, first - timedelta(days=10))) for sid in ("NIFTY50_TRI", "NIFTY50")}
        estimates = [r["symbol"] for r in rows if r["txn_type"] == "opening_balance" and r["source"] == "system"]
        result = performance.compute(txns, {s: price(s) for s in symbols}, closes, indices, today, range_, estimates)
        result["disclaimer"] = PERFORMANCE_DISCLAIMER
        return result
    except Exception as e:
        logger.error(f"Error computing performance: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/projection/assumptions")
async def projection_assumptions(clerk_user_id: str = Depends(get_current_user_id)):
    """The retirement projection's assumptions, shared by the Goals page and the Retirement agent."""
    return PROJECTION_ASSUMPTIONS


# ---------------------------------------------------------------------------
# Lump sum vs staggered explorer (Phase 3, index level only)
# ---------------------------------------------------------------------------

LIQUID_YIELD_SYMBOL = os.getenv("LIQUID_YIELD_SYMBOL", "HDFCLIQF")
FALLBACK_CASH_YIELD = 0.06
DEPLOYMENT_DISCLAIMER = (
    "Historical Nifty 50 outcomes from every start date, not a forecast and not a recommendation. Start dates "
    "overlap, so the periods are not independent, and the cheapest-valuation results rest on a few market crises. "
    "Data ends at least 30 days ago. Investment in securities market are subject to market risks."
)


def _liquid_yield(today: date) -> Dict:
    """Default yield on waiting cash: a liquid fund's NAV growth over the last 12 months."""
    navs = _series(db.prices.closes(LIQUID_YIELD_SYMBOL, today - timedelta(days=400)))
    if navs and navs.first <= navs.last - timedelta(days=360):
        start = navs.at(navs.last - timedelta(days=365))
        if start:
            return {"value": round(navs.values[-1] / start - 1, 4), "as_of": navs.last.isoformat(),
                    "basis": "Last 12 months' growth in a liquid fund's NAV (AMFI)"}
    return {"value": FALLBACK_CASH_YIELD, "as_of": None, "basis": "A round 6%; no liquid-fund NAV history is loaded"}


@app.get("/api/market/deployment-history")
async def deployment_history(
    months: int = 6,
    cash_yield: Optional[float] = None,
    clerk_user_id: str = Depends(get_current_user_id),
):
    if months not in explorer.PLANS:
        raise HTTPException(status_code=400, detail=f"months must be one of {list(explorer.PLANS)}")
    if cash_yield is not None and not 0 <= cash_yield <= 0.15:
        raise HTTPException(status_code=400, detail="cash_yield must be between 0 and 0.15")
    try:
        row = db.market.chart("deployment", MARKET_METHOD_VERSION)
        if not row or not row["payload"].get("available"):
            return {"available": False, "disclaimer": DEPLOYMENT_DISCLAIMER}
        table = row["payload"]
        default_yield = _liquid_yield(datetime.now(IST).date())
        chosen = default_yield["value"] if cash_yield is None else cash_yield
        return {
            "available": True,
            "as_of": row["as_of"],
            "method_version": MARKET_METHOD_VERSION,
            "series": table["series"],
            "source": table["source"],
            "data_until": table["data_until"],
            "step_trading_days": table["step_trading_days"],
            "has_temperature": table["has_temperature"],
            "default_cash_yield": default_yield,
            **explorer.explore(table, months, chosen),
            "disclaimer": DEPLOYMENT_DISCLAIMER,
        }
    except Exception as e:
        logger.error(f"Error loading deployment history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/reset-accounts")
async def reset_accounts(clerk_user_id: str = Depends(get_current_user_id)):
    """Delete all accounts for the current user"""

    try:
        # Get user
        user = db.users.find_by_clerk_id(clerk_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get all accounts for user
        accounts = db.accounts.find_by_user(clerk_user_id)

        # Delete each account (positions will cascade delete)
        deleted_count = 0
        for account in accounts:
            try:
                # Positions are deleted automatically via CASCADE
                db.accounts.delete(account['id'])
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Could not delete account {account['id']}: {e}")

        return {
            "message": f"Deleted {deleted_count} account(s)",
            "accounts_deleted": deleted_count
        }

    except Exception as e:
        logger.error(f"Error resetting accounts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/populate-test-data")
async def populate_test_data(clerk_user_id: str = Depends(get_current_user_id)):
    """Populate test data for the current user"""

    try:
        # Get user
        user = db.users.find_by_clerk_id(clerk_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Define missing instruments that might not be in the database
        # (individual Indian stocks - the ETFs/mutual funds referenced in accounts_data
        # below are expected to already exist via seed_data.py's INSTRUMENTS catalog)
        missing_instruments = {
            "RELIANCE": {
                "name": "Reliance Industries Ltd.",
                "type": "stock",
                "current_price": 2850.00,
                "allocation_regions": {"india": 100},
                "allocation_sectors": {"energy": 100},
                "allocation_asset_class": {"equity": 100}
            },
            "TCS": {
                "name": "Tata Consultancy Services Ltd.",
                "type": "stock",
                "current_price": 3850.00,
                "allocation_regions": {"india": 100},
                "allocation_sectors": {"technology": 100},
                "allocation_asset_class": {"equity": 100}
            },
            "INFY": {
                "name": "Infosys Ltd.",
                "type": "stock",
                "current_price": 1650.00,
                "allocation_regions": {"india": 100},
                "allocation_sectors": {"technology": 100},
                "allocation_asset_class": {"equity": 100}
            },
            "HDFCBANK": {
                "name": "HDFC Bank Ltd.",
                "type": "stock",
                "current_price": 1680.00,
                "allocation_regions": {"india": 100},
                "allocation_sectors": {"financials": 100},
                "allocation_asset_class": {"equity": 100}
            },
            "ICICIBANK": {
                "name": "ICICI Bank Ltd.",
                "type": "stock",
                "current_price": 1150.00,
                "allocation_regions": {"india": 100},
                "allocation_sectors": {"financials": 100},
                "allocation_asset_class": {"equity": 100}
            },
            "BHARTIARTL": {
                "name": "Bharti Airtel Ltd.",
                "type": "stock",
                "current_price": 1180.00,
                "allocation_regions": {"india": 100},
                "allocation_sectors": {"communication": 100},
                "allocation_asset_class": {"equity": 100}
            },
        }

        # Check and add missing instruments
        for symbol, info in missing_instruments.items():
            existing = db.instruments.find_by_symbol(symbol)
            if not existing:
                try:
                    from src.schemas import InstrumentCreate

                    instrument_data = InstrumentCreate(
                        symbol=symbol,
                        name=info["name"],
                        instrument_type=info["type"],
                        current_price=Decimal(str(info["current_price"])),
                        allocation_regions=info["allocation_regions"],
                        allocation_sectors=info["allocation_sectors"],
                        allocation_asset_class=info["allocation_asset_class"]
                    )
                    db.instruments.create_instrument(instrument_data)
                    logger.info(f"Added missing instrument: {symbol}")
                except Exception as e:
                    logger.warning(f"Could not add instrument {symbol}: {e}")

        # Create accounts with test data
        accounts_data = [
            {
                "name": "EPF - Long-term",
                "purpose": "Primary retirement savings account with employer match",
                "cash": 5000.00,
                "positions": [
                    ("NIFTYBEES", 150),   # Nifty 50 ETF
                    ("UTINIFTY", 100),    # Nifty 50 Index Fund
                    ("LIQUIDBEES", 200),  # Liquid ETF (fixed income)
                    ("JUNIORBEES", 75),   # Nifty Next 50 ETF
                    ("BANKBEES", 50),     # Bank Nifty ETF
                ]
            },
            {
                "name": "PPF Account",
                "purpose": "Tax-free retirement growth account",
                "cash": 2500.00,
                "positions": [
                    ("NIFTYBEES", 80),    # Nifty 50 ETF
                    ("ITBEES", 60),       # IT sector ETF
                    ("GOLDBEES", 40),     # Gold ETF
                    ("SILVERBEES", 25),   # Silver ETF
                    ("ICICICORP", 30),    # Corporate Bond Fund
                    ("LIQUIDBEES", 45),   # Liquid ETF
                ]
            },
            {
                "name": "Demat / Trading Account",
                "purpose": "Taxable investment account for individual stocks",
                "cash": 10000.00,
                "positions": [
                    ("RELIANCE", 15),     # Reliance Industries
                    ("TCS", 50),          # Tata Consultancy Services
                    ("INFY", 10),         # Infosys
                    ("HDFCBANK", 25),     # HDFC Bank
                    ("ICICIBANK", 30),    # ICICI Bank
                    ("BHARTIARTL", 20),   # Bharti Airtel
                ]
            }
        ]

        created_accounts = []
        for account_data in accounts_data:
            # Create account
            account_id = db.accounts.create_account(
                clerk_user_id=clerk_user_id,
                account_name=account_data["name"],
                account_purpose=account_data["purpose"],
                cash_balance=Decimal(str(account_data["cash"]))
            )

            # Add positions
            for symbol, quantity in account_data["positions"]:
                try:
                    ledger.set_quantity(db, account_id, symbol, float(quantity), datetime.now(IST).date())
                except Exception as e:
                    logger.warning(f"Could not add position {symbol}: {e}")

            created_accounts.append(account_id)

        # Get all accounts with their positions for summary
        all_accounts = []
        for account_id in created_accounts:
            account = db.accounts.find_by_id(account_id)
            positions = db.positions.find_by_account(account_id)
            account['positions'] = positions
            all_accounts.append(account)

        return {
            "message": "Test data populated successfully",
            "accounts_created": len(created_accounts),
            "accounts": all_accounts
        }

    except Exception as e:
        logger.error(f"Error populating test data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Lambda handler
handler = Mangum(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)