"""
Database models and query builders
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, date
from decimal import Decimal
from .client import DataAPIClient
from .schemas import (
    InstrumentCreate, UserCreate, AccountCreate, 
    PositionCreate, JobCreate, JobUpdate
)


class BaseModel:
    """Base class for database models"""
    
    table_name = None
    
    def __init__(self, db: DataAPIClient):
        self.db = db
        if not self.table_name:
            raise ValueError("table_name must be defined")
    
    def find_by_id(self, id: Any) -> Optional[Dict]:
        """Find a record by ID"""
        sql = f"SELECT * FROM {self.table_name} WHERE id = :id::uuid"
        return self.db.query_one(sql, [{'name': 'id', 'value': {'stringValue': str(id)}}])
    
    def find_all(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Find all records with pagination"""
        sql = f"SELECT * FROM {self.table_name} LIMIT :limit OFFSET :offset"
        params = [
            {'name': 'limit', 'value': {'longValue': limit}},
            {'name': 'offset', 'value': {'longValue': offset}}
        ]
        return self.db.query(sql, params)
    
    def create(self, data: Dict, returning: str = 'id') -> str:
        """Create a new record"""
        return self.db.insert(self.table_name, data, returning=returning)
    
    def update(self, id: Any, data: Dict) -> int:
        """Update a record by ID"""
        return self.db.update(self.table_name, data, "id = :id::uuid", {'id': str(id)})
    
    def delete(self, id: Any) -> int:
        """Delete a record by ID"""
        return self.db.delete(self.table_name, "id = :id::uuid", {'id': str(id)})


class Users(BaseModel):
    """Users table operations"""
    table_name = 'users'
    
    def find_by_clerk_id(self, clerk_user_id: str) -> Optional[Dict]:
        """Find user by Clerk ID"""
        sql = f"SELECT * FROM {self.table_name} WHERE clerk_user_id = :clerk_id"
        params = [{'name': 'clerk_id', 'value': {'stringValue': clerk_user_id}}]
        return self.db.query_one(sql, params)
    
    def create_user(self, clerk_user_id: str, display_name: str = None, 
                   years_until_retirement: int = None,
                   target_retirement_income: Decimal = None) -> str:
        """Create a new user"""
        data = {
            'clerk_user_id': clerk_user_id,
            'display_name': display_name,
            'years_until_retirement': years_until_retirement,
            'target_retirement_income': target_retirement_income
        }
        # Remove None values
        data = {k: v for k, v in data.items() if v is not None}
        return self.db.insert(self.table_name, data, returning='clerk_user_id')


