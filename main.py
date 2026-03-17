"""LLM-orchestrated tool runner.

Usage:
python main.py "what is the weather in Tokyo"
"""

from __future__ import annotations

import json
import os
import sys
from urllib.request import Request, urlopen

from tool import current_time, search_google, weather_check


SYSTEM_PROMPT = """You are a tool router.
Choose exactly one tool for each user query.

Available tools:
1) weather_check(city: str)
2) search_google(query: str, open_in_browser: bool)
3) current_time(use_utc: bool)

Return only valid JSON with this exact schema:
{
  "tool": "weather_check" | "search_google" | "current_time",
  "arguments": { ... }
}

Rules:
- If asking for weather in a location, use weather_check with city.
- If asking to search/find/look up web info, use search_google with query.
- If asking current time/date/clock, use current_time.
- open_in_browser should default to false unless user explicitly asks to open browser.
- use_utc should be true only if user explicitly asks for UTC.
"""


def _load_env_file(file_path: str = ".env") -> None:
	if not os.path.exists(file_path):
		return

	try:
		with open(file_path, "r", encoding="utf-8") as env_file:
			for raw_line in env_file:
				line = raw_line.strip()
				if not line or line.startswith("#"):
					continue
				if line.startswith("export "):
					line = line[len("export ") :].strip()
				if "=" not in line:
					continue

				key, value = line.split("=", 1)
				key = key.strip()
				value = value.strip()
				if not key or key in os.environ:
					continue

				if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
					value = value[1:-1]
				os.environ[key] = value
	except OSError:
		# Keep running even when local env file cannot be read.
		pass


_load_env_file()


def _call_router_llm(user_query: str) -> dict:
	azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
	azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()

	if azure_endpoint and azure_deployment:
		api_key = os.getenv("AZURE_OPENAI_API_KEY", "").strip() or os.getenv(
			"OPENAI_API_KEY", ""
		).strip()
		if not api_key:
			raise RuntimeError("AZURE_OPENAI_API_KEY (or OPENAI_API_KEY) is not set.")

		api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21").strip()
		endpoint = azure_endpoint.rstrip("/")
		url = (
			f"{endpoint}/openai/deployments/{azure_deployment}/chat/completions"
			f"?api-version={api_version}"
		)
		payload = {
			"temperature": 0,
			"messages": [
				{"role": "system", "content": SYSTEM_PROMPT},
				{"role": "user", "content": user_query},
			],
		}
		headers = {
			"api-key": api_key,
			"Content-Type": "application/json",
		}
	else:
		api_key = os.getenv("OPENAI_API_KEY", "").strip()
		if not api_key:
			raise RuntimeError(
				"Set Azure env vars (AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_DEPLOYMENT + key) "
				"or OPENAI_API_KEY for public OpenAI API."
			)

		model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
		url = "https://api.openai.com/v1/chat/completions"
		payload = {
			"model": model,
			"temperature": 0,
			"messages": [
				{"role": "system", "content": SYSTEM_PROMPT},
				{"role": "user", "content": user_query},
			],
		}
		headers = {
			"Authorization": f"Bearer {api_key}",
			"Content-Type": "application/json",
		}

	request = Request(
		url,
		data=json.dumps(payload).encode("utf-8"),
		headers=headers,
		method="POST",
	)

	with urlopen(request, timeout=20) as response:  # nosec B310
		body = json.loads(response.read().decode("utf-8"))

	content = body["choices"][0]["message"]["content"]
	return json.loads(content)


def _execute_tool(tool_name: str, arguments: dict) -> str:
	if tool_name == "weather_check":
		return weather_check(arguments.get("city", ""))
	if tool_name == "search_google":
		return search_google(
			arguments.get("query", ""),
			bool(arguments.get("open_in_browser", False)),
		)
	if tool_name == "current_time":
		return current_time(bool(arguments.get("use_utc", False)))
	raise ValueError(f"Unknown tool selected by LLM: {tool_name}")


def run(query: str) -> str:
	route = _call_router_llm(query)
	tool_name = route.get("tool", "")
	arguments = route.get("arguments", {})
	result = _execute_tool(tool_name, arguments)
	return f"tool={tool_name}\nargs={json.dumps(arguments)}\nresult={result}"


if __name__ == "__main__":
	if len(sys.argv) < 2:
		print('Usage: python main.py "your query"')
		sys.exit(1)

	user_query = " ".join(sys.argv[1:]).strip()
	try:
		print(run(user_query))
	except Exception as exc:
		print(f"Error: {exc}")
		sys.exit(1)