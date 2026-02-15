"""Journal API client for accessing student information via Top Academy API.

This module provides a Python wrapper for the Top Academy Journal API,
allowing users to retrieve course schedules, homework assignments, user profiles,
and payment history.

Example:
    >>> journal = Journal(login='user', password='pass', app_key='key')
    >>> userinfo = journal.get_userinfo()
    >>> homework = journal.get_homework()
    >>> journal.close()
    
    # Or use as context manager:
    >>> with Journal(login='user', password='pass', app_key='key') as journal:
    ...     userinfo = journal.get_userinfo()
"""
import requests
import logging
from typing import Any, Dict, Optional, List, TypedDict

logger = logging.getLogger(__name__)

class JournalError(Exception):
    """Basic Journal Client Error."""


class AuthorizationError(JournalError):
    """Authorization error.""" 


class ScheduleItem(TypedDict):
    """Schedule item containing lesson information."""
    date: str
    lesson: int
    started_at: str
    finished_at: str
    teacher_name: str
    subject_name: str
    room_name: str

class CounterItem(TypedDict):
    """Counter item with type and count."""
    counter_type: int
    counter: int

class UserInfo(TypedDict):
    """User information including groups, profile, and academic details."""
    groups: List[Dict[str, Any]]
    manual_link: str | None
    student_id: int
    current_group_id: int
    full_name: str
    achieves_count: int
    stream_id: int
    stream_name: str
    group_name: str
    level: int
    photo: str
    gaming_points: List[Dict[str, int]]
    spent_gaming_points: List[Dict[str, int]]
    visibility: Dict[str, bool]
    current_group_status: int
    birthday: str
    age: int
    last_date_visit: str
    registration_date: str
    gender: int
    study_form_short_name: str

