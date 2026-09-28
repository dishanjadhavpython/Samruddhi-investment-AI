"""
Retirement Specialist Agent Lambda Handler
"""

import os
import json
import asyncio
import logging
from typing import Dict, Any
from datetime import date, datetime
from zoneinfo import ZoneInfo

from agents import Agent, Runner, trace
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from litellm.exceptions import RateLimitError


class AgentTemporaryError(Exception):
    """Temporary error that should trigger retry"""
    pass

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

# Import database package
from src import Database
from src import audit

from src.compliance import checked_narrative
from src.guardrails import with_disclosure

from templates import RETIREMENT_INSTRUCTIONS
from agent import age_on, create_agent
from observability import observe

logger = logging.getLogger()
logger.setLevel(logging.INFO)

IST = ZoneInfo("Asia/Kolkata")

def get_user_preferences(job_id: str) -> Dict[str, Any]:
    """The user's saved retirement inputs. Age and monthly contribution stay
    None when the user hasn't entered them; the agent says so rather than
    assuming a value."""
    db = Database()
    job = db.jobs.find_by_id(job_id)
    if not job or not job.get('clerk_user_id'):
        raise ValueError(f"Job {job_id} has no user")
    user = db.users.find_by_clerk_id(job['clerk_user_id'])
    if not user:
        raise ValueError(f"User for job {job_id} not found")

    dob = user.get('date_of_birth')
    dob = date.fromisoformat(str(dob)[:10]) if dob else None
    contribution = user.get('monthly_contribution')
    return {
        'years_until_retirement': int(user.get('years_until_retirement') or 0),
        'target_retirement_income': float(user.get('target_retirement_income') or 0),
        'current_age': age_on(dob, datetime.now(IST).date()),
        'monthly_contribution': float(contribution) if contribution not in (None, '') else None,
    }

