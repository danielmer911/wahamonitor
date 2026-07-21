from anthropic import Anthropic


class AnthropicProvider:
    def __init__(self, model: str, api_key: str):
        self.model = model
        self._client = Anthropic(api_key=api_key)

    def generate(self, prompt: str) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
