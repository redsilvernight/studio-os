"""Local executor of remote task launches (AIB R3). The daemon pulls the
launches that target this machine and applies its own policy before
accepting; execution itself is layered on top through `on_accepted`."""

from studio_client.launch.policy import LaunchPolicy, evaluate_launch
from studio_client.launch.puller import ACTIVE_STATUSES, LaunchPoll, LaunchPuller

__all__ = ["ACTIVE_STATUSES", "LaunchPoll", "LaunchPolicy", "LaunchPuller", "evaluate_launch"]
