from __future__ import annotations
import ipaddress
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CARD_REGEX = re.compile(r"^\d{12,19}$")
SHA_REGEX = re.compile(r"^[a-f0-9]{32,64}$", re.IGNORECASE)
DOMAIN_REGEX = re.compile(
    r"^(?=.{4,253}$)([A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,63}$"
)


@dataclass(slots=True, frozen=True)
class CheckerResult:
    status: str
    summary: str
    details: Dict[str, Any]

    def to_message(self) -> str:
        lines = [f"Status: {self.status}", f"Summary: {self.summary}"]
        for key, value in self.details.items():
            lines.append(f"{key}: {value}")
        return "\n".join(lines)


class CheckerService:
    def __init__(self, timeout: float = 12.0) -> None:
        self._timeout = timeout

    async def analyze(self, query: str) -> CheckerResult:
        query = query.strip()
        if not query:
            return CheckerResult(
                status="error",
                summary="No query provided.",
                details={"hint": "Send a URL, IP, email, or hash to analyze."},
            )

        if self._looks_like_url(query):
            return await self._check_url(query)

        if self._looks_like_ip(query):
            return CheckerResult(
                status="ok",
                summary="IP address detected.",
                details=self._describe_ip(query),
            )

        if EMAIL_REGEX.match(query):
            return CheckerResult(
                status="ok",
                summary="Email address detected.",
                details={"domain": query.split("@", 1)[1]},
            )

        if CARD_REGEX.match(query):
            return CheckerResult(
                status="warning",
                summary="Card-like number detected.",
                details={"length": len(query)},
            )

        if SHA_REGEX.match(query):
            return CheckerResult(
                status="ok",
                summary="Hash-like string detected.",
                details={"length": len(query)},
            )

        return CheckerResult(
            status="info",
            summary="Generic text processed.",
            details={"characters": len(query)},
        )

    def _looks_like_url(self, query: str) -> bool:
        return query.startswith(("http://", "https://")) or DOMAIN_REGEX.match(
            query.lower()
        )

    def _looks_like_ip(self, query: str) -> bool:
        try:
            ipaddress.ip_address(query)
        except ValueError:
            return False
        return True

    def _describe_ip(self, query: str) -> Dict[str, Any]:
        try:
            ip_obj = ipaddress.ip_address(query)
            return {
                "version": f"IPv{ip_obj.version}",
                "is_private": ip_obj.is_private,
                "is_loopback": ip_obj.is_loopback,
                "is_reserved": ip_obj.is_reserved,
            }
        except ValueError:
            return {"error": "Invalid IP address format."}

    async def _check_url(self, query: str) -> CheckerResult:
        url = query if query.startswith(("http://", "https://")) else f"https://{query}"
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                return CheckerResult(
                    status="error",
                    summary="Failed to fetch the URL.",
                    details={"reason": str(exc)},
                )

        return CheckerResult(
            status="ok" if response.status_code < 500 else "warning",
            summary=f"Received {response.status_code} from {response.url.host}.",
            details={
                "status_code": response.status_code,
                "final_url": str(response.url),
                "content_type": response.headers.get("content-type", "unknown"),
                "content_length": response.headers.get("content-length", "unknown"),
            },
        )
