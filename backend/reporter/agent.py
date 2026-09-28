"""
Report Writer Agent - generates portfolio analysis narratives.
"""

import os
import re
import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from agents import function_tool, RunContextWrapper
from agents.extensions.models.litellm_model import LitellmModel

from src.guardrails import NarrativeFacts, figures_in, validate_narrative
from src.market_brief import add_facts, brief_lines, display_date

logger = logging.getLogger()

# Knowledge base v2 (backend/ingest): dated, sourced, chunked notes
KB_INDEX = os.getenv("KB_INDEX_NAME", "financial-research-v2")
KB_MAX_AGE_DAYS = 14
KB_TOP_K = 12
KB_MAX_SOURCES = 4
KB_EXCERPT_CHARS = 700


@dataclass
class ReporterContext:
    """Context for the Reporter agent"""

    job_id: str
    portfolio_data: Dict[str, Any]
    user_data: Dict[str, Any]
    db: Optional[Any] = None  # Database connection (optional for testing)
    # Knowledge-base outcome, saved in report_payload: not_called, ok, empty or error
    kb_status: str = "not_called"
    # The notes shown to the model, saved in report_payload so the report's [n] resolve
    citations: List[Dict[str, Any]] = field(default_factory=list)
    # The market backdrop from jobs.market_payload (src/market_brief.py)
    market_payload: Optional[Dict[str, Any]] = None


