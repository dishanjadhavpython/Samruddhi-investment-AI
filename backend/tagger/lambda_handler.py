"""
InstrumentTagger Lambda Handler
Classifies financial instruments and updates the database.
"""

import os
import json
import asyncio
import logging
from typing import List, Dict, Any

from src import Database
from src import audit
from src.schemas import InstrumentCreate
from agent import tag_instruments, classification_to_db_format
from templates import TAGGER_INSTRUCTIONS
from observability import observe

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize database
db = Database()

async def process_instruments(instruments: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Process and classify instruments asynchronously.
    
    Args:
        instruments: List of instruments to classify
        
    Returns:
        Processing results
    """
    # Run the classification
    logger.info(f"Classifying {len(instruments)} instruments")
    classifications = await tag_instruments(instruments)
    
    # Update database with classifications
    updated = []
    errors = []
    
    for classification in classifications:
        try:
            # Convert to database format
            db_instrument = classification_to_db_format(classification)
            
            # Check if instrument exists
            existing = db.instruments.find_by_symbol(classification.symbol)
            
            if existing:
                # Update allocations only; the price stays as the pricer wrote it
                rows = db.instruments.update_classification(db_instrument)
                logger.info(f"Updated {classification.symbol} in database ({rows} rows)")
            else:
                # Create new instrument
                db.instruments.create_instrument(db_instrument)
                logger.info(f"Created {classification.symbol} in database")
            
            updated.append(classification.symbol)
            
        except Exception as e:
            logger.error(f"Error updating {classification.symbol}: {e}")
            errors.append({
                'symbol': classification.symbol,
                'error': str(e)
            })
    
    # Prepare response (convert Pydantic models to dicts)
    return {
        'tagged': len(classifications),
        'updated': updated,
        'errors': errors,
        'classifications': [
            {
                'symbol': c.symbol,
                'name': c.name,
                'type': c.instrument_type,
                'asset_class': c.allocation_asset_class.model_dump(),
                'regions': c.allocation_regions.model_dump(),
                'sectors': c.allocation_sectors.model_dump()
            }
            for c in classifications
        ]
    }

def lambda_handler(event, context):
    """
    Lambda handler for instrument tagging.

    Expected event format:
    {
        "instruments": [
            {"symbol": "VTI", "name": "Vanguard Total Stock Market ETF"},
            ...
        ]
    }
    """
    # Wrap entire handler with observability context
    with observe():
        try:
            # Parse the event
            instruments = event.get('instruments', [])

            if not instruments:
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': 'No instruments provided'})
                }

            # Process all instruments in a single async context
            result = asyncio.run(process_instruments(instruments))

            # One record per batch: the classifications written to instruments
            audit.log_run(
                'tagger',
                job_id=event.get('job_id'),
                final=result['classifications'],
                sources={'instruments': instruments},
                extra={
                    'prompt_template_sha256': audit.sha256(TAGGER_INSTRUCTIONS),
                    'updated': result['updated'],
                    'errors': result['errors'],
                },
            )

            return {
                'statusCode': 200,
                'body': json.dumps(result)
            }

        except Exception as e:
            logger.error(f"Lambda handler error: {e}")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': str(e)})
            }