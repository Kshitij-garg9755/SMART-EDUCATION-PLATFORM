import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener


class GatewayApiError(Exception):
    def __init__(self, status_code=None, code="gateway_unavailable"):
        super().__init__(code)
        self.status_code = status_code
        self.code = code


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


class UpiGatewayClient:
    def __init__(self, base_url, api_key, api_secret, timeout=10):
        self.base_url = str(base_url or "").rstrip("/")
        self.api_key = str(api_key or "")
        self.api_secret = str(api_secret or "")
        self.timeout = max(1, min(int(timeout), 30))
        parsed = urlsplit(self.base_url)
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise GatewayApiError(code="gateway_configuration")

    def create_order(self, payload):
        return self._request("POST", "/api/v1/orders", payload)

    def get_order(self, order_or_client_id):
        identifier = quote(str(order_or_client_id), safe="")
        return self._request("GET", "/api/v1/orders/" + identifier)

    def _request(self, method, path, payload=None):
        if not self.api_key or not self.api_secret:
            raise GatewayApiError(code="gateway_not_configured")

        body = None
        headers = {
            "Accept": "application/json",
            "X-Api-Key": self.api_key,
            "X-Api-Secret": self.api_secret,
        }
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path, data=body, headers=headers, method=method)
        opener = build_opener(
            _NoRedirectHandler,
            HTTPSHandler(context=ssl.create_default_context()),
        )

        try:
            with opener.open(request, timeout=self.timeout) as response:
                status_code = response.status
                response_body = response.read(65537)
        except HTTPError as error:
            status_code = error.code
            response_body = error.read(65537)
        except (URLError, TimeoutError, OSError):
            raise GatewayApiError(code="gateway_unavailable") from None

        if len(response_body) > 65536:
            raise GatewayApiError(status_code=status_code, code="gateway_response_too_large")
        try:
            response_data = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GatewayApiError(status_code=status_code, code="gateway_invalid_response") from None

        if status_code not in {200, 201}:
            raise GatewayApiError(status_code=status_code, code="gateway_request_rejected")
        if not isinstance(response_data, dict) or response_data.get("success") is not True:
            raise GatewayApiError(status_code=status_code, code="gateway_invalid_response")
        data = response_data.get("data")
        if not isinstance(data, dict):
            raise GatewayApiError(status_code=status_code, code="gateway_invalid_response")
        return data