class Instruments(BaseModel):
    """Instruments table operations"""
    table_name = 'instruments'

    def find_all(self, limit: int = None, offset: int = 0) -> List[Dict]:
        """Find all instruments - no limit by default for autocomplete"""
        sql = f"SELECT * FROM {self.table_name} ORDER BY symbol"
        return self.db.query(sql, [])

    def find_by_symbol(self, symbol: str) -> Optional[Dict]:
        """Find instrument by symbol"""
        sql = f"SELECT * FROM {self.table_name} WHERE symbol = :symbol"
        params = [{'name': 'symbol', 'value': {'stringValue': symbol}}]
        return self.db.query_one(sql, params)
    
    def create_instrument(self, instrument: InstrumentCreate) -> str:
        """Create a new instrument with validation"""
        # Validate using Pydantic
        validated = instrument.model_dump()
        
        # Convert allocations to JSON strings for storage
        data = {
            'symbol': validated['symbol'],
            'name': validated['name'],
            'instrument_type': validated['instrument_type'],
            'allocation_regions': validated['allocation_regions'],
            'allocation_sectors': validated['allocation_sectors'],
            'allocation_asset_class': validated['allocation_asset_class']
        }
        
        return self.db.insert(self.table_name, data, returning='symbol')

    def update_classification(self, instrument: InstrumentCreate) -> int:
        """Update name, type and allocations for an existing instrument.

        Never touches current_price: backend/pricer is its only writer
        (see backend/test_price_writers.py).
        """
        validated = instrument.model_dump()
        data = {
            'name': validated['name'],
            'instrument_type': validated['instrument_type'],
            'allocation_regions': validated['allocation_regions'],
            'allocation_sectors': validated['allocation_sectors'],
            'allocation_asset_class': validated['allocation_asset_class']
        }
        return self.db.update(
            self.table_name, data, 'symbol = :symbol', {'symbol': validated['symbol']}
        )

    def update_price(self, symbol: str, price: float) -> int:
        """Update just the current_price for an instrument.

        Instruments are keyed by `symbol` (not a uuid `id`), so the generic
        BaseModel.update() (which assumes an `id::uuid` column) doesn't apply here.
        """
        return self.db.update(
            'instruments', {'current_price': price}, 'symbol = :symbol', {'symbol': symbol}
        )

    def find_by_type(self, instrument_type: str) -> List[Dict]:
        """Find all instruments of a specific type"""
        sql = f"SELECT * FROM {self.table_name} WHERE instrument_type = :type ORDER BY symbol"
        params = [{'name': 'type', 'value': {'stringValue': instrument_type}}]
        return self.db.query(sql, params)
    
    def search(self, query: str) -> List[Dict]:
        """Search instruments by symbol or name"""
        sql = f"""
            SELECT * FROM {self.table_name} 
            WHERE LOWER(symbol) LIKE LOWER(:query) 
               OR LOWER(name) LIKE LOWER(:query)
            ORDER BY symbol
            LIMIT 20
        """
        params = [{'name': 'query', 'value': {'stringValue': f'%{query}%'}}]
        return self.db.query(sql, params)


class Accounts(BaseModel):
    """Accounts table operations"""
    table_name = 'accounts'
    
    def find_by_user(self, clerk_user_id: str) -> List[Dict]:
        """Find all accounts for a user"""
        sql = f"""
            SELECT * FROM {self.table_name} 
            WHERE clerk_user_id = :user_id 
            ORDER BY created_at DESC
        """
        params = [{'name': 'user_id', 'value': {'stringValue': clerk_user_id}}]
        return self.db.query(sql, params)
    
    def create_account(self, clerk_user_id: str, account_name: str,
                      account_purpose: str = None, cash_balance: Decimal = Decimal('0'),
                      cash_interest: Decimal = Decimal('0'), account_type: str = 'other') -> str:
        """Create a new account"""
        data = {
            'clerk_user_id': clerk_user_id,
            'account_name': account_name,
            'account_purpose': account_purpose,
            'cash_balance': cash_balance,
            'cash_interest': cash_interest,
            'account_type': account_type,
        }
        return self.db.insert(self.table_name, data, returning='id')

    def adjust_cash(self, account_id: str, delta: float) -> Optional[float]:
        """Add delta to the cash balance unless that would take it below zero.

        Returns the new balance, or None when the balance was too small.
        """
        row = self.db.query_one(
            """
            UPDATE accounts SET cash_balance = cash_balance + :delta::numeric
            WHERE id = :id::uuid AND cash_balance + :delta::numeric >= 0
            RETURNING cash_balance::float AS cash_balance
            """,
            [
                {'name': 'delta', 'value': {'stringValue': f"{delta:.2f}"}},
                {'name': 'id', 'value': {'stringValue': account_id}},
            ],
        )
        return row['cash_balance'] if row else None


