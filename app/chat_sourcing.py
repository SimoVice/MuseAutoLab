"""Evidence-backed chat supplements, without changing engineering state."""

import re

from app.engineering import state_for
from app.parts_proposal import build_parts_proposal, cold_transfer_candidate_rows
from app.platform_profiles import platform_profiles


def complete_platform_comparison(current, updated, message, reply):
    """Ensure relevant discovery/comparison replies retain both source and cost bases."""
    liquid = updated.get("workflow", {}).get("kind") == "liquid_preparation"
    explicit = bool(re.search(
        r"\b(?:compare|comparison|difference|alternatives|options)\b", message, re.I
    ))
    both_named = bool(re.search(r"jubilee", message, re.I)) and bool(
        re.search(r"opentrons|ot-?2", message, re.I)
    )
    platform_scope = bool(re.search(
        r"\b(?:platforms?|automation bases?|prebuilt|open.hardware|liquid.handlers?)\b",
        message, re.I,
    ))
    named_platform = bool(re.search(r"jubilee|opentrons|ot-?2", message, re.I))
    component_scope = bool(re.search(
        r"\b(?:tips?|racks?|fridges?|refrigerators?|cameras?|arms?|grippers?|suppliers?)\b",
        message, re.I,
    ))
    platform_shopping = both_named or platform_scope or (named_platform and not component_scope)
    first_discovery = liquid and not state_for(current)["selected_platform_id"] and (
        current.get("workflow", {}).get("kind") != "liquid_preparation"
    )
    if not (first_discovery or (explicit and platform_shopping)):
        return reply
    missing = []
    for profile in platform_profiles():
        cost = profile["cost_context"]
        amount = cost["amount"]
        # Do not repeat a grounded comparison already written by the model.
        linked = profile["source_url"] in reply or cost["source_url"] in reply
        priced = f"{amount:,}" in reply or str(amount) in reply
        if linked and priced:
            continue
        if profile["id"] == "jubilee":
            detail = (f"about ${amount:,.0f} for self-sourced US base parts "
                      "(historical upstream estimate). Custom tools and assembly are additional.")
        else:
            detail = (f"starting at ${amount:,.0f}; assembled base, with selected "
                      "pipette configuration and consumables to verify.")
        checked = ("page retrieved " + cost["retrieved_at"] if cost.get("retrieved_at")
                   else "reference reviewed " + cost["checked_on"])
        missing.append(f"- [{profile['label']}]({cost['source_url']}): {detail} ({checked})")
    if missing:
        reply += ("\n\nPlatform cost references (USD):\n" + "\n".join(missing)
                  + "\nConfiguration, shipping, tax and commissioning require a quote.")
    return reply


def cold_component_reply(project, report=None, estimate=None):
    project_rows = build_parts_proposal(project, report, estimate)["rows"]
    rows = [row for row in project_rows if row["group_id"].startswith("cold-transfer-")]
    if not rows:
        rows = cold_transfer_candidate_rows(project)
    lines = []
    for row in rows:
        low, high = row["line_total_low_usd"], row["line_total_high_usd"]
        label = row.get("selected_product_label") or row["label"]
        price = f"${low:,.2f}" if low == high else f"${low:,.0f}–${high:,.0f}"
        lines.append(f"- [{label}]({row['source_url']}): {price} "
                     f"({row['price_kind'].replace('_', ' ')}). {row['price_note']}")
        for alternative in row["alternatives"]:
            if alternative["url"] != row["source_url"]:
                lines.append(f"  Alternative: [{alternative['label']}]({alternative['url']}) — "
                             f"{alternative['note']}")
    return ("\n\nReviewed component candidates (US/USD):\n" + "\n".join(lines)
            + "\nBudget ranges exclude shipping, tax and integration labor. "
            "Candidate compatibility still needs checking.")


def complete_equipment_question(current, updated, reply):
    """Ask one concrete compatibility question only once a layout is developed."""
    selected = state_for(updated)["selected_platform_id"]
    if not selected or not updated.get("engineering_design"):
        return reply
    newly_developed = not current.get("engineering_design")
    newly_selected = selected != state_for(current)["selected_platform_id"]
    if not (newly_developed or newly_selected):
        return reply
    equipment = updated.get("brief", {}).get("equipment") or ""
    specific = bool(re.search(
        r"eppendorf|research plus|ept[.]?i[.]?p|gilson|rainin|sartorius|brand|"
        r"make/model|model\s+\S+|part\s*(?:number|no[.]?|#)|\b[A-Z]{1,5}[- ]?\d{2,5}\b",
        equipment, re.I,
    ))
    if specific and re.search(r"tips?|labware|rack", equipment, re.I):
        return reply
    equipment_questions = [question.strip() for question in re.findall(r"[^.!?\n]+\?", reply)
                           if re.search(r"pipette|tip|instrument", question, re.I)]
    if equipment_questions:
        question = equipment_questions[-1]
        if reply.rstrip().endswith(question):
            return reply
        return reply.replace(question, "", 1).rstrip() + "\n\n" + question
    if selected == "jubilee":
        question = ("The pipette mount and tip interface still need checking. "
                    "What make/model or part number are your current pipette and tips?")
    else:
        question = ("A manual pipette is not assumed compatible. "
                    "Which OT-2 instrument pipette and tip/labware configuration do you have, "
                    "or should we propose one?")
    return reply + "\n\n" + question


def complete_component_changes(current, updated, reply):
    """Expose added/reselected purchase scopes after a machine already exists."""
    if not any(current.get(key) for key in (
        "engineering_design", "concept_design", "bench_station"
    )):
        return reply
    before = {row["group_id"]: row for row in build_parts_proposal(current)["rows"]}
    after = build_parts_proposal(updated)["rows"]

    def identity(row):
        return (row.get("selected_id"), row.get("selected_product_label"),
                row["label"], row.get("source_url"), tuple(row.get("component_ids", [])))

    changed = [row for row in after if not row["group_id"].startswith("cold-transfer-")
               and (row["group_id"] not in before
                    or identity(row) != identity(before[row["group_id"]]))]
    lines = []
    for row in changed:
        low, high = row["line_total_low_usd"], row["line_total_high_usd"]
        url = row["source_url"]
        # Preserve model/source-specific explanations already complete in chat.
        if url in reply and (f"{low:,.0f}" in reply or str(low) in reply):
            continue
        price = f"${low:,.0f}" if low == high else f"${low:,.0f}–${high:,.0f}"
        kind = row["price_kind"].replace("_", " ")
        label = row.get("selected_product_label") or row["label"]
        lines.append(f"- [{label}]({url}): {price} for this purchase scope ({kind}).")
        if len(lines) == 3:
            break
    if lines:
        reply += ("\n\nComponent proposals:\n" + "\n".join(lines)
                  + "\nOpen Parts & prices for every component, alternatives and assembly links. "
                  "Budget allowances are estimates; integration and labor are additional.")
    return reply
