from supabase import create_client, Client
from config import get_settings
from functools import lru_cache


@lru_cache
def get_supabase() -> Client:
    """
    Returns a Supabase client using the SERVICE_ROLE_KEY.
    This key bypasses RLS at the client level — the backend MUST enforce
    user_id scoping on every query manually (via auth.py JWT extraction).
    RLS on the database remains as a second line of defense.
    See Section 5 of the dev plan.
    """
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
