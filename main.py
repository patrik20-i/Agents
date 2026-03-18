"""LLM-orchestrated tool runner.

Usage:
python main.py "what is the weather in Tokyo"
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.request import Request, urlopen

from tool import current_time, search_google, weather_check
from tools_x import get_client


SYSTEM_PROMPT = """You are a tool router.
Choose exactly one tool for each user query.

Available tools:
1) weather_check(city: str)
2) search_google(query: str, open_in_browser: bool)
3) current_time(use_utc: bool)
4) x_api(operation: str, arguments: object)

Return only valid JSON with this exact schema:
{
	"tool": "weather_check" | "search_google" | "current_time" | "x_api",
  "arguments": { ... }
}

Rules:
- If asking for weather in a location, use weather_check with city.
- If asking to search/find/look up web info, use search_google with query.
- If asking current time/date/clock, use current_time.
- If asking to do anything related to X/Twitter account operations, use x_api.
- open_in_browser should default to false unless user explicitly asks to open browser.
- use_utc should be true only if user explicitly asks for UTC.

For x_api, put this shape in arguments:
{
	"operation": "...",
	"arguments": { ... }
}

Supported x_api operations and arguments:
- get_me(user_fields?)
- get_user_by_id(user_id, user_fields?)
- get_user_by_username(username, user_fields?)
- create_post(text, reply_to_post_id?, quote_post_id?, media_ids?, poll_options?, poll_duration_minutes?)
- delete_post(post_id)
- get_post_by_id(post_id, tweet_fields?, expansions?)
- get_posts_by_ids(ids, tweet_fields?)
- search_recent_posts(query, max_results?, tweet_fields?)
- search_all_posts(query, max_results?, tweet_fields?)
- get_user_posts(user_id, max_results?, exclude_replies?, exclude_reposts?)
- get_home_timeline(max_results?)
- get_mentions(user_id, max_results?)
- like_post(user_id, post_id)
- unlike_post(user_id, post_id)
- repost(user_id, post_id)
- undo_repost(user_id, post_id)
- bookmark_post(user_id, post_id)
- remove_bookmark(user_id, post_id)
- follow_user(source_user_id, target_user_id)
- unfollow_user(source_user_id, target_user_id)
- block_user(source_user_id, target_user_id)
- unblock_user(source_user_id, target_user_id)
- mute_user(source_user_id, target_user_id)
- unmute_user(source_user_id, target_user_id)
- get_followers(user_id, max_results?)
- get_following(user_id, max_results?)
- create_list(name, description?, private?)
- update_list(list_id, name?, description?, private?)
- delete_list(list_id)
- add_list_member(list_id, user_id)
- remove_list_member(list_id, user_id)
- follow_list(list_id, user_id)
- unfollow_list(list_id, user_id)
- get_space(space_id, space_fields?)
- search_spaces(query, state?)
- get_stream_rules()
- add_stream_rules(rules)
- delete_stream_rules(rule_ids)
- connect_filtered_stream(tweet_fields?, expansions?)
- connect_sampled_stream(tweet_fields?, expansions?)
- create_compliance_job(job_type, name, resumable?)
- list_compliance_jobs(job_type)
- get_compliance_job(job_id)
- create_dm(participant_id, text)
- create_group_dm(participant_ids, text)

If user asks to upload media, use operation upload_media_simple with:
- media_path (local file path)
- media_type (like image/jpeg)
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


def _as_bool(value: Any, default: bool = False) -> bool:
	if isinstance(value, bool):
		return value
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes", "y", "on"}
	if isinstance(value, (int, float)):
		return bool(value)
	return default


def _as_int(value: Any, default: int) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		return default


def _as_str_list(value: Any) -> list[str]:
	if isinstance(value, list):
		return [str(v) for v in value]
	if isinstance(value, str):
		items = [chunk.strip() for chunk in value.split(",")]
		return [item for item in items if item]
	return []