class Positions(BaseModel):
    """Positions table operations"""
    table_name = 'positions'
    
    def find_by_account(self, account_id: str) -> List[Dict]:
        """Find all positions in an account"""
        sql = f"""
            SELECT p.*, i.name as instrument_name, i.instrument_type, i.current_price
            FROM {self.table_name} p
            JOIN instruments i ON p.symbol = i.symbol
            WHERE p.account_id = :account_id::uuid
            ORDER BY p.symbol
        """
        params = [{'name': 'account_id', 'value': {'stringValue': account_id}}]
        return self.db.query(sql, params)
    
    def find_by_account_with_instruments(self, account_id: str) -> List[Dict]:
        """Positions in an account, each with its full instrument row under 'instrument'.

        One query instead of one instrument lookup per position.
        """
        sql = f"""
            SELECT p.*, i.name AS instrument_name, i.instrument_type, i.current_price,
                   to_jsonb(i) AS instrument
            FROM {self.table_name} p
            JOIN instruments i ON p.symbol = i.symbol
            WHERE p.account_id = :account_id::uuid
            ORDER BY p.symbol
        """
        params = [{'name': 'account_id', 'value': {'stringValue': account_id}}]
        return self.db.query(sql, params)

    def count_by_user(self, clerk_user_id: str) -> int:
        """Number of positions across all of a user's accounts"""
        sql = f"""
            SELECT COUNT(*) AS count
            FROM {self.table_name} p
            JOIN accounts a ON p.account_id = a.id
            WHERE a.clerk_user_id = :clerk_user_id
        """
        params = [{'name': 'clerk_user_id', 'value': {'stringValue': clerk_user_id}}]
        rows = self.db.query(sql, params)
        return int(rows[0]['count']) if rows else 0

    def get_portfolio_value(self, account_id: str) -> Dict:
        """Calculate total portfolio value using current prices from instruments table"""
        sql = """
            SELECT 
                COUNT(DISTINCT p.symbol) as num_positions,
                SUM(p.quantity * i.current_price) as total_value,
                SUM(p.quantity) as total_shares
            FROM positions p
            JOIN instruments i ON p.symbol = i.symbol
            WHERE p.account_id = :account_id::uuid
        """
        params = [
            {'name': 'account_id', 'value': {'stringValue': account_id}}
        ]
        result = self.db.query_one(sql, params)
        if result:
            return {
                'num_positions': result.get('num_positions', 0),
                'total_value': float(result.get('total_value', 0)) if result.get('total_value') else 0,
                'total_shares': float(result.get('total_shares', 0)) if result.get('total_shares') else 0
            }
        return {'num_positions': 0, 'total_value': 0, 'total_shares': 0}
    
    def add_position(self, account_id: str, symbol: str, quantity: Decimal) -> str:
        """Add or update a position"""
        # Use UPSERT to handle existing positions
        sql = """
            INSERT INTO positions (account_id, symbol, quantity, as_of_date)
            VALUES (:account_id::uuid, :symbol, :quantity::numeric, :as_of_date::date)
            ON CONFLICT (account_id, symbol) 
            DO UPDATE SET 
                quantity = EXCLUDED.quantity,
                as_of_date = EXCLUDED.as_of_date,
                updated_at = NOW()
            RETURNING id
        """
        params = [
            {'name': 'account_id', 'value': {'stringValue': account_id}},
            {'name': 'symbol', 'value': {'stringValue': symbol}},
            {'name': 'quantity', 'value': {'stringValue': str(quantity)}},
            {'name': 'as_of_date', 'value': {'stringValue': date.today().isoformat()}}
        ]
        response = self.db.execute(sql, params)
        if response.get('records'):
            return response['records'][0][0].get('stringValue')
        return None

    def find_holding(self, account_id: str, symbol: str) -> Optional[Dict]:
        sql = f"SELECT * FROM {self.table_name} WHERE account_id = :account_id::uuid AND symbol = :symbol"
        return self.db.query_one(sql, [
            {'name': 'account_id', 'value': {'stringValue': account_id}},
            {'name': 'symbol', 'value': {'stringValue': symbol}},
        ])

    def set_from_ledger(self, account_id: str, symbol: str, quantity: float, avg_cost: Optional[float],
                        cost_basis: Optional[float], first_buy_date: Optional[date]) -> None:
        """Write a holding's quantity and cost as the ledger computed them (src/ledger.py)."""
        def num(value, digits):
            return {'stringValue': f"{value:.{digits}f}"} if value is not None else {'isNull': True}

        self.db.execute(
            """
            INSERT INTO positions (account_id, symbol, quantity, avg_cost, cost_basis, first_buy_date, as_of_date)
            VALUES (:account_id::uuid, :symbol, :quantity::numeric, :avg_cost::numeric, :cost_basis::numeric,
                    :first_buy_date::date, CURRENT_DATE)
            ON CONFLICT (account_id, symbol) DO UPDATE SET
                quantity = EXCLUDED.quantity, avg_cost = EXCLUDED.avg_cost, cost_basis = EXCLUDED.cost_basis,
                first_buy_date = EXCLUDED.first_buy_date, as_of_date = CURRENT_DATE, updated_at = NOW()
            """,
            [
                {'name': 'account_id', 'value': {'stringValue': account_id}},
                {'name': 'symbol', 'value': {'stringValue': symbol}},
                {'name': 'quantity', 'value': num(quantity, 8)},
                {'name': 'avg_cost', 'value': num(avg_cost, 4)},
                {'name': 'cost_basis', 'value': num(cost_basis, 2)},
                {'name': 'first_buy_date', 'value': {'stringValue': first_buy_date.isoformat()} if first_buy_date else {'isNull': True}},
            ],
        )

    def delete_holding(self, account_id: str, symbol: str) -> int:
        return self.db.delete(self.table_name, "account_id = :account_id::uuid AND symbol = :symbol",
                              {'account_id': account_id, 'symbol': symbol})

    def all_holdings(self) -> List[Dict]:
        """Every (account, symbol) with a position, for one-off backfills."""
        return self.db.query(
            "SELECT p.account_id::text AS account_id, p.symbol, p.quantity::float AS quantity, "
            "COALESCE(p.as_of_date, p.created_at::date)::text AS as_of_date FROM positions p ORDER BY 1, 2"
        )


