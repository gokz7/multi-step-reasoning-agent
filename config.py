"""
config.py - All settings for the reasoning agent, kept in one place.

Every value can be changed with an environment variable (or a .env file),
so nothing needs to be edited inside the code to switch LLM provider or model.
"""

import os                                                         # read environment variables

try:                                                              # python-dotenv is optional
    from dotenv import load_dotenv                                # loads values from a .env file
    load_dotenv()                                                 # put .env values into os.environ
except ImportError:                                               # if the package is not installed
    pass                                                          # just use normal environment variables

# Which LLM to use: "gemini", "openai" or "anthropic" (offline tests build a MockClient directly)
PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()            # default is Gemini (free tier)

DEFAULT_MODELS = {                                                # default model for each provider
    "gemini": "gemini-3.1-flash-lite",                            # stable, free tier; gemini-flash-latest returned 503 (high demand) in testing
    "openai": "gpt-5.4-mini",                                     # small, cheap OpenAI model
    "anthropic": "claude-haiku-5-5",                              # small, cheap Anthropic model
}

MODEL_NAME = os.getenv("LLM_MODEL", DEFAULT_MODELS.get(PROVIDER, ""))  # user can override the model

TEMPERATURE = 0.0                                                 # 0 = most repeatable answers (used by Gemini)

MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))                  # extra plan+execute rounds after a failed verification

API_RETRY_ATTEMPTS = 3                                            # how many times to retry one API call on an error
API_RETRY_WAIT_SECONDS = 20                                       # wait between API retries (helps with rate limits)
API_TIMEOUT_SECONDS = 60                                          # give up on a single call after this long
MIN_SECONDS_BETWEEN_CALLS = float(os.getenv("MIN_SECONDS_BETWEEN_CALLS", "4"))  # spacing for free-tier rate limits

NUMBER_TOLERANCE = 1e-6                                           # how close two numbers must be to count as equal

LOG_DIR = "logs"                                                  # folder for trace logs and test results
TRACE_LOG_FILE = os.path.join(LOG_DIR, "agent_trace.jsonl")       # full internal reasoning of every run