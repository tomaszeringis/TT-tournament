import os
import datetime
from typing import Optional
from msal import ConfidentialClientApplication
from msgraph import GraphServiceClient
from msgraph.generated.models.event import Event
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.body_type import BodyType
from msgraph.generated.models.date_time_time_zone import DateTimeTimeZone
from msgraph.generated.models.location import Location
from msgraph.generated.models.attendee import Attendee
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.attendee_type import AttendeeType
from msgraph.generated.models.free_busy_status import FreeBusyStatus
from kiota_abstractions.authentication.access_token_provider import AccessTokenProvider
from kiota_abstractions.authentication.allowed_hosts_validator import AllowedHostsValidator
from kiota_abstractions.authentication.base_bearer_token_authentication_provider import BaseBearerTokenAuthenticationProvider

# Import models
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import Match, Player, SessionLocal

# Azure AD configuration - Should be in environment variables
CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "YOUR_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "YOUR_CLIENT_SECRET")
TENANT_ID = os.getenv("AZURE_TENANT_ID", "common")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["https://graph.microsoft.com/Calendars.ReadWrite"]

class MyAccessTokenProvider(AccessTokenProvider):
    def __init__(self, token: str):
        self.token = token
    
    async def get_authorization_token(self, uri: str, additional_authentication_context: Optional[dict] = None) -> str:
        return self.token

    def get_allowed_hosts_validator(self) -> AllowedHostsValidator:
        return AllowedHostsValidator()

def get_obo_token(user_assertion: str) -> str:
    """
    Acquire a token for Microsoft Graph using the On-Behalf-Of flow.
    """
    app = ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )
    
    result = app.acquire_token_on_behalf_of(
        user_assertion=user_assertion,
        scopes=SCOPES
    )
    
    if "access_token" in result:
        return result["access_token"]
    else:
        error_msg = result.get("error_description", result.get("error", "Unknown error"))
        raise Exception(f"Failed to acquire OBO token: {error_msg}")

async def create_match_event(match: Match, user_assertion: str = None):
    """
    Create an Outlook calendar event for the given match.
    The user_assertion is the access token of the authenticated user.
    """
    if not user_assertion:
        # For demo purposes, we might want to check an env var if not passed
        user_assertion = os.getenv("USER_ACCESS_TOKEN")
        if not user_assertion:
            raise ValueError("user_assertion (access token) is required for OBO flow")

    # 1. Get player emails from database
    db = SessionLocal()
    try:
        p1 = db.query(Player).filter(Player.name == match.player1).first()
        p2 = db.query(Player).filter(Player.name == match.player2).first()
        
        attendee_emails = []
        if p1 and p1.email:
            attendee_emails.append(p1.email)
        if p2 and p2.email:
            attendee_emails.append(p2.email)
            
        if not attendee_emails:
            # Fallback if players not found or no emails
            print(f"Warning: No emails found for players {match.player1} or {match.player2}")

        # 2. Get Graph token using OBO flow
        graph_token = get_obo_token(user_assertion)
        
        # 3. Initialize Graph Client
        token_provider = MyAccessTokenProvider(graph_token)
        auth_provider = BaseBearerTokenAuthenticationProvider(token_provider)
        graph_client = GraphServiceClient(auth_provider)
        
        # 4. Prepare Event data
        start_time = match.scheduled_time or datetime.datetime.utcnow()
        end_time = start_time + datetime.timedelta(hours=1)
        
        new_event = Event()
        new_event.subject = f"🏓 Match: {match.player1} vs {match.player2}"
        new_event.body = ItemBody(
            content=f"Tournament match between {match.player1} and {match.player2}.",
            content_type=BodyType.Text
        )
        
        new_event.start = DateTimeTimeZone(
            date_time=start_time.strftime("%Y-%m-%dT%H:%M:%S"),
            time_zone="UTC"
        )
        new_event.end = DateTimeTimeZone(
            date_time=end_time.strftime("%Y-%m-%dT%H:%M:%S"),
            time_zone="UTC"
        )
        
        if match.location:
            new_event.location = Location(display_name=match.location)
            
        # Add attendees
        attendees = []
        for email in attendee_emails:
            attendee = Attendee()
            attendee.email_address = EmailAddress(address=email)
            attendee.type = AttendeeType.Required
            attendees.append(attendee)
        new_event.attendees = attendees
        
        # Set status to busy
        new_event.show_as = FreeBusyStatus.Busy
        
        # 5. Create event in Graph
        try:
            created_event = await graph_client.me.events.post(new_event)
            return created_event
        except Exception as e:
            print(f"Error creating calendar event: {e}")
            raise
            
    finally:
        db.close()