class Transactions(BaseModel):
    """The transaction ledger. Positions are derived from it by src/ledger.py."""
    table_name = 'transactions'

    COLUMNS = """t.id::text AS id, t.account_id::text AS account_id, t.txn_type, t.trade_date::text AS trade_date,
                 t.symbol, t.quantity::float AS quantity, t.price::float AS price, t.amount::float AS amount,
                 t.fees::float AS fees, t.cash_effect::float AS cash_effect, t.source, t.external_ref, t.note,
                 t.created_at::text AS created_at, t.updated_at::text AS updated_at"""

    def get(self, txn_id: str) -> Optional[Dict]:
        return self.db.query_one(
            f"SELECT {self.COLUMNS}, a.clerk_user_id FROM transactions t JOIN accounts a ON a.id = t.account_id "
            "WHERE t.id = :id::uuid",
            [{'name': 'id', 'value': {'stringValue': txn_id}}],
        )

    def for_user(self, clerk_user_id: str, account_id: str = None, symbol: str = None) -> List[Dict]:
        where = ["a.clerk_user_id = :user_id"]
        params = [{'name': 'user_id', 'value': {'stringValue': clerk_user_id}}]
        if account_id:
            where.append("t.account_id = :account_id::uuid")
            params.append({'name': 'account_id', 'value': {'stringValue': account_id}})
        if symbol:
            where.append("t.symbol = :symbol")
            params.append({'name': 'symbol', 'value': {'stringValue': symbol}})
        return self.db.query(
            f"""
            SELECT {self.COLUMNS}, a.account_name
            FROM transactions t JOIN accounts a ON a.id = t.account_id
            WHERE {' AND '.join(where)}
            ORDER BY t.trade_date DESC, t.created_at DESC
            """,
            params,
        )

    def for_holding(self, account_id: str, symbol: str) -> List[Dict]:
        return self.db.query(
            f"SELECT {self.COLUMNS} FROM transactions t WHERE t.account_id = :account_id::uuid AND t.symbol = :symbol",
            [
                {'name': 'account_id', 'value': {'stringValue': account_id}},
                {'name': 'symbol', 'value': {'stringValue': symbol}},
            ],
        )

    INSERT_SQL = """
        INSERT INTO transactions (account_id, txn_type, trade_date, symbol, quantity, price, amount, fees,
                                  cash_effect, source, external_ref, note)
        VALUES (:account_id::uuid, :txn_type, :trade_date::date, :symbol, :quantity::numeric, :price::numeric,
                :amount::numeric, :fees::numeric, :cash_effect::numeric, :source, :external_ref, :note)
        ON CONFLICT (account_id, source, external_ref) DO NOTHING
    """

    @staticmethod
    def _params(account_id: str, row: Dict) -> List[Dict]:
        def num(key, digits):
            value = row.get(key)
            return {'stringValue': f"{value:.{digits}f}"} if value is not None else {'isNull': True}

        def text(key):
            value = row.get(key)
            return {'stringValue': str(value)} if value not in (None, "") else {'isNull': True}

        return [
            {'name': 'account_id', 'value': {'stringValue': account_id}},
            {'name': 'txn_type', 'value': {'stringValue': row['txn_type']}},
            {'name': 'trade_date', 'value': {'stringValue': row['trade_date'].isoformat()}},
            {'name': 'symbol', 'value': text('symbol')},
            {'name': 'quantity', 'value': num('quantity', 8)},
            {'name': 'price', 'value': num('price', 4)},
            {'name': 'amount', 'value': num('amount', 2)},
            {'name': 'fees', 'value': {'stringValue': f"{row.get('fees') or 0:.2f}"}},
            {'name': 'cash_effect', 'value': {'stringValue': f"{row.get('cash_effect') or 0:.2f}"}},
            {'name': 'source', 'value': {'stringValue': row.get('source', 'manual')}},
            {'name': 'external_ref', 'value': text('external_ref')},
            {'name': 'note', 'value': text('note')},
        ]

    def insert_row(self, account_id: str, row: Dict) -> Optional[str]:
        """Insert one ledger row; returns its id, or None when (source, external_ref) is already there."""
        found = self.db.query_one(self.INSERT_SQL + " RETURNING id::text AS id", self._params(account_id, row))
        return found['id'] if found else None

    def insert_many(self, account_id: str, rows: List[Dict], batch: int = 200) -> None:
        """Insert many rows in batched Data API calls (CSV import); duplicates are skipped."""
        sets = [self._params(account_id, row) for row in rows]
        for start in range(0, len(sets), batch):
            self.db.batch_execute(self.INSERT_SQL, sets[start:start + batch])

    def refs(self, account_id: str, source: str) -> set:
        rows = self.db.query(
            "SELECT external_ref FROM transactions WHERE account_id = :account_id::uuid AND source = :source "
            "AND external_ref IS NOT NULL",
            [
                {'name': 'account_id', 'value': {'stringValue': account_id}},
                {'name': 'source', 'value': {'stringValue': source}},
            ],
        )
        return {r['external_ref'] for r in rows}

    def update_row(self, txn_id: str, fields: Dict) -> int:
        return self.db.update(self.table_name, fields, "id = :id::uuid", {'id': txn_id})

    def delete_holding(self, account_id: str, symbol: str) -> int:
        return self.db.delete(self.table_name, "account_id = :account_id::uuid AND symbol = :symbol",
                              {'account_id': account_id, 'symbol': symbol})


