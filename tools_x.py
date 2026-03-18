"""Tools for calling X API operations on an account.

This module provides a lightweight client and grouped helper functions for
major X API operation kinds exposed in the public API docs:
- Users
- Posts
- Engagement (likes, reposts, bookmarks)
- Relationships (follow, block, mute)
- Timelines and search
- Lists
- Spaces
- Direct Messages
- Media upload

Auth sources (from environment variables):
- App/Bearer token: X_BEARER_TOKEN
- User context (OAuth 1.0a):
  - X_API_KEY
  - X_API_SECRET
  - X_ACCESS_TOKEN
  - X_ACCESS_TOKEN_SECRET

Notes:
- Many write endpoints require user-context auth (OAuth 1.0a).
- For some endpoints, elevated access may be required by X.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
import base64
import hmac
import json
import os
import secrets
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen


API_BASE_V2 = "https://api.x.com/2"
UPLOAD_BASE_V1 = "https://upload.twitter.com/1.1"


def _pct_encode(value: str) -> str:
	return quote(value, safe="~-._")


def _utc_ts() -> str:
	return str(int(datetime.now(timezone.utc).timestamp()))


@dataclass
class XCredentials:
	bearer_token: str = ""
	api_key: str = ""
	api_secret: str = ""
	access_token: str = ""
	access_token_secret: str = ""

	@classmethod
	def from_env(cls) -> "XCredentials":
		return cls(
			bearer_token=os.getenv("X_BEARER_TOKEN", "").strip(),
			api_key=os.getenv("X_API_KEY", "").strip(),
			api_secret=os.getenv("X_API_SECRET", "").strip(),
			access_token=os.getenv("X_ACCESS_TOKEN", "").strip(),
			access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET", "").strip(),
		)

	def has_bearer(self) -> bool:
		return bool(self.bearer_token)

	def has_oauth1(self) -> bool:
		return all(
			[self.api_key, self.api_secret, self.access_token, self.access_token_secret]
		)


class XApiClient:
	"""Simple X API client supporting bearer and OAuth 1.0a user-context auth."""

	def __init__(
		self,
		credentials: XCredentials | None = None,
		api_base_v2: str = API_BASE_V2,
		upload_base_v1: str = UPLOAD_BASE_V1,
	) -> None:
		self.creds = credentials or XCredentials.from_env()
		self.api_base_v2 = api_base_v2.rstrip("/")
		self.upload_base_v1 = upload_base_v1.rstrip("/")

	def _oauth1_auth_header(
		self,
		method: str,
		url: str,
		params: dict[str, Any] | None,
		body_form: dict[str, Any] | None,
	) -> str:
		if not self.creds.has_oauth1():
			raise RuntimeError(
				"OAuth 1.0a credentials are missing. Set X_API_KEY, X_API_SECRET, "
				"X_ACCESS_TOKEN, and X_ACCESS_TOKEN_SECRET."
			)

		oauth_params: dict[str, str] = {
			"oauth_consumer_key": self.creds.api_key,
			"oauth_nonce": secrets.token_hex(16),
			"oauth_signature_method": "HMAC-SHA1",
			"oauth_timestamp": _utc_ts(),
			"oauth_token": self.creds.access_token,
			"oauth_version": "1.0",
		}

		base_pairs: list[tuple[str, str]] = []

		for k, v in (params or {}).items():
			if v is None:
				continue
			if isinstance(v, list):
				for item in v:
					base_pairs.append((_pct_encode(str(k)), _pct_encode(str(item))))
			else:
				base_pairs.append((_pct_encode(str(k)), _pct_encode(str(v))))

		for k, v in (body_form or {}).items():
			if v is None:
				continue
			if isinstance(v, list):
				for item in v:
					base_pairs.append((_pct_encode(str(k)), _pct_encode(str(item))))
			else:
				base_pairs.append((_pct_encode(str(k)), _pct_encode(str(v))))

		for k, v in oauth_params.items():
			base_pairs.append((_pct_encode(k), _pct_encode(v)))

		base_pairs.sort()
		normalized = "&".join([f"{k}={v}" for k, v in base_pairs])

		parsed = urlparse(url)
		base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
		signature_base = "&".join(
			[
				_pct_encode(method.upper()),
				_pct_encode(base_url),
				_pct_encode(normalized),
			]
		)
		signing_key = "&".join(
			[_pct_encode(self.creds.api_secret), _pct_encode(self.creds.access_token_secret)]
		)

		digest = hmac.new(
			signing_key.encode("utf-8"),
			signature_base.encode("utf-8"),
			sha1,
		).digest()
		oauth_params["oauth_signature"] = base64.b64encode(digest).decode("utf-8")

		header_items = [
			f'{_pct_encode(k)}="{_pct_encode(v)}"'
			for k, v in sorted(oauth_params.items())
		]
		return "OAuth " + ", ".join(header_items)

	def request(
		self,
		method: str,
		path: str,
		*,
		params: dict[str, Any] | None = None,
		json_body: dict[str, Any] | None = None,
		form_body: dict[str, Any] | None = None,
		use_upload_api: bool = False,
		auth_mode: str = "auto",
		timeout: int = 25,
	) -> dict[str, Any]:
		"""Send an API request.

		auth_mode:
		- auto: use OAuth1 for write methods if available, else bearer
		- bearer: force bearer token
		- oauth1: force OAuth 1.0a user-context
		"""
		method = method.upper()
		base = self.upload_base_v1 if use_upload_api else self.api_base_v2
		if not path.startswith("/"):
			path = "/" + path
		url = base + path

		headers: dict[str, str] = {
			"Accept": "application/json",
			"User-Agent": "x-api-tools/1.0",
		}

		data: bytes | None = None
		body_form: dict[str, Any] | None = None

		if json_body is not None:
			data = json.dumps(json_body).encode("utf-8")
			headers["Content-Type"] = "application/json"
		elif form_body is not None:
			body_form = form_body
			encoded = urlencode(form_body, doseq=True)
			data = encoded.encode("utf-8")
			headers["Content-Type"] = "application/x-www-form-urlencoded"

		if params:
			url = f"{url}?{urlencode(params, doseq=True)}"

		mode = auth_mode
		if mode == "auto":
			if method in {"POST", "PUT", "PATCH", "DELETE"} and self.creds.has_oauth1():
				mode = "oauth1"
			else:
				mode = "bearer"

		if mode == "oauth1":
			headers["Authorization"] = self._oauth1_auth_header(
				method=method,
				url=url,
				params=params,
				body_form=body_form,
			)
		elif mode == "bearer":
			if not self.creds.has_bearer():
				raise RuntimeError("X_BEARER_TOKEN is not set.")
			headers["Authorization"] = f"Bearer {self.creds.bearer_token}"
		else:
			raise ValueError(f"Unsupported auth_mode: {auth_mode}")

		req = Request(url=url, data=data, headers=headers, method=method)
		with urlopen(req, timeout=timeout) as response:  # nosec B310
			raw = response.read().decode("utf-8", errors="replace")
			if not raw.strip():
				return {"status": response.status, "data": None}
			return json.loads(raw)

	# Users operations
	def get_me(self, user_fields: str | None = None) -> dict[str, Any]:
		params = {"user.fields": user_fields} if user_fields else None
		return self.request("GET", "/users/me", params=params, auth_mode="oauth1")

	def get_user_by_id(self, user_id: str, user_fields: str | None = None) -> dict[str, Any]:
		params = {"user.fields": user_fields} if user_fields else None
		return self.request("GET", f"/users/{user_id}", params=params)

	def get_user_by_username(
		self,
		username: str,
		user_fields: str | None = None,
	) -> dict[str, Any]:
		params = {"user.fields": user_fields} if user_fields else None
		return self.request("GET", f"/users/by/username/{username}", params=params)

	# Posts operations
	def create_post(
		self,
		text: str,
		*,
		reply_to_post_id: str | None = None,
		quote_post_id: str | None = None,
		media_ids: list[str] | None = None,
		poll_options: list[str] | None = None,
		poll_duration_minutes: int | None = None,
	) -> dict[str, Any]:
		body: dict[str, Any] = {"text": text}
		if reply_to_post_id:
			body["reply"] = {"in_reply_to_tweet_id": reply_to_post_id}
		if quote_post_id:
			body["quote_tweet_id"] = quote_post_id
		if media_ids:
			body["media"] = {"media_ids": media_ids}
		if poll_options and poll_duration_minutes:
			body["poll"] = {
				"options": poll_options,
				"duration_minutes": poll_duration_minutes,
			}
		return self.request("POST", "/tweets", json_body=body, auth_mode="oauth1")

	def delete_post(self, post_id: str) -> dict[str, Any]:
		return self.request("DELETE", f"/tweets/{post_id}", auth_mode="oauth1")

	def get_post_by_id(
		self,
		post_id: str,
		tweet_fields: str | None = None,
		expansions: str | None = None,
	) -> dict[str, Any]:
		params: dict[str, Any] = {}
		if tweet_fields:
			params["tweet.fields"] = tweet_fields
		if expansions:
			params["expansions"] = expansions
		return self.request("GET", f"/tweets/{post_id}", params=params or None)

	def search_recent_posts(
		self,
		query: str,
		*,
		max_results: int = 10,
		tweet_fields: str | None = None,
	) -> dict[str, Any]:
		params: dict[str, Any] = {"query": query, "max_results": max_results}
		if tweet_fields:
			params["tweet.fields"] = tweet_fields
		return self.request("GET", "/tweets/search/recent", params=params)

	def search_all_posts(
		self,
		query: str,
		*,
		max_results: int = 10,
		tweet_fields: str | None = None,
	) -> dict[str, Any]:
		params: dict[str, Any] = {"query": query, "max_results": max_results}
		if tweet_fields:
			params["tweet.fields"] = tweet_fields
		return self.request("GET", "/tweets/search/all", params=params)

	def get_user_posts(
		self,
		user_id: str,
		*,
		max_results: int = 10,
		exclude_replies: bool = False,
		exclude_reposts: bool = False,
	) -> dict[str, Any]:
		params: dict[str, Any] = {"max_results": max_results}
		exclude_values: list[str] = []
		if exclude_replies:
			exclude_values.append("replies")
		if exclude_reposts:
			exclude_values.append("retweets")
		if exclude_values:
			params["exclude"] = exclude_values
		return self.request("GET", f"/users/{user_id}/tweets", params=params)

	def get_posts_by_ids(
		self,
		ids: list[str],
		*,
		tweet_fields: str | None = None,
	) -> dict[str, Any]:
		params: dict[str, Any] = {"ids": ",".join(ids)}
		if tweet_fields:
			params["tweet.fields"] = tweet_fields
		return self.request("GET", "/tweets", params=params)

	# Streaming operations
	def get_stream_rules(self) -> dict[str, Any]:
		return self.request("GET", "/tweets/search/stream/rules")

	def add_stream_rules(self, rules: list[dict[str, str]]) -> dict[str, Any]:
		return self.request(
			"POST",
			"/tweets/search/stream/rules",
			json_body={"add": rules},
			auth_mode="oauth1",
		)

	def delete_stream_rules(self, rule_ids: list[str]) -> dict[str, Any]:
		return self.request(
			"POST",
			"/tweets/search/stream/rules",
			json_body={"delete": {"ids": rule_ids}},
			auth_mode="oauth1",
		)

	def connect_filtered_stream(
		self,
		*,
		tweet_fields: str | None = None,
		expansions: str | None = None,
	) -> dict[str, Any]:
		params: dict[str, Any] = {}
		if tweet_fields:
			params["tweet.fields"] = tweet_fields
		if expansions:
			params["expansions"] = expansions
		return self.request("GET", "/tweets/search/stream", params=params or None, timeout=90)

	def connect_sampled_stream(
		self,
		*,
		tweet_fields: str | None = None,
		expansions: str | None = None,
	) -> dict[str, Any]:
		params: dict[str, Any] = {}
		if tweet_fields:
			params["tweet.fields"] = tweet_fields
		if expansions:
			params["expansions"] = expansions
		return self.request("GET", "/tweets/sample/stream", params=params or None, timeout=90)

	# Compliance operations
	def create_compliance_job(
		self,
		*,
		job_type: str,
		name: str,
		resumable: bool = False,
	) -> dict[str, Any]:
		body = {
			"type": job_type,
			"name": name,
			"resumable": resumable,
		}
		return self.request("POST", "/compliance/jobs", json_body=body, auth_mode="oauth1")

	def list_compliance_jobs(self, job_type: str) -> dict[str, Any]:
		return self.request("GET", "/compliance/jobs", params={"type": job_type})

	def get_compliance_job(self, job_id: str) -> dict[str, Any]:
		return self.request("GET", f"/compliance/jobs/{job_id}")

	# Timelines and mentions
	def get_home_timeline(self, *, max_results: int = 10) -> dict[str, Any]:
		return self.request(
			"GET",
			"/users/me/timelines/reverse_chronological",
			params={"max_results": max_results},
			auth_mode="oauth1",
		)

	def get_mentions(self, user_id: str, *, max_results: int = 10) -> dict[str, Any]:
		return self.request(
			"GET",
			f"/users/{user_id}/mentions",
			params={"max_results": max_results},
			auth_mode="oauth1",
		)

	# Engagement operations
	def like_post(self, user_id: str, post_id: str) -> dict[str, Any]:
		return self.request(
			"POST",
			f"/users/{user_id}/likes",
			json_body={"tweet_id": post_id},
			auth_mode="oauth1",
		)

	def unlike_post(self, user_id: str, post_id: str) -> dict[str, Any]:
		return self.request("DELETE", f"/users/{user_id}/likes/{post_id}", auth_mode="oauth1")

	def repost(self, user_id: str, post_id: str) -> dict[str, Any]:
		return self.request(
			"POST",
			f"/users/{user_id}/retweets",
			json_body={"tweet_id": post_id},
			auth_mode="oauth1",
		)

	def undo_repost(self, user_id: str, post_id: str) -> dict[str, Any]:
		return self.request(
			"DELETE",
			f"/users/{user_id}/retweets/{post_id}",
			auth_mode="oauth1",
		)

	def bookmark_post(self, user_id: str, post_id: str) -> dict[str, Any]:
		return self.request(
			"POST",
			f"/users/{user_id}/bookmarks",
			json_body={"tweet_id": post_id},
			auth_mode="oauth1",
		)

	def remove_bookmark(self, user_id: str, post_id: str) -> dict[str, Any]:
		return self.request(
			"DELETE",
			f"/users/{user_id}/bookmarks/{post_id}",
			auth_mode="oauth1",
		)

	# Relationship operations
	def follow_user(self, source_user_id: str, target_user_id: str) -> dict[str, Any]:
		return self.request(
			"POST",
			f"/users/{source_user_id}/following",
			json_body={"target_user_id": target_user_id},
			auth_mode="oauth1",
		)

	def unfollow_user(self, source_user_id: str, target_user_id: str) -> dict[str, Any]:
		return self.request(
			"DELETE",
			f"/users/{source_user_id}/following/{target_user_id}",
			auth_mode="oauth1",
		)

	def block_user(self, source_user_id: str, target_user_id: str) -> dict[str, Any]:
		return self.request(
			"POST",
			f"/users/{source_user_id}/blocking",
			json_body={"target_user_id": target_user_id},
			auth_mode="oauth1",
		)

	def unblock_user(self, source_user_id: str, target_user_id: str) -> dict[str, Any]:
		return self.request(
			"DELETE",
			f"/users/{source_user_id}/blocking/{target_user_id}",
			auth_mode="oauth1",
		)

	def mute_user(self, source_user_id: str, target_user_id: str) -> dict[str, Any]:
		return self.request(
			"POST",
			f"/users/{source_user_id}/muting",
			json_body={"target_user_id": target_user_id},
			auth_mode="oauth1",
		)

	def unmute_user(self, source_user_id: str, target_user_id: str) -> dict[str, Any]:
		return self.request(
			"DELETE",
			f"/users/{source_user_id}/muting/{target_user_id}",
			auth_mode="oauth1",
		)

	def get_followers(self, user_id: str, *, max_results: int = 50) -> dict[str, Any]:
		return self.request(
			"GET",
			f"/users/{user_id}/followers",
			params={"max_results": max_results},
		)

	def get_following(self, user_id: str, *, max_results: int = 50) -> dict[str, Any]:
		return self.request(
			"GET",
			f"/users/{user_id}/following",
			params={"max_results": max_results},
		)

	# Lists operations
	def create_list(
		self,
		name: str,
		*,
		description: str | None = None,
		private: bool = False,
	) -> dict[str, Any]:
		body: dict[str, Any] = {
			"name": name,
			"private": private,
		}
		if description:
			body["description"] = description
		return self.request("POST", "/lists", json_body=body, auth_mode="oauth1")

	def update_list(
		self,
		list_id: str,
		*,
		name: str | None = None,
		description: str | None = None,
		private: bool | None = None,
	) -> dict[str, Any]:
		body: dict[str, Any] = {}
		if name is not None:
			body["name"] = name
		if description is not None:
			body["description"] = description
		if private is not None:
			body["private"] = private
		return self.request("PUT", f"/lists/{list_id}", json_body=body, auth_mode="oauth1")

	def delete_list(self, list_id: str) -> dict[str, Any]:
		return self.request("DELETE", f"/lists/{list_id}", auth_mode="oauth1")

	def add_list_member(self, list_id: str, user_id: str) -> dict[str, Any]:
		return self.request(
			"POST",
			f"/lists/{list_id}/members",
			json_body={"user_id": user_id},
			auth_mode="oauth1",
		)

	def remove_list_member(self, list_id: str, user_id: str) -> dict[str, Any]:
		return self.request("DELETE", f"/lists/{list_id}/members/{user_id}", auth_mode="oauth1")

	def follow_list(self, list_id: str, user_id: str) -> dict[str, Any]:
		return self.request(
			"POST",
			f"/users/{user_id}/followed_lists",
			json_body={"list_id": list_id},
			auth_mode="oauth1",
		)

	def unfollow_list(self, list_id: str, user_id: str) -> dict[str, Any]:
		return self.request(
			"DELETE",
			f"/users/{user_id}/followed_lists/{list_id}",
			auth_mode="oauth1",
		)

	# Spaces operations
	def get_space(self, space_id: str, *, space_fields: str | None = None) -> dict[str, Any]:
		params = {"space.fields": space_fields} if space_fields else None
		return self.request("GET", f"/spaces/{space_id}", params=params)

	def search_spaces(self, query: str, *, state: str = "all") -> dict[str, Any]:
		return self.request(
			"GET",
			"/spaces/search",
			params={"query": query, "state": state},
		)

	# Direct message operations
	def create_dm(self, participant_id: str, text: str) -> dict[str, Any]:
		body = {
			"conversation_type": "dm",
			"recipient_id": participant_id,
			"text": text,
		}
		return self.request(
			"POST",
			f"/dm_conversations/with/{participant_id}/messages",
			json_body=body,
			auth_mode="oauth1",
		)

	def create_group_dm(self, participant_ids: list[str], text: str) -> dict[str, Any]:
		body = {
			"conversation_type": "group",
			"participant_ids": participant_ids,
			"text": text,
		}
		return self.request("POST", "/dm_conversations", json_body=body, auth_mode="oauth1")

	# Media upload operations (v1.1 upload endpoint)
	def upload_media_simple(self, media_bytes: bytes, media_type: str) -> dict[str, Any]:
		b64_data = base64.b64encode(media_bytes).decode("ascii")
		form = {
			"media_data": b64_data,
			"media_category": "tweet_image",
		}
		if media_type:
			form["media_type"] = media_type
		return self.request(
			"POST",
			"/media/upload.json",
			form_body=form,
			use_upload_api=True,
			auth_mode="oauth1",
		)


def get_client() -> XApiClient:
	"""Create a client from environment credentials."""
	return XApiClient()


def supported_operation_kinds() -> dict[str, list[str]]:
	"""Return supported operation kinds and helper method names."""
	return {
		"users": [
			"get_me",
			"get_user_by_id",
			"get_user_by_username",
		],
		"posts": [
			"create_post",
			"delete_post",
			"get_post_by_id",
			"search_recent_posts",
			"search_all_posts",
			"get_user_posts",
			"get_posts_by_ids",
		],
		"timelines": [
			"get_home_timeline",
			"get_mentions",
		],
		"engagement": [
			"like_post",
			"unlike_post",
			"repost",
			"undo_repost",
			"bookmark_post",
			"remove_bookmark",
		],
		"relationships": [
			"follow_user",
			"unfollow_user",
			"block_user",
			"unblock_user",
			"mute_user",
			"unmute_user",
			"get_followers",
			"get_following",
		],
		"lists": [
			"create_list",
			"update_list",
			"delete_list",
			"add_list_member",
			"remove_list_member",
			"follow_list",
			"unfollow_list",
		],
		"spaces": [
			"get_space",
			"search_spaces",
		],
		"streaming": [
			"get_stream_rules",
			"add_stream_rules",
			"delete_stream_rules",
			"connect_filtered_stream",
			"connect_sampled_stream",
		],
		"compliance": [
			"create_compliance_job",
			"list_compliance_jobs",
			"get_compliance_job",
		],
		"direct_messages": [
			"create_dm",
			"create_group_dm",
		],
		"media_upload": [
			"upload_media_simple",
		],
	}


def x_get_me() -> dict[str, Any]:
	return get_client().get_me()


def x_get_user_by_id(user_id: str) -> dict[str, Any]:
	return get_client().get_user_by_id(user_id)


def x_get_user_by_username(username: str) -> dict[str, Any]:
	return get_client().get_user_by_username(username)


def x_create_post(text: str) -> dict[str, Any]:
	return get_client().create_post(text)


def x_delete_post(post_id: str) -> dict[str, Any]:
	return get_client().delete_post(post_id)


def x_search_recent_posts(query: str, max_results: int = 10) -> dict[str, Any]:
	return get_client().search_recent_posts(query, max_results=max_results)


def x_like_post(user_id: str, post_id: str) -> dict[str, Any]:
	return get_client().like_post(user_id, post_id)


def x_follow_user(source_user_id: str, target_user_id: str) -> dict[str, Any]:
	return get_client().follow_user(source_user_id, target_user_id)


if __name__ == "__main__":
	ops = supported_operation_kinds()
	print(json.dumps(ops, indent=2))