class Journal:
    API_BASE = "https://msapi.top-academy.ru/api/v2"
    TIMEOUT = 20

    def __init__(
        self,
        login: str,
        password: str,
        app_key: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        """Initialize Journal API client with credentials.
        
        Args:
            login: User login/username
            password: User password
            app_key: Application key for API access (required)
            user_agent: Optional custom User-Agent header string
            
        Raises:
            ValueError: If app_key is not provided
        """
        self.login = login
        self.password = password
        self.app_key = app_key
        if not self.app_key:
            logger.error("APP_KEY not provided during initialization")
            raise ValueError("APP_KEY not passed")

        self.logger = logging.getLogger(f"{__name__}.Journal")
        self.session = requests.Session()
        self.logger.debug(f"Initializing Journal client for user: {login}")
        self.session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": "https://journal.top-academy.ru",
            "Referer": "https://journal.top-academy.ru/",
            "User-Agent": "Mozilla/5.0"
        })
        if user_agent:
            self.session.headers.update({"User-Agent": user_agent})

        self.access_token: Optional[str] = None

    def _authorize(self) -> None:
        """Authenticate with the API and obtain access token."""
        self.logger.info(f"Attempting authorization for user: {self.login}")
        response: requests.Response = self.session.post(
            f"{self.API_BASE}/auth/login",
            json={
                "username": self.login,
                "password": self.password,
                "application_key": self.app_key,
                "id_city": None,
            },
            timeout=self.TIMEOUT,
        )

        if not response.ok:
            self.logger.error(f"Authorization failed: {response.status_code} - {response.text}")
            raise AuthorizationError(
                f"Authorization failed: {response.status_code} {response.text}"
            )

        data = response.json()

        token = data.get("access_token")
        if not token:
            self.logger.error("No access_token in authorization response")
            raise AuthorizationError("There is no access_token in the response.")

        self.access_token = token
        self.session.headers.update({
            "Authorization": f"Bearer {self.access_token}"
        })
        self.logger.info("Authorization successful")

    def _request(
        self,
        method: str,
        endpoint: str,
        retry: bool = True,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Make an HTTP request to the API with automatic re-authorization on 401.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            retry: Whether to retry on 401 Unauthorized
            **kwargs: Additional arguments to pass to requests
            
        Returns:
            JSON response as dictionary
        """
        if not self.access_token:
            self.logger.debug("No access token available, authorizing...")
            self._authorize()

        self.logger.debug(f"Making {method} request to {endpoint}")
        response = self.session.request(
            method=method,
            url=f"{self.API_BASE}{endpoint}",
            timeout=self.TIMEOUT,
            **kwargs,
        )
        
        if response.status_code == 401 and retry:
            self.logger.warning("Received 401 Unauthorized, retrying after re-authorization")
            self._authorize()
            return self._request(method, endpoint, retry=False, **kwargs)

        try:
            self.logger.debug(f"Response status: {response.status_code}")
            response.raise_for_status()
        except requests.RequestException as e:
            self.logger.error(f"Request error {method} {endpoint}: {e}")
            raise JournalError(
                f"Request error {method} {endpoint}: {e}"
            ) from e

        self.logger.debug(f"Successfully received response from {endpoint}")
        return response.json()

    def get_by_custom_url(self, url: str) -> Dict[str, Any]:
        """Make a GET request to a custom URL endpoint.
        
        Args:
            url: Custom endpoint URL
            
        Returns:
            JSON response as dictionary
        """
        return self._request("GET", url)

    def get_userinfo(self) -> UserInfo:
        """Get user profile information including groups, academic status, and personal details.
        
        Returns:
            UserInfo object containing user profile data
        """
        self.logger.info("Fetching user profile information")
        return self._request("GET", "/settings/user-info")

    def get_count_homework(self) -> List[CounterItem]:
        """Get count of homework assignments by status.
        
        Returns:
            List of CounterItems representing homework count by status
        """
        self.logger.info("Fetching homework count by status")
        return self._request("GET", "/count/homework")

    def get_homework(self, page: int = 1, status: int = 0, homework_type: int = 0, group_id: Optional[int] = None) -> dict:
        """Get homework assignments with filtering options.
        
        Args:
            page: Page number for pagination (must be >= 1)
            status: Filter by homework status
            homework_type: Filter by homework type
            group_id: Group ID (defaults to user's first group if available)
            
        Returns:
            Dictionary containing homework list and pagination info
            
        Raises:
            ValueError: If page number is less than 1
            JournalError: If user has no groups and group_id not provided
        """
        if page < 1:
            self.logger.error(f"Invalid page number: {page}")
            raise ValueError("Page number must be >= 1")
            
        params = {
            "page": page,
            "status": status,
            "type": homework_type
        }
        params["group_id"] = group_id
        self.logger.info(f"Fetching homework (page={page}, status={status}, type={homework_type}, group_id={group_id})")
        return self._request("GET", "/homework/operations/list", params=params)

    def _get_schedule(self, endpoint: str, date_filter: str) -> List[ScheduleItem]:
        """Internal method to fetch schedule data from specified endpoint.
        
        Args:
            endpoint: API endpoint for schedule data
            date_filter: Date filter parameter
            
        Returns:
            List of ScheduleItems
        """
        return self._request("GET", endpoint, params={"date_filter": date_filter})

    def get_schedule_by_month(self, date_filter: str) -> List[ScheduleItem]:
        """Get schedule for an entire month.
        
        Args:
            date_filter: Month filter in format YYYY-MM-DD
            
        Returns:
            List of ScheduleItems for the month
        """        
        self.logger.info(f"Fetching schedule for month: {date_filter}")        
        return self._get_schedule("/schedule/operations/get-month", date_filter)

    def get_schedule_by_date_range(self, date_filter: str) -> List[ScheduleItem]:
        """Get schedule for a date range.
        
        Args:
            date_filter: Date range filter parameter
            
        Returns:
            List of ScheduleItems within the date range
        """
        self.logger.info(f"Fetching schedule for date range: {date_filter}")
        return self._get_schedule("/schedule/operations/get-by-date-range", date_filter)

    def get_schedule_by_date(self, date_filter: str) -> List[ScheduleItem]:
        """Get schedule for a specific date.
        
        Args:
            date_filter: Date filter in format YYYY-MM-DD
            
        Returns:
            List of ScheduleItems for the specified date
        """
        self.logger.info(f"Fetching schedule for date: {date_filter}")
        return self._get_schedule("/schedule/operations/get-by-date", date_filter)

    def get_payment_history(self) -> dict:
        """Get payment history.
        
        Returns:
            Dictionary containing payment history entries
        """
        self.logger.info("Fetching payment history")
        return self._request("GET", "/payment/operations/history")

    def close(self) -> None:
        """Close the session and cleanup resources."""
        self.logger.debug("Closing Journal client session")
        self.session.close()
        self.logger.info("Journal client session closed")

    def __enter__(self):
        self.logger.debug("Entering context manager")
        return self

    def __exit__(self, exc_type, exc, tb):
        """Context manager exit, cleanup resources."""
        if exc_type:
            self.logger.error(f"Context manager exiting with exception: {exc_type.__name__}: {exc}")
        else:
            self.logger.debug("Context manager exiting normally")
        self.close()
