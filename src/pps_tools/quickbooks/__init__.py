"""QuickBooks Online transaction categorization.

Connects to QBO via OAuth2, fetches uncategorized transactions,
uses Claude to suggest accounting categories, and writes approved
categorizations back to QBO.
"""

from pps_tools.quickbooks.qbo_client import QBOClient, QBOAuth
from pps_tools.quickbooks.categorizer import Categorizer, Suggestion
from pps_tools.quickbooks.models import Transaction, Account

__all__ = [
    "QBOClient",
    "QBOAuth",
    "Categorizer",
    "Suggestion",
    "Transaction",
    "Account",
]
