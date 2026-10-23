"""
llm_client.py - One small wrapper around each LLM provider.

All clients share the same method: ask(prompt) -> text.
The planner, executor and verifier only call ask(), so they never know
which provider is behind it. Switching provider = changing LLM_PROVIDER.

MockClient returns pre-written answers. It lets us test the agent loop
(retries, failures) without an API key or internet.
"""

import time                                                       # for waiting between calls

import config                                                     # provider, model and retry settings


class LLMClient:
    """Base class. Child classes only need to write _generate()."""

    def __init__(self, model_name):
        self.model_name = model_name                              # which model to call
        self.last_call_time = 0.0                                 # when the last API call happened
        self.call_count = 0                                       # number of LLM calls (useful in logs)

    def _generate(self, prompt):
        raise NotImplementedError                                 # each provider writes its own version

    def ask(self, prompt):
        """Send a prompt and return the reply text, retrying on API errors."""
        last_error = None                                         # remember the last error for the message
        for attempt in range(1, config.API_RETRY_ATTEMPTS + 1):   # try a few times
            self._wait_for_rate_limit()                           # keep calls spaced out
            try:
                self.call_count += 1                              # count this call
                text = self._generate(prompt)                     # real provider call
                if text and text.strip():                         # got a non-empty reply
                    return text                                   # done
                last_error = "Empty reply from model"             # treat empty reply as an error
            except Exception as error:                            # network error, rate limit, etc.
                last_error = str(error)                           # keep the message
            short_error = " ".join(str(last_error).split())[:200]  # one-line, shortened error text
            if attempt < config.API_RETRY_ATTEMPTS:               # more attempts left
                print(f"[LLM] call failed (attempt {attempt}/{config.API_RETRY_ATTEMPTS}): {short_error} "
                      f"... retrying in {config.API_RETRY_WAIT_SECONDS}s")  # show why we are waiting
                time.sleep(config.API_RETRY_WAIT_SECONDS)         # wait before trying again
            else:
                print(f"[LLM] call failed (attempt {attempt}/{config.API_RETRY_ATTEMPTS}): {short_error}")  # last try
        raise RuntimeError(f"LLM call failed after retries: {last_error}")  # give up

    def _wait_for_rate_limit(self):
        """Sleep if the previous call was too recent."""
        gap = time.time() - self.last_call_time                   # seconds since the last call
        if gap < config.MIN_SECONDS_BETWEEN_CALLS:                # too soon
            time.sleep(config.MIN_SECONDS_BETWEEN_CALLS - gap)    # wait the remaining time
        self.last_call_time = time.time()                         # update the timestamp


class GeminiClient(LLMClient):
    """Google Gemini. Needs GEMINI_API_KEY in the environment."""

    def __init__(self, model_name):
        super().__init__(model_name)                              # set shared fields
        from google import genai                                  # imported here so other providers don't need it
        from google.genai import types                            # config object for the request
        self.client = genai.Client(                               # reads GEMINI_API_KEY automatically
            http_options=types.HttpOptions(
                timeout=config.API_TIMEOUT_SECONDS * 1000,        # library expects milliseconds
                retry_options=types.HttpRetryOptions(attempts=1),  # no hidden library retries; our ask() retries visibly
            )
        )
        self.request_config = types.GenerateContentConfig(        # settings sent with every request
            temperature=config.TEMPERATURE,                       # repeatable answers
            response_mime_type="application/json",                # ask Gemini to reply in pure JSON
        )

    def _generate(self, prompt):
        response = self.client.models.generate_content(           # one API call
            model=self.model_name,                                # e.g. gemini-3.1-flash-lite
            contents=prompt,                                      # the full prompt text
            config=self.request_config,                           # temperature + JSON mode
        )
        return response.text                                      # reply as plain text


class OpenAIClient(LLMClient):
    """OpenAI. Needs OPENAI_API_KEY in the environment."""

    def __init__(self, model_name):
        super().__init__(model_name)                              # set shared fields
        from openai import OpenAI                                 # imported only when this provider is used
        self.client = OpenAI()                                    # reads OPENAI_API_KEY automatically

    def _generate(self, prompt):
        response = self.client.chat.completions.create(           # one API call
            model=self.model_name,                                # e.g. gpt-5.4-mini
            messages=[{"role": "user", "content": prompt}],       # prompt as a single user message
            response_format={"type": "json_object"},              # force a JSON reply
        )                                                         # temperature left default: some newer models reject other values
        return response.choices[0].message.content                # reply text


class AnthropicClient(LLMClient):
    """Anthropic Claude. Needs ANTHROPIC_API_KEY in the environment."""

    def __init__(self, model_name):
        super().__init__(model_name)                              # set shared fields
        import anthropic                                          # imported only when this provider is used
        self.client = anthropic.Anthropic()                       # reads ANTHROPIC_API_KEY automatically

    def _generate(self, prompt):
        response = self.client.messages.create(                   # one API call
            model=self.model_name,                                # e.g. claude-haiku-5-5
            max_tokens=2000,                                      # enough room for a JSON answer
            messages=[{"role": "user", "content": prompt}],       # prompt as a single user message
        )
        return response.content[0].text                           # reply text


class MockClient(LLMClient):
    """Fake LLM for offline tests. Returns scripted replies in order."""

    def __init__(self, scripted_replies):
        super().__init__("mock")                                  # set shared fields
        self.scripted_replies = list(scripted_replies)            # replies to hand out, first to last
        self.prompts_seen = []                                    # every prompt it received (for test checks)

    def ask(self, prompt):
        self.call_count += 1                                      # count calls like a real client
        self.prompts_seen.append(prompt)                          # remember the prompt
        if not self.scripted_replies:                             # test script ran out of replies
            raise RuntimeError("MockClient has no more scripted replies")
        return self.scripted_replies.pop(0)                       # give the next reply (no waiting, no retries)


def get_client(provider=None, model_name=None):
    """Create the client for the chosen provider (defaults come from config)."""
    provider = (provider or config.PROVIDER).lower()              # e.g. "gemini"
    model_name = model_name or config.MODEL_NAME                  # e.g. "gemini-3.1-flash-lite"
    if provider == "gemini":
        return GeminiClient(model_name)
    if provider == "openai":
        return OpenAIClient(model_name)
    if provider == "anthropic":
        return AnthropicClient(model_name)
    raise ValueError(f"Unknown LLM_PROVIDER '{provider}'. Use gemini, openai or anthropic.")  # mock is built directly in tests