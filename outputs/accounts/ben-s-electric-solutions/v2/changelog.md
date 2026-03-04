# Changelog: ben-s-electric-solutions - v1 to v2

_Generated: 2026-03-04T06:32:08.431151+00:00_

**13 fields changed**

| Field | v1 Value | v2 Value | Reason |
|-------|----------|----------|--------|
| `business_hours.end` | 4:30 | 5:00 PM | Client confirmed 5:00 PM end time - website listing was outdated |
| `business_hours.start` | 8 | 8:30 AM | Client confirmed 8:30 AM start time - website listing was outdated |
| `business_hours.timezone` | America/Edmonton (inferred) | America/Edmonton | Timezone explicitly confirmed by client (Calgary, Alberta) |
| `call_routing.transfer_phone_number` | null | 403-555-0192 | Ben's second personal number confirmed during onboarding follow-up |
| `call_transfer_rules.transfer_timeout_seconds` | 30 | 45 | Client requested longer timeout to give more time to answer |
| `emergency_routing_rules.allowed_clients` | [{'company': 'G&M Pressure Washing', 'contact_name': 'Shelley Manley', 'phone':  | [{'company': 'G&M Pressure Washing', 'contact_name': 'Shelley Manley', 'phone':  | Additional emergency client added: Northland Property Management |
| `emergency_routing_rules.transfer_to` | Ben's personal number (pending) | 403-555-0192 | Updated during onboarding follow-up |
| `integration_constraints` | [] | ["Never create or modify ServiceTrade jobs directly. All job creation handled ma | Client specified ServiceTrade must not be touched by Clara |
| `notification_preferences.sms_number` | Ben's main line (same as business line — to be confirmed) | 403-555-0147 | Ben's main business line confirmed for SMS notifications |
| `office_address` | null | Calgary, Alberta, Canada (mobile operation - no fixed client-facing address) | Client confirmed mobile operation - Calgary, Alberta |
| `pricing_info.commercial_hourly_rate` | null | $115/hour | Commercial rate differs from residential - added per client |
| `pricing_info.notes` | $115 call-out fee gets technician to job site. Hourly starts after arrival. | $115 call-out fee gets technician to job site. Hourly starts after arrival. Comm | Updated during onboarding follow-up |
| `questions_or_unknowns` | ["Ben's second phone number for direct call transfers (pending — to be shared vi | [] | Resolved unknowns from onboarding update |
