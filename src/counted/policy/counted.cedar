// Counted authorization policy, evaluated by Strands CedarAuthorization before EVERY tool call.
// Principals: Role::"family", Role::"caseworker", Role::"certifier", Role::"service" (API key holders).
// The guarantee this file encodes: only a human certifier can sign; nobody, not even the agent,
// can ask for a determination before the disaster facts have been checked against public records.

// Anyone in an interview may record what they are told and check public facts.
permit (
  principal,
  action in [Action::"record_details", Action::"record_circumstance", Action::"record_concern",
             Action::"check_disaster_context"],
  resource
);

// A determination may be requested only after the declaration/weather check has run,
// and only once at least one circumstance or concern is on file.
permit (
  principal,
  action == Action::"request_determination",
  resource
) when { context.session.context_checked && context.session.facts_on_file > 0 };

// Signing a statement is a medicolegal act. Only a certifier principal, never the agent's own role.
permit (
  principal == Role::"certifier",
  action == Action::"sign_certifier_statement",
  resource
);

// Hard stop on runaway loops: a real interview never needs more than 60 recorded items.
forbid (
  principal,
  action == Action::"record_circumstance",
  resource
) when { context.session.call_count > 60 };
