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
        logger.info(f"API Request: {method} {endpoint} | Data: {data}")
        try:
            async with aiohttp.ClientSession() as session:
                if method == "GET":
                    async with session.get(url, headers=self.headers, params=data) as response:
                        result = await response.json()
                        if response.status != 200:
                            logger.error(f"API Error: {method} {endpoint} | Status: {response.status} | Response: {result}")
                        else:
                            logger.info(f"API Success: {method} {endpoint} | Response: {result}")
                        return result
                elif method == "POST":
                    async with session.post(url, headers=self.headers, json=data) as response:
                        result = await response.json()
                        if response.status != 200:
                            logger.error(f"API Error: {method} {endpoint} | Status: {response.status} | Response: {result}")
                        else:
                            logger.info(f"API Success: {method} {endpoint} | Response: {result}")
                        return result
                elif method == "PUT":
                    async with session.put(url, headers=self.headers, json=data) as response:
                        result = await response.json()
                        if response.status != 200:
                            logger.error(f"API Error: {method} {endpoint} | Status: {response.status} | Response: {result}")
                        else:
                            logger.info(f"API Success: {method} {endpoint} | Response: {result}")
                        return result
                elif method == "DELETE":
                    async with session.delete(url, headers=self.headers, json=data) as response:
                        result = await response.json()
                        if response.status != 200:
                            logger.error(f"API Error: {method} {endpoint} | Status: {response.status} | Response: {result}")
                        else:
                            logger.info(f"API Success: {method} {endpoint} | Response: {result}")
                        return result
        except Exception as e:
            logger.error(f"API Exception: {method} {endpoint} | Data: {data} | Error: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def get_balance(self) -> Dict[str, Any]:
        return await self._request("GET", "/balance")

    async def get_tariffs(self) -> Dict[str, Any]:
        return await self._request("GET", "/tariffs")

    async def calculate_price(self, days: int, devices: int = 1, extra_service: bool = False) -> Dict[str, Any]:
        params = {"days": days, "devices": devices}
        if extra_service:
            params["extra_service"] = "true"
        return await self._request("GET", "/calculate", params)

    async def create_subscription(self, days: int, devices: int = 1, extra_service: bool = False) -> Dict[str, Any]:
        data = {"days": days, "devices": devices}
        if extra_service:
            data["extra_service"] = True
        return await self._request("POST", "/subscription/create", data)

    async def extend_subscription(self, uuid: str, days: int, devices: int = None) -> Dict[str, Any]:
        data = {"uuid": uuid, "days": days}
        if devices:
            data["devices"] = devices
        return await self._request("POST", "/subscription/extend", data)

    async def get_subscription_status(self, uuid: str) -> Dict[str, Any]:
        return await self._request("GET", f"/subscription/{uuid}")

    async def update_subscription_metadata(self, uuid: str, name: str = None, description: str = None, website: str = None, telegram: str = None) -> Dict[str, Any]:
        data = {"uuid": uuid}
        if name:
            data["name"] = name
        if description:
            data["description"] = description
        if website:
            data["website"] = website
        if telegram:
            data["telegram"] = telegram
        return await self._request("POST", "/subscription/metadata", data)

    async def revoke_subscription(self, uuid: str) -> Dict[str, Any]:
        data = {"uuid": uuid}
        return await self._request("POST", "/subscription/revoke", data)

    async def change_devices(self, uuid: str, devices: int) -> Dict[str, Any]:
        data = {"uuid": uuid, "devices": devices}
        return await self._request("POST", "/subscription/devices", data)

    async def get_history(self) -> Dict[str, Any]:
        return await self._request("GET", "/history")


_api_instance: Optional[MWSharkAPI] = None


def get_api(api_key: str = None) -> Optional[MWSharkAPI]:
    global _api_instance
    if api_key:
        _api_instance = MWSharkAPI(api_key)
    return _api_instance


async def create_subscription_for_user(api_key: str, user_id: int, days: int, devices: int = 1, extra_service: bool = False) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    data = {"days": days, "devices": devices}
    if extra_service:
        data["extra_service"] = True
    return await api._request("POST", "/subscription/create", data)


async def extend_subscription_for_user(api_key: str, uuid: str, days: int, devices: int = None) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    data = {"uuid": uuid, "days": days}
    if devices:
        data["devices"] = devices
    return await api._request("POST", "/subscription/extend", data)


async def revoke_subscription_for_user(api_key: str, uuid: str) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    data = {"uuid": uuid}
    return await api._request("POST", "/subscription/revoke", data)


async def change_subscription_devices(api_key: str, uuid: str, devices: int) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    data = {"uuid": uuid, "devices": devices}
    return await api._request("POST", "/subscription/devices", data)


async def update_subscription_metadata(api_key: str, uuid: str, name: str = None, description: str = None, website: str = None, telegram: str = None) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    data = {"uuid": uuid}
    if name:
        data["name"] = name
    if description:
        data["description"] = description
    if website:
        data["website"] = website
    if telegram:
        data["telegram"] = telegram
    return await api._request("POST", "/subscription/metadata", data)


async def get_subscription_status(api_key: str, uuid: str) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    return await api._request("GET", f"/subscription/{uuid}")


async def get_api_balance(api_key: str) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    return await api.get_balance()


async def get_api_tariffs(api_key: str) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    return await api.get_tariffs()


async def calculate_api_price(api_key: str, days: int, devices: int = 1, extra_service: bool = False) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    return await api.calculate_price(days, devices, extra_service)


async def get_api_history(api_key: str) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    return await api.get_history()


async def get_subscription_by_uuid(api_key: str, uuid: str) -> Dict[str, Any]:
    api = MWSharkAPI(api_key)
    return await api.get_subscription_status(uuid)