def calculate_portfolio_metrics(portfolio_data: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate basic portfolio metrics."""
    metrics = {
        "total_value": 0,
        "cash_balance": 0,
        "num_accounts": len(portfolio_data.get("accounts", [])),
        "num_positions": 0,
        "unique_symbols": set(),
    }

    for account in portfolio_data.get("accounts", []):
        metrics["cash_balance"] += float(account.get("cash_balance", 0))
        positions = account.get("positions", [])
        metrics["num_positions"] += len(positions)

        for position in positions:
            symbol = position.get("symbol")
            if symbol:
                metrics["unique_symbols"].add(symbol)

            # Calculate value if we have price
            instrument = position.get("instrument", {})
            if instrument.get("current_price"):
                value = float(position.get("quantity", 0)) * float(instrument["current_price"])
                metrics["total_value"] += value

    metrics["total_value"] += metrics["cash_balance"]
    metrics["unique_symbols"] = len(metrics["unique_symbols"])

    return metrics


def clean_name(name: str) -> str:
    """An instrument name as a short label: up to its first sentence break, at most 80 characters.

    Names can come from users (custom symbols), so a name carrying extra
    sentences must not reach the Compliance Checker's list of holdings.
    """
    return re.split(r"[.!?\n]", name or "", maxsplit=1)[0].strip()[:80]


def collect_report_facts(portfolio_data: Dict[str, Any], user_data: Dict[str, Any]) -> NarrativeFacts:
    """Every ₹ and % figure the code computed, and simple arithmetic on them, for grounding the report."""
    metrics = calculate_portfolio_metrics(portfolio_data)
    total = metrics["total_value"]
    invested = total - metrics["cash_balance"]
    target = float(user_data.get("target_retirement_income") or 0)
    facts = NarrativeFacts(
        amounts=[total, metrics["cash_balance"], invested, target, target / 12],  # target a year and a month
        percents=[100.0],
    )
    if total > 0:
        facts.percents += [100 * metrics["cash_balance"] / total, 100 * invested / total]
    if target > 0:
        facts.percents += [100 * total / target, 100 * invested / target]

    aggregates: Dict[str, Dict[str, float]] = {}
    for account in portfolio_data.get("accounts", []):
        cash = float(account.get("cash_balance", 0))
        account_total = cash
        facts.amounts.append(cash)
        for position in account.get("positions", []):
            instrument = position.get("instrument", {})
            facts.securities += [position.get("symbol", ""), clean_name(instrument.get("name", ""))]
            value = 0.0
            if instrument.get("current_price"):
                value = float(position.get("quantity", 0)) * float(instrument["current_price"])
                facts.amounts.append(value)
                account_total += value
                for base in (total, invested):  # share of everything, and of the holdings alone
                    if base > 0:
                        facts.percents.append(100 * value / base)
            for key in ("allocation_asset_class", "allocation_regions", "allocation_sectors"):
                for name, pct in (instrument.get(key) or {}).items():
                    facts.percents.append(float(pct))
                    aggregates.setdefault(key, {}).setdefault(name, 0.0)
                    aggregates[key][name] += value * float(pct) / 100
        facts.amounts.append(account_total)

    mix = portfolio_mix(portfolio_data)
    for shares in mix.values():
        facts.percents += list(shares.values())

    # Portfolio-level mix, as a share of invested value and of total value
    invested = total - metrics["cash_balance"]
    for breakdown in aggregates.values():
        for amount in breakdown.values():
            facts.amounts.append(amount)
            for base in (invested, total):
                if base > 0:
                    facts.percents.append(100 * amount / base)
    return facts


MIX_KEYS = {"allocation_asset_class": "Asset classes", "allocation_regions": "Regions", "allocation_sectors": "Largest sectors"}


def portfolio_mix(portfolio_data: Dict[str, Any]) -> Dict[str, Any]:
    """Shares of the invested value (holdings, not cash) by holding, asset class, region and sector.

    Computed here so the report quotes figures instead of working them out:
    in evals the model's own sums were often wrong.
    """
    values: Dict[str, float] = {}
    by_key: Dict[str, Dict[str, float]] = {key: {} for key in MIX_KEYS}
    for account in portfolio_data.get("accounts", []):
        for position in account.get("positions", []):
            instrument = position.get("instrument", {})
            if not instrument.get("current_price"):
                continue
            value = float(position.get("quantity", 0)) * float(instrument["current_price"])
            values[position.get("symbol", "?")] = values.get(position.get("symbol", "?"), 0.0) + value
            for key in MIX_KEYS:
                for name, pct in (instrument.get(key) or {}).items():
                    by_key[key][name] = by_key[key].get(name, 0.0) + value * float(pct) / 100
    invested = sum(values.values())
    if invested <= 0:
        return {}
    share = lambda d: dict(sorted(((k, 100 * v / invested) for k, v in d.items()), key=lambda kv: -kv[1]))  # noqa: E731
    return {"holdings": share(values), **{key: share(d) for key, d in by_key.items()}}


def _shares(shares: Dict[str, float], limit: Optional[int] = None) -> str:
    items = list(shares.items())[:limit] if limit else shares.items()
    return ", ".join(f"{name.replace('_', ' ')} {pct:.1f}%" for name, pct in items)


def top_allocations(allocation: Optional[Dict[str, Any]], limit: int = 2) -> str:
    """Render the largest slices of an allocation dict, e.g. 'equity 100%'."""
    if not allocation:
        return ""
    ranked = sorted(allocation.items(), key=lambda kv: float(kv[1]), reverse=True)
    return ", ".join(f"{name} {float(pct):g}%" for name, pct in ranked[:limit])


def format_portfolio_for_analysis(portfolio_data: Dict[str, Any], user_data: Dict[str, Any]) -> str:
    """Format portfolio data for agent analysis."""
    metrics = calculate_portfolio_metrics(portfolio_data)

    lines = [
        f"Portfolio Overview:",
        f"- {metrics['num_accounts']} accounts",
        f"- {metrics['num_positions']} total positions",
        f"- {metrics['unique_symbols']} unique holdings",
        f"- ₹{metrics['total_value'] - metrics['cash_balance']:,.2f} invested in holdings",
        f"- ₹{metrics['cash_balance']:,.2f} in cash",
        f"- ₹{metrics['total_value']:,.2f} total value, holdings and cash together (do not add the cash again)"
        if metrics["total_value"] > 0
        else "",
        "",
        "Account Details:",
    ]

    for account in portfolio_data.get("accounts", []):
        name = account.get("name", "Unknown")
        cash = float(account.get("cash_balance", 0))
        lines.append(f"\n{name} (₹{cash:,.2f} cash):")

        for position in account.get("positions", []):
            symbol = position.get("symbol")
            quantity = float(position.get("quantity", 0))
            instrument = position.get("instrument", {})

            # Include allocation info if available (instrument rows store these
            # as allocation_* dicts, e.g. {"equity": 100})
            allocations = []
            asset_class = top_allocations(instrument.get("allocation_asset_class"))
            if asset_class:
                allocations.append(f"Asset: {asset_class}")
            regions = top_allocations(instrument.get("allocation_regions"))
            if regions:
                allocations.append(f"Regions: {regions}")

            value_str = ""
            if instrument.get("current_price"):
                value = quantity * float(instrument["current_price"])
                value_str = f", worth ₹{value:,.2f}"

            alloc_str = f" ({', '.join(allocations)})" if allocations else ""
            lines.append(f"  - {symbol}: {quantity:,.2f} units{value_str}{alloc_str}")

    mix = portfolio_mix(portfolio_data)
    if mix:
        lines += ["", "Portfolio mix (shares of the invested value, computed for you; quote these, don't work out your own):"]
        lines.append(f"- Holdings: {_shares(mix['holdings'])}")
        for key, label in MIX_KEYS.items():
            if mix.get(key):
                lines.append(f"- {label}: {_shares(mix[key], 5 if key == 'allocation_sectors' else None)}")
        if metrics["total_value"] > 0 and metrics["cash_balance"] > 0:
            lines.append(f"- Cash is {100 * metrics['cash_balance'] / metrics['total_value']:.1f}% of the total value")

    # Add user context
    lines.extend(
        [
            "",
            "User Profile:",
            f"- Years to retirement: {user_data.get('years_until_retirement', 'Not specified')}",
            f"- Target retirement income: ₹{user_data.get('target_retirement_income', 0):,.0f}/year",
        ]
    )

    return "\n".join(lines)


# update_report tool removed - report is now saved directly in lambda_handler


def held_symbols(portfolio_data: Dict[str, Any]) -> List[str]:
    return sorted(
        {p.get("symbol") for a in portfolio_data.get("accounts", []) for p in a.get("positions", []) if p.get("symbol")}
    )


def select_citations(vectors: List[Dict[str, Any]], held: List[str], limit: int = KB_MAX_SOURCES) -> List[Dict[str, Any]]:
    """The best chunk from each source, most relevant first.

    A note tagged with symbols counts only when the user holds one of them;
    an untagged note (RBI policy, the daily market digest) is market-wide.
    """
    held_set = {s.upper() for s in held}
    chosen: Dict[str, Dict[str, Any]] = {}
    for vector in sorted(vectors, key=lambda v: v.get("distance", 0.0)):
        meta = vector.get("metadata") or {}
        symbols = {str(s).upper() for s in (meta.get("symbols") or [])}
        if symbols and not symbols & held_set:
            continue
        source = meta.get("source_url") or meta.get("title") or vector.get("key")
        if source in chosen or not meta.get("text"):
            continue
        published = meta.get("published_ts")
        chosen[source] = {
            "n": len(chosen) + 1,
            "title": meta.get("title") or "Untitled note",
            "source_name": meta.get("source_name") or "Unknown source",
            "published": datetime.fromtimestamp(float(published), tz=timezone.utc).date().isoformat() if published else None,
            "url": meta.get("source_url"),
            "doc_type": meta.get("doc_type"),
            "key": vector.get("key"),
            "excerpt": meta["text"][:KB_EXCERPT_CHARS],
        }
        if len(chosen) >= limit:
            break
    return list(chosen.values())


def held_names(portfolio_data: Dict[str, Any]) -> List[str]:
    names = set(held_symbols(portfolio_data))
    for account in portfolio_data.get("accounts", []):
        for position in account.get("positions", []):
            names.add(clean_name((position.get("instrument") or {}).get("name") or ""))
    return sorted(n for n in names if n)


def clean_citations(citations: List[Dict[str, Any]], facts: NarrativeFacts) -> List[Dict[str, Any]]:
    """Drop excerpt sentences the report itself couldn't say.

    Research text is untrusted input: a rating, target price, timing call,
    instruction, or a zone other than the computed one never reaches the
    model, so it can't be repeated. Ingest v2 filters sell-side language
    too; this also covers anything stored another way. A note with nothing
    left is dropped and the rest renumbered.
    """
    cleaned = []
    for c in citations:
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", c.get("excerpt", "")) if s.strip()]
        kept = [s for s in sentences if validate_narrative(s, facts).passed]
        if kept:
            cleaned.append({**c, "n": len(cleaned) + 1, "excerpt": " ".join(kept), "dropped_sentences": len(sentences) - len(kept)})
    return cleaned


def format_citations(citations: List[Dict[str, Any]]) -> str:
    if not citations:
        return (
            f"No research published in the last {KB_MAX_AGE_DAYS} days matched these holdings. "
            "Say so in one sentence; do not describe news from memory."
        )
    lines = [f"Recent research (published in the last {KB_MAX_AGE_DAYS} days). Cite as [n] where used:"]
    for c in citations:
        where = f" {c['url']}" if c.get("url") else ""
        lines.append(f"[{c['n']}] {c['title']} - {c['source_name']}, {display_date(c['published']) or 'undated'}.{where}")
        lines.append(f"    {c['excerpt']}")
    return "\n".join(lines)


def _embed(text: str) -> List[float]:
    import boto3

    region = os.getenv("DEFAULT_AWS_REGION", "us-east-1")
    sagemaker = boto3.client("sagemaker-runtime", region_name=region)
    response = sagemaker.invoke_endpoint(
        EndpointName=os.getenv("SAGEMAKER_ENDPOINT", "samruddhi-embedding-endpoint"),
        ContentType="application/json",
        Body=json.dumps({"inputs": text}),
    )
    result = json.loads(response["Body"].read().decode())
    while isinstance(result, list) and result and isinstance(result[0], list):
        result = result[0]  # [[[embedding]]] -> [embedding]
    return result


def search_research(symbols: List[str], now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Query the knowledge base for notes published in the last 14 days (raw vectors)."""
    import boto3

    bucket = os.getenv("VECTOR_BUCKET")
    if not bucket:
        raise ValueError("VECTOR_BUCKET is not set")
    query = f"Indian market news {' '.join(symbols[:5])}" if symbols else "Indian market news RBI SEBI Nifty 50"
    cutoff = int((now or time.time()) - KB_MAX_AGE_DAYS * 86400)
    s3v = boto3.client("s3vectors", region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1"))
    response = s3v.query_vectors(
        vectorBucketName=bucket,
        indexName=KB_INDEX,
        queryVector={"float32": _embed(query)},
        topK=KB_TOP_K,
        filter={"published_ts": {"$gte": cutoff}},
        returnMetadata=True,
        returnDistance=True,
    )
    return response.get("vectors", [])


def research_for(context: ReporterContext, symbols: List[str], search=search_research) -> str:
    """The tool's work: search, keep one note per source, clean, and number them."""
    try:
        facts = add_facts(NarrativeFacts(securities=held_names(context.portfolio_data)), context.market_payload)
        chosen = select_citations(search(symbols), held_symbols(context.portfolio_data))
        context.citations = clean_citations(chosen, facts)
        context.kb_status = "ok" if context.citations else "empty"
        if not context.citations:
            logger.warning(f"Reporter: no usable research from the last {KB_MAX_AGE_DAYS} days in {KB_INDEX}")
        return format_citations(context.citations)
    except Exception as e:
        context.kb_status = "error"
        context.citations = []
        logger.error(f"Reporter: could not query the knowledge base {KB_INDEX}: {e}")
        return "Research notes are unavailable for this run. Say so in one sentence; do not describe news from memory."


@function_tool
async def get_market_insights(
    wrapper: RunContextWrapper[ReporterContext], symbols: List[str]
) -> str:
    """
    Retrieve recent research notes (last 14 days) for the holdings, with source and date.

    Args:
        wrapper: Context wrapper with job_id and database
        symbols: List of symbols to get insights for

    Returns:
        Numbered, dated research notes to cite as [n]
    """
    return research_for(wrapper.context, symbols)


def add_source_facts(facts: NarrativeFacts, citations: List[Dict[str, Any]]) -> NarrativeFacts:
    """Figures quoted from a cited note are grounded in that note."""
    for c in citations:
        amounts, percents = figures_in(c.get("excerpt", ""))
        facts.amounts += amounts
        facts.percents += percents
    return facts


def report_sections(market_payload: Optional[Dict[str, Any]]) -> str:
    sections = [
        "Summary",
        "Portfolio Composition",
        "Risk Profile",
        "Diversification",
        "Retirement Readiness (against the user's own target)",
    ]
    if not market_payload or market_payload.get("context_allowed", True):
        sections.append("Market Backdrop (the as-of date and valuation zone exactly as given, or that it is not available)")
    sections += [
        "Recent Research (from get_market_insights, cited as [n]; say plainly if none)",
        "Observations",
        "Questions you may want to discuss with a SEBI-registered adviser",
        "Sources (only if you cited research)",
    ]
    return "\n".join(f"- {name}" for name in sections)


def create_agent(
    job_id: str,
    portfolio_data: Dict[str, Any],
    user_data: Dict[str, Any],
    db=None,
    market_payload: Optional[Dict[str, Any]] = None,
):
    """Create the reporter agent with tools and context."""

    # Get model configuration
    model_id = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-3-7-sonnet-20250219-v1:0")
    # Set region for LiteLLM Bedrock calls
    bedrock_region = os.getenv("BEDROCK_REGION", "us-west-2")
    logger.info(f"DEBUG: BEDROCK_REGION from env = {bedrock_region}")
    os.environ["AWS_REGION_NAME"] = bedrock_region
    logger.info(f"DEBUG: Set AWS_REGION_NAME to {bedrock_region}")

    model = LitellmModel(model=f"bedrock/{model_id}")

    # Create context
    context = ReporterContext(
        job_id=job_id, portfolio_data=portfolio_data, user_data=user_data, db=db, market_payload=market_payload
    )

    # Tools - only get_market_insights now, report saved in lambda_handler
    tools = [get_market_insights]

    # Format portfolio for analysis
    portfolio_summary = format_portfolio_for_analysis(portfolio_data, user_data)

    # Create task
    task = f"""Analyze this investment portfolio and write a comprehensive report.

{portfolio_summary}

{brief_lines(market_payload)}

Your task:
1. First, get recent research for the top holdings using get_market_insights()
2. Describe the portfolio's current state: its mix, concentration and risks
3. Generate a detailed, professional analysis report in markdown format

The report should include:
{report_sections(market_payload)}

Provide your complete analysis as the final output in clear markdown format.
Make the report informative yet accessible to a retail investor. Describe; do not instruct."""

    return model, tools, task, context