class Prices:
    """Daily closes (price_bars_daily) and index series (market_series) for returns."""

    def __init__(self, db_client: DataAPIClient):
        self.db = db_client

    def close_on_or_before(self, symbol: str, day: date) -> Optional[float]:
        row = self.db.query_one(
            """
            SELECT close::float AS close FROM price_bars_daily
            WHERE symbol = :symbol AND trade_date <= :day::date AND close > 0
            ORDER BY trade_date DESC LIMIT 1
            """,
            [
                {'name': 'symbol', 'value': {'stringValue': symbol}},
                {'name': 'day', 'value': {'stringValue': day.isoformat()}},
            ],
        )
        return row['close'] if row else None

    def closes(self, symbol: str, start: date) -> List[Dict]:
        return self.db.query(
            """
            SELECT trade_date::text AS d, close::float AS v FROM price_bars_daily
            WHERE symbol = :symbol AND trade_date >= :start::date AND close > 0 ORDER BY trade_date
            """,
            [
                {'name': 'symbol', 'value': {'stringValue': symbol}},
                {'name': 'start', 'value': {'stringValue': start.isoformat()}},
            ],
        )

    def bars(self, symbol: str, start: date) -> List[Dict]:
        """Daily OHLC bars, oldest first. NAV funds have a close only."""
        return self.db.query(
            """
            SELECT trade_date::text AS d, open::float AS o, high::float AS h, low::float AS l,
                   close::float AS c, source
            FROM price_bars_daily
            WHERE symbol = :symbol AND trade_date >= :start::date AND close > 0 ORDER BY trade_date
            """,
            [
                {'name': 'symbol', 'value': {'stringValue': symbol}},
                {'name': 'start', 'value': {'stringValue': start.isoformat()}},
            ],
        )

    def series(self, series_id: str, start: date) -> List[Dict]:
        return self.db.query(
            """
            SELECT obs_date::text AS d, value::float AS v FROM market_series
            WHERE series_id = :series_id AND obs_date >= :start::date ORDER BY obs_date
            """,
            [
                {'name': 'series_id', 'value': {'stringValue': series_id}},
                {'name': 'start', 'value': {'stringValue': start.isoformat()}},
            ],
        )


