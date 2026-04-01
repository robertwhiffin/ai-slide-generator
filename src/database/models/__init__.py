"""Database models."""

from src.database.models.deck_contributor import DeckContributor
from src.database.models.feedback import FeedbackConversation, SurveyResponse
from src.database.models.genie_space import ConfigGenieSpace
from src.database.models.google_global_credentials import GoogleGlobalCredentials
from src.database.models.google_oauth_token import GoogleOAuthToken
from src.database.models.identity import AppIdentity
from src.database.models.image import ImageAsset
from src.database.models.profile import ConfigProfile
from src.database.models.profile_contributor import (
    ConfigProfileContributor,
    IdentityType,
    PermissionLevel,
    ProfileContributor,  # Backward compatibility alias
)
from src.database.models.prompts import ConfigPrompts
from src.database.models.request_log import RequestLog
from src.database.models.session import (
    ChatRequest,
    ExportJob,
    SessionMessage,
    SessionSlideDeck,
    SlideDeckVersion,
    UserSession,
)
from src.database.models.slide_comment import SlideComment
from src.database.models.slide_deck_prompt import SlideDeckPromptLibrary
from src.database.models.slide_style_library import SlideStyleLibrary
from src.database.models.user_preference import UserProfilePreference

__all__ = [
    "AppIdentity",
    "ChatRequest",
    "ConfigGenieSpace",
    "DeckContributor",
    "ConfigProfile",
    "ConfigProfileContributor",
    "ConfigPrompts",
    "ExportJob",
    "FeedbackConversation",
    "GoogleGlobalCredentials",
    "GoogleOAuthToken",
    "IdentityType",
    "ImageAsset",
    "PermissionLevel",
    "ProfileContributor",  # Backward compatibility alias
    "RequestLog",
    "SessionMessage",
    "SessionSlideDeck",
    "SlideComment",
    "SlideDeckPromptLibrary",
    "SlideDeckVersion",
    "SlideStyleLibrary",
    "SurveyResponse",
    "UserProfilePreference",
    "UserSession",
]

