"""Fintech tools: lending, KYC, fraud and AML. Business rules live in the tools, not in the prompt,
so the model cannot talk its way around a limit."""
import re

from ..clients import policy
from ..data import ds
from .common import effect, err, ok


def get_loan_account(loan_id: str) -> dict:
    """Get a loan account: customer, language, EMI, instalments paid, overdue amount and days past due.

    Args:
        loan_id: Loan identifier such as LN-1002.
    """
    loan = ds("loans").get(loan_id.upper())
    return ok(loan_id=loan_id.upper(), **loan) if loan else err(f"No loan {loan_id}")


def list_overdue_loans(min_days_past_due: int = 1) -> dict:
    """List loans that are overdue by at least the given number of days.

    Args:
        min_days_past_due: Minimum days past due.
    """
    rows = [{"loan_id": k, **v} for k, v in ds("loans").items() if v["days_past_due"] >= min_days_past_due]
    return ok(count=len(rows), loans=rows)


def check_loan_eligibility(monthly_income: float, existing_emi: float, credit_score: int, requested_amount: float, tenure_months: int = 12) -> dict:
    """Apply the lender's eligibility rules. Returns eligible or not, the proposed EMI and the reasons.

    Args:
        monthly_income: Applicant's net monthly income in rupees.
        existing_emi: Total of current monthly loan instalments in rupees.
        credit_score: Credit bureau score between 300 and 900.
        requested_amount: Loan amount requested in rupees.
        tenure_months: Repayment period in months.
    """
    rate, min_score = policy("lending.flat_rate_pct"), policy("lending.min_credit_score")
    max_foir, max_multiple = policy("lending.max_foir_pct") / 100, policy("lending.max_income_multiple")
    interest = requested_amount * rate / 100 * tenure_months / 12  # flat annual rate, deducted upfront in this lender's model
    emi = round(requested_amount / tenure_months, 2)
    foir = round((existing_emi + emi) / max(monthly_income, 1), 3)
    reasons = []
    if credit_score < min_score:
        reasons.append(f"Credit score below {min_score}")
    if foir > max_foir:
        reasons.append(f"Instalments would be {foir:.0%} of income, above the {max_foir:.0%} limit")
    if requested_amount > monthly_income * max_multiple:
        reasons.append(f"Amount above {max_multiple:g} times monthly income")
    return ok(eligible=not reasons, proposed_emi=emi, upfront_interest=round(interest, 2), net_disbursal=round(requested_amount - interest, 2),
              instalment_to_income=foir, reasons=reasons or ["Meets score, income and amount rules"])


def record_promise_to_pay(loan_id: str, promised_date: str, amount: float) -> dict:
    """Record the date and amount a borrower has promised to pay.

    Args:
        loan_id: Loan identifier.
        promised_date: Date promised, ISO format YYYY-MM-DD.
        amount: Amount promised in rupees.
    """
    if loan_id.upper() not in ds("loans"):
        return err(f"No loan {loan_id}")
    return ok(ptp_id=effect("promise_to_pay", {"loan_id": loan_id.upper(), "date": promised_date, "amount": amount}))


def _check_settlement(loan_id: str = "", waiver_pct: float = 0, reason: str = "", **_) -> dict | None:
    """Limits checked BEFORE a human is asked to approve, and again when the tool runs."""
    limit, min_paid = policy("lending.max_waiver_pct"), policy("lending.min_paid_instalments_for_waiver")
    if waiver_pct <= 0:
        return err("Waiver percentage must be above zero")
    if waiver_pct > limit:
        return err(f"Refused: a waiver of {waiver_pct:g} percent is above this client's limit of {limit:g} percent. Nothing was offered.")
    loan = ds("loans").get(str(loan_id).upper())
    if not loan:
        return err(f"No loan {loan_id}")
    if loan["paid_instalments"] < min_paid:
        return err(f"Refused: the borrower has paid {loan['paid_instalments']} instalments; this client allows a waiver only after {min_paid}.")
    return None


def offer_settlement(loan_id: str, waiver_pct: float, reason: str) -> dict:
    """Offer the borrower a late-fee waiver or settlement. Always requires human approval before it is offered.
    The platform refuses any waiver above the client's limit.

    Args:
        loan_id: Loan identifier.
        waiver_pct: Percentage of the overdue amount to waive. Must be within the client's limit.
        reason: Why the waiver is justified.
    """
    refusal = _check_settlement(loan_id=loan_id, waiver_pct=waiver_pct, reason=reason)
    if refusal:
        return refusal
    loan = ds("loans")[loan_id.upper()]
    return ok(offer_id=effect("settlement_offer", {"loan_id": loan_id.upper(), "waiver_pct": waiver_pct, "reason": reason,
                                                   "waived_amount": round(loan["overdue_amount"] * waiver_pct / 100, 2)}))


def get_transaction(txn_id: str) -> dict:
    """Get a card or account transaction with device, city and time signals.

    Args:
        txn_id: Transaction identifier such as TXN-9003.
    """
    t = ds("transactions").get(txn_id.upper())
    return ok(txn_id=txn_id.upper(), **t) if t else err(f"No transaction {txn_id}")


def list_account_transactions(account_id: str) -> dict:
    """List recent transactions on an account.

    Args:
        account_id: Account identifier such as ACC-7002.
    """
    rows = ds("account_txns").get(account_id.upper())
    return ok(account_id=account_id.upper(), transactions=rows, reporting_threshold=policy("lending.reporting_threshold_inr")) if rows else err(f"No account {account_id}")


def get_customer_risk_profile(account_id: str) -> dict:
    """Get the customer's risk band, normal monthly spend, home city and past alerts.

    Args:
        account_id: Account identifier.
    """
    r = ds("risk").get(account_id.upper())
    return ok(account_id=account_id.upper(), **r) if r else err(f"No profile for {account_id}")


def hold_transaction(txn_id: str, reason: str) -> dict:
    """Place a temporary hold on a transaction. Requires human approval.

    Args:
        txn_id: Transaction identifier.
        reason: Evidence-based reason for the hold.
    """
    return ok(hold_id=effect("transaction_hold", {"txn_id": txn_id.upper(), "reason": reason}))


def extract_kyc_fields(applicant_id: str) -> dict:
    """Read the applicant's uploaded KYC documents and return the extracted fields per document.
    In production this step sends the document images to Gemini; the demo returns stored extraction results.

    Args:
        applicant_id: Applicant identifier such as APP-2001.
    """
    docs = ds("kyc_docs").get(applicant_id.upper())
    return ok(applicant_id=applicant_id.upper(), documents=docs) if docs else err(f"No documents for {applicant_id}")


def verify_id_format(id_type: str, value: str) -> dict:
    """Check that an ID number has a valid format. Supports pan and aadhaar_masked.

    Args:
        id_type: pan or aadhaar_masked.
        value: The ID value to check.
    """
    patterns = {"pan": r"^[A-Z]{5}[0-9]{4}[A-Z]$", "aadhaar_masked": r"^XXXX-XXXX-[0-9]{4}$"}
    if id_type not in patterns:
        return err("id_type must be pan or aadhaar_masked")
    return ok(id_type=id_type, valid=bool(re.match(patterns[id_type], value.strip().upper())), masked="****" + value[-4:])


PRECHECKS = {"offer_settlement": _check_settlement}
