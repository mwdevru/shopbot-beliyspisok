import logging
import aiohttp
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

API_BASE_URL = "https://vpn.mwshark.host/api/v1"


class MWSharkAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }

    async def _request(self, method: str, endpoint: str, data: dict = None) -> Dict[str, Any]:
        url = f"{API_BASE_URL}{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                if method == "GET":
                    async with session.get(url, headers=self.headers, params=data) as response:
                        result = await response.json()
                        if response.status != 200:
                            logger.error(f"API Error: {response.status} - {result}")
                        return result
                elif method == "POST":
                    async with session.post(url, headers=self.headers, json=data) as response:
                        result = await response.json()
                        if response.status != 200:
                            logger.error(f"API Error: {response.status} - {result}")
                        return result
        except Exception as e:
            logger.error(f"MWShark API request failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def get_balance(self) -> Dict[str, Any]:
        return await self._request("GET", "/balance")

    async def get_tariffs(self) -> Dict[str, Any]:
        return await self._request("GET", "/tariffs")

    async def calculate_price(self, days: int) -> Dict[str, Any]:
        return await self._request("GET", f"/calculate?days={days}")

    async def create_subscription(self, user_id: int, days: int = 30, devices: int = 1, name: str = None) -> Dict[str, Any]:
        data = {"user_id": user_id, "days": days, "devices": devices}
        if name:
            data["name"] = name
        return await self._request("POST", "/subscription/create", data)

    async def extend_subscription(self, user_id: int, days: int, devices: int = None) -> Dict[str, Any]:
        data = {"user_id": user_id, "days": days}
        if devices:
            data["devices"] = devices
        return await self._request("POST", "/subscription/extend", data)

    async def revoke_subscription(self, user_id: int) -> Dict[str, Any]:
        data = {"user_id": user_id}
        return await self._request("POST", "/subscription/revoke", data)

    async def change_devices(self, uuid: str, devices: int) -> Dict[str, Any]:
        data = {"uuid": uuid, "devices": devices}
        return await self._request("POST", "/subscription/devices", data)

    async def get_grants(self, user_id: int = None) -> Dict[str, Any]:
        endpoint = f"/grants?user_id={user_id}" if user_id else "/grants"
        return await self._request("GET", endpoint)

    async def get_subscription_status(self, user_id: int) -> Dict[str, Any]:
        return await self._request("GET", f"/subscription/{user_id}")

    async def get_history(self) -> Dict[str, Any]:
        return await self._request("GET", "/history")


_api_instance: Optional[MWSharkAPI] = None


def get_api(api_key: str = None) -> Optional[MWSharkAPI]:
    global _api_instance
    if api_key:
        _api_instance = MWSharkAPI(api_key)
    return _api_instance


async def create_subscription_for_user(api_key: str, user_id: int, days: int, name: str = None, devices: int = 1) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    data = {"user_id": user_id, "days": days, "devices": devices}
    if name:
        data["name"] = name
    return await api._request("POST", "/subscription/create", data)


async def extend_subscription_for_user(api_key: str, user_id: int, days: int, devices: int = None) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    data = {"user_id": user_id, "days": days}
    if devices:
        data["devices"] = devices
    return await api._request("POST", "/subscription/extend", data)


async def revoke_subscription_for_user(api_key: str, user_id: int) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    data = {"user_id": user_id}
    return await api._request("POST", "/subscription/revoke", data)


async def change_subscription_devices(api_key: str, uuid: str, devices: int) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    data = {"uuid": uuid, "devices": devices}
    return await api._request("POST", "/subscription/devices", data)


async def get_user_grants(api_key: str, user_id: int = None) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    return await api.get_grants(user_id)


async def get_user_subscription(api_key: str, user_id: int) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    return await api._request("GET", f"/subscription/{user_id}")


async def get_api_balance(api_key: str) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    return await api.get_balance()


async def get_api_tariffs(api_key: str) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    return await api.get_tariffs()


async def calculate_api_price(api_key: str, days: int) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    return await api.calculate_price(days)


async def get_api_history(api_key: str) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    return await api.get_history()
