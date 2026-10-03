"""Unit tests for QBO model parsing."""

from pps_tools.quickbooks.models import Account, Transaction


def test_account_from_qbo():
    raw = {
        "Id": "42",
        "Name": "Office Supplies",
        "AccountType": "Expense",
        "AccountSubType": "OfficeGeneralAdministrativeExpenses",
        "FullyQualifiedName": "Office Supplies",
        "Active": True,
    }
    a = Account.from_qbo(raw)
    assert a.id == "42"
    assert a.account_type == "Expense"
    assert a.account_sub_type == "OfficeGeneralAdministrativeExpenses"
    assert a.active is True


def test_transaction_from_purchase():
    raw = {
        "Id": "123",
        "SyncToken": "2",
        "TxnDate": "2025-03-01",
        "TotalAmt": 45.67,
        "PaymentType": "Cash",
        "PrivateNote": "coffee for staff meeting",
        "EntityRef": {"value": "9", "name": "Starbucks"},
        "CurrencyRef": {"value": "USD"},
        "Line": [
            {
                "Id": "1",
                "Description": "morning coffee",
                "Amount": 45.67,
                "DetailType": "AccountBasedExpenseLineDetail",
                "AccountBasedExpenseLineDetail": {
                    "AccountRef": {"value": "7", "name": "Uncategorized Expense"},
                },
            }
        ],
    }
    t = Transaction.from_purchase(raw)
    assert t.id == "123"
    assert t.sync_token == "2"
    assert t.payee_name == "Starbucks"
    assert t.amount == 45.67
    assert t.line_id == "1"
    assert t.current_account_id == "7"
    assert t.current_account_name == "Uncategorized Expense"
    assert t.memo == "coffee for staff meeting"
