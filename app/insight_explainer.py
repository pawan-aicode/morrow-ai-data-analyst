"""Grounded AI explanations for calculated data insights."""

import json
import urllib.request
import urllib.error

from app.agent import MODEL, OLLAMA_URL



def _validate_explanation(explanation, factual):
    """Detect selected contradictions between AI text and supplied facts."""
    issues = []
    lowered = explanation.lower()

    context = factual.get("business_context") or {}
    currency = context.get("currency")

    currency_symbols = {
        "₹": "INR",
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
    }

    allowed_symbols = set()
    if currency:
        upper_currency = currency.upper()
        for symbol, code in currency_symbols.items():
            if code in upper_currency or symbol in currency:
                allowed_symbols.add(symbol)

    for symbol in currency_symbols:
        if symbol in explanation and symbol not in allowed_symbols:
            issues.append(
                f"Unsupported currency symbol '{symbol}'. "
                "Use only the explicitly supplied currency."
            )

    granularity = (context.get("row_granularity") or "").lower()
    measure_meaning = context.get("measure_meaning")

    one_row_per_order = (
        "one row per order" in granularity
        or "one row per completed order" in granularity
    )

    if one_row_per_order and measure_meaning:
        contradictory_average_phrases = (
            "does not necessarily represent a per-transaction value",
            "not necessarily represent a per-transaction value",
            "does not necessarily represent a per-order value",
            "not necessarily represent a per-order value",
            "does not necessarily reflect per-transaction figures",
            "does not necessarily reflect per transaction figures",
            "not necessarily reflect per-transaction figures",
            "not necessarily reflect per transaction figures",
            "may not reflect per-transaction figures",
            "may not reflect per transaction figures",
            "does not necessarily reflect per-order figures",
            "not necessarily reflect per-order figures",
        )
        if any(phrase in lowered for phrase in contradictory_average_phrases):
            issues.append(
                "The supplied row granularity establishes one row per order. "
                "Do not say the average may not represent a per-order value."
            )

    trends = factual.get("monthly_trends") or []
    statuses = [
        item.get("period_status")
        for trend in trends
        for item in trend.get("monthly_changes", [])
    ]
    comparisons = [
        item.get("comparison_status")
        for trend in trends
        for item in trend.get("monthly_changes", [])
    ]

    completeness_not_assessed = (
        bool(statuses)
        and all(status == "not_assessed" for status in statuses)
    )
    has_confirmed_gap = "missing_calendar_month" in comparisons

    unsupported_completeness_phrases = (
        "no missing calendar months",
        "there are no missing months",
        "all months are complete",
        "the dataset is complete",
        "the data is complete",
        "complete data coverage",
    )

    if completeness_not_assessed and any(
        phrase in lowered for phrase in unsupported_completeness_phrases
    ):
        issues.append(
            "Completeness is not assessed. Do not claim that the dataset "
            "is complete or that no calendar months are missing."
        )

    missing_month_recommendations = (
        "collect data for missing months",
        "gather data for missing months",
        "obtain data for missing months",
    )
    if not has_confirmed_gap and any(
        phrase in lowered for phrase in missing_month_recommendations
    ):
        issues.append(
            "No missing calendar month is established. Do not recommend "
            "collecting data for missing months."
        )

    has_partial_period = "partial_period" in statuses
    if has_partial_period and any(
        phrase in lowered
        for phrase in (
            "all months are complete",
            "every month is complete",
            "the partial month is complete",
        )
    ):
        issues.append(
            "At least one period is partial. Do not describe every month "
            "or the partial month as complete."
        )

    return issues