class Jobs(BaseModel):
    """Jobs table operations"""
    table_name = 'jobs'
    
    def create_job(self, clerk_user_id: str, job_type: str, 
                  request_payload: Dict = None) -> str:
        """Create a new job"""
        data = {
            'clerk_user_id': clerk_user_id,
            'job_type': job_type,
            'status': 'pending',
            'request_payload': request_payload
        }
        return self.db.insert(self.table_name, data, returning='id')
    
    def update_status(self, job_id: str, status: str, error_message: str = None) -> int:
        """Update job status"""
        data = {'status': status}
        
        if status == 'running':
            data['started_at'] = datetime.utcnow()
        elif status in ['completed', 'failed']:
            data['completed_at'] = datetime.utcnow()
        
        if error_message:
            data['error_message'] = error_message
        
        return self.db.update(self.table_name, data, "id = :id::uuid", {'id': job_id})
    
    def update_report(self, job_id: str, report_payload: Dict) -> int:
        """Update job with Reporter agent's analysis"""
        data = {'report_payload': report_payload}
        return self.db.update(self.table_name, data, "id = :id::uuid", {'id': job_id})
    
    def update_charts(self, job_id: str, charts_payload: Dict) -> int:
        """Update job with Charter agent's visualization data"""
        data = {'charts_payload': charts_payload}
        return self.db.update(self.table_name, data, "id = :id::uuid", {'id': job_id})
    
    def update_retirement(self, job_id: str, retirement_payload: Dict) -> int:
        """Update job with Retirement agent's projections"""
        data = {'retirement_payload': retirement_payload}
        return self.db.update(self.table_name, data, "id = :id::uuid", {'id': job_id})
    
    def update_summary(self, job_id: str, summary_payload: Dict) -> int:
        """Update job with Planner's final summary"""
        data = {'summary_payload': summary_payload}
        return self.db.update(self.table_name, data, "id = :id::uuid", {'id': job_id})

    def update_market(self, job_id: str, market_payload: Dict) -> int:
        """Save the market backdrop this job may use (Planner's invoke_market_context)"""
        data = {'market_payload': market_payload}
        return self.db.update(self.table_name, data, "id = :id::uuid", {'id': job_id})
    
    def find_by_user(self, clerk_user_id: str, status: str = None, 
                    limit: int = 20) -> List[Dict]:
        """Find jobs for a user"""
        if status:
            sql = f"""
                SELECT * FROM {self.table_name}
                WHERE clerk_user_id = :user_id AND status = :status
                ORDER BY created_at DESC
                LIMIT :limit
            """
            params = [
                {'name': 'user_id', 'value': {'stringValue': clerk_user_id}},
                {'name': 'status', 'value': {'stringValue': status}},
                {'name': 'limit', 'value': {'longValue': limit}}
            ]
        else:
            sql = f"""
                SELECT * FROM {self.table_name}
                WHERE clerk_user_id = :user_id
                ORDER BY created_at DESC
                LIMIT :limit
            """
            params = [
                {'name': 'user_id', 'value': {'stringValue': clerk_user_id}},
                {'name': 'limit', 'value': {'longValue': limit}}
            ]

        return self.db.query(sql, params)

    def find_summaries_by_user(self, clerk_user_id: str, limit: int = 20) -> List[Dict]:
        """A user's jobs without the large JSONB payloads.

        Keeps a list of many jobs well under the Data API's 1 MiB response
        limit. The flags say which agents delivered; report_excerpt feeds the
        dashboard's "latest insight".
        """
        sql = f"""
            SELECT id, clerk_user_id, job_type, status, request_payload, error_message,
                   created_at, started_at, completed_at, updated_at,
                   (report_payload->>'content') IS NOT NULL AS has_report,
                   CASE WHEN jsonb_typeof(charts_payload) = 'object'
                        THEN (SELECT COUNT(*) FROM jsonb_object_keys(charts_payload))
                        ELSE 0 END AS chart_count,
                   (retirement_payload->>'analysis') IS NOT NULL AS has_retirement,
                   LEFT(report_payload->>'content', 600) AS report_excerpt,
                   report_payload->>'kb_status' AS kb_status
            FROM {self.table_name}
            WHERE clerk_user_id = :user_id
            ORDER BY created_at DESC
            LIMIT :limit
        """
        params = [
            {'name': 'user_id', 'value': {'stringValue': clerk_user_id}},
            {'name': 'limit', 'value': {'longValue': limit}}
        ]
        return self.db.query(sql, params)


