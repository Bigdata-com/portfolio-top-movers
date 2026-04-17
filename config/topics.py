"""
Topic templates for SGX Top Movers news searches.
Focused topics for daily price movement analysis.
"""

from typing import Dict, List

# Desk-style standard topics (financial metrics, M&A, leadership, etc.)
STANDARD_TOPICS: List[Dict[str, str]] = [
    # Financial metrics
    {
        "topic_name": "Financial Metrics",
        "topic_text": (
            "{company} reported earnings results beating or missing revenue and profit expectations"
        ),
    },
    {
        "topic_name": "Financial Metrics",
        "topic_text": (
            "{company} announced changes to full year financial guidance or operational outlook"
        ),
    },
    {
        "topic_name": "Financial Metrics",
        "topic_text": (
            "{company} showing notable improvement or deterioration in margins revenue or profitability"
        ),
    },
    # M&A
    {
        "topic_name": "M&A",
        "topic_text": "{company} agreed to acquire a company for billions in a cash or stock deal",
    },
    {
        "topic_name": "M&A",
        "topic_text": "{company} selling divesting or spinning off a business unit or subsidiary",
    },
    {
        "topic_name": "M&A",
        "topic_text": (
            "{company} announced a major strategic partnership or joint venture with another company"
        ),
    },
    # Leadership
    {
        "topic_name": "Leadership",
        "topic_text": "{company} names new chief executive or top executive steps down from role",
    },
    {
        "topic_name": "Leadership",
        "topic_text": (
            "{company} leadership transition as longtime executive departs or senior management reshuffled"
        ),
    },
    # Competition
    {
        "topic_name": "Competition",
        "topic_text": "{company} won or lost a significant customer contract or renewed a major deal",
    },
    {
        "topic_name": "Competition",
        "topic_text": "{company} losing or gaining market share to competitors in its core business",
    },
    {
        "topic_name": "Competition",
        "topic_text": "{company} responding to new competitive threat or disruptive market entrant",
    },
    # Products
    {
        "topic_name": "Products",
        "topic_text": (
            "{company} launched a new product service or announced a significant pipeline development"
        ),
    },
    # Supply chain
    {
        "topic_name": "Supply Chain",
        "topic_text": (
            "{company} experiencing operational disruptions capacity constraints or logistics challenges"
        ),
    },
    {
        "topic_name": "Supply Chain",
        "topic_text": (
            "supply chain disruptions or input shortages affecting {company} production and margins"
        ),
    },
    {
        "topic_name": "Supply Chain",
        "topic_text": (
            "{company} achieved production milestone or announced manufacturing efficiency improvement"
        ),
    },
    # Costs
    {
        "topic_name": "Costs",
        "topic_text": (
            "{company} announced cost cutting restructuring layoffs or expense reduction program"
        ),
    },
    # Regulatory
    {
        "topic_name": "Regulatory",
        "topic_text": (
            "new regulation or government policy materially affecting {company} business or compliance costs"
        ),
    },
    {
        "topic_name": "Regulatory",
        "topic_text": "{company} facing material litigation legal judgment or adverse court ruling",
    },
    # Industry
    {
        "topic_name": "Industry",
        "topic_text": (
            "macroeconomic headwinds or tailwinds from interest rates inflation or consumer demand "
            "affecting {company}"
        ),
    },
    {
        "topic_name": "Industry",
        "topic_text": (
            "structural industry shift or sector disruption directly impacting {company} competitive position"
        ),
    },
    # Financing
    {
        "topic_name": "Financing",
        "topic_text": (
            "{company} announced share buyback dividend increase capital raise or major capital "
            "allocation decision"
        ),
    },
    {
        "topic_name": "Financing",
        "topic_text": (
            "{company} increased reduced or suspended dividend payments or its share repurchase program"
        ),
    },
]