def explain_factual_insights(factual):
    if not isinstance(factual, dict):
        raise TypeError("Factual insights must be a dictionary.")

    prompt = f"""
You are Morrow, an analytical business intelligence assistant.

Interpret only these PRE-CALCULATED findings:
{json.dumps(factual, ensure_ascii=False, allow_nan=False)}

RULES:

1. FACTUAL ACCURACY
- Use only facts supplied above.
- Never invent, estimate, recalculate, or round additional numbers.
- Every numerical claim must match a supplied value.
- Use a currency symbol or currency name only when business_context.currency
  explicitly identifies it. Otherwise describe amounts without a currency.
- Use row_granularity and measure_meaning only when explicitly supplied.
- Do not infer transaction-level meaning from a column name alone.
- Do not claim statistical unreliability merely because a dataset has
  a particular row count.
- Never invent business events, customer behaviour, market conditions,
  operational problems, or explanations.
- Comparisons do not establish causation.

2. MONTHLY PERFORMANCE
- Use only supplied monthly changes and rankings.
- "complete" periods are eligible for normal performance analysis.
- "partial_period" means provisional. Explain the limitation.
- "after_completeness_date" means outside declared data coverage.
  Do not interpret its value as business performance.
- "not_assessed" means completeness was not confirmed.
  It does not mean calendar months are missing.
- Claim that months are missing only when comparison_status explicitly
  identifies "missing_calendar_month".
- Respect comparison_status. Do not compare across missing calendar
  months or non-positive previous values.
- Use only supplied largest increase and largest decline.
- Never rank excluded periods.

3. DATA QUALITY AND SCOPE
- If is_sampled is true, state that findings apply only to loaded rows.
- Use unprocessed_rows only when available.
- Never guess missing or unprocessed row counts.
- Describe average as the arithmetic mean of valid values in its column.
- If row_granularity explicitly establishes one row per order and
  measure_meaning identifies the order-level measure, describe the average
  as the average value per order.
- Never call it average transaction value unless transaction-level
  data explicitly establishes that meaning.
- Mention limitations that materially affect interpretation.

4. BUSINESS INTERPRETATION
- Explain what the observed figures mean, not why they happened.
- Distinguish observations from hypotheses.
- If a cause is unknown, say the dataset does not establish it.
- Do not exaggerate small differences.
- Prioritise decision-relevant findings.

5. RECOMMENDATIONS
- Give specific, practical next steps linked to observed findings.
- When a monthly increase or decline is supplied, suggest investigating
  available dimensions such as order counts, categories, or segments.
  Do not claim those dimensions explain the change without evidence.
- Do not recommend collecting data for missing months unless the supplied
  comparison_status explicitly identifies missing calendar months.
- Frame unverified explanations as things to investigate.
- Do not recommend actions requiring unavailable evidence.
- Explain what additional data would help when evidence is insufficient.

OUTPUT FORMAT:

EXECUTIVE SUMMARY
Summarise the overall picture in two or three sentences.

PERFORMANCE FINDINGS
Explain the most important supported numeric, monthly, or category findings.

RISKS AND DATA LIMITATIONS
Identify relevant sampling, incomplete-period, coverage, or data-quality issues.

BUSINESS INTERPRETATION
Explain what can reasonably be concluded and what remains unknown.

RECOMMENDED NEXT ACTIONS
Give up to three specific actions. Link each action to a finding or
explain what additional information is needed.

Keep the complete analysis under 220 words.
Use clear, professional, direct language.
Return plain text only. Do not use markdown tables.
"""

    body = json.dumps({
        "model": MODEL,
        "stream": False,
        "think": False,
        "messages": [
            {
                "role": "system",
                "content": "Explain verified findings. Never fabricate facts."
            },
            {"role": "user", "content": prompt}
        ],
        "options": {"temperature": 0, "num_predict": 500}
    }).encode("utf-8")

    request = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"}
    )

    for attempt in range(2):
        if attempt == 1:
            retry_feedback = (
                "\\n\\nVALIDATION FEEDBACK — CORRECT THESE ISSUES:\\n"
                + "\\n".join(f"- {issue}" for issue in issues)
                + "\\nReturn the complete corrected analysis."
            )
            retry_payload = json.loads(body.decode("utf-8"))
            retry_payload["messages"][1]["content"] += retry_feedback
            request.data = json.dumps(retry_payload).encode("utf-8")

        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
            explanation = result["message"]["content"].strip()
        except (
            urllib.error.URLError,
            TimeoutError,
            KeyError,
            ValueError,
            TypeError
        ) as exc:
            raise RuntimeError(
                "AI explanation failed. Check Ollama and model availability."
            ) from exc

        if not explanation:
            raise RuntimeError("The AI model returned an empty explanation.")

        issues = _validate_explanation(explanation, factual)
        if not issues:
            return explanation[:3000]

    raise RuntimeError(
        "AI explanation failed validation after one retry: "
        + "; ".join(issues)
    )