class Market:
    """Read side of the market pipeline (written by backend/market).

    Index-level data only; nothing here depends on the user.
    """

    def __init__(self, db_client: DataAPIClient):
        self.db = db_client

    def latest_signal(self, method_version: str) -> Optional[Dict]:
        return self.db.query_one(
            """
            SELECT as_of::text AS as_of, method_version, valuation_score::float AS valuation_score, zone,
                   indicators, history_stats, narrative, created_at::text AS created_at
            FROM market_signals
            WHERE method_version = :method_version
            ORDER BY as_of DESC LIMIT 1
            """,
            [{'name': 'method_version', 'value': {'stringValue': method_version}}],
        )

    def signal_on(self, as_of: date, method_version: str) -> Optional[Dict]:
        return self.db.query_one(
            """
            SELECT as_of::text AS as_of, method_version, valuation_score::float AS valuation_score, zone,
                   indicators, history_stats, narrative, created_at::text AS created_at
            FROM market_signals
            WHERE as_of = :as_of::date AND method_version = :method_version
            """,
            [
                {'name': 'as_of', 'value': {'stringValue': as_of.isoformat()}},
                {'name': 'method_version', 'value': {'stringValue': method_version}},
            ],
        )

    def set_narrative(self, as_of: date, method_version: str, narrative: Dict) -> int:
        """Store the day's shared narrative (backend/signals) on its signal row"""
        return self.db.update(
            'market_signals',
            {'narrative': narrative},
            "as_of = :as_of::date AND method_version = :method_version",
            {'as_of': as_of.isoformat(), 'method_version': method_version},
        )

    def chart(self, chart_id: str, method_version: str) -> Optional[Dict]:
        return self.db.query_one(
            """
            SELECT as_of::text AS as_of, payload, updated_at::text AS updated_at
            FROM market_charts
            WHERE chart_id = :chart_id AND method_version = :method_version
            """,
            [
                {'name': 'chart_id', 'value': {'stringValue': chart_id}},
                {'name': 'method_version', 'value': {'stringValue': method_version}},
            ],
        )

    def holidays(self, start: date, end: date) -> List[date]:
        rows = self.db.query(
            """
            SELECT trade_date::text AS d FROM market_holidays
            WHERE trade_date BETWEEN :start::date AND :end::date ORDER BY trade_date
            """,
            [
                {'name': 'start', 'value': {'stringValue': start.isoformat()}},
                {'name': 'end', 'value': {'stringValue': end.isoformat()}},
            ],
        )
        return [date.fromisoformat(r['d']) for r in rows]


