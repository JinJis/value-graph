"""OpenDART statement concept maps (IFRS ``account_id`` -> our field name).

Extracted from ``opendart.py`` (the KR provider god-module) so the dense
account-id dictionaries live apart from the HTTP client + provider classes.
Sibling of ``sec_edgar_concepts.py`` on the US side.
"""

from __future__ import annotations

INCOME_MAP = {
    "ifrs-full_Revenue": "revenue",
    "ifrs_Revenue": "revenue",
    "ifrs-full_CostOfSales": "cost_of_revenue",
    "ifrs-full_GrossProfit": "gross_profit",
    "dart_OperatingIncomeLoss": "operating_income",
    "ifrs-full_ProfitLossFromOperatingActivities": "operating_income",
    "ifrs-full_ProfitLoss": "net_income",
    "ifrs-full_IncomeTaxExpenseContinuingOperations": "income_tax_expense",
    "ifrs-full_BasicEarningsLossPerShare": "earnings_per_share",
    "ifrs-full_DilutedEarningsLossPerShare": "earnings_per_share_diluted",
}
BALANCE_MAP = {
    "ifrs-full_Assets": "total_assets",
    "ifrs-full_CurrentAssets": "current_assets",
    "ifrs-full_NoncurrentAssets": "non_current_assets",
    "ifrs-full_CashAndCashEquivalents": "cash_and_equivalents",
    "ifrs-full_Inventories": "inventory",
    "ifrs-full_Liabilities": "total_liabilities",
    "ifrs-full_CurrentLiabilities": "current_liabilities",
    "ifrs-full_NoncurrentLiabilities": "non_current_liabilities",
    "ifrs-full_Equity": "shareholders_equity",
    "ifrs-full_RetainedEarnings": "retained_earnings",
}
CASHFLOW_MAP = {
    "ifrs-full_CashFlowsFromUsedInOperatingActivities": "net_cash_flow_from_operations",
    "ifrs-full_CashFlowsFromUsedInInvestingActivities": "net_cash_flow_from_investing",
    "ifrs-full_CashFlowsFromUsedInFinancingActivities": "net_cash_flow_from_financing",
}
