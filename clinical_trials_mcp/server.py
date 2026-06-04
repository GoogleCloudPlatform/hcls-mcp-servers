#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Clinical Trials MCP Server

Wraps the ClinicalTrials.gov v2 API into an MCP server that lets LLM agents
search trials, retrieve full study records, access results data (outcomes,
adverse events, study arms), compare trials, match patients, analyze
endpoints, and explore investigators and sponsor pipelines.

No authentication required. Designed for stateless deployment on Google Cloud Run.
"""

import json
import os
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from api_client import (
    format_api_error,
    get_study,
    get_study_results,
    search_studies,
)

PORT = int(os.environ.get("PORT", "8080"))

mcp = FastMCP(
    "clinical_trials_mcp",
    host="0.0.0.0",
    port=PORT,
    stateless_http=True,
    json_response=True,
)


def _json_out(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _md_trial_summary(study: Dict[str, Any]) -> str:
    """Format a single study as a concise markdown block."""
    proto = study.get("protocolSection", {})
    ident = proto.get("identificationModule", {})
    status = proto.get("statusModule", {})
    design = proto.get("designModule", {})
    enroll = design.get("enrollmentInfo", {})
    sponsor = proto.get("sponsorCollaboratorsModule", {})
    lead = sponsor.get("leadSponsor", {})
    conditions = proto.get("conditionsModule", {})

    nct_id = ident.get("nctId", "N/A")
    title = ident.get("briefTitle", "Untitled")
    overall_status = status.get("overallStatus", "Unknown")
    phases_list = design.get("phases", [])
    phase = ", ".join(phases_list) if phases_list else "N/A"
    enrollment = enroll.get("count", "N/A")
    sponsor_name = lead.get("name", "N/A")
    condition_list = conditions.get("conditions", [])

    lines = [
        f"### {nct_id}: {title}",
        f"**Status:** {overall_status} | **Phase:** {phase} | **Enrollment:** {enrollment}",
        f"**Sponsor:** {sponsor_name}",
    ]
    if condition_list:
        lines.append(f"**Conditions:** {', '.join(condition_list[:5])}")
    return "\n".join(lines)


def _build_search_params(
    condition: Optional[str] = None,
    intervention: Optional[str] = None,
    sponsor: Optional[str] = None,
    location: Optional[str] = None,
    status: Optional[List[str]] = None,
    phase: Optional[List[str]] = None,
    study_type: Optional[str] = None,
    page_size: int = 10,
    page_token: Optional[str] = None,
    advanced_query: Optional[str] = None,
    count_total: bool = False,
) -> Dict[str, Any]:
    """Build query params dict for the /studies endpoint."""
    params: Dict[str, Any] = {"pageSize": page_size}

    query_parts = []
    if condition:
        query_parts.append(f"AREA[Condition]{condition}")
    if intervention:
        query_parts.append(f"AREA[InterventionName]{intervention}")
    if sponsor:
        query_parts.append(f"AREA[LeadSponsorName]{sponsor}")
    if location:
        query_parts.append(f"AREA[LocationCountry]{location}")

    if advanced_query:
        query_parts.append(advanced_query)

    if query_parts:
        params["query.term"] = " AND ".join(query_parts)
    if condition and not advanced_query:
        params["query.cond"] = condition
    if intervention and not advanced_query:
        params["query.intr"] = intervention

    if status:
        params["filter.overallStatus"] = ",".join(status)
    if phase:
        params["filter.phase"] = ",".join(phase)
    if study_type:
        params["filter.studyType"] = study_type
    if page_token:
        params["pageToken"] = page_token
    if count_total:
        params["countTotal"] = "true"

    return params


# ---------------------------------------------------------------------------
# Tool 1: search_trials
# ---------------------------------------------------------------------------
@mcp.tool(
    name="search_trials",
    annotations={
        "title": "Search Clinical Trials",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_trials(
    condition: Optional[str] = None,
    intervention: Optional[str] = None,
    sponsor: Optional[str] = None,
    location: Optional[str] = None,
    status: Optional[List[str]] = None,
    phase: Optional[List[str]] = None,
    study_type: Optional[str] = None,
    page_size: int = 10,
    page_token: Optional[str] = None,
    advanced_query: Optional[str] = None,
    count_total: bool = False,
    response_format: str = "markdown",
) -> str:
    """Search ClinicalTrials.gov for clinical trials matching criteria.

    Supports filtering by condition, intervention/drug, sponsor, location,
    recruitment status, phase, and study type. Use advanced_query for Essie
    expression syntax (e.g., 'AREA[StartDate]RANGE[2023-01-01,MAX]').

    NOTE: Results include legacy records with overallStatus: 'UNKNOWN'. 
    To get only active/recruiting trials, explicitly pass status=['RECRUITING'].

    Status values: RECRUITING, COMPLETED, ACTIVE_NOT_RECRUITING,
    NOT_YET_RECRUITING, TERMINATED, WITHDRAWN, SUSPENDED, UNKNOWN.

    Phase values: EARLY_PHASE1, PHASE1, PHASE2, PHASE3, PHASE4, NA.
    """
    try:
        params = _build_search_params(
            condition=condition,
            intervention=intervention,
            sponsor=sponsor,
            location=location,
            status=status,
            phase=phase,
            study_type=study_type,
            page_size=page_size,
            page_token=page_token,
            advanced_query=advanced_query,
            count_total=count_total,
        )
        data = await search_studies(params)
        studies = data.get("studies", [])
        total = data.get("totalCount")
        next_token = data.get("nextPageToken")

        if not studies:
            return "No trials found matching your criteria. Try broadening your search."

        if response_format == "json":
            return _json_out({
                "totalCount": total,
                "count": len(studies),
                "nextPageToken": next_token,
                "studies": studies,
            })

        lines = ["# Clinical Trial Search Results", ""]
        if total is not None:
            lines.append(f"**{total} total results** (showing {len(studies)})")
        else:
            lines.append(f"Showing {len(studies)} results")
        lines.append("")

        for s in studies:
            lines.append(_md_trial_summary(s))
            lines.append("")

        if next_token:
            lines.append(f"*More results available. Use page_token='{next_token}' to continue.*")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 2: get_trial
# ---------------------------------------------------------------------------
@mcp.tool(
    name="get_trial",
    annotations={
        "title": "Get Trial Details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_trial(
    nct_id: str,
    response_format: str = "markdown",
) -> str:
    """Get comprehensive details for a specific clinical trial by NCT ID.

    Returns protocol information including eligibility criteria, study design,
    endpoints, locations, sponsor details, and enrollment numbers. NCT ID
    format: 'NCT' followed by 8 digits (e.g., NCT04567890).
    """
    try:
        data = await get_study(nct_id.strip().upper())

        if response_format == "json":
            return _json_out(data)

        proto = data.get("protocolSection", {})
        ident = proto.get("identificationModule", {})
        status_mod = proto.get("statusModule", {})
        desc = proto.get("descriptionModule", {})
        design = proto.get("designModule", {})
        enroll = design.get("enrollmentInfo", {})
        elig = proto.get("eligibilityModule", {})
        sponsor_mod = proto.get("sponsorCollaboratorsModule", {})
        lead = sponsor_mod.get("leadSponsor", {})
        conditions = proto.get("conditionsModule", {})
        arms_mod = proto.get("armsInterventionsModule", {})
        outcomes_mod = proto.get("outcomesModule", {})
        contacts_mod = proto.get("contactsLocationsModule", {})

        has_results = data.get("hasResults", False)
        phases = design.get("phases", [])

        lines = [
            f"# {ident.get('nctId', nct_id)}: {ident.get('briefTitle', 'Untitled')}",
            "",
            f"**Official Title:** {ident.get('officialTitle', 'N/A')}",
            f"**Status:** {status_mod.get('overallStatus', 'N/A')}",
            f"**Phase:** {', '.join(phases) if phases else 'N/A'}",
            f"**Enrollment:** {enroll.get('count', 'N/A')} ({enroll.get('type', 'N/A')})",
            f"**Sponsor:** {lead.get('name', 'N/A')}",
            f"**Has Results:** {'Yes' if has_results else 'No'}",
            "",
        ]

        cond_list = conditions.get("conditions", [])
        if cond_list:
            lines.append(f"**Conditions:** {', '.join(cond_list)}")
            lines.append("")

        brief_summary = desc.get("briefSummary", "")
        if brief_summary:
            lines.append("## Summary")
            lines.append(brief_summary)
            lines.append("")

        # Design
        lines.append("## Study Design")
        lines.append(f"- **Type:** {design.get('studyType', 'N/A')}")
        design_info = design.get("designInfo", {})
        if design_info:
            lines.append(f"- **Allocation:** {design_info.get('allocation', 'N/A')}")
            lines.append(f"- **Masking:** {design_info.get('maskingInfo', {}).get('masking', 'N/A')}")
            lines.append(f"- **Primary Purpose:** {design_info.get('primaryPurpose', 'N/A')}")
        lines.append("")

        # Eligibility
        if elig:
            lines.append("## Eligibility")
            lines.append(f"- **Sex:** {elig.get('sex', 'ALL')}")
            lines.append(f"- **Min Age:** {elig.get('minimumAge', 'N/A')}")
            lines.append(f"- **Max Age:** {elig.get('maximumAge', 'N/A')}")
            criteria_text = elig.get("eligibilityCriteria", "")
            if criteria_text:
                lines.append("")
                lines.append(criteria_text[:2000])
                if len(criteria_text) > 2000:
                    lines.append("*(truncated — use json format for full criteria)*")
            lines.append("")

        # Arms & Interventions
        arm_groups = arms_mod.get("armGroups", [])
        interventions = arms_mod.get("interventions", [])
        if arm_groups or interventions:
            lines.append("## Arms & Interventions")
            for arm in arm_groups:
                lines.append(f"- **{arm.get('label', 'N/A')}** ({arm.get('type', 'N/A')}): {arm.get('description', 'N/A')}")
            for interv in interventions:
                lines.append(f"- **{interv.get('type', 'N/A')}:** {interv.get('name', 'N/A')} — {interv.get('description', 'N/A')}")
            lines.append("")

        # Outcomes
        primaries = outcomes_mod.get("primaryOutcomes", [])
        secondaries = outcomes_mod.get("secondaryOutcomes", [])
        if primaries or secondaries:
            lines.append("## Endpoints")
            for outcome in primaries:
                lines.append(f"- **Primary:** {outcome.get('measure', 'N/A')} (timeframe: {outcome.get('timeFrame', 'N/A')})")
            for outcome in secondaries[:5]:
                lines.append(f"- **Secondary:** {outcome.get('measure', 'N/A')} (timeframe: {outcome.get('timeFrame', 'N/A')})")
            if len(secondaries) > 5:
                lines.append(f"*... and {len(secondaries) - 5} more secondary endpoints*")
            lines.append("")

        # Locations (first 5)
        locations = contacts_mod.get("locations", [])
        if locations:
            lines.append("## Locations")
            for loc in locations[:5]:
                facility = loc.get("facility", "N/A")
                city = loc.get("city", "")
                state = loc.get("state", "")
                country = loc.get("country", "")
                loc_str = ", ".join(filter(None, [city, state, country]))
                lines.append(f"- {facility} — {loc_str}")
            if len(locations) > 5:
                lines.append(f"*... and {len(locations) - 5} more locations*")
            lines.append("")

        # Dates
        lines.append("## Key Dates")
        lines.append(f"- **Start:** {status_mod.get('startDateStruct', {}).get('date', 'N/A')}")
        lines.append(f"- **Primary Completion:** {status_mod.get('primaryCompletionDateStruct', {}).get('date', 'N/A')}")
        lines.append(f"- **Last Updated:** {status_mod.get('lastUpdatePostDateStruct', {}).get('date', 'N/A')}")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 3: get_study_results
# ---------------------------------------------------------------------------
@mcp.tool(
    name="get_study_results",
    annotations={
        "title": "Get Study Results",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def tool_get_study_results(
    nct_id: str,
    response_format: str = "markdown",
) -> str:
    """Get posted results for a completed clinical trial including outcome
    measures with statistical data (p-values, confidence intervals),
    participant flow, and baseline characteristics.

    Only trials that have posted results will return data. Check hasResults
    in get_trial output first. Returns outcome measures grouped by type
    (primary/secondary) with group data, statistical analyses, and effect sizes.
    """
    try:
        data = await get_study_results(nct_id.strip().upper())
        results = data.get("resultsSection")

        if not results:
            has_results = data.get("hasResults", False)
            if not has_results:
                return f"No results posted for {nct_id}. This trial may still be ongoing or has not yet submitted results."
            return f"Results section is empty for {nct_id}."

        if response_format == "json":
            return _json_out(results)

        lines = [f"# Study Results: {nct_id}", ""]

        # Participant flow
        flow = results.get("participantFlowModule", {})
        flow_groups = flow.get("groups", [])
        if flow_groups:
            lines.append("## Participant Flow")
            for group in flow_groups:
                lines.append(f"- **{group.get('title', 'N/A')}** ({group.get('id', '')}): {group.get('description', 'N/A')}")
            periods = flow.get("periods", [])
            for period in periods:
                lines.append(f"\n**Period: {period.get('title', 'N/A')}**")
                milestones = period.get("milestones", [])
                for ms in milestones:
                    achievements = ms.get("achievements", [])
                    counts = ", ".join([f"{a.get('groupId', '?')}: {a.get('numSubjects', '?')}" for a in achievements])
                    lines.append(f"  - {ms.get('type', 'N/A')}: {counts}")
            lines.append("")

        # Baseline characteristics
        baseline = results.get("baselineCharacteristicsModule", {})
        baseline_measures = baseline.get("measures", [])
        if baseline_measures:
            lines.append("## Baseline Characteristics")
            for measure in baseline_measures[:10]:
                lines.append(f"- **{measure.get('title', 'N/A')}** ({measure.get('paramType', 'N/A')})")
                classes = measure.get("classes", [])
                for cls in classes[:3]:
                    categories = cls.get("categories", [])
                    for cat in categories[:3]:
                        measurements = cat.get("measurements", [])
                        vals = ", ".join([f"{m.get('groupId', '?')}: {m.get('value', '?')}" for m in measurements])
                        cat_title = cat.get("title", "")
                        if cat_title:
                            lines.append(f"  - {cat_title}: {vals}")
                        else:
                            lines.append(f"  - {vals}")
            lines.append("")

        # Outcome measures
        outcomes = results.get("outcomeMeasuresModule", {})
        outcome_list = outcomes.get("outcomeMeasures", [])
        if outcome_list:
            lines.append("## Outcome Measures")
            for outcome in outcome_list:
                outcome_type = outcome.get("type", "N/A")
                lines.append(f"\n### {outcome_type}: {outcome.get('title', 'N/A')}")
                lines.append(f"**Description:** {outcome.get('description', 'N/A')}")
                lines.append(f"**Time Frame:** {outcome.get('timeFrame', 'N/A')}")
                lines.append(f"**Parameter:** {outcome.get('paramType', 'N/A')} ({outcome.get('unitOfMeasure', '')})")

                # Group data
                groups = outcome.get("groups", [])
                for group in groups:
                    lines.append(f"- {group.get('title', 'N/A')} ({group.get('id', '')})")

                # Class data with measurements
                classes = outcome.get("classes", [])
                for cls in classes[:5]:
                    cls_title = cls.get("title", "")
                    if cls_title:
                        lines.append(f"\n**{cls_title}:**")
                    categories = cls.get("categories", [])
                    for cat in categories:
                        measurements = cat.get("measurements", [])
                        for m in measurements:
                            spread = m.get("spread", "")
                            spread_str = f" (±{spread})" if spread else ""
                            lines.append(f"  - {m.get('groupId', '?')}: {m.get('value', '?')}{spread_str}")

                # Statistical analyses
                analyses = outcome.get("analyses", [])
                if analyses:
                    lines.append("\n**Statistical Analyses:**")
                    for analysis in analyses:
                        groups_analyzed = analysis.get("groupIds", [])
                        lines.append(f"  - Groups: {', '.join(groups_analyzed)}")
                        p_value = analysis.get("pValue", "")
                        if p_value:
                            lines.append(f"    P-value: {p_value}")
                        method = analysis.get("statisticalMethod", "")
                        if method:
                            lines.append(f"    Method: {method}")
                        estimate = analysis.get("estimateComment", "") or analysis.get("paramValue", "")
                        if estimate:
                            lines.append(f"    Estimate: {estimate}")
                        ci_lower = analysis.get("ciLowerLimit", "")
                        ci_upper = analysis.get("ciUpperLimit", "")
                        if ci_lower and ci_upper:
                            ci_pct = analysis.get("ciPctValue", "95")
                            lines.append(f"    {ci_pct}% CI: [{ci_lower}, {ci_upper}]")

            lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 4: get_adverse_events
# ---------------------------------------------------------------------------
@mcp.tool(
    name="get_adverse_events",
    annotations={
        "title": "Get Adverse Events",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_adverse_events(
    nct_id: str,
    response_format: str = "markdown",
) -> str:
    """Get adverse event data from a completed clinical trial.

    Returns serious adverse events and other adverse events organized by
    organ system class, with frequency counts per study arm. Only available
    for trials that have posted results.
    """
    try:
        data = await get_study_results(nct_id.strip().upper())
        results = data.get("resultsSection")

        if not results:
            return f"No results posted for {nct_id}. Adverse event data is only available for trials with posted results."

        ae_module = results.get("adverseEventsModule")
        if not ae_module:
            return f"No adverse event data available for {nct_id}."

        if response_format == "json":
            return _json_out(ae_module)

        lines = [f"# Adverse Events: {nct_id}", ""]

        # Overview
        freq_threshold = ae_module.get("frequencyThreshold", "N/A")
        timeframe = ae_module.get("timeFrame", "N/A")
        description = ae_module.get("description", "")
        lines.append(f"**Frequency Threshold:** {freq_threshold}%")
        lines.append(f"**Time Frame:** {timeframe}")
        if description:
            lines.append(f"**Description:** {description}")
        lines.append("")

        # Event groups
        event_groups = ae_module.get("eventGroups", [])
        if event_groups:
            lines.append("## Study Arms")
            for group in event_groups:
                deaths = group.get("deathsNumAffected", "N/A")
                serious_affected = group.get("seriousNumAffected", "N/A")
                serious_at_risk = group.get("seriousNumAtRisk", "N/A")
                other_affected = group.get("otherNumAffected", "N/A")
                other_at_risk = group.get("otherNumAtRisk", "N/A")
                lines.append(f"**{group.get('title', 'N/A')}** ({group.get('id', '')})")
                lines.append(f"  - Deaths: {deaths}")
                lines.append(f"  - Serious AEs: {serious_affected}/{serious_at_risk} at risk")
                lines.append(f"  - Other AEs: {other_affected}/{other_at_risk} at risk")
            lines.append("")

        # Serious adverse events
        serious_events = ae_module.get("seriousEvents", [])
        if serious_events:
            lines.append("## Serious Adverse Events")
            for event in serious_events[:20]:
                term = event.get("term", "N/A")
                organ = event.get("organSystem", "N/A")
                stats = event.get("stats", [])
                counts = ", ".join([
                    f"{s.get('groupId', '?')}: {s.get('numAffected', '?')}/{s.get('numAtRisk', '?')}"
                    for s in stats
                ])
                lines.append(f"- **{term}** ({organ}): {counts}")
            if len(serious_events) > 20:
                lines.append(f"*... and {len(serious_events) - 20} more serious events*")
            lines.append("")

        # Other adverse events
        other_events = ae_module.get("otherEvents", [])
        if other_events:
            lines.append("## Other Adverse Events")
            for event in other_events[:20]:
                term = event.get("term", "N/A")
                organ = event.get("organSystem", "N/A")
                stats = event.get("stats", [])
                counts = ", ".join([
                    f"{s.get('groupId', '?')}: {s.get('numAffected', '?')}/{s.get('numAtRisk', '?')}"
                    for s in stats
                ])
                lines.append(f"- **{term}** ({organ}): {counts}")
            if len(other_events) > 20:
                lines.append(f"*... and {len(other_events) - 20} more other events*")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 5: get_study_arms
# ---------------------------------------------------------------------------
@mcp.tool(
    name="get_study_arms",
    annotations={
        "title": "Get Study Arms & Interventions",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_study_arms(
    nct_id: str,
    response_format: str = "markdown",
) -> str:
    """Get detailed study arm and intervention information for a clinical trial.

    Returns arm descriptions, types (experimental, comparator, placebo),
    intervention details (drug names, dosing, administration route), and
    participant counts if results are available.
    """
    try:
        data = await get_study(nct_id.strip().upper())
        proto = data.get("protocolSection", {})
        arms_mod = proto.get("armsInterventionsModule", {})
        design = proto.get("designModule", {})

        arm_groups = arms_mod.get("armGroups", [])
        interventions = arms_mod.get("interventions", [])

        if not arm_groups and not interventions:
            return f"No arm or intervention data available for {nct_id}."

        # Check if results have participant counts
        results = data.get("resultsSection", {})
        flow = results.get("participantFlowModule", {})
        flow_groups = {g.get("id"): g for g in flow.get("groups", [])}

        if response_format == "json":
            return _json_out({
                "nctId": nct_id,
                "designInfo": design.get("designInfo", {}),
                "enrollmentInfo": design.get("enrollmentInfo", {}),
                "armGroups": arm_groups,
                "interventions": interventions,
                "participantFlow": flow if flow else None,
            })

        lines = [f"# Study Arms: {nct_id}", ""]

        design_info = design.get("designInfo", {})
        if design_info:
            lines.append(f"**Allocation:** {design_info.get('allocation', 'N/A')}")
            lines.append(f"**Intervention Model:** {design_info.get('interventionModel', 'N/A')}")
            masking = design_info.get("maskingInfo", {})
            if masking:
                lines.append(f"**Masking:** {masking.get('masking', 'N/A')}")
            lines.append("")

        if arm_groups:
            lines.append("## Arms")
            for arm in arm_groups:
                lines.append(f"\n### {arm.get('label', 'N/A')} ({arm.get('type', 'N/A')})")
                desc = arm.get("description", "")
                if desc:
                    lines.append(desc)
                arm_interventions = arm.get("interventionNames", [])
                if arm_interventions:
                    lines.append(f"**Interventions:** {', '.join(arm_interventions)}")
            lines.append("")

        if interventions:
            lines.append("## Interventions")
            for interv in interventions:
                lines.append(f"\n### {interv.get('name', 'N/A')} ({interv.get('type', 'N/A')})")
                desc = interv.get("description", "")
                if desc:
                    lines.append(desc)
                arm_labels = interv.get("armGroupLabels", [])
                if arm_labels:
                    lines.append(f"**Arms:** {', '.join(arm_labels)}")
                other_names = interv.get("otherNames", [])
                if other_names:
                    lines.append(f"**Other Names:** {', '.join(other_names)}")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 6: compare_trials
# ---------------------------------------------------------------------------
@mcp.tool(
    name="compare_trials",
    annotations={
        "title": "Compare Clinical Trials",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def compare_trials(
    nct_ids: List[str],
    response_format: str = "markdown",
) -> str:
    """Compare 2-5 clinical trials side by side.

    Highlights differences in study design, phases, enrollment, endpoints,
    interventions, and status. Useful for competitive landscape analysis
    and protocol benchmarking.
    """
    if len(nct_ids) < 2 or len(nct_ids) > 5:
        return "Error: Provide between 2 and 5 NCT IDs for comparison."

    try:
        import asyncio as aio
        tasks = [get_study(nid.strip().upper()) for nid in nct_ids]
        results = await aio.gather(*tasks, return_exceptions=True)

        studies = []
        errors = []
        for nid, result in zip(nct_ids, results):
            if isinstance(result, Exception):
                errors.append(f"{nid}: {format_api_error(result)}")
            else:
                studies.append(result)

        if not studies:
            return "Error: Could not retrieve any of the requested trials.\n" + "\n".join(errors)

        if response_format == "json":
            return _json_out({"studies": studies, "errors": errors})

        lines = ["# Trial Comparison", ""]
        if errors:
            lines.append("**Errors:**")
            for err in errors:
                lines.append(f"- {err}")
            lines.append("")

        # Build comparison table
        headers = ["Field"] + [
            s.get("protocolSection", {}).get("identificationModule", {}).get("nctId", "?")
            for s in studies
        ]
        rows = []

        def _get(study: Dict, *keys: str) -> str:
            val = study
            for k in keys:
                if isinstance(val, dict):
                    val = val.get(k, {})
                else:
                    return "N/A"
            return str(val) if val else "N/A"

        field_paths = [
            ("Title", lambda s: _get(s, "protocolSection", "identificationModule", "briefTitle")),
            ("Status", lambda s: _get(s, "protocolSection", "statusModule", "overallStatus")),
            ("Phase", lambda s: ", ".join(_get(s, "protocolSection", "designModule").get("phases", []) if isinstance(_get(s, "protocolSection", "designModule"), dict) else [])),
            ("Enrollment", lambda s: str(_get(s, "protocolSection", "designModule", "enrollmentInfo").get("count", "N/A") if isinstance(_get(s, "protocolSection", "designModule", "enrollmentInfo"), dict) else "N/A")),
            ("Sponsor", lambda s: _get(s, "protocolSection", "sponsorCollaboratorsModule", "leadSponsor").get("name", "N/A") if isinstance(_get(s, "protocolSection", "sponsorCollaboratorsModule", "leadSponsor"), dict) else "N/A"),
            ("Study Type", lambda s: _get(s, "protocolSection", "designModule", "studyType")),
            ("Has Results", lambda s: "Yes" if s.get("hasResults") else "No"),
        ]

        for label, extractor in field_paths:
            row = [label] + [extractor(s) for s in studies]
            rows.append(row)

        # Format as markdown table
        col_widths = [max(len(str(cell)) for cell in col) for col in zip(headers, *rows)]
        header_line = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
        sep_line = " | ".join("-" * w for w in col_widths)
        lines.append(f"| {header_line} |")
        lines.append(f"| {sep_line} |")
        for row in rows:
            row_line = " | ".join(str(c).ljust(w) for c, w in zip(row, col_widths))
            lines.append(f"| {row_line} |")
        lines.append("")

        # Compare primary endpoints
        lines.append("## Primary Endpoints")
        for s in studies:
            proto = s.get("protocolSection", {})
            nid = proto.get("identificationModule", {}).get("nctId", "?")
            outcomes = proto.get("outcomesModule", {}).get("primaryOutcomes", [])
            lines.append(f"\n**{nid}:**")
            if outcomes:
                for o in outcomes:
                    lines.append(f"- {o.get('measure', 'N/A')} ({o.get('timeFrame', 'N/A')})")
            else:
                lines.append("- None listed")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 7: match_patient
# ---------------------------------------------------------------------------
@mcp.tool(
    name="match_patient",
    annotations={
        "title": "Match Patient to Trials",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def match_patient(
    condition: str,
    age: Optional[str] = None,
    sex: Optional[str] = None,
    location: Optional[str] = None,
    eligibility_keywords: Optional[str] = None,
    status: Optional[List[str]] = None,
    page_size: int = 10,
    response_format: str = "markdown",
) -> str:
    """Find recruiting clinical trials matching patient eligibility criteria.

    Searches for trials a specific patient might qualify for based on their
    condition, age, sex, location, and clinical criteria. Defaults to
    RECRUITING status only.

    Args:
        condition: Primary medical condition (e.g., 'breast cancer', 'diabetes').
        age: Patient age in format 'X Years' (e.g., '65 Years').
        sex: MALE, FEMALE, or ALL.
        location: Geographic location (city, state, or country).
        eligibility_keywords: Keywords to match in eligibility criteria
            (e.g., 'HbA1c > 8', 'BRCA mutation', 'treatment naive').
        status: Trial status filter. Defaults to ['RECRUITING'].
    """
    try:
        if status is None:
            status = ["RECRUITING"]

        params = _build_search_params(
            condition=condition,
            location=location,
            status=status,
            page_size=page_size,
        )

        # Add eligibility-specific filters
        query_parts = []
        if eligibility_keywords:
            query_parts.append(eligibility_keywords)
        if age:
            params["query.patient"] = age
        if sex and sex.upper() in ("MALE", "FEMALE"):
            params["filter.sex"] = sex.upper()

        if query_parts:
            existing = params.get("query.term", "")
            if existing:
                params["query.term"] = f"{existing} AND {' AND '.join(query_parts)}"
            else:
                params["query.term"] = " AND ".join(query_parts)

        data = await search_studies(params)
        studies = data.get("studies", [])

        if not studies:
            return f"No recruiting trials found matching patient criteria for '{condition}'. Try broadening your search."

        if response_format == "json":
            return _json_out(data)

        lines = [f"# Patient-Trial Matches: {condition}", ""]
        lines.append(f"Found {len(studies)} potential matches")
        if age:
            lines.append(f"**Patient Age:** {age}")
        if sex:
            lines.append(f"**Sex:** {sex}")
        if location:
            lines.append(f"**Location:** {location}")
        lines.append("")

        for s in studies:
            proto = s.get("protocolSection", {})
            ident = proto.get("identificationModule", {})
            elig = proto.get("eligibilityModule", {})
            contacts = proto.get("contactsLocationsModule", {})
            locations = contacts.get("locations", [])

            lines.append(_md_trial_summary(s))

            # Show eligibility summary
            min_age = elig.get("minimumAge", "N/A")
            max_age = elig.get("maximumAge", "N/A")
            elig_sex = elig.get("sex", "ALL")
            lines.append(f"**Eligibility:** Ages {min_age}–{max_age}, Sex: {elig_sex}")

            if locations:
                loc = locations[0]
                lines.append(f"**Nearest Site:** {loc.get('facility', 'N/A')} — {loc.get('city', '')}, {loc.get('country', '')}")
            lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 8: summarize_endpoints
# ---------------------------------------------------------------------------
@mcp.tool(
    name="summarize_endpoints",
    annotations={
        "title": "Summarize Endpoints Across Trials",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def summarize_endpoints(
    condition: str,
    phase: Optional[List[str]] = None,
    page_size: int = 50,
    response_format: str = "markdown",
) -> str:
    """Analyze primary and secondary endpoints across multiple trials for a condition.

    Identifies common endpoint patterns and measures used in a therapeutic area.
    Useful for protocol design and competitive analysis.
    """
    try:
        params = _build_search_params(
            condition=condition,
            phase=phase,
            page_size=page_size,
        )
        data = await search_studies(params)
        studies = data.get("studies", [])

        if not studies:
            return f"No trials found for '{condition}' to analyze endpoints."

        primary_endpoints: Dict[str, int] = {}
        secondary_endpoints: Dict[str, int] = {}
        timeframes: Dict[str, int] = {}

        for s in studies:
            outcomes = s.get("protocolSection", {}).get("outcomesModule", {})
            for outcome in outcomes.get("primaryOutcomes", []):
                measure = outcome.get("measure", "").strip()
                if measure:
                    primary_endpoints[measure] = primary_endpoints.get(measure, 0) + 1
                tf = outcome.get("timeFrame", "").strip()
                if tf:
                    timeframes[tf] = timeframes.get(tf, 0) + 1

            for outcome in outcomes.get("secondaryOutcomes", []):
                measure = outcome.get("measure", "").strip()
                if measure:
                    secondary_endpoints[measure] = secondary_endpoints.get(measure, 0) + 1

        if response_format == "json":
            return _json_out({
                "condition": condition,
                "trialsAnalyzed": len(studies),
                "primaryEndpoints": dict(sorted(primary_endpoints.items(), key=lambda x: -x[1])),
                "secondaryEndpoints": dict(sorted(secondary_endpoints.items(), key=lambda x: -x[1])),
                "timeframes": dict(sorted(timeframes.items(), key=lambda x: -x[1])),
            })

        lines = [f"# Endpoint Analysis: {condition}", ""]
        lines.append(f"Analyzed **{len(studies)}** trials")
        if phase:
            lines.append(f"**Phases:** {', '.join(phase)}")
        lines.append("")

        # Top primary endpoints
        sorted_primary = sorted(primary_endpoints.items(), key=lambda x: -x[1])
        if sorted_primary:
            lines.append("## Most Common Primary Endpoints")
            for measure, count in sorted_primary[:15]:
                lines.append(f"- {measure} ({count} trials)")
            lines.append("")

        # Top secondary endpoints
        sorted_secondary = sorted(secondary_endpoints.items(), key=lambda x: -x[1])
        if sorted_secondary:
            lines.append("## Most Common Secondary Endpoints")
            for measure, count in sorted_secondary[:15]:
                lines.append(f"- {measure} ({count} trials)")
            lines.append("")

        # Top timeframes
        sorted_tf = sorted(timeframes.items(), key=lambda x: -x[1])
        if sorted_tf:
            lines.append("## Common Timeframes")
            for tf, count in sorted_tf[:10]:
                lines.append(f"- {tf} ({count} trials)")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 9: search_investigators
# ---------------------------------------------------------------------------
@mcp.tool(
    name="search_investigators",
    annotations={
        "title": "Search Investigators & Sites",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_investigators(
    condition: Optional[str] = None,
    investigator_name: Optional[str] = None,
    institution: Optional[str] = None,
    location: Optional[str] = None,
    status: Optional[List[str]] = None,
    page_size: int = 20,
    response_format: str = "markdown",
) -> str:
    """Find principal investigators and research sites conducting clinical trials.

    Search by disease area, investigator name, institution, or location.
    Returns investigator names, roles, affiliations, and associated trial IDs.
    """
    try:
        query_parts = []
        if condition:
            query_parts.append(f"AREA[Condition]{condition}")
        if investigator_name:
            query_parts.append(f"AREA[OverallOfficialName]{investigator_name}")
        if institution:
            query_parts.append(f"AREA[LocationFacility]{institution}")
        if location:
            query_parts.append(f"AREA[LocationCountry]{location}")

        params: Dict[str, Any] = {"pageSize": page_size}
        if query_parts:
            params["query.term"] = " AND ".join(query_parts)
        if status:
            params["filter.overallStatus"] = ",".join(status)

        data = await search_studies(params)
        studies = data.get("studies", [])

        if not studies:
            return "No trials found matching your investigator/site search criteria."

        if response_format == "json":
            investigators = []
            for s in studies:
                proto = s.get("protocolSection", {})
                nct_id = proto.get("identificationModule", {}).get("nctId", "")
                title = proto.get("identificationModule", {}).get("briefTitle", "")
                contacts = proto.get("contactsLocationsModule", {})
                officials = contacts.get("overallOfficials", [])
                locations = contacts.get("locations", [])
                for official in officials:
                    investigators.append({
                        "name": official.get("name", ""),
                        "role": official.get("role", ""),
                        "affiliation": official.get("affiliation", ""),
                        "nctId": nct_id,
                        "trialTitle": title,
                    })
                for loc in locations:
                    investigators.append({
                        "facility": loc.get("facility", ""),
                        "city": loc.get("city", ""),
                        "state": loc.get("state", ""),
                        "country": loc.get("country", ""),
                        "nctId": nct_id,
                        "trialTitle": title,
                    })
            return _json_out(investigators)

        lines = ["# Investigators & Sites", ""]
        lines.append(f"Found across {len(studies)} trials")
        lines.append("")

        for s in studies:
            proto = s.get("protocolSection", {})
            ident = proto.get("identificationModule", {})
            contacts = proto.get("contactsLocationsModule", {})
            officials = contacts.get("overallOfficials", [])
            locs = contacts.get("locations", [])

            nct_id = ident.get("nctId", "")
            title = ident.get("briefTitle", "")

            if officials or locs:
                lines.append(f"### {nct_id}: {title}")
                for official in officials:
                    lines.append(f"- **{official.get('name', 'N/A')}** ({official.get('role', 'N/A')}) — {official.get('affiliation', 'N/A')}")
                for loc in locs[:3]:
                    lines.append(f"- {loc.get('facility', 'N/A')} — {loc.get('city', '')}, {loc.get('state', '')}, {loc.get('country', '')}")
                if len(locs) > 3:
                    lines.append(f"  *... and {len(locs) - 3} more sites*")
                lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Tool 10: search_by_sponsor
# ---------------------------------------------------------------------------
@mcp.tool(
    name="search_by_sponsor",
    annotations={
        "title": "Search Trials by Sponsor",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_by_sponsor(
    sponsor_name: str,
    condition: Optional[str] = None,
    phase: Optional[List[str]] = None,
    status: Optional[List[str]] = None,
    page_size: int = 20,
    count_total: bool = True,
    response_format: str = "markdown",
) -> str:
    """Find all clinical trials sponsored by a specific company or organization.

    Useful for pipeline analysis and competitive intelligence. Supports
    filtering by condition, phase, and status. Partial name matches work
    (e.g., 'Pfizer' matches 'Pfizer Inc').
    """
    try:
        params = _build_search_params(
            sponsor=sponsor_name,
            condition=condition,
            phase=phase,
            status=status,
            page_size=page_size,
            count_total=count_total,
        )
        data = await search_studies(params)
        studies = data.get("studies", [])
        total = data.get("totalCount")

        if not studies:
            return f"No trials found for sponsor '{sponsor_name}'."

        if response_format == "json":
            return _json_out(data)

        lines = [f"# Sponsor Pipeline: {sponsor_name}", ""]
        if total is not None:
            lines.append(f"**{total} total trials**")
        lines.append(f"Showing {len(studies)} results")
        if condition:
            lines.append(f"**Condition Filter:** {condition}")
        if phase:
            lines.append(f"**Phase Filter:** {', '.join(phase)}")
        if status:
            lines.append(f"**Status Filter:** {', '.join(status)}")
        lines.append("")

        # Group by phase for pipeline view
        by_phase: Dict[str, List[Dict]] = {}
        for s in studies:
            phases = s.get("protocolSection", {}).get("designModule", {}).get("phases", ["N/A"])
            phase_label = ", ".join(phases) if phases else "N/A"
            by_phase.setdefault(phase_label, []).append(s)

        for phase_label in sorted(by_phase.keys()):
            phase_studies = by_phase[phase_label]
            lines.append(f"## {phase_label} ({len(phase_studies)} trials)")
            for s in phase_studies:
                lines.append(_md_trial_summary(s))
                lines.append("")

        return "\n".join(lines)

    except Exception as exc:
        return format_api_error(exc)


# ---------------------------------------------------------------------------
# Health check endpoint
# ---------------------------------------------------------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": "clinical_trials_mcp"})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