@retry(
    retry=retry_if_exception_type((RateLimitError, AgentTemporaryError, TimeoutError, asyncio.TimeoutError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    before_sleep=lambda retry_state: logger.info(f"Retirement: Temporary error, retrying in {retry_state.next_action.sleep} seconds...")
)
async def run_retirement_agent(job_id: str, portfolio_data: Dict[str, Any]) -> Dict[str, Any]:
    """Run the retirement specialist agent."""
    
    # Get user preferences
    user_preferences = get_user_preferences(job_id)
    
    # Initialize database
    db = Database()
    
    # Create agent (simplified - no tools or context)
    model, tools, task, facts = create_agent(job_id, portfolio_data, user_preferences, db)
    
    # Run agent (simplified - no context)
    with trace("Retirement Agent"):
        agent = Agent(
            name="Retirement Specialist",
            instructions=RETIREMENT_INSTRUCTIONS,
            model=model,
            tools=tools  # Empty list now
        )
        
        try:
            result = await Runner.run(
                agent,
                input=task,
                max_turns=20
            )
        except (TimeoutError, asyncio.TimeoutError) as e:
            logger.warning(f"Retirement agent timeout: {e}")
            raise AgentTemporaryError(f"Timeout during agent execution: {e}")
        except Exception as e:
            error_str = str(e).lower()
            if "timeout" in error_str or "throttled" in error_str:
                logger.warning(f"Retirement temporary error: {e}")
                raise AgentTemporaryError(f"Temporary error: {e}")
            raise  # Re-raise non-retryable errors

        runs = [(task, result)]

        async def draft(feedback):
            if feedback is None:
                return result.final_output
            again_input = f"{task}\n\n{feedback}"
            again = await Runner.run(agent, input=again_input, max_turns=20)
            runs.append((again_input, again))
            return again.final_output

        # Regex guardrail, then the Compliance Checker agent: one rewrite with
        # feedback, otherwise a safe fallback. The disclosure is added in code.
        analysis, checks = await checked_narrative(draft, facts, "retirement analysis")
        if checks["outcome"] == "fallback":
            logger.error(f"Retirement: using the fallback narrative: {checks}")
        analysis = with_disclosure(analysis)

        audit_result = audit.log_run(
            'retirement',
            job_id=job_id,
            clerk_user_id=portfolio_data.get('user_id'),
            agent=agent,
            runs=runs,
            checks=checks,
            facts=facts,
            final=analysis,
            sources={'user_inputs': user_preferences},
        )

        # Save the analysis to database
        retirement_payload = {
            'analysis': analysis,
            'generated_at': datetime.utcnow().isoformat(),
            'agent': 'retirement',
            'guardrail': checks['guardrail'],
            'compliance': checks['compliance'],
            'checks': {'attempts': checks['attempts'], 'outcome': checks['outcome']},
            'audit': {k: audit_result.get(k) for k in ('status', 'key', 'sha256')},
        }
        
        success = db.jobs.update_retirement(job_id, retirement_payload)
        
        if not success:
            logger.error(f"Failed to save retirement analysis for job {job_id}")
        
        return {
            'success': success,
            'message': 'Retirement analysis completed' if success else 'Analysis completed but failed to save',
            'final_output': result.final_output
        }

def lambda_handler(event, context):
    """
    Lambda handler expecting job_id in event.

    Expected event:
    {
        "job_id": "uuid",
        "portfolio_data": {...}  # Optional, will load from DB if not provided
    }
    """
    # Wrap entire handler with observability context
    with observe() as observability:
        try:
            logger.info(f"Retirement Lambda invoked with event: {json.dumps(event)[:500]}")

            # Parse event
            if isinstance(event, str):
                event = json.loads(event)

            job_id = event.get('job_id')
            if not job_id:
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': 'job_id is required'})
                }

            portfolio_data = event.get('portfolio_data')
            if not portfolio_data:
                # Try to load from database
                logger.info(f"Retirement Loading portfolio data for job {job_id}")
                try:
                    import sys
                    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
                    from src import Database

                    db = Database()
                    job = db.jobs.find_by_id(job_id)
                    if job:
                        if observability:
                            observability.create_event(
                                name="Retirement Started!", status_message="OK"
                            )
                        
                        # portfolio_data = job.get('request_payload', {}).get('portfolio_data', {})
                        user_id = job['clerk_user_id']
                        user = db.users.find_by_clerk_id(user_id)
                        accounts = db.accounts.find_by_user(user_id)

                        portfolio_data = {
                            'user_id': user_id,
                            'job_id': job_id,
                            'years_until_retirement': user.get('years_until_retirement', 30) if user else 30,
                            'accounts': []
                        }

                        for account in accounts:
                            account_data = {
                                'id': account['id'],
                                'name': account['account_name'],
                                'type': account.get('account_type', 'investment'),
                                'cash_balance': float(account.get('cash_balance', 0)),
                                'positions': []
                            }

                            positions = db.positions.find_by_account(account['id'])
                            for position in positions:
                                instrument = db.instruments.find_by_symbol(position['symbol'])
                                if instrument:
                                    account_data['positions'].append({
                                        'symbol': position['symbol'],
                                        'quantity': float(position['quantity']),
                                        'instrument': instrument
                                    })

                            portfolio_data['accounts'].append(account_data)

                        logger.info(f"Retirement: Loaded {len(portfolio_data['accounts'])} accounts with positions")
                    else:
                        logger.error(f"Retirement: Job {job_id} not found")
                        return {
                            'statusCode': 404,
                            'body': json.dumps({'error': f'Job {job_id} not found'})
                        }
                except Exception as e:
                    logger.error(f"Could not load portfolio from database: {e}")
                    return {
                        'statusCode': 400,
                        'body': json.dumps({'error': 'No portfolio data provided'})
                    }

            logger.info(f"Retirement: Processing job {job_id}")

            # Run the agent
            result = asyncio.run(run_retirement_agent(job_id, portfolio_data))

            logger.info(f"Retirement completed for job {job_id}")

            return {
                'statusCode': 200,
                'body': json.dumps(result)
            }

        except Exception as e:
            logger.error(f"Error in retirement: {e}", exc_info=True)
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'success': False,
                    'error': str(e)
                })
            }

# For local testing
if __name__ == "__main__":
    test_event = {
        "job_id": "test-retirement-123",
        "portfolio_data": {
            "accounts": [
                {
                    "name": "EPF",
                    "type": "retirement",
                    "cash_balance": 10000,
                    "positions": [
                        {
                            "symbol": "NIFTYBEES",
                            "quantity": 100,
                            "instrument": {
                                "name": "Nippon India ETF Nifty BeES",
                                "current_price": 245.30,
                                "allocation_asset_class": {"equity": 100}
                            }
                        },
                        {
                            "symbol": "HDFCLIQF",
                            "quantity": 100,
                            "instrument": {
                                "name": "HDFC Liquid Fund",
                                "current_price": 4650.30,
                                "allocation_asset_class": {"fixed_income": 100}
                            }
                        }
                    ]
                }
            ]
        }
    }
    
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))