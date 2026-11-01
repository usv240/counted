"""Runtime configuration. Every value can be overridden with an environment variable."""

import os

REGION = os.getenv("AWS_REGION", "us-east-1")

# Model roster. Claude carries the interview and the examiner seat; Amazon Nova sits a second,
# independent examiner seat so the panel never depends on a single model family.
INTERVIEW_MODEL = os.getenv("COUNTED_INTERVIEW_MODEL", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
EXAMINER_MODEL = os.getenv("COUNTED_EXAMINER_MODEL", "global.anthropic.claude-sonnet-4-6")
SECOND_EXAMINER_MODEL = os.getenv("COUNTED_SECOND_EXAMINER_MODEL", "us.amazon.nova-2-lite-v1:0")
ADJUDICATOR_MODEL = os.getenv("COUNTED_ADJUDICATOR_MODEL", "us.anthropic.claude-opus-4-6-v1")
# Used by ModelRouter when a primary model is throttled or unavailable.
FALLBACK_MODEL = os.getenv("COUNTED_FALLBACK_MODEL", "global.anthropic.claude-sonnet-4-5-20250929-v1:0")
# The second examiner's backup stays outside the Claude family, so the panel keeps two model families.
SECOND_EXAMINER_FALLBACK = os.getenv("COUNTED_SECOND_EXAMINER_FALLBACK", "us.amazon.nova-pro-v1:0")

# Days after a disaster's official end during which an indirect causal chain is still credible
# (e.g. a dialysis patient who missed sessions during the outage and died a week later).
AFTERMATH_WINDOW_DAYS = int(os.getenv("COUNTED_AFTERMATH_DAYS", "30"))

HTTP_USER_AGENT = "Counted/0.1 (disaster death attribution research; github.com/usv240/counted)"