# Topics optimized for daily price movement analysis (compact queries)
MOVERS_TOPICS = [
    # Earnings & Financial Performance
    {"topic_name": "Earnings", "topic_text": "{company} earnings results profit revenue guidance forecast beat miss"},
    {"topic_name": "Earnings", "topic_text": "{company} quarterly results financial performance margin growth"},
    
    # Analyst Activity
    {"topic_name": "Analyst", "topic_text": "{company} analyst upgrade downgrade price target rating recommendation"},
    {"topic_name": "Analyst", "topic_text": "{company} broker research buy sell hold rating revision"},
    
    # Corporate Actions
    {"topic_name": "Corporate Action", "topic_text": "{company} dividend buyback share repurchase capital return"},
    {"topic_name": "Corporate Action", "topic_text": "{company} rights issue placement fundraising equity"},
    
    # M&A Activity
    {"topic_name": "M&A", "topic_text": "{company} acquisition merger takeover deal bid offer"},
    {"topic_name": "M&A", "topic_text": "{company} divestiture sale asset disposal"},
    
    # Management & Leadership
    {"topic_name": "Leadership", "topic_text": "{company} CEO executive management leadership appointment resignation"},
    
    # Contracts & Business
    {"topic_name": "Business", "topic_text": "{company} contract win order deal partnership agreement"},
    {"topic_name": "Business", "topic_text": "{company} expansion investment project development"},
    
    # Regulatory & Legal
    {"topic_name": "Regulatory", "topic_text": "{company} regulatory approval license permit government"},
    {"topic_name": "Regulatory", "topic_text": "{company} investigation lawsuit legal compliance fine penalty"},
    
    # Market Sentiment
    {"topic_name": "Market", "topic_text": "{company} stock price trading volume investor sentiment"},
    {"topic_name": "Market", "topic_text": "{company} index inclusion exclusion benchmark rebalancing"},
    
    # Industry & Macro
    {"topic_name": "Industry", "topic_text": "{company} sector industry outlook trend competition"},
]


# Simplified topics for faster processing (fewer queries)
MOVERS_TOPICS_MINI = [
    {"topic_name": "Earnings", "topic_text": "{company} earnings results profit revenue guidance quarterly financial performance"},
    {"topic_name": "Analyst", "topic_text": "{company} analyst upgrade downgrade price target rating recommendation broker"},
    {"topic_name": "Corporate Action", "topic_text": "{company} dividend buyback acquisition merger deal announcement"},
    {"topic_name": "Business", "topic_text": "{company} contract order partnership expansion investment project"},
    {"topic_name": "Market", "topic_text": "{company} stock price trading sentiment news development"},
]




def get_movers_topics(mini: bool = False, standard: bool = False) -> List[Dict[str, str]]:
    """
    Get topics for movers analysis.

    Args:
        mini: If True, return reduced topic set for faster processing.
        standard: If True, return STANDARD_TOPICS (desk-style); ignored when mini is True.

    Returns:
        List of topic dictionaries
    """
    if mini:
        return MOVERS_TOPICS_MINI
    if standard:
        return STANDARD_TOPICS
    return MOVERS_TOPICS


def format_topic_for_company(topic: Dict[str, str], company_name: str) -> Dict[str, str]:
    """
    Format a topic template with company name.
    
    Args:
        topic: Topic dict with topic_name and topic_text
        company_name: Company name to substitute
        
    Returns:
        Formatted topic dict
    """
    return {
        "topic_name": topic["topic_name"],
        "topic_text": topic["topic_text"].format(company=company_name)
    }


def get_topics_for_company(
    company_name: str, mini: bool = False, standard: bool = False
) -> List[Dict[str, str]]:
    """
    Get formatted topics for a specific company.

    Args:
        company_name: Company name
        mini: Use reduced topic set
        standard: Use STANDARD_TOPICS when not mini

    Returns:
        List of formatted topics
    """
    topics = get_movers_topics(mini=mini, standard=standard)
    return [format_topic_for_company(t, company_name) for t in topics]
