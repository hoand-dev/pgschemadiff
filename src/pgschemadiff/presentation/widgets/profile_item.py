"""Widget cho mỗi item trong profile list — hiển thị 2 dòng."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import ListItem, Static

from pgschemadiff.domain.models import Profile


class ProfileListItem(ListItem):
    """Một item trong ListView, gắn kèm Profile object để truy xuất khi select."""

    def __init__(self, profile: Profile) -> None:
        super().__init__()
        self.profile = profile

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"▸ {self.profile.name}", classes="profile-name")
            yield Static(f"  {self.profile.summary()}", classes="profile-summary")