class AiFeedback:
    """"Report a problem" on AI-written text (migration 006)"""

    SURFACES = ('report', 'retirement', 'charts', 'market_narrative', 'other')
    CATEGORIES = ('advice', 'wrong_number', 'outdated', 'unclear', 'other')

    def __init__(self, db_client: DataAPIClient):
        self.db = db_client

    def create(self, clerk_user_id: str, surface: str, category: str,
               message: Optional[str] = None, job_id: Optional[str] = None) -> str:
        return self.db.query_one(
            """
            INSERT INTO ai_feedback (clerk_user_id, job_id, surface, category, message)
            VALUES (:user_id, CAST(:job_id AS uuid), :surface, :category, :message)
            RETURNING id::text AS id
            """,
            [
                {'name': 'user_id', 'value': {'stringValue': clerk_user_id}},
                {'name': 'job_id', 'value': {'stringValue': job_id} if job_id else {'isNull': True}},
                {'name': 'surface', 'value': {'stringValue': surface}},
                {'name': 'category', 'value': {'stringValue': category}},
                {'name': 'message', 'value': {'stringValue': message} if message else {'isNull': True}},
            ],
        )['id']

    def count_since(self, clerk_user_id: str, since: datetime) -> int:
        row = self.db.query_one(
            """
            SELECT COUNT(*) AS n FROM ai_feedback
            WHERE clerk_user_id = :user_id AND created_at >= :since::timestamptz
            """,
            [
                {'name': 'user_id', 'value': {'stringValue': clerk_user_id}},
                {'name': 'since', 'value': {'stringValue': since.isoformat()}},
            ],
        )
        return int(row['n']) if row else 0


class Database:
    """Main database interface providing access to all models"""

    def __init__(self, cluster_arn: str = None, secret_arn: str = None,
                 database: str = None, region: str = None):
        """Initialize database with all model classes"""
        self.client = DataAPIClient(cluster_arn, secret_arn, database, region)

        # Initialize all models
        self.users = Users(self.client)
        self.instruments = Instruments(self.client)
        self.accounts = Accounts(self.client)
        self.positions = Positions(self.client)
        self.jobs = Jobs(self.client)
        self.market = Market(self.client)
        self.transactions = Transactions(self.client)
        self.prices = Prices(self.client)
        self.ai_feedback = AiFeedback(self.client)
    
    def execute_raw(self, sql: str, parameters: List[Dict] = None) -> Dict:
        """Execute raw SQL for complex queries"""
        return self.client.execute(sql, parameters)
    
    def query_raw(self, sql: str, parameters: List[Dict] = None) -> List[Dict]:
        """Execute raw SELECT query"""
        return self.client.query(sql, parameters)