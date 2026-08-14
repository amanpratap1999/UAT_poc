"""Navigation for Change Management."""

from agent.core.logging import get_logger
from agent.domain.actions import AgentAction

logger = get_logger(__name__)


class ChangeNavigator:
    """Produces navigation actions for Change Management."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def navigate_to_change_list(self) -> AgentAction:
        """Action to navigate to the open Change Requests list."""
        url = f"{self.base_url}/change_request_list.do?sysparm_query=active=true"
        return AgentAction(
            action_type="navigate", target=url, reasoning="Open the list of active Change Requests"  # type: ignore[arg-type]
        )

    def navigate_to_new_change(self) -> AgentAction:
        """Action to navigate to the new Change Request form."""
        url = f"{self.base_url}/change_request.do?sys_id=-1"
        return AgentAction(
            action_type="navigate", target=url, reasoning="Open a new Change Request form"  # type: ignore[arg-type]
        )

    def navigate_to_change(self, change_number: str) -> AgentAction:
        """Action to search and open a specific Change Request."""
        # Using the standard text search parameter for simplicity
        url = f"{self.base_url}/change_request_list.do?sysparm_query=number={change_number}"
        return AgentAction(
            action_type="navigate",  # type: ignore[arg-type]
            target=url,
            reasoning=f"Search for Change Request {change_number}",
        )