def _execute_x_operation(operation: str, args: dict[str, Any]) -> dict[str, Any]:
	client = get_client()

	if operation == "get_me":
		return client.get_me(user_fields=args.get("user_fields"))
	if operation == "get_user_by_id":
		return client.get_user_by_id(
			str(args.get("user_id", "")),
			user_fields=args.get("user_fields"),
		)
	if operation == "get_user_by_username":
		return client.get_user_by_username(
			str(args.get("username", "")),
			user_fields=args.get("user_fields"),
		)
	if operation == "create_post":
		return client.create_post(
			text=str(args.get("text", "")),
			reply_to_post_id=args.get("reply_to_post_id"),
			quote_post_id=args.get("quote_post_id"),
			media_ids=_as_str_list(args.get("media_ids")) or None,
			poll_options=_as_str_list(args.get("poll_options")) or None,
			poll_duration_minutes=_as_int(args.get("poll_duration_minutes"), 0) or None,
		)
	if operation == "delete_post":
		return client.delete_post(str(args.get("post_id", "")))
	if operation == "get_post_by_id":
		return client.get_post_by_id(
			str(args.get("post_id", "")),
			tweet_fields=args.get("tweet_fields"),
			expansions=args.get("expansions"),
		)
	if operation == "get_posts_by_ids":
		return client.get_posts_by_ids(
			ids=_as_str_list(args.get("ids")),
			tweet_fields=args.get("tweet_fields"),
		)
	if operation == "search_recent_posts":
		return client.search_recent_posts(
			query=str(args.get("query", "")),
			max_results=_as_int(args.get("max_results"), 10),
			tweet_fields=args.get("tweet_fields"),
		)
	if operation == "search_all_posts":
		return client.search_all_posts(
			query=str(args.get("query", "")),
			max_results=_as_int(args.get("max_results"), 10),
			tweet_fields=args.get("tweet_fields"),
		)
	if operation == "get_user_posts":
		return client.get_user_posts(
			user_id=str(args.get("user_id", "")),
			max_results=_as_int(args.get("max_results"), 10),
			exclude_replies=_as_bool(args.get("exclude_replies"), False),
			exclude_reposts=_as_bool(args.get("exclude_reposts"), False),
		)
	if operation == "get_home_timeline":
		return client.get_home_timeline(max_results=_as_int(args.get("max_results"), 10))
	if operation == "get_mentions":
		return client.get_mentions(
			user_id=str(args.get("user_id", "")),
			max_results=_as_int(args.get("max_results"), 10),
		)
	if operation == "like_post":
		return client.like_post(str(args.get("user_id", "")), str(args.get("post_id", "")))
	if operation == "unlike_post":
		return client.unlike_post(
			str(args.get("user_id", "")),
			str(args.get("post_id", "")),
		)
	if operation == "repost":
		return client.repost(str(args.get("user_id", "")), str(args.get("post_id", "")))
	if operation == "undo_repost":
		return client.undo_repost(
			str(args.get("user_id", "")),
			str(args.get("post_id", "")),
		)
	if operation == "bookmark_post":
		return client.bookmark_post(
			str(args.get("user_id", "")),
			str(args.get("post_id", "")),
		)
	if operation == "remove_bookmark":
		return client.remove_bookmark(
			str(args.get("user_id", "")),
			str(args.get("post_id", "")),
		)
	if operation == "follow_user":
		return client.follow_user(
			str(args.get("source_user_id", "")),
			str(args.get("target_user_id", "")),
		)
	if operation == "unfollow_user":
		return client.unfollow_user(
			str(args.get("source_user_id", "")),
			str(args.get("target_user_id", "")),
		)
	if operation == "block_user":
		return client.block_user(
			str(args.get("source_user_id", "")),
			str(args.get("target_user_id", "")),
		)
	if operation == "unblock_user":
		return client.unblock_user(
			str(args.get("source_user_id", "")),
			str(args.get("target_user_id", "")),
		)
	if operation == "mute_user":
		return client.mute_user(
			str(args.get("source_user_id", "")),
			str(args.get("target_user_id", "")),
		)
	if operation == "unmute_user":
		return client.unmute_user(
			str(args.get("source_user_id", "")),
			str(args.get("target_user_id", "")),
		)
	if operation == "get_followers":
		return client.get_followers(
			str(args.get("user_id", "")),
			max_results=_as_int(args.get("max_results"), 50),
		)
	if operation == "get_following":
		return client.get_following(
			str(args.get("user_id", "")),
			max_results=_as_int(args.get("max_results"), 50),
		)
	if operation == "create_list":
		return client.create_list(
			name=str(args.get("name", "")),
			description=args.get("description"),
			private=_as_bool(args.get("private"), False),
		)
	if operation == "update_list":
		return client.update_list(
			list_id=str(args.get("list_id", "")),
			name=args.get("name"),
			description=args.get("description"),
			private=(None if "private" not in args else _as_bool(args.get("private"))),
		)
	if operation == "delete_list":
		return client.delete_list(str(args.get("list_id", "")))
	if operation == "add_list_member":
		return client.add_list_member(
			str(args.get("list_id", "")),
			str(args.get("user_id", "")),
		)
	if operation == "remove_list_member":
		return client.remove_list_member(
			str(args.get("list_id", "")),
			str(args.get("user_id", "")),
		)
	if operation == "follow_list":
		return client.follow_list(
			str(args.get("list_id", "")),
			str(args.get("user_id", "")),
		)
	if operation == "unfollow_list":
		return client.unfollow_list(
			str(args.get("list_id", "")),
			str(args.get("user_id", "")),
		)
	if operation == "get_space":
		return client.get_space(
			str(args.get("space_id", "")),
			space_fields=args.get("space_fields"),
		)
	if operation == "search_spaces":
		return client.search_spaces(
			query=str(args.get("query", "")),
			state=str(args.get("state", "all")),
		)
	if operation == "get_stream_rules":
		return client.get_stream_rules()
	if operation == "add_stream_rules":
		rules = args.get("rules")
		if not isinstance(rules, list):
			rules = []
		return client.add_stream_rules(rules)
	if operation == "delete_stream_rules":
		return client.delete_stream_rules(_as_str_list(args.get("rule_ids")))
	if operation == "connect_filtered_stream":
		return client.connect_filtered_stream(
			tweet_fields=args.get("tweet_fields"),
			expansions=args.get("expansions"),
		)
	if operation == "connect_sampled_stream":
		return client.connect_sampled_stream(
			tweet_fields=args.get("tweet_fields"),
			expansions=args.get("expansions"),
		)
	if operation == "create_compliance_job":
		return client.create_compliance_job(
			job_type=str(args.get("job_type", "")),
			name=str(args.get("name", "")),
			resumable=_as_bool(args.get("resumable"), False),
		)
	if operation == "list_compliance_jobs":
		return client.list_compliance_jobs(str(args.get("job_type", "")))
	if operation == "get_compliance_job":
		return client.get_compliance_job(str(args.get("job_id", "")))
	if operation == "create_dm":
		return client.create_dm(
			participant_id=str(args.get("participant_id", "")),
			text=str(args.get("text", "")),
		)
	if operation == "create_group_dm":
		return client.create_group_dm(
			participant_ids=_as_str_list(args.get("participant_ids")),
			text=str(args.get("text", "")),
		)
	if operation == "upload_media_simple":
		media_path = str(args.get("media_path", "")).strip()
		if not media_path:
			raise ValueError("upload_media_simple requires media_path")
		with open(media_path, "rb") as media_file:
			media_bytes = media_file.read()
		return client.upload_media_simple(
			media_bytes=media_bytes,
			media_type=str(args.get("media_type", "application/octet-stream")),
		)

	raise ValueError(f"Unknown x_api operation: {operation}")


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
	if tool_name == "x_api":
		op = str(arguments.get("operation", "")).strip()
		x_args = arguments.get("arguments", {})
		if not isinstance(x_args, dict):
			x_args = {}
		result = _execute_x_operation(op, x_args)
		return json.dumps(result, ensure_ascii=True)
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