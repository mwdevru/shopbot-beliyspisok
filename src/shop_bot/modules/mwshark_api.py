"""
MW VPN API Client
API Documentation: https://vpn.mwshark.host/api/docs
"""

import logging
import aiohttp
from typing import Optional, Dict, List, Any

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
        """Make API request"""
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
        """Get current balance and account statistics"""
        return await self._request("GET", "/balance")

    async def get_tariffs(self) -> Dict[str, Any]:
        """Get list of available tariffs with prices"""
        return await self._request("GET", "/tariffs")

    async def calculate_price(self, days: int) -> Dict[str, Any]:
        """Calculate subscription price for any number of days (1-365)"""
        return await self._request("GET", f"/calculate?days={days}")

    async def create_subscription(self, user_id: int, days: int = 30, name: str = None) -> Dict[str, Any]:
        """
        Create new VPN subscription
        
        Args:
            user_id: Telegram ID of the user
            days: Number of days (1-365, default 30)
            name: Subscription name (optional)
        
        Returns:
            Subscription details with link and payment info
        """
        data = {
            "user_id": user_id,
            "days": days
        }
        if name:
            data["name"] = name
            
        return await self._request("POST", "/subscription/create")

    async def extend_subscription(self, user_id: int, days: int) -> Dict[str, Any]:
        """
        Extend existing subscription
        
        Args:
            user_id: Telegram ID of the user
            days: Number of days to extend (1-365)
        
        Returns:
            Updated subscription details and payment info
        """
        data = {
            "user_id": user_id,
            "days": days
        }
        return await self._request("POST", "/subscription/extend", data)

    async def get_subscription_status(self, user_id: int) -> Dict[str, Any]:
        """Get subscription status for a user"""
        return await self._request("GET", f"/subscription/{user_id}")

    async def get_history(self) -> Dict[str, Any]:
        """Get purchase history"""
        return await self._request("GET", "/history")


# Singleton instance
_api_instance: Optional[MWSharkAPI] = None


def get_api(api_key: str = None) -> Optional[MWSharkAPI]:
    """Get or create API instance"""
    global _api_instance
    
    if api_key:
        _api_instance = MWSharkAPI(api_key)
    
    return _api_instance


async def create_subscription_for_user(api_key: str, user_id: int, days: int, name: str = None) -> Dict[str, Any]:
    """
    Create a new subscription for user
    
    Returns dict with:
        - success: bool
        - subscription: {user_id, uuid, link, expiry_date, days}
        - payment: {amount, new_balance}
    """
    api = MWSharkAPI(api_key)
    
    data = {
        "user_id": user_id,
        "days": days
    }
    if name:
        data["name"] = name
    
    return await api._request("POST", "/subscription/create", data)


async def extend_subscription_for_user(api_key: str, user_id: int, days: int) -> Dict[str, Any]:
    """
    Extend existing subscription for user
    
    Returns dict with:
        - success: bool
        - subscription: {user_id, expiry_date, days_added}
        - payment: {amount, new_balance}
    """
    api = MWSharkAPI(api_key)
    
    data = {
        "user_id": user_id,
        "days": days
    }
    
    return await api._request("POST", "/subscription/extend", data)


async def get_user_subscription(api_key: str, user_id: int) -> Dict[str, Any]:
    """
    Get subscription status for user
    
    Returns dict with:
        - success: bool
        - subscription: {user_id, uuid, email, expiry_date, is_active, limit_ip}
    """
    api = MWSharkAPI(api_key)
    return await api._request("GET", f"/subscription/{user_id}")


async def get_api_balance(api_key: str) -> Dict[str, Any]:
    """
    Get reseller balance
    
    Returns dict with:
        - success: bool
        - balance: float
        - total_topups: float
        - total_spent: float
        - total_purchases: int
    """
    api = MWSharkAPI(api_key)
    return await api.get_balance()


async def get_api_tariffs(api_key: str) -> Dict[str, Any]:
    """
    Get available tariffs from API
    
    Returns dict with:
        - success: bool
        - tariffs: [{id, name, days, price, currency}]
    """
    api = MWSharkAPI(api_key)
    return await api.get_tariffs()


async def calculate_api_price(api_key: str, days: int) -> Dict[str, Any]:
    """
    Calculate price for custom days
    
    Returns dict with:
        - success: bool
        - days: int
        - price: float
        - price_per_day: float
        - currency: str
    """
    api = MWSharkAPI(api_key)
    return await api.calculate_price(days)
