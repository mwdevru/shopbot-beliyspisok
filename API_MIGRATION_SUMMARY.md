# API Migration Summary

## Changes Made

### 1. API Module (mwshark_api.py)
- Added support for PUT and DELETE HTTP methods
- Updated `calculate_price()` to accept `devices` and `extra_service` parameters
- Changed `create_subscription()` to remove `user_id` parameter (API creates subscriptions without user binding)
- Updated `extend_subscription()` to use UUID instead of user_id
- Changed `revoke_subscription()` to use UUID instead of user_id
- Updated `change_devices()` to use PUT method
- Added `update_subscription_metadata()` method for updating subscription metadata
- Removed `get_grants()` method (not in new API)
- Changed `get_subscription_status()` to use UUID instead of user_id

### 2. Database (database.py)
- Added `subscription_uuid` column to `vpn_keys` table
- Updated `add_new_key()` to store subscription UUID
- Updated `update_key_info()` to update subscription UUID
- Added migration logic to add UUID column to existing databases

### 3. Bot Handlers (handlers.py)
- Updated trial key creation to store subscription UUID
- Modified payment processing to:
  - Store UUID when creating new subscriptions
  - Use UUID for extending existing subscriptions
  - Retrieve UUID from database before extending

### 4. Webhook Server (app.py)
- Updated admin key grant to store subscription UUID
- Modified extend/revoke operations to use UUID from database
- Added UUID validation before API calls

## Key API Changes

### Old API Structure
```
POST /subscription/create - with user_id in body
POST /subscription/extend - with user_id in body
POST /subscription/revoke - with user_id in body
GET /subscription/{user_id}
```

### New API Structure
```
POST /subscription - without user_id, returns UUID
POST /subscription/{uuid}/extend
DELETE /subscription/{uuid}
GET /subscription/{uuid}
PUT /subscription/{uuid}/devices
PUT /subscription/{uuid}/metadata
```

## Migration Notes

1. Subscriptions are now created without Telegram user binding
2. UUID is the primary identifier for subscription operations
3. Extra service option available with 7% markup
4. Metadata can be updated separately
5. Device count changes use PUT method
6. All extend/revoke operations require UUID lookup from database

## Testing Recommendations

1. Test trial key creation
2. Test new subscription purchase
3. Test subscription extension
4. Test admin panel key operations
5. Verify UUID storage in database
6. Test migration on existing databases
