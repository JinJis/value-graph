"""SEC EDGAR XBRL concept maps: normalized statement field -> ordered candidate us-gaap
tags. The same field maps to different tags across filers, so callers try each in order.
Single source for the income / balance / cash-flow field->concept mappings."""

from __future__ import annotations


# --- XBRL concept maps (field -> ordered candidate us-gaap tags) ----------
INCOME_MAP: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
    "gross_profit": ["GrossProfit"],
    "operating_expense": ["OperatingExpenses", "CostsAndExpenses", "OperatingCostsAndExpenses"],
    "selling_general_and_administrative_expenses": [
        "SellingGeneralAndAdministrativeExpense",
        "GeneralAndAdministrativeExpense",
    ],
    "research_and_development": ["ResearchAndDevelopmentExpense"],
    "operating_income": ["OperatingIncomeLoss"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating"],
    "income_tax_expense": ["IncomeTaxExpenseBenefit"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "net_income_common_stock": ["NetIncomeLossAvailableToCommonStockholdersBasic"],
    "consolidated_income": ["ProfitLoss"],
    "earnings_per_share": ["EarningsPerShareBasic"],
    "earnings_per_share_diluted": ["EarningsPerShareDiluted"],
    "dividends_per_common_share": ["CommonStockDividendsPerShareDeclared"],
    "weighted_average_shares": ["WeightedAverageNumberOfSharesOutstandingBasic"],
    "weighted_average_shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}

BALANCE_MAP: dict[str, list[str]] = {
    "total_assets": ["Assets"],
    "current_assets": ["AssetsCurrent"],
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "inventory": ["InventoryNet"],
    "trade_and_non_trade_receivables": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "non_current_assets": ["AssetsNoncurrent"],
    "property_plant_and_equipment": ["PropertyPlantAndEquipmentNet"],
    "goodwill_and_intangible_assets": ["Goodwill"],
    "outstanding_shares": ["CommonStockSharesOutstanding"],
    "total_liabilities": ["Liabilities"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "current_debt": ["LongTermDebtCurrent", "DebtCurrent", "CommercialPaper"],
    "trade_and_non_trade_payables": ["AccountsPayableCurrent"],
    "deferred_revenue": ["ContractWithCustomerLiabilityCurrent", "DeferredRevenueCurrent"],
    "non_current_liabilities": ["LiabilitiesNoncurrent"],
    "non_current_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "tax_liabilities": ["TaxesPayableCurrent"],
    "shareholders_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
}

CASHFLOW_MAP: dict[str, list[str]] = {
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "depreciation_and_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndOther",
        "Depreciation",
    ],
    "share_based_compensation": ["ShareBasedCompensation", "ShareBasedCompensationExpense"],
    "net_cash_flow_from_operations": ["NetCashProvidedByUsedInOperatingActivities"],
    "capital_expenditure": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "business_acquisitions_and_disposals": ["PaymentsToAcquireBusinessesNetOfCashAcquired"],
    "net_cash_flow_from_investing": ["NetCashProvidedByUsedInInvestingActivities"],
    "issuance_or_repayment_of_debt_securities": ["ProceedsFromIssuanceOfLongTermDebt"],
    "issuance_or_purchase_of_equity_shares": ["PaymentsForRepurchaseOfCommonStock"],
    "dividends_and_other_cash_distributions": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "net_cash_flow_from_financing": ["NetCashProvidedByUsedInFinancingActivities"],
    "change_in_cash_and_equivalents": [
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "CashAndCashEquivalentsPeriodIncreaseDecrease",
    ],
}
